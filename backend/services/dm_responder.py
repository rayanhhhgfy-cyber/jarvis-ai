# ====================================================================
# JARVIS OMEGA — DM Responder (background service)
# ====================================================================
"""
Polls Sir's connected Messenger + Instagram accounts for new incoming
DMs, generates a reply with the free LLM (Groq Llama 3.3 70B primary,
Gemini 2.5 Flash fallback) and sends it as Sir.

Rules, by design:
* Only runs when ``DM_RESPONDER_ENABLED=true`` in env AND at least one
  connector is connected. Default is OFF.
* It works on its own, on the server: each poll opens the recent
  threads, replies, and is done — Sir never has to open Instagram or
  Messenger himself for Jarvis to answer.
* Only one-to-one threads (never groups), never replies to Sir's own
  messages, never replies twice to the same message (seen-state file).
* The one-minute rule: when a friend messages and Sir has not answered
  within one minute, Jarvis replies. The first reply in a conversation
  introduces Jarvis, says Sir is busy and cannot respond right now, and
  invites the friend to tell Jarvis if it is important — Jarvis will
  make sure Sir sees it. Follow-ups keep the conversation going
  back-and-forth (no re-introduction) and answer promptly, still
  stepping aside the moment Sir replies himself.
* At most 5 replies per platform per poll, so a flood can never turn
  into a spam run.
* Every failure is logged and surfaced in status; the loop never dies
  silently. A new DM also fires a Web Push notification so Sir knows
  Jarvis answered — that push is how Jarvis reports back to him.
* Credentials are read from the encrypted connector vault at poll time
  (cookies/session preferred when present, else email+password login).
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.config import settings
from backend.services import dm_auth
from backend.services.dm_clients import (
    DMClientError,
    InstagramClient,
    MessengerClient,
)
from backend.services.dm_llm import generate_dm_reply
from shared.logger import get_logger

log = get_logger("dm_responder")

_MAX_REPLIES_PER_POLL = 5
# Give Sir one minute to answer a new message himself before Jarvis
# steps in. (Polls run every dm_poll_interval_seconds, 60s by default,
# so the first reply lands roughly 1–2 minutes after their message.)
_REPLY_DELAY_SECONDS = 60
_SEEN_FILE = "./storage/dm_seen.json"


class DMResponder:
    """Background DM poller for the connected platforms."""

    def __init__(self, seen_path: str = _SEEN_FILE) -> None:
        self._seen_path = Path(seen_path)
        self._seen: dict[str, dict[str, str]] = {}  # platform -> thread_id -> message_id
        # Messages waiting out the one-minute rule:
        # platform -> thread_id -> {"message_id", "first_seen" (ISO time)}
        self._pending: dict[str, dict[str, dict[str, str]]] = {}
        # Threads where Jarvis already introduced itself:
        # platform -> thread_id -> True
        self._introduced: dict[str, dict[str, bool]] = {}
        self._task: asyncio.Task | None = None
        self._running = False
        self._state: dict[str, dict[str, Any]] = {
            p: {"last_poll": None, "last_error": None, "replied": 0, "degraded": False}
            for p in dm_auth.PLATFORMS
        }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._running

    def get_status(self) -> dict[str, Any]:
        return {
            "enabled": bool(settings.dm_responder_enabled),
            "running": self._running,
            "poll_interval_seconds": settings.dm_poll_interval_seconds,
            "platforms": {
                p: {
                    "connected": dm_auth.connector_status(p)["connected"],
                    **self._state[p],
                }
                for p in dm_auth.PLATFORMS
            },
        }

    async def start(self) -> None:
        """Start the poll loop (no-op unless enabled + a connector exists)."""
        if not settings.dm_responder_enabled:
            log.info("dm_responder_disabled_by_config")
            return
        if not any(dm_auth.connector_status(p)["connected"] for p in dm_auth.PLATFORMS):
            log.info("dm_responder_no_connectors_connected")
            return
        if self._running:
            return
        self._load_seen()
        self._running = True
        self._task = asyncio.create_task(self._loop())
        log.info("dm_responder_started", interval=settings.dm_poll_interval_seconds)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        log.info("dm_responder_stopped")

    async def _loop(self) -> None:
        while self._running:
            try:
                await self.poll_once()
            except Exception as e:
                log.error("dm_responder_poll_failed", error=str(e))
            await asyncio.sleep(max(15, settings.dm_poll_interval_seconds))

    # ------------------------------------------------------------------
    # One poll cycle
    # ------------------------------------------------------------------

    async def poll_once(self) -> dict[str, Any]:
        """Poll every connected platform once. Returns per-platform counts."""
        results: dict[str, Any] = {}
        for platform in dm_auth.PLATFORMS:
            if not dm_auth.connector_status(platform)["connected"]:
                results[platform] = {"skipped": True, "reason": "not connected"}
                continue
            try:
                results[platform] = await self._poll_platform(platform)
                self._state[platform]["last_error"] = None
                self._state[platform]["degraded"] = False
            except Exception as e:
                self._state[platform]["last_error"] = str(e)[:200]
                self._state[platform]["degraded"] = True
                log.error("dm_poll_platform_failed", platform=platform, error=str(e))
                results[platform] = {"ok": False, "error": str(e)[:200]}
            self._state[platform]["last_poll"] = datetime.now(UTC).isoformat()
        return results

    async def introduce_latest(self) -> dict[str, Any]:
        """Send the first-reply introduction to the most recent unseen DM.

        Used when Sir asks the dashboard chat to introduce Jarvis to the
        last person who messaged him. Skips the one-minute wait (Sir
        explicitly asked), but still only targets a thread where the last
        message is from the other person, is not a group, and Jarvis has
        not introduced itself yet. Marks the thread seen + introduced so
        the poll loop does not send a duplicate introduction.
        """
        any_connected = False
        session_error: dict[str, Any] | None = None
        for platform in dm_auth.PLATFORMS:
            blob = dm_auth.load_connector(platform)
            if not blob:
                continue
            any_connected = True
            data = blob.get("data") or {}
            method = blob.get("method")
            try:
                client = self._build_client(platform, method, data)
            except Exception as e:
                log.warning("dm_introduce_client_failed", platform=platform, error=str(e))
                session_error = session_error or {"platform": platform, "error": str(e)}
                continue
            try:
                if platform == "messenger":
                    valid = await client.validate()
                else:
                    valid = await asyncio.to_thread(client.validate)
            except Exception as e:
                log.warning("dm_introduce_validate_failed", platform=platform, error=str(e))
                session_error = session_error or {"platform": platform, "error": str(e)}
                continue
            if not valid:
                session_error = session_error or {
                    "platform": platform,
                    "error": f"{platform} session expired — reconnect in the Connectors tab.",
                }
                continue
            try:
                threads = await client.list_recent(limit=5)
            except Exception as e:
                log.warning("dm_introduce_list_failed", platform=platform, error=str(e))
                session_error = session_error or {"platform": platform, "error": str(e)}
                continue
            for msg in threads or []:
                if msg.get("is_group"):
                    continue
                if not msg.get("text"):
                    continue
                thread_id = msg["thread_id"]
                if client.user_id and str(msg.get("sender_id")) == str(client.user_id):
                    continue  # Sir answered this thread himself.
                if self._introduced.get(platform, {}).get(thread_id):
                    continue  # Already introduced — not a first reply.
                gen = await generate_dm_reply(
                    platform, msg["sender_name"], msg["text"], first_reply=True
                )
                if not gen.get("ok"):
                    return {"ok": False, "reason": "gen_failed", "error": gen.get("error")}
                try:
                    await client.send(thread_id, gen["reply"])
                except Exception as e:
                    return {"ok": False, "reason": "send_failed", "error": str(e)}
                self._mark_seen(platform, thread_id, msg["message_id"])
                self._introduced.setdefault(platform, {})[thread_id] = True
                self._clear_pending(platform, thread_id)
                self._persist_state()
                self._state[platform]["replied"] += 1
                await self._notify_new_dm(platform, msg)
                return {
                    "ok": True,
                    "platform": platform,
                    "sender_name": msg["sender_name"],
                    "thread_id": thread_id,
                }
        if session_error:
            return {"ok": False, "reason": "session_expired", **session_error}
        if not any_connected:
            return {"ok": False, "reason": "no_connector"}
        return {"ok": False, "reason": "no_unseen"}

    async def _poll_platform(self, platform: str) -> dict[str, Any]:
        blob = dm_auth.load_connector(platform)
        if not blob:
            return {"ok": False, "error": "no credentials stored"}
        data = blob.get("data") or {}
        method = blob.get("method")

        client = self._build_client(platform, method, data)
        if platform == "messenger":
            if not await client.validate():
                raise DMClientError("Messenger session expired — reconnect in the Connectors tab.")
        else:
            if not await asyncio.to_thread(client.validate):
                raise DMClientError("Instagram session expired — reconnect in the Connectors tab.")

        threads = await client.list_recent(limit=10)
        replied = 0
        for msg in threads:
            if replied >= _MAX_REPLIES_PER_POLL:
                break
            if msg.get("is_group"):
                continue
            if not msg.get("text"):
                continue
            thread_id = msg["thread_id"]
            if client.user_id and str(msg.get("sender_id")) == str(client.user_id):
                # Sir answered this thread himself — Jarvis stands down.
                self._clear_pending(platform, thread_id)
                continue
            seen_id = self._seen.get(platform, {}).get(thread_id)
            if seen_id == msg["message_id"]:
                self._clear_pending(platform, thread_id)
                continue
            first_reply = not self._introduced.get(platform, {}).get(thread_id)
            if first_reply:
                # The one-minute rule: give Sir a minute to answer a new
                # message himself. Record when it was first seen and wait;
                # a newer message restarts the clock.
                pending = self._pending.get(platform, {}).get(thread_id)
                if not pending or pending.get("message_id") != msg["message_id"]:
                    self._pending.setdefault(platform, {})[thread_id] = {
                        "message_id": msg["message_id"],
                        "first_seen": datetime.now(UTC).isoformat(),
                    }
                    self._persist_state()
                    continue
                try:
                    first_seen = datetime.fromisoformat(pending["first_seen"])
                except (KeyError, TypeError, ValueError):
                    first_seen = datetime.now(UTC)
                waited = (datetime.now(UTC) - first_seen).total_seconds()
                if waited < _REPLY_DELAY_SECONDS:
                    continue
            # Generate + send the reply.
            gen = await generate_dm_reply(
                platform, msg["sender_name"], msg["text"], first_reply=first_reply
            )
            if not gen.get("ok"):
                log.warning("dm_reply_gen_failed", platform=platform, error=gen.get("error"))
                continue
            try:
                await client.send(thread_id, gen["reply"])
            except Exception as e:
                log.warning("dm_reply_send_failed", platform=platform, error=str(e))
                continue
            self._mark_seen(platform, thread_id, msg["message_id"])
            self._introduced.setdefault(platform, {})[thread_id] = True
            self._clear_pending(platform, thread_id)
            replied += 1
            self._state[platform]["replied"] += 1
            await self._notify_new_dm(platform, msg)
        return {"ok": True, "threads_seen": len(threads), "replied": replied}

    def _build_client(self, platform: str, method: str | None, data: dict[str, Any]):
        """Build the platform client from the stored credential blob."""
        if platform == "messenger":
            cookies = data.get("cookies") or {}
            return MessengerClient(cookies=cookies)
        # Instagram: full instagrapi settings (from a password login) are
        # preferred — set_settings() restores the whole session. Cookies
        # alone fall back to login_by_sessionid(), which Instagram rejects
        # for browser/web sessions on the private API.
        cookies = data.get("cookies") or {}
        settings = data.get("settings") or {}
        return InstagramClient(session_cookies=cookies, settings=settings)

    # ------------------------------------------------------------------
    # Seen-state + notifications
    # ------------------------------------------------------------------

    def _load_seen(self) -> None:
        try:
            if self._seen_path.exists():
                data = json.loads(self._seen_path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and "seen" in data:
                    self._seen = data.get("seen") or {}
                    self._pending = data.get("pending") or {}
                    self._introduced = data.get("introduced") or {}
                elif isinstance(data, dict):
                    # Old flat format: the whole file was the seen map.
                    self._seen = data
        except Exception:
            self._seen = {}
            self._pending = {}
            self._introduced = {}

    def _persist_state(self) -> None:
        try:
            self._seen_path.parent.mkdir(parents=True, exist_ok=True)
            self._seen_path.write_text(json.dumps({
                "seen": self._seen,
                "pending": self._pending,
                "introduced": self._introduced,
            }), encoding="utf-8")
        except Exception as e:
            log.warning("dm_seen_persist_failed", error=str(e))

    def _clear_pending(self, platform: str, thread_id: str) -> None:
        if self._pending.get(platform, {}).pop(thread_id, None) is not None:
            if not self._pending[platform]:
                self._pending.pop(platform, None)
            self._persist_state()

    def _mark_seen(self, platform: str, thread_id: str, message_id: str) -> None:
        self._seen.setdefault(platform, {})[thread_id] = message_id
        self._persist_state()

    async def _notify_new_dm(self, platform: str, msg: dict[str, Any]) -> None:
        """Web Push so Sir knows Jarvis answered a DM."""
        try:
            from backend.notification_engine import notification_engine
            from shared.models import Notification

            name = dm_auth.PLATFORMS[platform]["name"]
            await notification_engine.send_notification(Notification(
                title=f"JARVIS — رد على رسالة {name}",
                body=f"{msg.get('sender_name', '')}: {(msg.get('text') or '')[:80]}",
                category="dm_reply",
                data={"platform": platform, "thread_id": msg.get("thread_id", "")},
            ))
        except Exception as e:
            log.debug("dm_push_notify_failed", error=str(e))


# Process-wide singleton
dm_responder = DMResponder()
