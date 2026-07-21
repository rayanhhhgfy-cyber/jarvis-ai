# ====================================================================
# JARVIS OMEGA - Marketing Plugin (Phase 11)
# ====================================================================
"""
Multi-platform marketing: content generation, scheduling, and posting.

Platforms supported (all free):
  * Twitter / X        - direct API v2 with bearer token in vault
  * Mastodon           - any instance, access token in vault
  * Reddit             - script-app OAuth (free)
  * LinkedIn           - "share URL" approach (opens browser); official
                         API requires business verification
  * Discord / Telegram - reuse webhooks from Phase 8 communication plugin
  * Email              - reuse existing email.send (SMTP)

Every post is logged to the ``posts`` table with status / engagement /
error info, so Sir can see exactly what's been published and what's queued.

Content generation uses the existing OpenRouter LLM (free tier).
"""

from __future__ import annotations

import asyncio
import json
import urllib.parse
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import httpx

from backend.tools import tool, RiskTier
from backend import business_db
from backend.config import settings
from shared.logger import get_logger

log = get_logger("marketing")


def _cred(key: str) -> Optional[str]:
    try:
        from backend.services.credentials_vault import credentials_vault
        return credentials_vault.get(key) or None
    except Exception:
        return None


# --------------------------------------------------------------------
# Content generation
# --------------------------------------------------------------------

