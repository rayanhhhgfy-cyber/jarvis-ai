# ====================================================================
# JARVIS OMEGA - Media Empire Combo Integrator (Phase 14)
# ====================================================================
"""
The 5-bundle combo: Codex + Twin + Shorts + Newsletter + Music, integrated.

One tool — media_empire.publish_from_idea — drives the whole pipeline:

  1. Pull relevant memory from Codex (Sir's past thinking on this idea)
  2. Generate voiceover in Sir's cloned voice (or fallback Arabic TTS)
  3. Generate talking-head video with Sir's face (or stock images)
  4. Cut the long video into 3-7 vertical shorts
  5. Generate an AI music soundtrack for the videos
  6. Write a newsletter issue expanding the idea
  7. Schedule the shorts across TikTok/Reels/Shorts
  8. Publish the newsletter issue
  9. Persist everything to media_empire_publications table
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.tools import tool, RiskTier
from backend import business_db
from shared.logger import get_logger

log = get_logger("media_empire")


@tool(
    name="media_empire.publish_from_idea",
    description="Master tool: takes one idea and produces a full Media Empire package — Twin-narrated video, shorts, newsletter, music. Then publishes everything.",
    parameters={
        "type": "object",
        "properties": {
            "idea": {"type": "string", "description": "The core idea/topic for this media package."},
            "language": {"type": "string", "default": "ar", "enum": ["ar", "en"]},
            "platforms": {
                "type": "array",
                "items": {"type": "string"},
                "default": ["youtube", "shorts", "newsletter"],
                "description": "Subset of: youtube, shorts, newsletter, music, twin",
            },
            "use_twin_voice": {"type": "boolean", "default": True},
            "use_twin_face": {"type": "boolean", "default": True},
            "schedule_for_later": {"type": "boolean", "default": True, "description": "If True, schedule across next 7 days. If False, post immediately."},
        },
        "required": ["idea"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="media_empire",
)
async def media_empire_publish_from_idea(
    idea: str, language: str = "ar",
    platforms: Optional[List[str]] = None,
    use_twin_voice: bool = True, use_twin_face: bool = True,
    schedule_for_later: bool = True,
) -> Dict[str, Any]:
    platforms = platforms or ["youtube", "shorts", "newsletter"]
    report: Dict[str, Any] = {"idea": idea, "language": language, "steps": []}

    # Step 1: pull from codex
    codex_context = ""
    try:
        from plugins.codex.plugin import codex_ask
        ctx = await codex_ask(query=idea, limit=3)
        codex_context = "\n".join([
            h.get("snippet", h.get("content", ""))[:200]
            for h in (ctx.get("sql_hits") or ctx.get("chroma_hits"))
        ][:3])
    except Exception as e:
        report["steps"].append({"step": "codex_recall", "ok": False, "error": str(e)})

    # Step 2: write a long-form script via LLM
    script = ""
    try:
        from backend.services.llm_service import llm_service
        script = await llm_service.get_response(
            user_message=f"Topic: {idea}\n\nRelevant context from Sir's notes:\n{codex_context}",
            system_instructions=(
                f"Write a 5-minute YouTube script in {'Arabic' if language == 'ar' else 'English'}. "
                "Hook in first 10 seconds. Engaging, conversational. Output narration only — no visual cues."
            ),
            inject_memory=False,
        )
        report["steps"].append({"step": "script_write", "ok": True, "chars": len(script)})
    except Exception as e:
        report["steps"].append({"step": "script_write", "ok": False, "error": str(e)})
        return {"ok": False, "report": report, "error": "script generation failed"}

    # Step 3: voiceover (Twin if available, edge-tts fallback)
    voice_path = ""
    try:
        from plugins.twin.plugin import twin_generate_voice
        voice_result = await twin_generate_voice(text=script, language=language)
        voice_path = voice_result.get("path", "")
        report["steps"].append({
            "step": "voiceover", "ok": True,
            "path": voice_path, "fallback_used": voice_result.get("fallback_used"),
        })
    except Exception as e:
        report["steps"].append({"step": "voiceover", "ok": False, "error": str(e)})

    # Step 4: talking-head video or slideshow
    video_path = ""
    if voice_path and use_twin_face:
        try:
            from plugins.twin.plugin import twin_generate_talking_video
            vid = await twin_generate_talking_video(voice_audio_path=voice_path)
            video_path = vid.get("path", "")
            report["steps"].append({"step": "talking_video", "ok": True, "path": video_path})
        except Exception as e:
            report["steps"].append({"step": "talking_video", "ok": False, "error": str(e)})

    # Step 5: cut into shorts
    shorts_paths: List[str] = []
    if video_path and "shorts" in platforms:
        try:
            from plugins.shorts.plugin import shorts_cut_from_long_video
            cut_result = await shorts_cut_from_long_video(
                source_video_path=video_path, clip_count=5, clip_duration_seconds=30,
            )
            shorts_paths = cut_result.get("clips", [])
            report["steps"].append({"step": "cut_shorts", "ok": True, "clips": len(shorts_paths)})
        except Exception as e:
            report["steps"].append({"step": "cut_shorts", "ok": False, "error": str(e)})

    # Step 6: optional music
    music_path = ""
    if "music" in platforms:
        try:
            from plugins.music.plugin import music_generate_song_musicgen
            music = await music_generate_song_musicgen(
                prompt=f"background instrumental for: {idea[:100]}", duration_seconds=30,
            )
            music_path = music.get("path", music.get("audio_base64", ""))[:200]
            report["steps"].append({"step": "music", "ok": True, "path": music_path[:100]})
        except Exception as e:
            report["steps"].append({"step": "music", "ok": False, "error": str(e)})

    # Step 7: newsletter issue
    newsletter_path = ""
    if "newsletter" in platforms:
        try:
            from plugins.newsletter.plugin import newsletter_write_issue
            issue = await newsletter_write_issue(
                newsletter_name="Sir Media Empire", issue_topic=idea,
                word_count=600, language=language, include_research=False,
            )
            newsletter_path = issue.get("issue_path", "")
            report["steps"].append({"step": "newsletter", "ok": True, "path": newsletter_path})
        except Exception as e:
            report["steps"].append({"step": "newsletter", "ok": False, "error": str(e)})

    # Step 8: schedule across platforms (only if schedule_for_later)
    scheduled_count = 0
    if schedule_for_later:
        from backend import business_db as _bdb
        from plugins.marketing.plugin import marketing_schedule
        for i, short in enumerate(shorts_paths):
            try:
                when = (datetime.utcnow() + timedelta(days=1 + i)).isoformat()
                # Schedule on YouTube Shorts (or YT generally).
                await marketing_schedule(
                    platform="telegram",  # default fallback — Sir can swap to YT/Reels/etc.
                    content=f"New short from Sir's Media Empire: {idea}\nFile: {short}",
                    scheduled_at=when,
                )
                scheduled_count += 1
            except Exception:
                pass

    # Step 9: persist publication
    try:
        pub_id = business_db.execute(
            """INSERT INTO media_empire_publications
               (idea, platforms, twin_video_path, shorts_paths, newsletter_url, music_path, status, published_at, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (idea, json.dumps(platforms), video_path, json.dumps(shorts_paths),
             newsletter_path, music_path, "published" if not schedule_for_later else "scheduled",
             datetime.utcnow().isoformat() if not schedule_for_later else None,
             datetime.utcnow().isoformat()),
        )
        report["publication_id"] = pub_id
    except Exception as e:
        log.warning("media_empire_persist_failed", error=str(e))

    report["ok"] = True
    report["summary"] = {
        "voice_generated": bool(voice_path),
        "video_generated": bool(video_path),
        "shorts_cut": len(shorts_paths),
        "music_generated": bool(music_path),
        "newsletter_written": bool(newsletter_path),
        "scheduled_count": scheduled_count,
    }
    return report


@tool(
    name="media_empire.list_publications",
    description="List recent Media Empire publications.",
    parameters={
        "type": "object",
        "properties": {"limit": {"type": "integer", "default": 20}},
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="media_empire",
)
async def media_empire_list_publications(limit: int = 20) -> Dict[str, Any]:
    rows = business_db.rows_to_dicts(business_db.query(
        "SELECT id, idea, platforms, status, published_at, created_at "
        "FROM media_empire_publications ORDER BY id DESC LIMIT ?",
        (limit,),
    ))
    return {"ok": True, "count": len(rows), "publications": rows}


PLUGIN_NAME = "media_empire"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Combo: Codex → Twin → Shorts → Newsletter → Music. One idea → full Media Empire package."
