# Phase 19: Cover Letter Factory (REAL)
from __future__ import annotations
from typing import Any, Dict
from backend.tools import tool, RiskTier

@tool(name="coverletter.generate", description="Generate a personalized cover letter from job description + applicant experience.", parameters={"type":"object","properties":{"job_title":{"type":"string"},"company":{"type":"string","default":""},"job_description":{"type":"string"},"applicant_name":{"type":"string"},"experience_summary":{"type":"string","default":""},"language":{"type":"string","default":"en","enum":["ar","en"]}},"required":["job_title","job_description","applicant_name"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="cover_letter")
async def generate(job_title: str, job_description: str, applicant_name: str, company: str = "", experience_summary: str = "", language: str = "en") -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    try:
        letter = await llm_service.get_response(user_message=f"Job: {job_title} at {company}\nDescription: {job_description[:1000]}\nApplicant: {applicant_name}\nExperience: {experience_summary}", system_instructions=f"Write a compelling, personalized cover letter in {'Arabic' if language=='ar' else 'English'}. Address the hiring manager. Show specific knowledge of the role. Reference 2 achievements. Close with confidence. 300-400 words.", inject_memory=False)
        return {"ok": True, "cover_letter": letter.strip(), "language": language, "note": "Sell for 25-50 JOD per cover letter alongside resume service."}
    except Exception as e: return {"ok": False, "error": str(e)}

PLUGIN_NAME = "cover_letter"; PLUGIN_VERSION = "1.0.0"
