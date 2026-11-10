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
* One-to-one threads AND group chats. Never replies to Sir's own
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

# Words that mark a message as important — when someone says it is
# important, Sir gets a louder alert (the push title says so).
_IMPORTANT_MARKERS = (
    "important", "urgent", "asap", "emergency", "critical",
    "مهم", "ضروري", "عاجل", "طارئ", "مهم جدا", "مهم جداً",
)


def _is_important(text: str) -> bool:
    """True when the sender says the message is important/urgent."""
    lowered = (text or "").lower()
    return any(marker in lowered for marker in _IMPORTANT_MARKERS)


def _vip_names() -> list[str]:
    """VIP contact names from config (comma-separated), lowercased."""
    return [
        n.strip().lower()
        for n in (settings.dm_vip_contacts or "").split(",")
        if n.strip()
    ]


def _is_vip(sender_name: str) -> bool:
    """True when the sender is one of Sir's VIP contacts."""
    name = (sender_name or "").lower()
    if not name:
        return False
    return any(vip in name or name in vip for vip in _vip_names())


# Words that mark a message as tricky — money, payments, or anything
# sensitive enough that Jarvis should draft, not auto-reply.
_TRICKY_MARKERS = (
    "money", "pay", "payment", "price", "cost", "buy", "sell",
    "send money", "transfer", "borrow", "lend", "debt", "owe",
    "فلوس", "ادفع", "ادفعلي", "سعر", "اشتري", "بيع", "حوّل", "حوالة",
    "دين", "قرض",
)


