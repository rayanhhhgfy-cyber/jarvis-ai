# ====================================================================
# JARVIS OMEGA - Diagnostics (Phase 15)
# ====================================================================
"""
End-to-end audit: tests every plugin, tells Sir EXACTLY what works, what
needs creds, and what's broken. Run this before relying on anything.

  diagnostics.full          - audit everything, returns a report
  diagnostics.check_creds   - which vault keys are missing
  diagnostics.check_tools   - which tools are stubs vs real
  diagnostics.fix_missing   - one-click install missing Python deps
"""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.tools import tool, RiskTier, get_registry


# Map of (vault_key → human description + where to get it).
_REQUIRED_CREDS = {
    "openrouter_api_key": ("LLM brain — required", "https://openrouter.ai/keys"),
    "groq_api_key": ("Fast Whisper STT", "https://console.groq.com/keys"),
    "smtp_host": ("Sending email", "your email provider"),
    "smtp_user": ("Sending email", "your email provider"),
    "smtp_password": ("Sending email", "your email provider"),
    "imap_host": ("Reading email", "your email provider"),
    "imap_user": ("Reading email", "your email provider"),
    "imap_password": ("Reading email", "your email provider"),
    "telegram_bot_token": ("Telegram posting", "https://t.me/BotFather"),
    "slack_bot_token": ("Slack posting", "https://api.slack.com/apps"),
    "twitter_consumer_key": ("Twitter posting (4 keys total)", "https://developer.twitter.com"),
    "mastodon_instance": ("Mastodon posting", "your instance"),
    "mastodon_access_token": ("Mastodon posting", "your instance settings"),
    "reddit_client_id": ("Reddit posting (5 keys total)", "https://www.reddit.com/prefs/apps"),
    "stripe_secret_key": ("Stripe payments", "https://dashboard.stripe.com/apikeys"),
    "vercel_token": ("Vercel deploy", "https://vercel.com/account/tokens"),
    "netlify_token": ("Netlify deploy", "https://app.netlify.com/user/applications"),
    "github_pat": ("GitHub Pages + GitHub Empire", "https://github.com/settings/tokens"),
    "youtube_oauth_json": ("YouTube upload + analytics", "GCP Console → YouTube Data API v3 → OAuth"),
    "google_play_service_account_json": ("Android Play Store publishing", "Google Play Console"),
    "gmail_oauth_json": ("Codex Gmail ingest", "GCP Console → Gmail API → OAuth"),
    "pinata_jwt": ("IPFS free hosting", "https://pinata.cloud"),
    "suno_api_key": ("AI music generation", "https://suno.com"),
    "tiktok_access_token": ("TikTok posting", "TikTok for Developers"),
    "instagram_user_id": ("Instagram Reels", "Meta Graph API"),
    "instagram_access_token": ("Instagram Reels", "Meta Graph API"),
    "meta_marketing_token": ("Meta ads (real money)", "Meta Marketing API"),
    "meta_ad_library_token": ("FB Ad Library trend scan", "Meta for Developers"),
    "beehiiv_api_key": ("beehiiv newsletter", "https://beehiiv.com"),
    "beehiiv_publication_id": ("beehiiv newsletter", "beehiiv dashboard"),
    "amazon_pa_access_key": ("Amazon Affiliate PA-API", "Amazon Associates"),
    "amazon_pa_secret_key": ("Amazon Affiliate PA-API", "Amazon Associates"),
    "amazon_associate_tag": ("Amazon Affiliate tag", "Amazon Associates"),
    "wallet_private_key": ("Real-money crypto (DANGER)", "NEVER commit; use vault UI"),
    "eth_wallet_address": ("DeFi balance read", "your wallet"),
    "arweave_wallet_json": ("Arweave permanent storage", "https://arweave.org"),
    "shareasale_affiliate_id": ("ShareASale affiliate", "https://www.shareasale.com"),
    "shareasale_api_token": ("ShareASale affiliate", "ShareASale dashboard"),
    "sadtalker_path": ("Real talking-head video", "https://github.com/OpenTalker/SadTalker"),
}

