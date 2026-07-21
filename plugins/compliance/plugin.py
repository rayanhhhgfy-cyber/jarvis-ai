# ====================================================================
# JARVIS OMEGA - Compliance Layer (Phase 15)
# ====================================================================
"""
Stay compliant across JOR PDPL, FTC, GDPR, YouTube ToS, Stripe terms.

  compliance.disclosure_inject   - inject correct disclosure per platform
  compliance.tos_check           - screen text for ToS violations
  compliance.privacy_audit       - check a website for privacy compliance
  compliance.ai_content_label    - add correct AI-generated label per platform
  compliance.brand_voice         - define Sir's brand guidelines + enforce
  compliance.terms_generator     - generate ToS + Privacy + Refund + Returns
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from backend.tools import tool, RiskTier
from backend.config import settings


# --------------------------------------------------------------------
# Disclosure injector (per platform)
# --------------------------------------------------------------------

_DISCLOSURES = {
    "ftc_affiliate_ar": (
        "\n\n---\n\n"
        "*إفصاح: بعض الروابط في هذا المحتوى هي روابط تابعة. قد نتلقى عمولة عند الشراء عبرها دون أي تكلفة إضافية عليك.*"
    ),
    "ftc_affiliate_en": (
        "\n\n---\n\n"
        "*Disclosure: Some links are affiliate links. We may earn a commission at no extra cost to you.*"
    ),
    "ai_generated_ar": "\n\n*هذا المحتوى تم إنشاؤه بمساعدة الذكاء الاصطناعي.*",
    "ai_generated_en": "\n\n*AI-assisted content.*",
    "sponsored_ar": "\n\n*هذا المحتوى برعاية [اسم العلامة التجارية].*",
    "sponsored_en": "\n\n*Sponsored by [Brand Name].*",
    "youtube_paid_promo": "\n\n[This video contains paid promotion. The link below is affiliate.]",
    "tiktok_disclosure": "#ad ",
    "instagram_disclosure": "#ad #sponsored ",
}


@tool(
    name="compliance.disclosure_inject",
    description="Inject the correct legal disclosure into content based on type + platform.",
    parameters={
        "type": "object",
        "properties": {
            "content": {"type": "string"},
            "disclosure_type": {
                "type": "string",
                "enum": ["ftc_affiliate", "ai_generated", "sponsored", "youtube_paid_promo", "tiktok_disclosure", "instagram_disclosure"],
            },
            "language": {"type": "string", "default": "ar", "enum": ["ar", "en"]},
            "prepend": {"type": "boolean", "default": False, "description": "Some platforms require the disclosure at the START."},
        },
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="compliance",
)
async def compliance_disclosure_inject(
    content: str, disclosure_type: str = "ai_generated",
    language: str = "ar", prepend: bool = False,
) -> Dict[str, Any]:
    key = f"{disclosure_type}_{language}"
    if disclosure_type in ("tiktok_disclosure", "instagram_disclosure", "youtube_paid_promo"):
        key = disclosure_type
    disclosure = _DISCLOSURES.get(key)
    if not disclosure:
        return {"ok": False, "error": f"unknown disclosure type: {disclosure_type}/{language}"}
    if prepend:
        result = disclosure + content
    else:
        result = content + disclosure
    return {"ok": True, "content_with_disclosure": result, "disclosure_added": disclosure_type}


# --------------------------------------------------------------------
# ToS check
# --------------------------------------------------------------------

# Patterns that violate common platform ToS.
_TOS_VIOLATIONS = {
    "youtube": [
        (r"spam\s+(comments|links|subscribers)", "YouTube bans spam engagement"),
        (r"buy\s+(views|subscribers|likes)", "Purchasing engagement violates YouTube ToS"),
        (r"misleading\s+(thumbnail|title)", "Misleading metadata violates YouTube policy"),
        (r"reupload(ed)?\s+(video|content)", "Reuploading others' content = copyright strike"),
    ],
    "instagram": [
        (r"bot\s+(followers|likes|comments)", "Bot engagement violates Meta ToS"),
        (r"buy\s+(followers|likes)", "Purchased engagement = account ban"),
        (r"mass\s+(follow|unfollow)", "Mass follow/unfollow triggers rate-limit bans"),
    ],
    "stripe": [
        (r"money\s+laundry", "Stripe prohibits money laundering"),
        (r"pharma.*(without\s+prescription|illegal)", "Stripe prohibits illegal pharma"),
        (r"firearm|weapon", "Stripe restricts weapons sales"),
    ],
    "ads_general": [
        (r"before\s+and\s+after\s+photo", "Before/after photos restricted in many ad policies"),
        (r"guaranteed\s+(income|results|cure)", "Guaranteed outcome claims often violate ad policies"),
        (r"get\s+rich\s+quick", "Get-rich-quick schemes violate most ad platforms"),
        (r"\bcure\b\s+(cancer|disease)", "Medical cure claims heavily restricted"),
    ],
}


@tool(
    name="compliance.tos_check",
    description="Screen content for ToS violations before publishing. Returns list of risks per platform.",
    parameters={
        "type": "object",
        "properties": {
            "content": {"type": "string"},
            "platforms": {
                "type": "array",
                "items": {"type": "string"},
                "default": ["youtube", "instagram", "stripe", "ads_general"],
            },
        },
        "required": ["content"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="compliance",
)
async def compliance_tos_check(content: str, platforms: Optional[List[str]] = None) -> Dict[str, Any]:
    platforms = platforms or ["youtube", "instagram", "stripe", "ads_general"]
    findings: List[Dict[str, str]] = []
    for plat in platforms:
        for pattern, reason in _TOS_VIOLATIONS.get(plat, []):
            if re.search(pattern, content, re.IGNORECASE):
                findings.append({"platform": plat, "issue": reason, "matched_pattern": pattern})
    severity = "high" if findings else "clean"
    return {
        "ok": True,
        "content_preview": content[:200],
        "platforms_checked": platforms,
        "violations_found": len(findings),
        "findings": findings,
        "verdict": severity,
        "recommendation": "FIX violations before posting" if findings else "No obvious ToS risks found.",
    }


# --------------------------------------------------------------------
# Privacy audit
# --------------------------------------------------------------------

@tool(
    name="compliance.privacy_audit",
    description="Audit a website URL for basic privacy compliance (privacy policy presence, cookie banner, HTTPS, PDPL/GDPR signals).",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string"},
        },
        "required": ["url"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="compliance",
)
async def compliance_privacy_audit(url: str) -> Dict[str, Any]:
    import httpx
    findings: List[Dict[str, str]] = []
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "JARVIS-Compliance/1.0"})
        html = resp.text.lower()
        # Check 1: HTTPS.
        if not url.startswith("https://"):
            findings.append({"severity": "high", "issue": "Site is not HTTPS — required for any data collection."})
        # Check 2: Privacy policy link.
        if "privacy policy" not in html and "سياسة الخصوصية" not in html:
            findings.append({"severity": "high", "issue": "No privacy policy link detected — required by JO PDPL + GDPR."})
        # Check 3: Cookie banner.
        if "cookie" not in html and "كوكي" not in html:
            findings.append({"severity": "medium", "issue": "No cookie consent banner detected — required by GDPR for EU users."})
        # Check 4: Contact info.
        if not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", html):
            findings.append({"severity": "medium", "issue": "No contact email found — PDPL requires a data controller contact."})
        # Check 5: Terms of service.
        if "terms of service" not in html and "شروط الاستخدام" not in html:
            findings.append({"severity": "medium", "issue": "No Terms of Service link detected."})
    except Exception as e:
        return {"ok": False, "error": f"couldn't fetch {url}: {e}"}

    score = max(0, 100 - 20 * len([f for f in findings if f["severity"] == "high"]) - 10 * len([f for f in findings if f["severity"] == "medium"]))
    return {
        "ok": True, "url": url,
        "compliance_score": score,
        "findings": findings,
        "verdict": "COMPLIANT" if not findings else "NEEDS FIXES",
    }


# --------------------------------------------------------------------
# AI content label
# --------------------------------------------------------------------

_AI_LABELS = {
    "youtube": "Add to video description: 'This video was created using AI tools.' YouTube requires disclosure of synthetic content.",
    "instagram": "Add post caption: 'Created with AI' — Meta requires AI disclosure.",
    "tiktok": "Use the 'AI-generated' content toggle in the TikTok uploader.",
    "twitter": "Add 'AI-generated' to tweet or use the AI label feature.",
    "google_play": "Declare AI usage in the Play Console Data Safety form.",
}


@tool(
    name="compliance.ai_content_label",
    description="Return the correct AI-content disclosure required by each platform.",
    parameters={
        "type": "object",
        "properties": {
            "platform": {"type": "string", "enum": ["youtube", "instagram", "tiktok", "twitter", "google_play"]},
        },
        "required": ["platform"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="compliance",
)
async def compliance_ai_content_label(platform: str) -> Dict[str, Any]:
    return {"ok": True, "platform": platform, "label": _AI_LABELS.get(platform, "No specific rule found.")}


# --------------------------------------------------------------------
# Brand voice
# --------------------------------------------------------------------

@tool(
    name="compliance.brand_voice_define",
    description="Define Sir's brand voice guidelines. Once set, JARVIS enforces it on every content generation.",
    parameters={
        "type": "object",
        "properties": {
            "voice_description": {"type": "string", "default": "", "description": "How Sir wants to sound. e.g. 'professional but warm, concise, never uses emoji'"},
            "do_list": {"type": "array", "items": {"type": "string"}, "default": []},
            "dont_list": {"type": "array", "items": {"type": "string"}, "default": []},
            "language": {"type": "string", "default": "ar", "enum": ["ar", "en"]},
        },
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="compliance",
)
async def compliance_brand_voice_define(
    voice_description: str = "",
    do_list: Optional[List[str]] = None, dont_list: Optional[List[str]] = None,
    language: str = "ar",
) -> Dict[str, Any]:
    do_list = do_list or []
    dont_list = dont_list or []
    # Persist to a file in storage.
    from pathlib import Path
    p = Path("./storage/brand_voice.json")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "voice_description": voice_description,
        "do": do_list, "dont": dont_list,
        "language": language,
        "defined_at": __import__("datetime").datetime.utcnow().isoformat(),
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"ok": True, "saved_to": str(p), "note": "JARVIS will load this on every content generation."}


@tool(
    name="compliance.brand_voice_check",
    description="Score a piece of content 0-100 against Sir's brand voice guidelines.",
    parameters={
        "type": "object",
        "properties": {
            "content": {"type": "string"},
        },
        "required": ["content"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="compliance",
)
async def compliance_brand_voice_check(content: str) -> Dict[str, Any]:
    from pathlib import Path
    p = Path("./storage/brand_voice.json")
    if not p.exists():
        return {"ok": False, "error": "no brand_voice.json — call compliance.brand_voice_define first"}
    guidelines = json.loads(p.read_text(encoding="utf-8"))
    from backend.services.llm_service import llm_service
    try:
        reply = await llm_service.get_response(
            user_message=f"Content to check:\n{content}\n\nBrand guidelines:\n{json.dumps(guidelines, indent=2)}",
            system_instructions=(
                "Score how well this content matches the brand voice (0-100). "
                "Output STRICT JSON: {\"score\": integer, \"issues\": [string], \"rewrite_suggestion\": string}"
            ),
            inject_memory=False,
        )
        text = reply.strip().lstrip("`").rstrip("`")
        if text.startswith("json"): text = text[4:]
        return {"ok": True, **json.loads(text)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# --------------------------------------------------------------------
# Full terms-of-service suite
# --------------------------------------------------------------------

@tool(
    name="compliance.terms_generator",
    description="Generate a full legal suite: ToS + Privacy Policy + Refund Policy + Return Policy. Bilingual.",
    parameters={
        "type": "object",
        "properties": {
            "business_name": {"type": "string"},
            "service_description": {"type": "string"},
            "contact_email": {"type": "string", "default": ""},
            "jurisdiction": {"type": "string", "default": "Hashemite Kingdom of Jordan"},
            "language": {"type": "string", "default": "both", "enum": ["ar", "en", "both"]},
        },
        "required": ["business_name", "service_description"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="compliance",
)
async def compliance_terms_generator(
    business_name: str, service_description: str, contact_email: str = "",
    jurisdiction: str = "Hashemite Kingdom of Jordan", language: str = "both",
) -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    docs: Dict[str, str] = {}
    lang_label = {"ar": "Arabic", "en": "English", "both": "Arabic AND English"}[language]
    doc_types = ["terms_of_service", "privacy_policy", "refund_policy", "return_policy"]
    for doc in doc_types:
        try:
            md = await llm_service.get_response(
                user_message=(
                    f"Business: {business_name}\nService: {service_description}\n"
                    f"Contact: {contact_email or '(not specified)'}\nJurisdiction: {jurisdiction}"
                ),
                system_instructions=(
                    f"You are a Jordanian lawyer. Generate a {doc.replace('_', ' ').title()} in {lang_label}. "
                    "Output Markdown only. Include all standard clauses for an online business "
                    "operating in Jordan. Add disclaimer: 'Draft — have a licensed lawyer review.'"
                ),
                inject_memory=False,
            )
            docs[doc] = md
        except Exception as e:
            docs[doc] = f"[Generation failed: {e}]"
    # Save all to disk.
    from pathlib import Path
    out_dir = Path(f"./storage/legal/{business_name.lower().replace(' ', '_')}")
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {}
    for doc, content in docs.items():
        p = out_dir / f"{doc}.md"
        p.write_text(content, encoding="utf-8")
        paths[doc] = str(p)
    return {"ok": True, "business": business_name, "language": language, "documents": paths}


PLUGIN_NAME = "compliance"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Compliance: disclosures, ToS screening, privacy audit, AI labels, brand voice, terms-of-service suite."
