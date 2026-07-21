# ====================================================================
# JARVIS OMEGA - Newsletter Empire (Phase 14)
# ====================================================================
"""
Run paid newsletter businesses across multiple niches.

  newsletter.spec              - define niche + audience + cadence
  newsletter.write_issue       - LLM + research pipeline
  newsletter.publish_substack  - Substack (free up to all subs, paid needs plan)
  newsletter.publish_beehiiv   - beehiiv (free up to 2.5k subs)
  newsletter.find_sponsors     - cold-email matching brands
  newsletter.archive_compile   - annual archive → ebook
  newsletter.subscribe_widget  - embeddable HTML form
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from backend.tools import tool, RiskTier
from backend import business_db


_NEWSLETTER_DIR = Path("./storage/newsletters")
_NEWSLETTER_DIR.mkdir(parents=True, exist_ok=True)


def _cred(key: str) -> Optional[str]:
    try:
        from backend.services.credentials_vault import credentials_vault
        return credentials_vault.get(key) or None
    except Exception:
        return None


@tool(
    name="newsletter.spec",
    description="Define a new newsletter: niche, audience, cadence, monetization. Returns spec + 12-issue editorial calendar.",
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "niche": {"type": "string"},
            "audience": {"type": "string"},
            "cadence": {"type": "string", "default": "weekly", "enum": ["daily", "weekly", "biweekly", "monthly"]},
            "language": {"type": "string", "default": "ar", "enum": ["ar", "en", "both"]},
            "monetization": {"type": "string", "default": "free", "enum": ["free", "paid_subscription", "sponsored", "affiliate"]},
        },
        "required": ["name", "niche"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="newsletter",
)
async def newsletter_spec(
    name: str, niche: str, audience: str = "", cadence: str = "weekly",
    language: str = "ar", monetization: str = "free",
) -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    sys_prompt = (
        f"You are a senior newsletter strategist. Design a 12-issue editorial calendar in {'Arabic' if language == 'ar' else 'English'}. "
        "Output STRICT JSON: {\"positioning\": string, \"value_proposition\": string, \"target_reader\": string, "
        "\"editorial_calendar\": [{\"issue\": integer, \"title\": string, \"outline\": string}]}"
    )
    try:
        reply = await llm_service.get_response(
            user_message=f"Name: {name}\nNiche: {niche}\nAudience: {audience}\nCadence: {cadence}",
            system_instructions=sys_prompt, inject_memory=False,
        )
        text = reply.strip().lstrip("`").rstrip("`")
        if text.startswith("json"): text = text[4:]
        parsed = json.loads(text)
        path = _NEWSLETTER_DIR / f"{name.lower().replace(' ', '_')}_spec.json"
        path.write_text(json.dumps(parsed, indent=2, ensure_ascii=False), encoding="utf-8")
        return {"ok": True, "name": name, "niche": niche, "spec_path": str(path), "spec": parsed}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="newsletter.write_issue",
    description="Write a full newsletter issue for a given topic.",
    parameters={
        "type": "object",
        "properties": {
            "newsletter_name": {"type": "string"},
            "issue_topic": {"type": "string"},
            "word_count": {"type": "integer", "default": 800},
            "language": {"type": "string", "default": "ar"},
            "tone": {"type": "string", "default": "insightful + practical"},
            "include_research": {"type": "boolean", "default": True},
        },
        "required": ["newsletter_name", "issue_topic"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="newsletter",
)
async def newsletter_write_issue(
    newsletter_name: str, issue_topic: str, word_count: int = 800,
    language: str = "ar", tone: str = "insightful + practical", include_research: bool = True,
) -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    # Optional: pull research from web plugin.
    research = ""
    if include_research:
        try:
            from plugins.web.plugin import web_extract_article, web_wikipedia
            # Just use Wikipedia for grounding.
            wiki = await web_wikipedia(query=issue_topic, lang=language)
            if wiki.get("ok"):
                research = f"Wikipedia context: {wiki.get('text', '')[:1500]}"
        except Exception:
            pass
    sys_prompt = (
        f"You are the editor of '{newsletter_name}'. Write this issue in {'Arabic' if language == 'ar' else 'English'}. "
        f"Tone: {tone}. Word count: ~{word_count}. Format: subject line + greeting + 3 sections + CTA. "
        "Output Markdown only."
    )
    user_msg = f"Topic: {issue_topic}\n\nResearch:\n{research}\n"
    try:
        issue = await llm_service.get_response(
            user_message=user_msg, system_instructions=sys_prompt, inject_memory=False,
        )
        fname = f"{newsletter_name.lower().replace(' ', '_')}_{datetime.utcnow().strftime('%Y%m%d')}.md"
        path = _NEWSLETTER_DIR / fname
        path.write_text(issue, encoding="utf-8")
        return {"ok": True, "issue_path": str(path), "chars": len(issue)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="newsletter.publish_substack",
    description="Publish an issue to Substack. Substack has limited API — uses SMTP-style post-by-email.",
    parameters={
        "type": "object",
        "properties": {
            "issue_path": {"type": "string"},
            "substack_post_email": {"type": "string", "description": "Your Substack post-by-email address (find in Substack settings)."},
        },
        "required": ["issue_path", "substack_post_email"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="newsletter",
)
async def newsletter_publish_substack(issue_path: str, substack_post_email: str) -> Dict[str, Any]:
    if not Path(issue_path).is_file():
        return {"ok": False, "error": "issue not found"}
    text = Path(issue_path).read_text(encoding="utf-8")
    # Use the first line as subject.
    lines = text.splitlines()
    subject = lines[0].lstrip("# ").strip() or f"Issue {datetime.utcnow().date()}"
    body = "\n".join(lines[1:]).strip()
    from plugins.communication.plugin import email_send
    return await email_send(to=substack_post_email, subject=subject, body=body)


@tool(
    name="newsletter.publish_beehiiv",
    description="Publish to beehiiv (free up to 2.5k subs). Requires beehiiv_api_key + publication_id in vault.",
    parameters={
        "type": "object",
        "properties": {
            "issue_path": {"type": "string"},
            "title": {"type": "string"},
        },
        "required": ["issue_path", "title"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="newsletter",
)
async def newsletter_publish_beehiiv(issue_path: str, title: str) -> Dict[str, Any]:
    key = _cred("beehiiv_api_key")
    pub_id = _cred("beehiiv_publication_id")
    if not (key and pub_id):
        return {"ok": False, "error": "beehiiv_api_key + beehiiv_publication_id missing"}
    if not Path(issue_path).is_file():
        return {"ok": False, "error": "issue not found"}
    content = Path(issue_path).read_text(encoding="utf-8")
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"https://api.beehiiv.com/v2/publications/{pub_id}/posts",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "title": title,
                    "content": content,
                    "content_html": f"<pre>{content}</pre>",
                    "status": "confirmed",
                    "audience": "free",
                    "publish_platforms": {"none": True},
                },
            )
        if resp.status_code >= 400:
            return {"ok": False, "status": resp.status_code, "error": resp.text[:300]}
        return {"ok": True, "post_id": resp.json().get("id"), "title": title}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="newsletter.find_sponsors",
    description="Find potential sponsors for a newsletter niche + generate cold-outreach emails.",
    parameters={
        "type": "object",
        "properties": {
            "newsletter_name": {"type": "string"},
            "niche": {"type": "string"},
            "subscriber_count": {"type": "integer", "default": 500},
            "open_rate_pct": {"type": "number", "default": 35},
            "rate_per_sponsorship_usd": {"type": "number", "default": 100},
        },
        "required": ["newsletter_name", "niche"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="newsletter",
)
async def newsletter_find_sponsors(
    newsletter_name: str, niche: str, subscriber_count: int = 500,
    open_rate_pct: float = 35, rate_per_sponsorship_usd: float = 100,
) -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    from plugins.sales.plugin import sales_find_leads
    # Find 20 candidate sponsors in the niche.
    leads = await sales_find_leads(niche=niche, location="United States", limit=20)
    sponsors = leads.get("leads", []) if leads.get("ok") else []

    # Generate outreach template.
    sys_prompt = (
        "Write a sponsor outreach email for a newsletter. Be specific. "
        "Output STRICT JSON: {\"subject\": string, \"body\": string}"
    )
    try:
        reply = await llm_service.get_response(
            user_message=(
                f"Newsletter: {newsletter_name}\nNiche: {niche}\n"
                f"Subscribers: {subscriber_count}\nOpen rate: {open_rate_pct}%\n"
                f"Rate: ${rate_per_sponsorship_usd}/issue"
            ),
            system_instructions=sys_prompt, inject_memory=False,
        )
        text = reply.strip().lstrip("`").rstrip("`")
        if text.startswith("json"): text = text[4:]
        parsed = json.loads(text)
    except Exception as e:
        return {"ok": False, "error": str(e)}

    return {
        "ok": True,
        "newsletter": newsletter_name,
        "potential_sponsors": sponsors[:10],
        "outreach_email": parsed,
        "media_kit": {
            "subscribers": subscriber_count, "open_rate_pct": open_rate_pct,
            "rate_per_sponsorship_usd": rate_per_sponsorship_usd,
        },
    }


@tool(
    name="newsletter.archive_compile",
    description="Compile all past issues into an ebook (markdown + HTML).",
    parameters={
        "type": "object",
        "properties": {
            "newsletter_name": {"type": "string"},
            "output_path": {"type": "string", "default": ""},
        },
        "required": ["newsletter_name"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="newsletter",
)
async def newsletter_archive_compile(newsletter_name: str, output_path: str = "") -> Dict[str, Any]:
    pattern = f"{newsletter_name.lower().replace(' ', '_')}_*.md"
    issues = sorted(_NEWSLETTER_DIR.glob(pattern))
    if not issues:
        return {"ok": False, "error": "no issues found"}
    combined = f"# {newsletter_name} — Annual Archive\n\n"
    for fp in issues:
        combined += f"\n\n## {fp.stem}\n\n" + fp.read_text(encoding="utf-8")
    out = output_path or str(_NEWSLETTER_DIR / f"{newsletter_name.lower().replace(' ', '_')}_archive.md")
    Path(out).write_text(combined, encoding="utf-8")
    return {"ok": True, "path": out, "issues": len(issues), "chars": len(combined)}


@tool(
    name="newsletter.subscribe_widget",
    description="Generate an embeddable HTML subscribe form for a newsletter.",
    parameters={
        "type": "object",
        "properties": {
            "newsletter_name": {"type": "string"},
            "submit_url": {"type": "string", "default": "#", "description": "Form action URL (Mailchimp, beehiiv, ConvertKit, etc.)."},
            "language": {"type": "string", "default": "ar", "enum": ["ar", "en"]},
        },
        "required": ["newsletter_name"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="newsletter",
)
async def newsletter_subscribe_widget(newsletter_name: str, submit_url: str = "#", language: str = "ar") -> Dict[str, Any]:
    is_ar = language == "ar"
    html = f"""<div dir="{'rtl' if is_ar else 'ltr'}" style="max-width:480px;margin:auto;font-family:Tajawal,Arial,sans-serif;padding:24px;border:1px solid #ddd;border-radius:8px">
  <h3>{newsletter_name}</h3>
  <p>{"اشترك ليصلك جديدنا أسبوعياً" if is_ar else "Subscribe for weekly updates"}</p>
  <form action="{submit_url}" method="POST">
    <input type="email" name="email" placeholder="{"بريدك الإلكتروني" if is_ar else "Your email"}" required
           style="width:100%;padding:10px;margin:6px 0;border:1px solid #ccc;border-radius:4px">
    <button type="submit" style="width:100%;padding:12px;background:#4f46e5;color:white;border:none;border-radius:4px;cursor:pointer">
      {"اشترك الآن" if is_ar else "Subscribe"}
    </button>
  </form>
</div>"""
    return {"ok": True, "html": html}


PLUGIN_NAME = "newsletter"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Newsletter empire: spec, write, publish (Substack/beehiiv), find sponsors, archive."