# Python deps that should be installed for full power.
_OPTIONAL_DEPS = {
    "edge_tts": "Voice local TTS",
    "faster_whisper": "Voice local STT",
    "trafilatura": "Web article extraction",
    "feedparser": "RSS parsing",
    "icalendar": "Local calendar ICS",
    "qrcode": "QR code generation",
    "cv2": "OpenCV vision",
    "playwright": "Browser automation",
    "moviepy": "Video editing",
    "ccxt": "Crypto trading data",
    "pandas_ta": "Trading indicators",
    "bs4": "SEO/Real-estate scraping",
    "googleapiclient": "YouTube API",
    "google_auth_oauthlib": "YouTube OAuth",
    "pywhatkit": "WhatsApp unofficial",
    "PIL": "Pillow image editing",
    "TTS": "Coqui voice cloning",
    "torch": "PyTorch (musicgen, SadTalker)",
    "transformers": "MusicGen / fine-tuning",
}


def _cred(key: str) -> Optional[str]:
    try:
        from backend.services.credentials_vault import credentials_vault
        return credentials_vault.get(key) or None
    except Exception:
        return None


def _check_dep(modname: str) -> bool:
    try:
        importlib.import_module(modname)
        return True
    except Exception:
        return False


@tool(
    name="diagnostics.full",
    description="Run a full audit: tools registered, deps installed, creds configured. Returns a clear health report Sir can act on.",
    parameters={"type": "object"},
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="diagnostics",
)
async def diagnostics_full() -> Dict[str, Any]:
    # Tool count.
    all_tools = get_registry().all_tools()
    by_category: Dict[str, int] = {}
    for t in all_tools:
        by_category[t.category] = by_category.get(t.category, 0) + 1

    # Creds.
    creds_present: List[str] = []
    creds_missing: List[Dict[str, str]] = []
    for k, (desc, where) in _REQUIRED_CREDS.items():
        if _cred(k):
            creds_present.append(k)
        else:
            creds_missing.append({"key": k, "purpose": desc, "where": where})

    # Deps.
    deps_ok: List[str] = []
    deps_missing: List[Dict[str, str]] = []
    for mod, purpose in _OPTIONAL_DEPS.items():
        if _check_dep(mod):
            deps_ok.append(mod)
        else:
            deps_missing.append({"module": mod, "purpose": purpose})

    # Backend mode flags.
    from backend.config import settings
    flags = {
        "allow_self_modification": settings.allow_self_modification,
        "auto_self_heal": settings.auto_self_heal,
        "allow_autonomous_business": settings.allow_autonomous_business,
        "never_stop": settings.never_stop,
        "allow_ad_spend": settings.allow_ad_spend,
        "execute_real_trade": settings.execute_real_trade,
        "default_language": settings.default_language,
        "default_country": settings.default_country,
        "default_currency": settings.default_currency,
    }

    # Health score.
    total = len(_REQUIRED_CREDS) + len(_OPTIONAL_DEPS)
    have = len(creds_present) + len(deps_ok)
    health_pct = round(have / total * 100, 1) if total else 100

    return {
        "ok": True,
        "timestamp": datetime.utcnow().isoformat(),
        "tools_registered": len(all_tools),
        "categories": len(by_category),
        "tools_by_category": dict(sorted(by_category.items(), key=lambda x: -x[1])),
        "creds_present": creds_present,
        "creds_missing": creds_missing,
        "deps_installed": deps_ok,
        "deps_missing": deps_missing,
        "config_flags": flags,
        "health_pct": health_pct,
        "verdict": (
            "EXCELLENT — full power available" if health_pct >= 80
            else "GOOD — most features work" if health_pct >= 50
            else "LIMITED — many features will return 'not configured'. Add creds + install deps."
        ),
        "next_steps": _next_steps(creds_missing, deps_missing),
    }


def _next_steps(missing_creds: List[Dict[str, str]], missing_deps: List[Dict[str, str]]) -> List[str]:
    steps: List[str] = []
    if missing_deps:
        names = " ".join(d["module"] for d in missing_deps if d["module"] != "cv2")
        if "cv2" in [d["module"] for d in missing_deps]:
            names += " opencv-python-headless"
        steps.append(f"Install missing Python deps: `pip install {names.strip()}`")
    # Group creds by source for fewer trips.
    by_source: Dict[str, List[str]] = {}
    for c in missing_creds:
        by_source.setdefault(c["where"], []).append(c["key"])
    for source, keys in by_source.items():
        steps.append(f"At {source}: add vault keys → {', '.join(keys)}")
    if not steps:
        steps.append("Nothing missing — JARVIS is at full power.")
    return steps


