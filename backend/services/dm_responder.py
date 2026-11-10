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
from datetime import UTC, datetime, timedelta
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


def _contact_notes(sender_name: str) -> str | None:
    """The facts Sir recorded about this person, or None."""
    from backend.services.dm_store import contacts

    name = (sender_name or "").strip()
    if not name:
        return None
    # Match by full name or first name, case-insensitive.
    for stored_name, data in contacts.all().items():
        if (
            name.lower() == stored_name.lower()
            or name.lower() in stored_name.lower()
            or stored_name.lower() in name.lower()
        ):
            notes = (data or {}).get("notes", "")
            if notes:
                return notes
    return None


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


# Questions about when Sir will be back — Jarvis asks Sir first
# (he never guesses Sir's schedule).
_AWAY_MARKERS = (
    "when will he be back", "when is he back", "when will rayyan be back",
    "when is rayyan back", "when will he reply", "when will he answer",
    "when are you back", "when will you be back", "when will you reply",
    "متى بيرجع", "متى رح يرجع", "متى رح يرد", "متى بيرجع ريان",
    "وين ريان", "وينه ريان",
)


def _is_away_question(text: str) -> bool:
    """True when the sender asks when Sir will be back / reply."""
    lowered = (text or "").lower()
    return any(marker in lowered for marker in _AWAY_MARKERS)


# Questions about whether Sir is free — Jarvis checks his calendar.
_FREE_MARKERS = (
    "are you free", "is he free", "is rayyan free", "are you available",
    "is he available", "free on", "free tomorrow", "free friday",
    "free saturday", "free sunday", "free monday", "free tuesday",
    "free wednesday", "free thursday",
    "فاضي", "متفرغ", "فاضي بكرة", "فاضي اليوم",
)


def _is_availability_question(text: str) -> bool:
    """True when the sender asks whether Sir is free."""
    lowered = (text or "").lower()
    return any(marker in lowered for marker in _FREE_MARKERS)


def _match_rule(sender_name: str, text: str) -> str | None:
    """The reply of the first custom auto-reply rule that matches.

    A rule matches when the person is "anyone" or the sender's name
    contains the rule's person, AND the message contains the rule's
    topic (case-insensitive substring). Returns the rule's reply, or
    None when no rule matches.
    """
    from backend.services.dm_store import rules as rules_store

    sender = (sender_name or "").lower()
    lowered = (text or "").lower()
    for rule in rules_store.all().values():
        person = (rule.get("person") or "").lower()
        topic = (rule.get("topic") or "").lower()
        reply = rule.get("reply") or ""
        if not topic or not reply:
            continue
        person_ok = person in ("anyone", "anybody", "everyone") or (
            person and (person in sender or sender in person)
        )
        if person_ok and topic in lowered:
            return reply
    return None


# Meeting requests — someone wants to meet Sir in person.
_MEETING_MARKERS = (
    "can we meet", "let's meet", "lets meet", "want to meet",
    "meet up", "meet tomorrow", "meet on", "meet this week",
    "meet you", "see you in person", "hang out",
    "نلتقي", "نتقابل", "نلتقى", "نلتقي بكرة", "نلتقي غدا",
)


def _is_meeting_request(text: str) -> bool:
    """True when the sender asks to meet Sir in person."""
    lowered = (text or "").lower()
    return any(marker in lowered for marker in _MEETING_MARKERS)


# Titles that always get a formal tone.
_FORMAL_TITLES = ("mr.", "mrs.", "ms.", "dr.", "teacher", "أستاذ", "استاذ", "معلم", "دكتور")


def _contact_tone(sender_name: str) -> str | None:
    """'formal' or 'casual' for this person, or None (use the default).

    A contact's stored tone wins; otherwise a formal title (Mr., Dr.,
    teacher, أستاذ) means formal.
    """
    from backend.services.dm_store import contacts

    name = (sender_name or "").strip()
    if not name:
        return None
    for stored_name, data in contacts.all().items():
        if (
            name.lower() == stored_name.lower()
            or name.lower() in stored_name.lower()
            or stored_name.lower() in name.lower()
        ):
            tone = (data or {}).get("tone", "")
            if tone in ("formal", "casual"):
                return tone
    lowered = name.lower()
    if any(title in lowered for title in _FORMAL_TITLES):
        return "formal"
    return None


