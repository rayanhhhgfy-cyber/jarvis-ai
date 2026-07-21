# ====================================================================
# JARVIS OMEGA - Course Creator (Phase 14)
# ====================================================================
"""
Auto-generate online courses for Udemy/Teachable/Skillshare.

  course.outline          - 10-module outline from a topic
  course.lesson_write     - 1500-word lesson per module
  course.generate_slides  - reveal.js slides per lesson
  course.voiceover        - Arabic narration via edge-tts
  course.quiz_generator   - 10 MCQs per lesson
  course.workbook_pdf     - exercises + cheat sheets (HTML → print to PDF)
  course.publish_udemy    - Udemy instructor API
  course.list_courses     - list all generated courses
"""

from __future__ import annotations

import json
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.tools import tool, RiskTier


_COURSE_DIR = Path("./storage/courses")
_COURSE_DIR.mkdir(parents=True, exist_ok=True)


@tool(
    name="course.outline",
    description="Generate a 10-module course outline from a topic.",
    parameters={
        "type": "object",
        "properties": {
            "topic": {"type": "string"},
            "audience": {"type": "string", "default": "beginners"},
            "language": {"type": "string", "default": "ar", "enum": ["ar", "en"]},
            "module_count": {"type": "integer", "default": 10},
        },
        "required": ["topic"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="course",
)
async def course_outline(topic: str, audience: str = "beginners", language: str = "ar", module_count: int = 10) -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    try:
        reply = await llm_service.get_response(
            user_message=f"Topic: {topic}\nAudience: {audience}\nModules: {module_count}",
            system_instructions=(
                f"You are a senior instructional designer. Output STRICT JSON in {'Arabic' if language == 'ar' else 'English'}: "
                "{\"course_title\": string, \"subtitle\": string, \"modules\": [{"
                "\"title\": string, \"learning_outcomes\": [string], \"key_concepts\": [string]"
                "}]}"
            ),
            inject_memory=False,
        )
        text = reply.strip().lstrip("`").rstrip("`")
        if text.startswith("json"): text = text[4:]
        outline = json.loads(text)
        # Persist.
        course_dir = _COURSE_DIR / topic.lower().replace(" ", "_")[:50]
        course_dir.mkdir(parents=True, exist_ok=True)
        (course_dir / "outline.json").write_text(json.dumps(outline, indent=2, ensure_ascii=False), encoding="utf-8")
        return {"ok": True, "course_dir": str(course_dir), "outline": outline}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="course.lesson_write",
    description="Write a full lesson for a course module. Markdown output, ~1500 words.",
    parameters={
        "type": "object",
        "properties": {
            "module_title": {"type": "string"},
            "key_concepts": {"type": "array", "items": {"type": "string"}},
            "audience": {"type": "string", "default": "beginners"},
            "language": {"type": "string", "default": "ar"},
            "course_dir": {"type": "string", "default": ""},
        },
        "required": ["module_title", "key_concepts"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="course",
)
async def course_lesson_write(
    module_title: str, key_concepts: List[str], audience: str = "beginners",
    language: str = "ar", course_dir: str = "",
) -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    try:
        lesson = await llm_service.get_response(
            user_message=f"Module: {module_title}\nKey concepts: {key_concepts}\nAudience: {audience}",
            system_instructions=(
                f"Write a 1500-word lesson in {'Arabic' if language == 'ar' else 'English'}. "
                "Include: intro, 3-5 sections with examples, exercises at end, summary. Markdown."
            ),
            inject_memory=False,
        )
        safe = "".join(c for c in module_title.lower() if c.isalnum() or c == "_")[:50]
        fname = f"{safe}.md"
        out = (Path(course_dir) if course_dir else _COURSE_DIR) / fname
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(lesson, encoding="utf-8")
        return {"ok": True, "lesson_path": str(out), "chars": len(lesson)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="course.generate_slides",
    description="Generate reveal.js HTML slides from a lesson.",
    parameters={
        "type": "object",
        "properties": {
            "lesson_path": {"type": "string"},
            "output_path": {"type": "string", "default": ""},
        },
        "required": ["lesson_path"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="course",
)
async def course_generate_slides(lesson_path: str, output_path: str = "") -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    if not Path(lesson_path).is_file():
        return {"ok": False, "error": "lesson not found"}
    text = Path(lesson_path).read_text(encoding="utf-8")
    try:
        html = await llm_service.get_response(
            user_message=f"Lesson content:\n{text[:6000]}",
            system_instructions=(
                "Convert this lesson into reveal.js HTML slides. One H2 = one slide. "
                "Use the CDN-prefixed reveal.js. Output HTML only — no markdown fences."
            ),
            inject_memory=False,
        )
        out = output_path or lesson_path.replace(".md", "_slides.html")
        Path(out).write_text(html, encoding="utf-8")
        return {"ok": True, "slides_path": out}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="course.voiceover",
    description="Generate Arabic narration for a lesson via edge-tts.",
    parameters={
        "type": "object",
        "properties": {
            "lesson_path": {"type": "string"},
            "voice": {"type": "string", "default": "ar-JZ-AyoubNeural"},
            "output_path": {"type": "string", "default": ""},
        },
        "required": ["lesson_path"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="course",
)
async def course_voiceover(lesson_path: str, voice: str = "ar-JZ-AyoubNeural", output_path: str = "") -> Dict[str, Any]:
    if not Path(lesson_path).is_file():
        return {"ok": False, "error": "lesson not found"}
    text = Path(lesson_path).read_text(encoding="utf-8")
    from plugins.voice_local.plugin import voice_tts_edge
    # Strip markdown for cleaner TTS.
    import re
    clean = re.sub(r"[#*`_>\-]", " ", text)
    clean = re.sub(r"\s+", " ", clean).strip()
    result = await voice_tts_edge(text=clean[:3000], voice=voice)  # edge-tts limit per call
    if not result.get("ok"):
        return result
    out = output_path or lesson_path.replace(".md", "_voiceover.mp3")
    import base64
    Path(out).write_bytes(base64.b64decode(result["audio_base64"]))
    return {"ok": True, "audio_path": out, "bytes": result["bytes"]}


@tool(
    name="course.quiz_generator",
    description="Generate 10 MCQs for a lesson.",
    parameters={
        "type": "object",
        "properties": {
            "lesson_path": {"type": "string"},
            "language": {"type": "string", "default": "ar"},
        },
        "required": ["lesson_path"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="course",
)
async def course_quiz_generator(lesson_path: str, language: str = "ar") -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    if not Path(lesson_path).is_file():
        return {"ok": False, "error": "lesson not found"}
    text = Path(lesson_path).read_text(encoding="utf-8")
    try:
        reply = await llm_service.get_response(
            user_message=f"Lesson:\n{text[:6000]}",
            system_instructions=(
                f"Generate 10 multiple-choice questions in {'Arabic' if language == 'ar' else 'English'} "
                "from this lesson. Output STRICT JSON: {"
                "\"questions\": [{\"question\": string, \"options\": [string, ...], \"correct_index\": integer, \"explanation\": string}]}"
            ),
            inject_memory=False,
        )
        t = reply.strip().lstrip("`").rstrip("`")
        if t.startswith("json"): t = t[4:]
        parsed = json.loads(t)
        # Save alongside lesson.
        out = lesson_path.replace(".md", "_quiz.json")
        Path(out).write_text(json.dumps(parsed, indent=2, ensure_ascii=False), encoding="utf-8")
        return {"ok": True, "quiz_path": out, "question_count": len(parsed.get("questions", []))}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="course.workbook_pdf",
    description="Generate an HTML workbook (exercises + cheat sheet) ready to print as PDF.",
    parameters={
        "type": "object",
        "properties": {
            "course_title": {"type": "string"},
            "modules": {"type": "array", "items": {"type": "object"}},
            "output_path": {"type": "string", "default": ""},
        },
        "required": ["course_title", "modules"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="course",
)
async def course_workbook_pdf(course_title: str, modules: List[Dict[str, Any]], output_path: str = "") -> Dict[str, Any]:
    sections = ""
    for m in modules:
        outs = "".join(f"<li>{o}</li>" for o in m.get("learning_outcomes", []))
        exercises = "".join(f"<li>{c}</li>" for c in m.get("key_concepts", []))
        sections += f"<section><h2>{m.get('title','')}</h2><h3>Learning Outcomes</h3><ul>{outs}</ul><h3>Practice</h3><ul>{exercises}</ul></section>"
    html = f"""<!DOCTYPE html><html dir="rtl" lang="ar"><head><meta charset="utf-8">
<title>{course_title} Workbook</title>
<style>body{{font-family:Tajawal,Arial,sans-serif;max-width:800px;margin:auto;padding:40px}}
h1,h2,h3{{color:#4f46e5}}@media print{{section{{page-break-after:always}}}}</style>
</head><body><h1>{course_title} — Workbook</h1>{sections}</body></html>"""
    out = output_path or str(_COURSE_DIR / f"{course_title.lower().replace(' ','_')}_workbook.html")
    Path(out).write_text(html, encoding="utf-8")
    return {"ok": True, "workbook_path": out, "note": "Open in browser → Print → Save as PDF."}


@tool(
    name="course.publish_udemy",
    description="Publish to Udemy. Udemy doesn't have a public course-creation API — opens browser.",
    parameters={
        "type": "object",
        "properties": {
            "course_title": {"type": "string"},
            "course_dir": {"type": "string"},
        },
        "required": ["course_title"],
    },
    risk_tier=RiskTier.TIER_2_SYSTEM,
    category="course",
)
async def course_publish_udemy(course_title: str, course_dir: str = "") -> Dict[str, Any]:
    webbrowser.open("https://www.udemy.com/instructor/courses/")
    return {
        "ok": True,
        "manual_url": "https://www.udemy.com/instructor/courses/",
        "course_title": course_title,
        "instructions": "Browser opened to Udemy instructor. Click 'New Course' and upload content from course_dir.",
    }


@tool(
    name="course.list_courses",
    description="List all generated courses.",
    parameters={"type": "object"},
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="course",
)
async def course_list_courses() -> Dict[str, Any]:
    courses = []
    for d in sorted(_COURSE_DIR.iterdir()):
        if d.is_dir():
            outline_file = d / "outline.json"
            title = d.name
            if outline_file.exists():
                try:
                    title = json.loads(outline_file.read_text(encoding="utf-8")).get("course_title", d.name)
                except Exception:
                    pass
            lessons = list(d.glob("*.md"))
            courses.append({
                "dir": str(d), "title": title,
                "lesson_count": len(lessons),
                "has_voiceovers": any("_voiceover.mp3" in l.name for l in d.rglob("*")),
            })
    return {"ok": True, "count": len(courses), "courses": courses}


PLUGIN_NAME = "course"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Auto-course creator: outline → lessons → slides → voiceover → quizzes → workbook → Udemy publish."