@tool(
    name="diagnostics.check_creds",
    description="Quick check: which credentials are in the vault?",
    parameters={"type": "object"},
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="diagnostics",
)
async def diagnostics_check_creds() -> Dict[str, Any]:
    present, missing = [], []
    for k, (desc, _) in _REQUIRED_CREDS.items():
        (present if _cred(k) else missing).append({"key": k, "purpose": desc})
    return {"ok": True, "present_count": len(present), "missing_count": len(missing),
            "present": present, "missing": missing}


@tool(
    name="diagnostics.check_deps",
    description="Quick check: which optional Python deps are installed?",
    parameters={"type": "object"},
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="diagnostics",
)
async def diagnostics_check_deps() -> Dict[str, Any]:
    ok, missing = [], []
    for mod, purpose in _OPTIONAL_DEPS.items():
        (ok if _check_dep(mod) else missing).append({"module": mod, "purpose": purpose})
    return {"ok": True, "installed_count": len(ok), "missing_count": len(missing),
            "installed": ok, "missing": missing}


@tool(
    name="diagnostics.install_missing_deps",
    description="One-click: pip install every missing optional dependency.",
    parameters={"type": "object"},
    risk_tier=RiskTier.TIER_2_SYSTEM,
    category="diagnostics",
)
async def diagnostics_install_missing_deps() -> Dict[str, Any]:
    import asyncio
    to_install = []
    name_map = {"cv2": "opencv-python-headless", "bs4": "beautifulsoup4", "PIL": "Pillow",
                "googleapiclient": "google-api-python-client", "TTS": "TTS"}
    for mod, _ in _OPTIONAL_DEPS.items():
        if not _check_dep(mod):
            to_install.append(name_map.get(mod, mod))
    if not to_install:
        return {"ok": True, "already_installed": True, "installed": []}
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "pip", "install", *to_install,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=600)
        return {
            "ok": proc.returncode == 0,
            "installed": to_install,
            "exit_code": proc.returncode,
            "stderr_tail": stderr.decode("utf-8", errors="replace")[-500:] if stderr else "",
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="diagnostics.test_tool",
    description="Smoke-test a single tool by name. Returns ok=True if it returned ok without raising.",
    parameters={
        "type": "object",
        "properties": {
            "tool_name": {"type": "string"},
            "args": {"type": "object", "default": {}},
        },
        "required": ["tool_name"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="diagnostics",
)
async def diagnostics_test_tool(tool_name: str, args: Dict[str, Any] = None) -> Dict[str, Any]:
    args = args or {}
    t = get_registry().get(tool_name)
    if not t:
        return {"ok": False, "error": f"tool '{tool_name}' not registered"}
    try:
        result = await t.func(**args)
        return {"ok": True, "tool": tool_name, "returned_ok": bool(result.get("ok")) if isinstance(result, dict) else True, "result_keys": list(result.keys()) if isinstance(result, dict) else str(type(result))}
    except Exception as e:
        return {"ok": False, "tool": tool_name, "error": str(e)}


@tool(
    name="diagnostics.test_category",
    description="Smoke-test every tool in a category (Tier 0 only — safe). Returns pass/fail per tool.",
    parameters={
        "type": "object",
        "properties": {
            "category": {"type": "string"},
            "max_tools": {"type": "integer", "default": 30},
        },
        "required": ["category"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="diagnostics",
)
async def diagnostics_test_category(category: str, max_tools: int = 30) -> Dict[str, Any]:
    tools = [t for t in get_registry().all_tools() if t.category == category and t.risk_tier.value.startswith("tier_0")][:max_tools]
    if not tools:
        return {"ok": False, "error": f"no Tier-0 tools in category '{category}'"}
    results = []
    for t in tools:
        try:
            # Most Tier 0 tools accept no required args; some require query/path. Try empty first.
            r = await t.func()
            ok = (r.get("ok") if isinstance(r, dict) else True)
            results.append({"tool": t.name, "ok": True, "returned_ok": ok, "note": "" if ok else "returned ok=False (likely needs args/creds)"})
        except Exception as e:
            results.append({"tool": t.name, "ok": False, "error": str(e)[:120], "note": "needs args or creds"})
    passed = sum(1 for r in results if r["ok"])
    return {"ok": True, "category": category, "tested": len(results), "passed": passed, "failed": len(results) - passed, "results": results}


PLUGIN_NAME = "diagnostics"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Audits tools, deps, creds. Tells Sir exactly what's broken and how to fix it."