# Abusive / harassing words — Jarvis stops replying to these.
_ABUSIVE_MARKERS = (
    "idiot", "stupid", "shut up", "hate you", "kill yourself",
    "غبي", "احمق", "اخرس", "بكرهك", "كلب", "حمار",
)


def _is_abusive(text: str) -> bool:
    """True when the message is abusive or harassing."""
    lowered = (text or "").lower()
    return any(marker in lowered for marker in _ABUSIVE_MARKERS)


def _in_quiet_hours(now: datetime | None = None) -> bool:
    """True when the current time is inside the configured quiet hours."""
    now = now or datetime.now(UTC)
    # Quiet hours are in Sir's timezone (Asia/Amman).
    from zoneinfo import ZoneInfo

    local = now.astimezone(ZoneInfo("Asia/Amman"))
    start_s, end_s = settings.dm_quiet_hours_start, settings.dm_quiet_hours_end
    try:
        sh, sm = (int(x) for x in start_s.split(":"))
        eh, em = (int(x) for x in end_s.split(":"))
    except (ValueError, AttributeError):
        return False
    start_minutes = sh * 60 + sm
    end_minutes = eh * 60 + em
    now_minutes = local.hour * 60 + local.minute
    if start_minutes <= end_minutes:
        return start_minutes <= now_minutes < end_minutes
    # Overnight window (e.g. 23:00 -> 07:00).
    return now_minutes >= start_minutes or now_minutes < end_minutes


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
        # Spam filter: muted threads (thread_key -> sender name) and the
        # recent message timestamps per thread for rate detection.
        self._muted: dict[str, str] = {}
        self._msg_times: dict[str, list[datetime]] = {}
        # Quiet hours: threads that already got the "morning" reply
        # tonight (so he does not repeat it all night).
        self._quiet_replied: set[str] = set()

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

    # ------------------------------------------------------------------
    # Scheduled messages + reminders (Sir asks on Telegram)
    # ------------------------------------------------------------------

    def schedule_dm(self, name: str, text: str, when: datetime) -> dict[str, Any]:
        """Queue a DM to be sent at ``when``. Returns the stored entry."""
        import uuid

        from backend.services.dm_store import scheduled_dms

        entry_id = f"dm_{uuid.uuid4().hex[:8]}"
        scheduled_dms.set(entry_id, {
            "name": name, "text": text,
            "when": when.astimezone(UTC).isoformat(),
            "created": datetime.now(UTC).isoformat(),
        })
        return {"ok": True, "id": entry_id, "when": when}

    async def run_due_scheduled(self) -> int:
        """Send every scheduled DM whose time has come. Returns count sent."""
        from backend.services.dm_store import scheduled_dms

        now = datetime.now(UTC)
        sent = 0
        for entry_id, entry in scheduled_dms.all().items():
            try:
                when = datetime.fromisoformat(entry["when"])
            except (KeyError, TypeError, ValueError):
                scheduled_dms.delete(entry_id)
                continue
            if when > now:
                continue
            result = await self.send_dm_to_name(entry["name"], entry["text"])
            scheduled_dms.delete(entry_id)
            if result.get("ok"):
                sent += 1
        return sent

    def add_reminder(self, text: str, when: datetime) -> dict[str, Any]:
        """Queue a Telegram reminder for Sir at ``when``."""
        import uuid

        from backend.services.dm_store import reminders

        entry_id = f"rem_{uuid.uuid4().hex[:8]}"
        reminders.set(entry_id, {
            "text": text,
            "when": when.astimezone(UTC).isoformat(),
            "created": datetime.now(UTC).isoformat(),
        })
        return {"ok": True, "id": entry_id, "when": when}

    async def run_due_reminders(self) -> int:
        """Send every due reminder to Sir on Telegram. Returns count sent."""
        from backend.services.dm_store import reminders
        from backend.services.telegram_notifier import send_telegram_message

        now = datetime.now(UTC)
        sent = 0
        for entry_id, entry in reminders.all().items():
            try:
                when = datetime.fromisoformat(entry["when"])
            except (KeyError, TypeError, ValueError):
                reminders.delete(entry_id)
                continue
            if when > now:
                continue
            try:
                await send_telegram_message(f"⏰ Reminder: {entry['text']}")
                sent += 1
            except Exception as e:
                log.debug("dm_reminder_failed", error=str(e))
            reminders.delete(entry_id)
        return sent

    # ------------------------------------------------------------------
    # Spam filter + quiet hours + calendar + birthdays + search
    # ------------------------------------------------------------------

    def _is_spamming(self, thread_id: str) -> bool:
        """True when one thread sent too many messages in the window."""
        now = datetime.now(UTC)
        window = timedelta(minutes=max(1, settings.dm_spam_window_minutes))
        times = self._msg_times.setdefault(thread_id, [])
        times[:] = [t for t in times if now - t < window]
        times.append(now)
        return len(times) > max(1, settings.dm_spam_max_messages)

    def unmute_thread(self, name: str) -> bool:
        """Unmute a muted thread by sender name. Returns True if unmuted."""
        needle = (name or "").strip().lower()
        for key, sender in list(self._muted.items()):
            if needle in sender.lower() or needle in key.lower():
                del self._muted[key]
                return True
        return False

    def _calendar_answer(self, text: str) -> str | None:
        """Answer an availability question from Sir's Jarvis calendar.

        The calendar is a simple store Sir fills on Telegram ("I'm busy
        Friday 5pm-8pm"). Returns the answer text, or None when the
        calendar has nothing for that day.
        """
        from backend.services.dm_store import calendar as cal_store

        entries = cal_store.all()
        if not entries:
            return None
        # Find the day the sender is asking about.
        from backend.services.dm_time import parse_time

        when = parse_time(text)
        if not when:
            return None
        day_key = when.astimezone(UTC).date().isoformat()
        for entry in entries.values():
            if entry.get("date") == day_key:
                return (
                    f"Rayyan is {entry.get('status', 'busy')} on "
                    f"{when.strftime('%A')}"
                    + (f" ({entry.get('detail', '')})" if entry.get("detail") else "")
                    + "."
                )
        return None

    async def check_birthdays(self) -> int:
        """Send Sir a Telegram note for any contact birthday today/tomorrow."""
        from backend.services.dm_store import contacts
        from backend.services.telegram_notifier import send_telegram_message

        today = datetime.now(UTC).date()
        tomorrow = today + timedelta(days=1)
        sent = 0
        for name, data in contacts.all().items():
            birthday = (data or {}).get("birthday", "")
            if not birthday:
                continue
            try:
                month, day = (int(x) for x in birthday.split("-"))
            except (ValueError, AttributeError):
                continue
            for target, label in ((today, "today"), (tomorrow, "tomorrow")):
                if target.month == month and target.day == day:
                    try:
                        await send_telegram_message(
                            f"🎂 {name}'s birthday is {label}!"
                            + (" Want me to send them a birthday wish?"
                               if label == "today" else "")
                        )
                        sent += 1
                    except Exception as e:
                        log.debug("dm_birthday_failed", error=str(e))
        return sent

    async def search_dms(
        self, query: str, name: str | None = None
    ) -> list[dict[str, Any]]:
        """Search recent DMs for a word or phrase.

        Searches the activity feed first, then (Instagram only) the
        thread history of the named person. Returns matches, newest first.
        """
        needle = (query or "").strip().lower()
        if not needle:
            return []
        results: list[dict[str, Any]] = []
        for entry in self.get_activity(limit=20):
            if name and name.lower() not in (entry.get("sender_name") or "").lower():
                continue
            if needle in (entry.get("text") or "").lower() or needle in (
                entry.get("reply") or ""
            ).lower():
                results.append({
                    "sender_name": entry.get("sender_name", ""),
                    "platform": entry.get("platform", ""),
                    "text": entry.get("text", ""),
                    "reply": entry.get("reply", ""),
                })
        if name:
            # Instagram thread history (deeper than the activity feed).
            blob = dm_auth.load_connector("instagram")
            if blob:
                data = blob.get("data") or {}
                try:
                    client = self._build_client("instagram", blob.get("method"), data)
                    threads = await client.list_recent(limit=10)
                    for msg in threads or []:
                        if name.lower() not in (msg.get("sender_name") or "").lower():
                            continue
                        get_messages = getattr(client, "get_thread_messages", None)
                        if not get_messages:
                            continue
                        history = await get_messages(msg["thread_id"], amount=20)
                        for item in history:
                            if needle in (item.get("text") or "").lower():
                                results.append({
                                    "sender_name": item.get("sender_name", ""),
                                    "platform": "instagram",
                                    "text": item.get("text", ""),
                                    "reply": "",
                                })
                except Exception as e:
                    log.debug("dm_search_failed", error=str(e))
        return results[:10]

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
        # Morning again: reset the quiet-hours "already replied" set so
        # tonight's first late message gets its one short reply.
        if not _in_quiet_hours():
            self._quiet_replied.clear()
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
            thread_key = f"{platform}:{thread_id}"
            # Spam filter: abusive messages or a flood from one thread
            # mute it — Jarvis stops replying and flags it to Sir.
            if thread_key in self._muted:
                self._mark_seen(platform, thread_id, msg["message_id"])
                continue
            if _is_abusive(msg.get("text") or "") or self._is_spamming(thread_id):
                self._muted[thread_key] = msg.get("sender_name", "")
                try:
                    from backend.services.telegram_notifier import send_telegram_message

                    await send_telegram_message(
                        f"🛑 {msg.get('sender_name', '')} has been muted — "
                        "abusive or spammy messages. I stopped replying. "
                        f"Say 'unmute {msg.get('sender_name', '')}' to resume."
                    )
                except Exception as e:
                    log.debug("dm_mute_notify_failed", error=str(e))
                self._mark_seen(platform, thread_id, msg["message_id"])
                self._persist_state()
                continue
            # Quiet hours: Jarvis does not reply late at night. The first
            # message in a thread gets one short "morning" reply; the rest
            # wait silently until morning. VIPs bypass quiet hours.
            if _in_quiet_hours() and not is_vip:
                if thread_key not in self._quiet_replied:
                    self._quiet_replied.add(thread_key)
                    try:
                        await client.send(
                            thread_id,
                            "It's late — Rayyan will get back to you in the morning.",
                        )
                    except Exception as e:
                        log.debug("dm_quiet_reply_failed", error=str(e))
                self._mark_seen(platform, thread_id, msg["message_id"])
                self._persist_state()
                continue
            # Custom auto-reply rules: Sir's own rules win over the LLM.
            # If a rule matches, its reply goes out as-is.
            rule_reply = _match_rule(msg.get("sender_name", ""), msg.get("text") or "")
            if rule_reply:
                try:
                    await client.send(thread_id, rule_reply)
                except Exception as e:
                    log.warning("dm_rule_send_failed", platform=platform, error=str(e))
                    continue
                self._mark_seen(platform, thread_id, msg["message_id"])
                self._introduced.setdefault(platform, {})[thread_id] = True
                self._clear_pending(platform, thread_id)
                self._persist_state()
                self._state[platform]["replied"] += 1
                replied += 1
                self._record_activity(platform, msg, rule_reply, important=False)
                continue
            # Meeting scheduling: someone wants to meet Sir. Ask Sir for
            # times first (never offer times on his behalf), then send them.
            if _is_meeting_request(msg.get("text") or ""):
                from backend.services.dm_store import meetings as meetings_store

                pending = meetings_store.get(thread_id)
                if not pending:
                    meetings_store.set(thread_id, {
                        "platform": platform,
                        "sender_name": msg.get("sender_name", ""),
                        "offered": [],
                        "awaiting_times": True,
                    })
                    try:
                        from backend.services.telegram_notifier import (
                            send_telegram_message,
                        )

                        await send_telegram_message(
                            f"📅 {msg.get('sender_name', '')} wants to meet. "
                            "What times should I offer them?\n\n"
                            "Reply with the times (for example 'Friday 5pm or "
                            "Saturday 10am') and I will send them."
                        )
                    except Exception as e:
                        log.debug("dm_meeting_notify_failed", error=str(e))
                    self._mark_seen(platform, thread_id, msg["message_id"])
                    self._persist_state()
                    continue
                # They replied after being offered times — did they pick one?
                if pending.get("offered"):
                    from backend.services.dm_time import parse_time

                    chosen = parse_time(msg.get("text") or "")
                    offered = pending.get("offered") or []
                    if chosen:
                        chosen_key = chosen.date().isoformat()
                        for slot in offered:
                            try:
                                slot_dt = datetime.fromisoformat(slot)
                            except (TypeError, ValueError):
                                continue
                            if slot_dt.date().isoformat() == chosen_key and (
                                slot_dt.hour == chosen.hour
                                or chosen.hour == 0
                            ):
                                # Booked: add it to the calendar and confirm.
                                from backend.services.dm_store import (
                                    calendar as cal_store,
                                )

                                cal_store.set(chosen_key, {
                                    "date": chosen_key,
                                    "status": "busy",
                                    "detail": f"Meeting with {msg.get('sender_name', '')}",
                                })
                                meetings_store.delete(thread_id)
                                confirm = (
                                    f"Done — see you {chosen.strftime('%A %H:%M')}!"
                                )
                                try:
                                    await client.send(thread_id, confirm)
                                except Exception as e:
                                    log.warning("dm_meeting_confirm_failed", platform=platform, error=str(e))
                                    continue
                                self._mark_seen(platform, thread_id, msg["message_id"])
                                self._introduced.setdefault(platform, {})[thread_id] = True
                                self._clear_pending(platform, thread_id)
                                self._persist_state()
                                self._state[platform]["replied"] += 1
                                replied += 1
                                self._record_activity(platform, msg, confirm, important=False)
                                try:
                                    from backend.services.telegram_notifier import (
                                        send_telegram_message,
                                    )

                                    await send_telegram_message(
                                        f"📅 Booked: meeting with "
                                        f"{msg.get('sender_name', '')} on "
                                        f"{chosen.strftime('%A %H:%M')}."
                                    )
                                except Exception as e:
                                    log.debug("dm_meeting_booked_notify_failed", error=str(e))
                                break
                        else:
                            # No offered slot matched — fall through to a
                            # normal reply (the meeting stays pending).
                            pass
                        if meetings_store.get(thread_id) is None:
                            continue
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
            # Away questions ("when will he be back?"): Jarvis asks Sir
            # first — he never guesses Sir's schedule. Same for money /
            # sensitive messages: draft it, do NOT auto-reply.
            is_away = _is_away_question(msg.get("text") or "")
            is_tricky = _is_tricky(msg.get("text") or "")
            if (is_away or is_tricky) and thread_id not in self._pending_drafts:
                gen = await generate_dm_reply(
                    platform,
                    msg["sender_name"],
                    msg["text"],
                    first_reply=first_reply,
                    is_group=bool(msg.get("is_group")),
                    media_url=msg.get("media_url"),
                    media_type=msg.get("media_type"),
                    contact_notes=_contact_notes(msg.get("sender_name", "")),
                    tone=_contact_tone(msg.get("sender_name", "")),
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

                        if is_away:
                            await send_telegram_message(
                                f"❓ {msg.get('sender_name', '')} asked when "
                                "you will be back. What should I tell them?\n\n"
                                "Reply with what to say, or 'send' to send "
                                f"this: {gen['reply']}"
                            )
                        else:
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
            # Availability questions ("are you free Friday?"): answer from
            # Sir's Jarvis calendar when it knows; otherwise ask Sir first.
            if _is_availability_question(msg.get("text") or "") and thread_id not in self._pending_drafts:
                calendar_answer = self._calendar_answer(msg.get("text") or "")
                if calendar_answer:
                    try:
                        await client.send(thread_id, calendar_answer)
                    except Exception as e:
                        log.warning("dm_calendar_send_failed", platform=platform, error=str(e))
                        continue
                    self._mark_seen(platform, thread_id, msg["message_id"])
                    self._introduced.setdefault(platform, {})[thread_id] = True
                    self._clear_pending(platform, thread_id)
                    self._persist_state()
                    self._state[platform]["replied"] += 1
                    replied += 1
                    self._record_activity(platform, msg, calendar_answer, important=False)
                    continue
                # Calendar does not know — ask Sir what to tell them.
                gen = await generate_dm_reply(
                    platform,
                    msg["sender_name"],
                    msg["text"],
                    first_reply=first_reply,
                    is_group=bool(msg.get("is_group")),
                    contact_notes=_contact_notes(msg.get("sender_name", "")),
                    tone=_contact_tone(msg.get("sender_name", "")),
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
                            f"📅 {msg.get('sender_name', '')} asked if you are "
                            f"free. What should I tell them?\n\n"
                            "Reply with what to say, or 'send' to send "
                            f"this: {gen['reply']}"
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
                contact_notes=_contact_notes(msg.get("sender_name", "")),
                tone=_contact_tone(msg.get("sender_name", "")),
            )
            if not gen.get("ok"):
                log.warning("dm_reply_gen_failed", platform=platform, error=gen.get("error"))
                continue
            # Voice reply: when the sender spoke (voice note) or is a VIP,
            # Jarvis answers with a voice note. Falls back to text on any
            # failure — a voice reply never breaks a DM reply.
            sent_as_voice = False
            if settings.dm_voice_replies and platform == "instagram" and (
                msg.get("media_type") == "voice" or is_vip
            ):
                from backend.services.dm_voice import send_voice_reply

                sent_as_voice = await send_voice_reply(client, thread_id, gen["reply"])
            if not sent_as_voice:
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