@tool(
    name="marketing.create_content",
    description="Generate social-media content for a topic. Returns 1-3 variants with hashtags. Uses the existing OpenRouter LLM.",
    parameters={
        "type": "object",
        "properties": {
            "topic": {"type": "string"},
            "platform": {"type": "string", "enum": ["twitter", "linkedin", "reddit", "blog", "email"], "default": "twitter"},
            "tone": {"type": "string", "default": "professional", "description": "e.g. 'professional', 'playful', 'urgent', 'inspirational'"},
            "variants": {"type": "integer", "default": 3},
            "include_cta": {"type": "boolean", "default": True},
            "max_length": {"type": "integer", "default": 280},
        },
        "required": ["topic"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="marketing",
)
async def marketing_create_content(
    topic: str, platform: str = "twitter", tone: str = "professional",
    variants: int = 3, include_cta: bool = True, max_length: int = 280,
) -> Dict[str, Any]:
    from backend.services.llm_service import llm_service

    platform_hints = {
        "twitter": f"Tweet style, max {max_length} chars. Punchy hook + value.",
        "linkedin": "Professional post, 3-5 short paragraphs, leadership tone.",
        "reddit": "Reddit post: title + body. Conversational, no marketing speak.",
        "blog": "Long-form blog post intro (300-500 words).",
        "email": "Marketing email: subject + preview + body. Personal tone.",
    }
    sys_prompt = (
        f"You are JARVIS, a senior content marketer. Platform: {platform}. "
        f"Tone: {tone}. {platform_hints.get(platform, '')}\n"
        f"Output STRICT JSON: {{\"variants\": [{{\"content\": string, \"hashtags\": [string, ...]}}]}}.\n"
        f"Emit {variants} variants. Include 3-6 hashtags where appropriate. "
        f"{'End with a clear CTA.' if include_cta else 'No CTA.'}\n"
        "Do NOT wrap in markdown fences."
    )
    try:
        reply = await llm_service.get_response(
            user_message=f"Topic: {topic}",
            system_instructions=sys_prompt,
            inject_memory=False,
        )
    except Exception as e:
        return {"ok": False, "error": f"LLM call failed: {e}"}

    # Parse JSON (tolerate fences / trailing prose).
    cleaned = reply.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        # Salvage largest {...} block.
        start = cleaned.find("{")
        if start == -1:
            return {"ok": False, "error": "LLM did not return JSON", "raw": cleaned[:300]}
        depth = 0
        for i in range(start, len(cleaned)):
            if cleaned[i] == "{":
                depth += 1
            elif cleaned[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        parsed = json.loads(cleaned[start:i + 1])
                        break
                    except json.JSONDecodeError:
                        return {"ok": False, "error": "LLM JSON unparseable", "raw": cleaned[:300]}
        else:
            return {"ok": False, "error": "LLM JSON unparseable", "raw": cleaned[:300]}

    out = parsed.get("variants", [])
    return {
        "ok": True,
        "topic": topic,
        "platform": platform,
        "tone": tone,
        "count": len(out),
        "variants": out,
    }


@tool(
    name="marketing.hashtag_research",
    description="Suggest high-relevance hashtags for a topic. Uses LLM (no paid keyword API).",
    parameters={
        "type": "object",
        "properties": {
            "topic": {"type": "string"},
            "count": {"type": "integer", "default": 15},
        },
        "required": ["topic"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="marketing",
)
async def marketing_hashtag_research(topic: str, count: int = 15) -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    try:
        reply = await llm_service.get_response(
            user_message=f"Topic: {topic}",
            system_instructions=(
                f"Suggest {count} effective hashtags for this topic. Output STRICT JSON: "
                "{\"hashtags\": [\"#tag1\", \"#tag2\", ...]}. Mix popular and niche tags. No prose."
            ),
            inject_memory=False,
        )
    except Exception as e:
        return {"ok": False, "error": str(e)}
    cleaned = reply.strip().lstrip("`").rstrip("`")
    if cleaned.startswith("json"):
        cleaned = cleaned[4:]
    try:
        parsed = json.loads(cleaned)
        return {"ok": True, "topic": topic, "hashtags": parsed.get("hashtags", [])[:count]}
    except json.JSONDecodeError:
        return {"ok": False, "error": "LLM did not return valid JSON", "raw": reply[:300]}


# --------------------------------------------------------------------
# Multi-platform posting
# --------------------------------------------------------------------

async def _twitter_post(text: str) -> Dict[str, Any]:
    """Twitter / X v2 — needs twitter_bearer_token + twitter_consumer_key + secret in vault."""
    bearer = _cred("twitter_bearer_token")
    consumer_key = _cred("twitter_consumer_key")
    consumer_secret = _cred("twitter_consumer_secret")
    access_token = _cred("twitter_access_token")
    access_secret = _cred("twitter_access_token_secret")
    if not all([consumer_key, consumer_secret, access_token, access_secret]):
        return {"ok": False, "error": "Twitter OAuth credentials missing in vault"}
    try:
        # Use OAuth 1.0a user-context (free tier allows 1,500 posts/month).
        from requests_oauthlib import OAuth1  # type: ignore
        import requests
        auth = OAuth1(consumer_key, consumer_secret, access_token, access_secret)
        resp = requests.post(
            "https://api.twitter.com/2/tweets",
            json={"text": text},
            auth=auth,
            timeout=30,
        )
        if resp.status_code >= 400:
            return {"ok": False, "status": resp.status_code, "error": resp.text[:300]}
        data = resp.json()
        return {"ok": True, "external_id": data.get("data", {}).get("id")}
    except ImportError:
        return {"ok": False, "error": "requests-oauthlib not installed"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def _mastodon_post(text: str, media_path: str = "") -> Dict[str, Any]:
    """Mastodon — needs mastodon_instance + mastodon_access_token in vault."""
    instance = _cred("mastodon_instance")  # e.g. https://mastodon.social
    token = _cred("mastodon_access_token")
    if not (instance and token):
        return {"ok": False, "error": "Mastodon instance / access token missing in vault"}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{instance.rstrip('/')}/api/v1/statuses",
                data={"status": text, "visibility": "public"},
                headers={"Authorization": f"Bearer {token}"},
            )
        if resp.status_code >= 400:
            return {"ok": False, "status": resp.status_code, "error": resp.text[:300]}
        return {"ok": True, "external_id": resp.json().get("id")}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def _reddit_post(title: str, body: str, subreddit: str) -> Dict[str, Any]:
    """Reddit - needs reddit_client_id + secret + username + password + user_agent in vault."""
    client_id = _cred("reddit_client_id")
    secret = _cred("reddit_client_secret")
    username = _cred("reddit_username")
    password = _cred("reddit_password")
    user_agent = _cred("reddit_user_agent") or "JARVIS-OMEGA/1.0 by /u/" + (username or "jarvis")
    if not all([client_id, secret, username, password]):
        return {"ok": False, "error": "Reddit credentials missing in vault"}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            # OAuth token
            tok = await client.post(
                "https://www.reddit.com/api/v1/access_token",
                data={"grant_type": "password", "username": username, "password": password},
                auth=(client_id, secret),
                headers={"User-Agent": user_agent},
            )
            if tok.status_code >= 400:
                return {"ok": False, "error": f"OAuth failed: {tok.text[:200]}"}
            access = tok.json().get("access_token")
            if not access:
                return {"ok": False, "error": "no access token in OAuth response"}
            # Submit
            resp = await client.post(
                "https://oauth.reddit.com/api/submit",
                data={
                    "kind": "self",
                    "sr": subreddit,
                    "title": title,
                    "text": body,
                },
                headers={
                    "Authorization": f"Bearer {access}",
                    "User-Agent": user_agent,
                },
            )
            if resp.status_code >= 400:
                return {"ok": False, "status": resp.status_code, "error": resp.text[:300]}
            data = resp.json()
            if not data.get("success"):
                return {"ok": False, "error": f"reddit rejected: {data}"}
            return {"ok": True, "external_id": data.get("json", {}).get("data", {}).get("id")}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def _linkedin_share(url: str, title: str, summary: str = "") -> Dict[str, Any]:
    """LinkedIn - returns the share URL Sir can open. (Full API needs business verification.)"""
    share = (
        f"https://www.linkedin.com/sharing/share-offsite/?url={urllib.parse.quote(url, safe='')}"
    )
    return {
        "ok": True,
        "share_url": share,
        "title": title,
        "summary": summary,
        "note": "Open this URL in a browser to post. LinkedIn's official API requires business verification.",
    }


async def _discord_post(webhook_name: str, text: str) -> Dict[str, Any]:
    url = _cred(webhook_name)
    if not url:
        return {"ok": False, "error": f"{webhook_name} not in vault"}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json={"content": text})
        if resp.status_code >= 400:
            return {"ok": False, "status": resp.status_code, "error": resp.text[:300]}
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def _telegram_post(chat_id: str, text: str) -> Dict[str, Any]:
    token = _cred("telegram_bot_token")
    if not token:
        return {"ok": False, "error": "telegram_bot_token not in vault"}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text},
            )
        if resp.status_code >= 400:
            return {"ok": False, "status": resp.status_code, "error": resp.text[:300]}
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def _email_post(to: str, subject: str, body: str) -> Dict[str, Any]:
    """Send via the existing SMTP tool."""
    from plugins.communication.plugin import email_send
    return await email_send(to=to, subject=subject, body=body)


# --------------------------------------------------------------------
# Unified posting tool
# --------------------------------------------------------------------

@tool(
    name="marketing.post",
    description="Post content to one or more platforms. Persists to the posts table with status. Supported: twitter, mastodon, reddit, linkedin, discord, telegram, email.",
    parameters={
        "type": "object",
        "properties": {
            "platform": {
                "type": "string",
                "enum": ["twitter", "mastodon", "reddit", "linkedin", "discord", "telegram", "email"],
            },
            "content": {"type": "string", "description": "Main text / body of the post."},
            "title": {"type": "string", "default": "", "description": "Required for reddit / email subject."},
            "subreddit": {"type": "string", "default": "", "description": "Required for reddit."},
            "webhook_name": {"type": "string", "default": "discord_webhook_general", "description": "Vault key for Discord webhook (Discord only)."},
            "chat_id": {"type": "string", "default": "", "description": "Telegram chat ID (Telegram only)."},
            "to": {"type": "string", "default": "", "description": "Recipient email (email only)."},
            "url": {"type": "string", "default": "", "description": "Shared URL (LinkedIn)."},
            "campaign_id": {"type": "integer", "default": 0, "description": "Optional: link to a campaign."},
        },
        "required": ["platform", "content"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="marketing",
)
async def marketing_post(
    platform: str, content: str, title: str = "", subreddit: str = "",
    webhook_name: str = "discord_webhook_general", chat_id: str = "",
    to: str = "", url: str = "", campaign_id: int = 0,
) -> Dict[str, Any]:
    # Dispatch
    result: Dict[str, Any]
    if platform == "twitter":
        result = await _twitter_post(content)
    elif platform == "mastodon":
        result = await _mastodon_post(content)
    elif platform == "reddit":
        if not subreddit:
            return {"ok": False, "error": "reddit posts require 'subreddit'"}
        result = await _reddit_post(title=title or content[:80], body=content, subreddit=subreddit)
    elif platform == "linkedin":
        if not url:
            return {"ok": False, "error": "linkedin posts require 'url' (the share-URL approach)"}
        result = await _linkedin_share(url=url, title=title, summary=content)
    elif platform == "discord":
        result = await _discord_post(webhook_name, content)
    elif platform == "telegram":
        if not chat_id:
            return {"ok": False, "error": "telegram posts require 'chat_id'"}
        result = await _telegram_post(chat_id, content)
    elif platform == "email":
        if not to:
            return {"ok": False, "error": "email posts require 'to'"}
        result = await _email_post(to=to, subject=title or "(no subject)", body=content)
    else:
        return {"ok": False, "error": f"unknown platform: {platform}"}

    # Persist to posts table
    status = "posted" if result.get("ok") else "failed"
    try:
        business_db.execute(
            """INSERT INTO posts (campaign_id, platform, content, scheduled_at, posted_at,
                                  external_id, status, error, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                campaign_id or None, platform, content,
                datetime.utcnow().isoformat(),
                datetime.utcnow().isoformat() if result.get("ok") else None,
                result.get("external_id"),
                status,
                result.get("error"),
                datetime.utcnow().isoformat(),
            ),
        )
        business_db.audit("post", "marketing", target=platform,
                          details={"content_len": len(content), "ok": result.get("ok")})
    except Exception as db_err:
        log.warning("post_persist_failed", error=str(db_err))

    return result


@tool(
    name="marketing.schedule",
    description="Schedule a post for later (stored as 'scheduled' status; the scheduler job publishes it).",
    parameters={
        "type": "object",
        "properties": {
            "platform": {"type": "string"},
            "content": {"type": "string"},
            "scheduled_at": {"type": "string", "description": "ISO 8601 datetime in UTC."},
            "title": {"type": "string", "default": ""},
            "subreddit": {"type": "string", "default": ""},
            "campaign_id": {"type": "integer", "default": 0},
        },
        "required": ["platform", "content", "scheduled_at"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="marketing",
)
async def marketing_schedule(
    platform: str, content: str, scheduled_at: str,
    title: str = "", subreddit: str = "", campaign_id: int = 0,
) -> Dict[str, Any]:
    try:
        dt = datetime.fromisoformat(scheduled_at)
    except ValueError as e:
        return {"ok": False, "error": f"invalid scheduled_at: {e}"}
    post_id = business_db.execute(
        """INSERT INTO posts (campaign_id, platform, content, title, subreddit, scheduled_at, status, created_at)
           VALUES (?, ?, ?, ?, ?, ?, 'scheduled', ?)""",
        (campaign_id or None, platform, content, title, subreddit,
         dt.isoformat(), datetime.utcnow().isoformat()),
    )
    return {"ok": True, "post_id": post_id, "scheduled_at": dt.isoformat()}


@tool(
    name="marketing.list_posts",
    description="List recent posts (optionally filter by status).",
    parameters={
        "type": "object",
        "properties": {
            "status": {"type": "string", "default": ""},
            "limit": {"type": "integer", "default": 20},
        },
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="marketing",
)
async def marketing_list_posts(status: str = "", limit: int = 20) -> Dict[str, Any]:
    sql = "SELECT id, platform, content, status, scheduled_at, posted_at, external_id, error FROM posts"
    params: tuple = ()
    if status:
        sql += " WHERE status = ?"
        params = (status,)
    sql += " ORDER BY id DESC LIMIT ?"
    params = params + (limit,)
    rows = business_db.rows_to_dicts(business_db.query(sql, params))
    return {"ok": True, "count": len(rows), "posts": rows}


@tool(
    name="marketing.create_campaign",
    description="Create a marketing campaign row in the DB.",
    parameters={
        "type": "object",
        "properties": {
            "client_id": {"type": "integer", "default": 0},
            "name": {"type": "string"},
            "platform": {"type": "string", "default": "twitter"},
            "objective": {"type": "string", "default": "awareness"},
            "start_date": {"type": "string", "default": ""},
            "end_date": {"type": "string", "default": ""},
            "budget": {"type": "number", "default": 0},
            "notes": {"type": "string", "default": ""},
        },
        "required": ["name"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="marketing",
)
async def marketing_create_campaign(
    client_id: int = 0, name: str = "", platform: str = "twitter",
    objective: str = "awareness", start_date: str = "", end_date: str = "",
    budget: float = 0, notes: str = "",
) -> Dict[str, Any]:
    cid = business_db.execute(
        """INSERT INTO campaigns (client_id, name, platform, objective, start_date, end_date, budget, notes, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (client_id or None, name, platform, objective, start_date or None, end_date or None,
         budget, notes, datetime.utcnow().isoformat()),
    )
    return {"ok": True, "campaign_id": cid, "name": name}


PLUGIN_NAME = "marketing"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Multi-platform marketing: content gen, scheduling, posting (Twitter/Mastodon/Reddit/LinkedIn/Discord/Telegram/Email)."