def _is_tricky(text: str) -> bool:
    """True when the message is about money or otherwise sensitive."""
    lowered = (text or "").lower()
    return any(marker in lowered for marker in _TRICKY_MARKERS)


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
        # "While you were away" feed: the last 20 DM replies, newest first.
        # In-memory only (Render's disk is wiped on every redeploy) — it is
        # a dashboard convenience, not a record.
        self._activity: list[dict[str, Any]] = []
        # Nudges: when Jarvis first replied to each thread, and which
        # threads already got a "still waiting" nudge (one per thread).
        self._first_reply_at: dict[str, dict[str, datetime]] = {}
        self._nudged: set[str] = set()
        # Drafts for tricky messages: thread_id -> the pending draft.
        # Jarvis does not auto-reply to these; Sir approves on Telegram.
        self._pending_drafts: dict[str, dict[str, Any]] = {}

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

    def get_activity(self, limit: int = 20) -> list[dict[str, Any]]:
        """Recent DM replies for the dashboard 'While you were away' feed."""
        return list(self._activity[: max(1, limit)])

    def get_pending_draft(self) -> dict[str, Any] | None:
        """The most recent tricky-message draft awaiting Sir's approval."""
        if not self._pending_drafts:
            return None
        # Most recently added draft (dicts preserve insertion order).
        return next(reversed(self._pending_drafts.values()))

    async def send_draft_reply(self, thread_id: str, text: str) -> dict[str, Any]:
        """Send Sir's approved (or edited) reply for a pending draft.

        Looks up the draft's platform + thread, sends via that platform's
        client, marks the thread seen + introduced, and clears the draft.
        Returns {"ok": True} or {"ok": False, "reason": ...}.
        """
        draft = self._pending_drafts.get(thread_id)
        if not draft:
            return {"ok": False, "reason": "no_draft"}
        platform = draft["platform"]
        blob = dm_auth.load_connector(platform)
        if not blob:
            return {"ok": False, "reason": "no_connector"}
        data = blob.get("data") or {}
        try:
            client = self._build_client(platform, blob.get("method"), data)
            await client.send(thread_id, text)
        except Exception as e:
            return {"ok": False, "reason": "send_failed", "error": str(e)}
        self._mark_seen(platform, thread_id, draft["message_id"])
        self._introduced.setdefault(platform, {})[thread_id] = True
        self._clear_pending(platform, thread_id)
        self._pending_drafts.pop(thread_id, None)
        self._persist_state()
        self._state[platform]["replied"] += 1
        self._record_activity(platform, draft, text, important=True)
        return {"ok": True, "platform": platform, "sender_name": draft["sender_name"]}

    async def send_dm_to_name(self, name: str, text: str) -> dict[str, Any]:
        """Send a DM to a person by name (Sir asked Jarvis to message them).

        Searches recent threads on both platforms for a sender whose name
        matches (case-insensitive substring). Returns {"ok": True, ...}
        or {"ok": False, "reason": "not_found"}.
        """
        needle = (name or "").strip().lower()
        if not needle or not text.strip():
            return {"ok": False, "reason": "bad_request"}
        for platform in dm_auth.PLATFORMS:
            blob = dm_auth.load_connector(platform)
            if not blob:
                continue
            data = blob.get("data") or {}
            try:
                client = self._build_client(platform, blob.get("method"), data)
                if platform == "messenger":
                    valid = await client.validate()
                else:
                    valid = await asyncio.to_thread(client.validate)
                if not valid:
                    continue
                threads = await client.list_recent(limit=10)
            except Exception as e:
                log.warning("dm_send_to_name_failed", platform=platform, error=str(e))
                continue
            for msg in threads or []:
                sender = (msg.get("sender_name") or "").lower()
                if needle in sender or sender in needle:
                    thread_id = msg["thread_id"]
                    try:
                        await client.send(thread_id, text)
                    except Exception as e:
                        return {"ok": False, "reason": "send_failed", "error": str(e)}
                    self._mark_seen(platform, thread_id, msg["message_id"])
                    self._introduced.setdefault(platform, {})[thread_id] = True
                    self._clear_pending(platform, thread_id)
                    self._persist_state()
                    self._state[platform]["replied"] += 1
                    self._record_activity(platform, msg, text, important=False)
                    return {
                        "ok": True,
                        "platform": platform,
                        "sender_name": msg["sender_name"],
                        "thread_id": thread_id,
                    }
        return {"ok": False, "reason": "not_found"}

    async def send_daily_digest(self) -> bool:
        """Send Sir the evening digest of today's DM activity on Telegram.

        Returns True when a digest was sent. Sends nothing when there
        was no activity (no noise) or Telegram is not configured.
        """
        activity = self.get_activity(limit=20)
        if not activity:
            return False
        lines = ["📬 Jarvis — today's DMs:"]
        for entry in reversed(activity):
            sender = entry.get("sender_name", "")
            plat = entry.get("platform", "")
            flag = " ⚠️" if entry.get("important") else ""
            lines.append(f"- {sender} ({plat}){flag}: {entry.get('text', '')[:60]}")
        needs_sir = [
            e for e in activity
            if e.get("important") or (e.get("reply") or "").strip() == ""
        ]
        if needs_sir:
            lines.append("")
            lines.append("Needs you:")
            for entry in needs_sir[:5]:
                lines.append(f"- {entry.get('sender_name', '')}: {entry.get('text', '')[:80]}")
        try:
            from backend.services.telegram_notifier import send_telegram_message

            return await send_telegram_message("\n".join(lines))
        except Exception as e:
            log.debug("dm_digest_failed", error=str(e))
            return False

    async def _maybe_nudge(
        self, platform: str, thread_id: str, sender_name: str
    ) -> None:
        """Ping Sir on Telegram when someone has been waiting too long.

        Fires once per thread: when Jarvis's first reply in a thread is
        older than ``dm_nudge_after_hours`` and the person is still
        talking to Jarvis (i.e. Sir has not stepped in), Sir gets one
        Telegram nudge. Never fires twice for the same thread.
        """
        key = f"{platform}:{thread_id}"
        if key in self._nudged:
            return
        first_at = self._first_reply_at.get(platform, {}).get(thread_id)
        if not first_at:
            return
        waited = (datetime.now(UTC) - first_at).total_seconds() / 3600.0
        if waited < max(0.5, settings.dm_nudge_after_hours):
            return
        self._nudged.add(key)
        try:
            from backend.services.telegram_notifier import send_telegram_message

            await send_telegram_message(
                f"⏰ {sender_name} is still waiting — they messaged again "
                f"and you have not replied yet. Check your DMs when you can."
            )
        except Exception as e:
            log.debug("dm_nudge_failed", error=str(e))

    def _record_activity(
        self,
        platform: str,
        msg: dict[str, Any],
        reply: str,
        important: bool,
    ) -> None:
        """Prepend one reply to the activity feed (kept to the last 20)."""
        text = (msg.get("text") or "")
        if not text and msg.get("media_type") == "photo":
            text = "[photo]"
        elif not text and msg.get("media_type") == "voice":
            text = "[voice note]"
        self._activity.insert(0, {
            "time": datetime.now(UTC).isoformat(),
            "platform": platform,
            "sender_name": msg.get("sender_name", ""),
            "text": text[:300],
            "reply": (reply or "")[:300],
            "important": important,
            "is_group": bool(msg.get("is_group")),
        })
        del self._activity[20:]

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
        # Catch-up: on a fresh start the seen-state is empty (the disk file
        # is wiped on every Render redeploy), so every old thread looks
        # "new" and the responder would introduce itself to the whole
        # inbox. Mark all current threads as seen WITHOUT replying, so
        # only messages that arrive AFTER startup get replies.
        await self._catch_up()
        self._task = asyncio.create_task(self._loop())
        log.info("dm_responder_started", interval=settings.dm_poll_interval_seconds)

    async def _catch_up(self) -> None:
        """Mark every existing thread as seen + introduced, without replying."""
        for platform in dm_auth.PLATFORMS:
            blob = dm_auth.load_connector(platform)
            if not blob:
                continue
            data = blob.get("data") or {}
            method = blob.get("method")
            try:
                client = self._build_client(platform, method, data)
                if platform == "messenger":
                    valid = await client.validate()
                else:
                    valid = await asyncio.to_thread(client.validate)
                if not valid:
                    continue
                threads = await client.list_recent(limit=10)
            except Exception as e:
                log.warning("dm_catch_up_failed", platform=platform, error=str(e))
                continue
            for msg in threads or []:
                thread_id = msg["thread_id"]
                self._mark_seen(platform, thread_id, msg["message_id"])
                self._introduced.setdefault(platform, {})[thread_id] = True
            self._persist_state()

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
                if not msg.get("text"):
                    continue
                thread_id = msg["thread_id"]
                if client.user_id and str(msg.get("sender_id")) == str(client.user_id):
                    continue  # Sir answered this thread himself.
                if self._introduced.get(platform, {}).get(thread_id):
                    continue  # Already introduced — not a first reply.
                gen = await generate_dm_reply(
                    platform,
                    msg["sender_name"],
                    msg["text"],
                    first_reply=True,
                    is_group=bool(msg.get("is_group")),
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
                await self._notify_new_dm(
                    platform, msg, important=_is_important(msg.get("text") or ""),
                    reply=gen["reply"],
                )
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
            # A message counts when it has text OR media (photo / voice).
            # Text-less media used to be skipped entirely — now Jarvis
            # sees the photo or hears the voice note and replies.
            if not msg.get("text") and not msg.get("media_url"):
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
            is_vip = _is_vip(msg.get("sender_name", ""))
            if first_reply and not is_vip:
                # The one-minute rule: give Sir a minute to answer a new
                # message himself. Record when it was first seen and wait;
                # a newer message restarts the clock. VIP contacts skip
                # the wait — they never wait on Sir.
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
            # Tricky message (money / sensitive): do NOT auto-reply.
            # Draft it and send the draft to Sir on Telegram for approval.
            if _is_tricky(msg.get("text") or "") and thread_id not in self._pending_drafts:
                gen = await generate_dm_reply(
                    platform,
                    msg["sender_name"],
                    msg["text"],
                    first_reply=first_reply,
                    is_group=bool(msg.get("is_group")),
                    media_url=msg.get("media_url"),
                    media_type=msg.get("media_type"),
                )
                if gen.get("ok"):
                    self._pending_drafts[thread_id] = {
                        "platform": platform,
                        "thread_id": thread_id,
                        "message_id": msg["message_id"],
                        "sender_name": msg.get("sender_name", ""),
                        "text": msg.get("text") or "",
                        "draft_reply": gen["reply"],
                    }
                    try:
                        from backend.services.telegram_notifier import (
                            send_telegram_message,
                        )

                        await send_telegram_message(
                            f"⚠️ {msg.get('sender_name', '')} said:\n"
                            f"{msg.get('text') or ''}\n\n"
                            f"Draft reply (I did NOT send it):\n{gen['reply']}\n\n"
                            "Reply 'send' to send it as-is, or type your own "
                            "reply and I will send that instead."
                        )
                    except Exception as e:
                        log.debug("dm_draft_notify_failed", error=str(e))
                self._mark_seen(platform, thread_id, msg["message_id"])
                self._persist_state()
                continue
            # Generate + send the reply.
            gen = await generate_dm_reply(
                platform,
                msg["sender_name"],
                msg["text"],
                first_reply=first_reply,
                is_group=bool(msg.get("is_group")),
                media_url=msg.get("media_url"),
                media_type=msg.get("media_type"),
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
            if first_reply:
                self._first_reply_at.setdefault(platform, {})[thread_id] = datetime.now(UTC)
            else:
                await self._maybe_nudge(platform, thread_id, msg.get("sender_name", ""))
            replied += 1
            self._state[platform]["replied"] += 1
            # VIP contacts always get a loud alert, even without the words.
            await self._notify_new_dm(
                platform, msg,
                important=_is_important(msg.get("text") or "") or is_vip,
                reply=gen["reply"],
            )
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

    async def _notify_new_dm(
        self, platform: str, msg: dict[str, Any], important: bool = False,
        reply: str = "",
    ) -> None:
        """Tell Sir Jarvis answered a DM — push, Telegram, and the activity feed.

        The push carries the sender, what they said, AND what Jarvis
        replied, so Sir sees the whole exchange at a glance. When the
        sender said the message is important, the push title says so
        loudly. The same story also goes to Sir on Telegram when it is
        configured, where he can answer back.
        """
        self._record_activity(platform, msg, reply, important)
        name = dm_auth.PLATFORMS[platform]["name"]
        sender = msg.get("sender_name", "")
        incoming = (msg.get("text") or "")[:80]
        try:
            from backend.notification_engine import notification_engine
            from shared.models import Notification

            title = (
                f"JARVIS — رسالة مهمة من {name} ⚠️"
                if important
                else f"JARVIS — رد على رسالة {name}"
            )
            body = f"{sender}: {incoming}"
            if reply:
                body += f"\nJarvis: {reply[:120]}"
            await notification_engine.send_notification(Notification(
                title=title,
                body=body,
                category="dm_reply",
                data={
                    "platform": platform,
                    "thread_id": msg.get("thread_id", ""),
                    "important": important,
                    "reply": reply[:300],
                },
            ))
        except Exception as e:
            log.debug("dm_push_notify_failed", error=str(e))
        try:
            from backend.services.telegram_notifier import send_telegram_message

            group = " (group)" if msg.get("is_group") else ""
            text = (
                f"💬 {name}{group} — {sender} wrote:\n"
                f"{incoming}"
            )
            if reply:
                text += f"\n\nJarvis replied:\n{reply[:300]}"
            if important:
                text = "⚠️ IMPORTANT — " + text
            await send_telegram_message(text)
        except Exception as e:
            log.debug("dm_telegram_notify_failed", error=str(e))


# Process-wide singleton
dm_responder = DMResponder()
