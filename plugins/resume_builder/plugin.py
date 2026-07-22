# Phase 19: AI Resume Builder (REAL - sell as service)
from __future__ import annotations
from pathlib import Path
from typing import Any, Dict
from backend.tools import tool, RiskTier

@tool(name="resume.generate", description="Generate a professional resume HTML from personal info + experience. Arabic or English.", parameters={"type":"object","properties":{"name":{"type":"string"},"title":{"type":"string"},"email":{"type":"string"},"phone":{"type":"string"},"experience":{"type":"array","items":{"type":"object"},"default":[]},"education":{"type":"array","items":{"type":"object"},"default":[]},"skills":{"type":"array","items":{"type":"string"},"default":[]},"language":{"type":"string","default":"ar","enum":["ar","en"]}},"required":["name","title"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="resume_builder")
async def generate(name: str, title: str, email: str = "", phone: str = "", experience: list = None, education: list = None, skills: list = None, language: str = "ar") -> Dict[str, Any]:
    experience = experience or []; education = education or []; skills = skills or []
    from backend.services.llm_service import llm_service
    try:
        summary = await llm_service.get_response(user_message=f"Name: {name}, Title: {title}, Skills: {skills}", system_instructions=f"Write a 2-sentence professional summary for a resume in {'Arabic' if language=='ar' else 'English'}.", inject_memory=False)
    except: summary = ""
    is_ar = language == "ar"
    exp_html = "".join(f"<div class='job'><h3>{e.get('role','')}</h3><p class='company'>{e.get('company','')} | {e.get('period','')}</p><p>{e.get('description','')}</p></div>" for e in experience)
    edu_html = "".join(f"<div class='edu'><strong>{e.get('degree','')}</strong> - {e.get('school','')} ({e.get('year','')})</div>" for e in education)
    skills_html = ", ".join(skills)
    html = f"""<!DOCTYPE html><html dir="{'rtl' if is_ar else 'ltr'}" lang="{language}"><head><meta charset="utf-8"><title>{name} - Resume</title><style>
body{{font-family:'Tajawal' if is_ar else 'Arial',sans-serif;max-width:800px;margin:auto;padding:40px;color:#222}}
h1{{font-size:2rem;color:#1a1a2e;border-bottom:3px solid #4f46e5;padding-bottom:8px}}
h2{{color:#4f46e5;margin-top:24px;border-bottom:1px solid #ddd;padding-bottom:4px}}
.job{{margin:12px 0}}.company{{color:#666;font-style:italic}}
.skills{{background:#f0fdf4;padding:12px;border-radius:8px;margin-top:8px}}
</style></head><body>
<h1>{name}</h1><p style="font-size:1.2rem;color:#666">{title}</p>
<p>{email} | {phone}</p>
<p style="margin-top:16px;font-size:1.05rem">{summary}</p>
<h2>{'الخبرات' if is_ar else 'Experience'}</h2>{exp_html}
<h2>{'التعليم' if is_ar else 'Education'}</h2>{edu_html}
<h2>{'المهارات' if is_ar else 'Skills'}</h2><div class="skills">{skills_html}</div>
</body></html>"""
    out = Path("./storage/resumes"); out.mkdir(parents=True, exist_ok=True)
    path = out / f"{name.replace(' ','_')}_resume.html"; path.write_text(html, encoding="utf-8")
    return {"ok": True, "path": str(path), "language": language, "note": "Sell for 50-100 JOD per resume."}

@tool(name="resume.cover_letter", description="Generate a matching cover letter for a specific job posting.", parameters={"type":"object","properties":{"job_description":{"type":"string"},"name":{"type":"string"},"experience_summary":{"type":"string","default":""}},"required":["job_description","name"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="resume_builder")
async def cover_letter(job_description: str, name: str, experience_summary: str = "") -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    try:
        letter = await llm_service.get_response(user_message=f"Job: {job_description[:1000]}\nApplicant: {name}\nExperience: {experience_summary}", system_instructions="Write a compelling, personalized cover letter. English. Professional but warm. 300 words.", inject_memory=False)
        return {"ok": True, "cover_letter": letter.strip()}
    except Exception as e: return {"ok": False, "error": str(e)}

PLUGIN_NAME = "resume_builder"; PLUGIN_VERSION = "1.0.0"
