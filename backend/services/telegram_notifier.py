# ====================================================================
# JARVIS OMEGA — Telegram Notifier (Jarvis talks to Sir directly)
# ====================================================================
"""
Sends Telegram messages to Sir and registers the bot webhook.

Why Telegram: it is the one free, phone-first channel where Jarvis can
reach Sir proactively — a push notification is a one-line alert, but a
Telegram message can carry the whole story (who wrote, what they said,
what Jarvis replied) and Sir can answer back in the same thread.

Setup (Sir's steps, once):
1. In Telegram, open @BotFather, send /newbot, pick a name + username.
   BotFather returns a bot token.
2. Start a chat with the new bot (tap Start) and send any message.
3. Open @userinfobot to get Sir's own Telegram user id (the chat id).
4. Set TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID in the Render env vars.
   The token never goes in chat, files, or the repo.

Both settings are read from env at call time (never cached), so a
redeploy picks them up. When either is unset, every function here is a
silent no-op — Telegram is an extra channel, never a hard dependency.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx

from backend.config import settings
from shared.logger import get_logger

log = get_logger("telegram_notifier")

_TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"
_DEFAULT_BASE_URL = "https://jarvis-ai-6c11.onrender.com"

# Every slash command the bot understands, in one place. The router uses
# this for /help and for translating commands into the natural-language
# intents the webhook already handles; set_telegram_commands() registers
# the same list with Telegram so the commands show in the app's menu.
# Keep descriptions short — Telegram shows them in the command picker.
TELEGRAM_COMMANDS: list[dict[str, str]] = [
    {"command": "start", "description": "Start Jarvis and see all commands",
     "usage": "/start"},
    {"command": "help", "description": "List every command Jarvis understands",
     "usage": "/help"},
    {"command": "send", "description": "Send a DM for you",
     "usage": "/send Omar I'll be there at 5"},
    {"command": "summarize", "description": "Summarize a conversation",
     "usage": "/summarize Omar"},
    {"command": "schedule", "description": "Schedule a DM for later",
     "usage": "/schedule Omar tomorrow at 5pm: I'll be there"},
    {"command": "remind", "description": "Set a reminder for yourself",
     "usage": "/remind call Omar tomorrow at 5pm"},
    {"command": "busy", "description": "Tell Jarvis you're busy",
     "usage": "/busy Friday 5pm-8pm because football practice"},
    {"command": "free", "description": "Tell Jarvis you're free",
     "usage": "/free Saturday"},
    {"command": "remember", "description": "Remember something about someone",
     "usage": "/remember Omar loves football"},
    {"command": "search", "description": "Search your DMs",
     "usage": "/search book"},
    {"command": "rules", "description": "List your auto-reply rules",
     "usage": "/rules"},
    {"command": "addrule", "description": "Add an auto-reply rule",
     "usage": "/addrule Omar | money | I'll check with Rayyan"},
    {"command": "delrule", "description": "Delete a rule by number",
     "usage": "/delrule 2"},
    {"command": "unmute", "description": "Unmute a muted conversation",
     "usage": "/unmute Omar"},
    {"command": "block", "description": "Stop Jarvis DMing someone until further notice",
     "usage": "/block Omar"},
    {"command": "unblock", "description": "Let Jarvis DM someone again",
     "usage": "/unblock Omar"},
    {"command": "rule", "description": "Save a standing rule to Jarvis's permanent memory",
     "usage": "/rule always answer me in Arabic"},
    {"command": "lesson", "description": "Save a lesson so Jarvis never repeats a mistake",
     "usage": "/lesson don't send the summary before I approve it"},
    {"command": "memory", "description": "Search Jarvis's permanent memory (Obsidian vault)",
     "usage": "/memory [words]"},
    {"command": "birthdaymsg", "description": "Set the birthday wish Jarvis sends",
     "usage": "/birthdaymsg Happy birthday {name}!"},
    {"command": "welcomemsg", "description": "Set the group welcome message",
     "usage": "/welcomemsg Welcome {name}!"},
    {"command": "activity", "description": "What happened while you were away",
     "usage": "/activity"},
    {"command": "briefing", "description": "Show or change your morning briefing",
     "usage": "/briefing"},
    {"command": "status", "description": "Check what's connected and running",
     "usage": "/status"},
    {"command": "cancel", "description": "Cancel a pending draft or meeting",
     "usage": "/cancel"},
    {"command": "responder", "description": "Turn the DM auto-replies on or off",
     "usage": "/responder on"},
    {"command": "connect", "description": "Connect Instagram, Messenger, GitHub or Vercel",
     "usage": "/connect instagram"},
    {"command": "disconnect", "description": "Disconnect Instagram, Messenger, GitHub or Vercel",
     "usage": "/disconnect instagram"},
    {"command": "github", "description": "Your GitHub: repos, issues, PRs, commits, open an issue",
     "usage": "/github repos"},
    {"command": "vercel", "description": "Your Vercel: projects, deployments, redeploy",
     "usage": "/vercel projects"},
    {"command": "call", "description": "Jarvis calls you — tap the link to answer",
     "usage": "/call"},
]

# True once set_telegram_commands() has succeeded at least once on this
# instance (so /api/telegram/status can report it without the token).
_commands_registered = False


def commands_registered() -> bool:
    """Whether the command menu has been registered with Telegram."""
    return _commands_registered


def _configured() -> tuple[str, str] | None:
    """(token, chat_id) when Telegram is configured, else None."""
    token = (settings.telegram_bot_token or "").strip()
    chat_id = (settings.telegram_chat_id or "").strip()
    if not token or not chat_id:
        return None
    return token, chat_id


async def send_telegram_message(
    text: str, client: httpx.AsyncClient | None = None
) -> bool:
    """Send one Telegram message to Sir. Returns True when Telegram accepted it.

    Never raises. When Telegram is not configured, returns False.
    """
    configured = _configured()
    if not configured:
        log.debug("telegram_not_configured")
        return False
    token, chat_id = configured
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=15.0)
    assert client is not None
    try:
        resp = await client.post(
            _TELEGRAM_API.format(token=token, method="sendMessage"),
            json={"chat_id": chat_id, "text": text},
        )
        if resp.status_code != 200:
            log.warning("telegram_send_failed", status_code=resp.status_code)
            return False
        return bool(resp.json().get("ok"))
    except Exception as e:
        log.warning("telegram_send_error", error=str(e))
        return False
    finally:
        if own_client:
            await client.aclose()


async def download_telegram_file(
    file_id: str, client: httpx.AsyncClient | None = None
) -> bytes | None:
    """Download a Telegram file's bytes (voice note, photo, video).

    Calls getFile for the file path, then downloads the file. Returns
    None on any failure. Never raises, and never logs the file URL —
    it carries the bot token, so only status codes are logged.
    """
    configured = _configured()
    if not configured or not file_id:
        return None
    token, _chat_id = configured
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=30.0)
    assert client is not None
    try:
        resp = await client.post(
            _TELEGRAM_API.format(token=token, method="getFile"),
            json={"file_id": file_id},
        )
        if resp.status_code != 200:
            log.warning("telegram_get_file_failed", status_code=resp.status_code)
            return None
        result = resp.json().get("result") or {}
        file_path = result.get("file_path") or ""
        if not file_path:
            log.warning("telegram_get_file_no_path")
            return None
        download = await client.get(
            f"https://api.telegram.org/file/bot{token}/{file_path}"
        )
        if download.status_code != 200:
            log.warning("telegram_file_download_failed", status_code=download.status_code)
            return None
        return download.content
    except Exception:
        log.warning("telegram_file_download_error")
        return None
    finally:
        if own_client:
            await client.aclose()


async def send_telegram_voice(
    audio_path: str, client: httpx.AsyncClient | None = None
) -> bool:
    """Send one Telegram voice message to Sir from an .ogg Opus file.

    Telegram voice messages must be OGG encoded with OPUS (see
    dm_voice._mp3_to_ogg). Returns True when Telegram accepted it.
    Never raises. When Telegram is not configured, returns False.
    """
    configured = _configured()
    if not configured:
        log.debug("telegram_not_configured")
        return False
    token, chat_id = configured
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=30.0)
    assert client is not None
    try:
        data = await asyncio.to_thread(Path(audio_path).read_bytes)
        resp = await client.post(
            _TELEGRAM_API.format(token=token, method="sendVoice"),
            data={"chat_id": chat_id},
            files={"voice": ("voice.ogg", data, "audio/ogg")},
        )
        if resp.status_code != 200:
            log.warning("telegram_voice_send_failed", status_code=resp.status_code)
            return False
        return bool(resp.json().get("ok"))
    except Exception as e:
        log.warning("telegram_voice_send_error", error=str(e))
        return False
    finally:
        if own_client:
            await client.aclose()


async def set_telegram_commands(
    client: httpx.AsyncClient | None = None,
) -> bool:
    """Register the bot's slash-command menu with Telegram (setMyCommands).

    Sends TELEGRAM_COMMANDS so Sir sees every command in the app's menu
    with its description. Returns True when Telegram accepted them.
    Never raises. When the token is unset, returns False.
    """
    global _commands_registered
    token = (settings.telegram_bot_token or "").strip()
    if not token:
        log.debug("telegram_commands_no_token")
        return False
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=15.0)
    assert client is not None
    try:
        resp = await client.post(
            _TELEGRAM_API.format(token=token, method="setMyCommands"),
            json={"commands": [
                {"command": c["command"], "description": c["description"]}
                for c in TELEGRAM_COMMANDS
            ]},
        )
        if resp.status_code != 200:
            log.warning("telegram_commands_failed", status_code=resp.status_code)
            return False
        ok = bool(resp.json().get("ok"))
        if ok:
            _commands_registered = True
            log.info("telegram_commands_set", count=len(TELEGRAM_COMMANDS))
        return ok
    except Exception as e:
        log.warning("telegram_commands_error", error=str(e))
        return False
    finally:
        if own_client:
            await client.aclose()


async def set_telegram_webhook(
    base_url: str = "", client: httpx.AsyncClient | None = None
) -> bool:
    """Register the bot webhook so Sir can reply to Jarvis on Telegram.

    ``base_url`` is the public backend URL; empty = the live Render URL.
    Returns True when Telegram accepted the webhook. Never raises.
    """
    token = (settings.telegram_bot_token or "").strip()
    if not token:
        log.debug("telegram_webhook_no_token")
        return False
    url = (base_url or settings.telegram_webhook_base_url or _DEFAULT_BASE_URL).rstrip("/")
    webhook_url = f"{url}/api/telegram/webhook"
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=15.0)
    assert client is not None
    try:
        resp = await client.post(
            _TELEGRAM_API.format(token=token, method="setWebhook"),
            json={"url": webhook_url},
        )
        if resp.status_code != 200:
            log.warning("telegram_webhook_failed", status_code=resp.status_code)
            return False
        ok = bool(resp.json().get("ok"))
        if ok:
            log.info("telegram_webhook_set", url=webhook_url)
        return ok
    except Exception as e:
        log.warning("telegram_webhook_error", error=str(e))
        return False
    finally:
        if own_client:
            await client.aclose()
