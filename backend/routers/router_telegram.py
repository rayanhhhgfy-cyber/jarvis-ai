# ====================================================================
# JARVIS OMEGA — Telegram Router (Jarvis talks to Sir on Telegram)
# ====================================================================
"""
Telegram bot endpoints.

* ``POST /api/telegram/webhook`` — Telegram delivers incoming bot
  messages here. Only messages from Sir's own chat id are answered;
  anything else is ignored (the bot is Sir's private line, not a
  public bot). Sir's message goes to the same LLM brain as the
  dashboard chat, and the answer is sent back on Telegram.
* ``POST /api/telegram/setup`` — registers the webhook with Telegram
  (called once after the bot token is set; also auto-registered on
  backend startup).
* ``GET /api/telegram/status`` — whether the bot is configured. Never
  returns the token.
* ``POST /api/telegram/test`` — sends Sir a test message to confirm
  the bot reaches him.

The bot token and Sir's chat id live in env vars (TELEGRAM_BOT_TOKEN,
TELEGRAM_CHAT_ID) — never in chat, files, or the repo.
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Request

from backend.config import settings
from backend.services.telegram_notifier import (
    send_telegram_message,
    set_telegram_webhook,
)
from shared.logger import get_logger

log = get_logger("router_telegram")

router = APIRouter(prefix="/api/telegram", tags=["Telegram"])

_TELEGRAM_SYSTEM = (
    "You are Jarvis, Rayyan's personal assistant. You are replying to "
    "Rayyan himself on Telegram. Answer helpfully and briefly, like a "
    "real person texting. You know everything about his projects and "
    "his DMs. If he asks about a message someone sent him, tell him "
    "what they said and what you replied. Never pretend to be Rayyan."
)

# "tell <name> <message>" — Sir asks Jarvis to send a DM for him.
_SEND_RE = re.compile(
    r"^(?:tell|message|send to|send a message to)\s+(\S+(?:\s+\S+)?)\s+(.+)$",
    re.IGNORECASE,
)
# "summarize ... with <name>" — Sir asks for a conversation summary.
_SUMMARIZE_RE = re.compile(
    r"summar\w*\s+(?:.*?\s+)?with\s+(\S+(?:\s+\S+)?)\s*$",
    re.IGNORECASE,
)
# "send <name> a message tomorrow at 5pm: <text>" — scheduled DM.
# The name is one word (send_dm_to_name matches by substring, so
# "Omar" still finds "Omar Haddad"). The "a message" part is optional.
_SCHEDULE_RE = re.compile(
    r"^(?:send|schedule)\s+(?:a\s+message\s+(?:to|for)\s+)?"
    r"(\S+)\s+(?:a\s+message\s+)?(.+?):\s*(.+)$",
    re.IGNORECASE,
)
# "remind me to <thing> tomorrow at 5pm" — reminder for Sir.
_REMIND_RE = re.compile(
    r"^remind me\s+(?:to\s+)?(.+?)\s+(tomorrow|tonight|today|in\s+\d+\s+\w+|at\s+.+|on\s+\w+.*)$",
    re.IGNORECASE,
)
# "remember that <name> <fact>" / "remember <name>'s birthday is <date>".
_REMEMBER_RE = re.compile(
    r"^remember\s+(?:that\s+)?(.+)$",
    re.IGNORECASE,
)
# "I'm busy Friday 5pm-8pm" / "I'm free Saturday" — calendar entry.
_BUSY_RE = re.compile(
    r"^i'?m\s+(busy|free)\s+(.+)$",
    re.IGNORECASE,
)
# "unmute <name>" — resume a muted thread.
_UNMUTE_RE = re.compile(r"^unmute\s+(\S+(?:\s+\S+)?)\s*$", re.IGNORECASE)
# "find the message where <name> mentioned <query>" / "search for <query>".
_SEARCH_RE = re.compile(
    r"^(?:find|search)(?:\s+the\s+message)?(?:\s+where\s+(\S+(?:\s+\S+)?)\s+mentioned\s+)?(.+)$",
    re.IGNORECASE,
)
# "add a rule: if <person> asks about <topic>, reply <text>".
_ADD_RULE_RE = re.compile(
    r"^add\s+a\s+rule:?\s+if\s+(.+?)\s+asks?\s+about\s+(.+?),\s*(?:reply|send|tell them)\s+(.+)$",
    re.IGNORECASE,
)
# "list my rules" / "show my rules".
_LIST_RULES_RE = re.compile(r"^(?:list|show)\s+(?:my\s+)?rules\s*$", re.IGNORECASE)
# "delete rule <number>".
_DELETE_RULE_RE = re.compile(r"^delete\s+rule\s+(\d+)\s*$", re.IGNORECASE)


async def _summarize_conversation(name: str) -> str:
    """Summarize the recent DM exchanges with one person, via the LLM.

    Uses the activity feed (the last 20 replies), so it covers recent
    conversations. Returns a short summary, or a clear "nothing found".
    """
    from backend.services.dm_responder import dm_responder
    from backend.services.llm_service import llm_service

    needle = (name or "").strip().lower()
    entries = [
        e for e in dm_responder.get_activity(limit=20)
        if needle in (e.get("sender_name") or "").lower()
    ]
    if not entries:
        return f"I have no recent DM activity with {name} to summarize."
    lines = []
    for entry in reversed(entries):
        lines.append(
            f"{entry.get('sender_name', '')}: {entry.get('text', '')[:200]} "
            f"-> Jarvis: {entry.get('reply', '')[:200]}"
        )
    summary = await llm_service.get_response(
        user_message=(
            "Summarize this DM conversation briefly: what was said, "
            "what was decided, and what is still open.\n\n" + "\n".join(lines)
        ),
        system_instructions=(
            "You are Jarvis. Summarize the conversation in a few short "
            "lines for Rayyan, in the language he used."
        ),
        inject_memory=False,
    )
    return summary or f"I could not summarize the conversation with {name}."


def _handle_remember(fact: str) -> str:
    """Store a fact about a person (contact memory) or a birthday.

    Understands "Omar loves football", "Omar's birthday is March 15",
    "Layla just started a new job". Returns a confirmation line.
    """
    from backend.services.dm_store import contacts

    fact = (fact or "").strip()
    if not fact:
        return "Tell me what to remember — for example 'remember that Omar loves football'."
    # Tone: "<name> is a teacher" -> formal; "<name> is a friend" -> casual.
    tone_match = re.match(
        r"^(\S+(?:\s+\S+)?)\s+is\s+(?:a\s+|my\s+)?(teacher|professor|friend|best friend)\s*$",
        fact,
        re.IGNORECASE,
    )
    if tone_match:
        name = tone_match.group(1).strip()
        role = tone_match.group(2).lower()
        tone = "formal" if role in ("teacher", "professor") else "casual"
        data = contacts.get(name, {}) or {}
        data["tone"] = tone
        contacts.set(name, data)
        return f"Noted — I will talk to {name} {'formally' if tone == 'formal' else 'casually'}."
    # Birthday: "<name>'s birthday is <month> <day>" or "<name> birthday <date>".
    bday = re.search(
        r"^(\S+(?:\s+\S+)?)'?s?\s+birthday\s+(?:is\s+)?(\w+)\s+(\d{1,2})",
        fact,
        re.IGNORECASE,
    )
    if bday:
        name = bday.group(1).strip()
        # "Omar's" -> "Omar" (the name group keeps the possessive).
        name = re.sub(r"'s$", "", name).strip()
        month_name = bday.group(2).lower()
        day = int(bday.group(3))
        months = {
            "january": 1, "february": 2, "march": 3, "april": 4, "may": 5,
            "june": 6, "july": 7, "august": 8, "september": 9, "october": 10,
            "november": 11, "december": 12,
        }
        month = months.get(month_name)
        if month and 1 <= day <= 31:
            data = contacts.get(name, {}) or {}
            data["birthday"] = f"{month:02d}-{day:02d}"
            contacts.set(name, data)
            return f"Noted — {name}'s birthday is {month_name.title()} {day}. I will remind you."
        return "I could not understand that date. Try 'Omar's birthday is March 15'."
    # General fact: "<name> <rest>" — the first 1-2 words are the name.
    words = fact.split()
    if len(words) < 2:
        return "Tell me who it is about — for example 'remember that Omar loves football'."
    name = words[0]
    note = " ".join(words[1:])
    # Two-word names: if the note starts with a lowercase word that looks
    # like part of a name, keep it simple — the first word is the name.
    data = contacts.get(name, {}) or {}
    existing = (data.get("notes") or "")
    data["notes"] = f"{existing} {note}".strip() if existing else note
    contacts.set(name, data)
    return f"Noted about {name} — I will remember that."


def _handle_busy_free(status: str, rest: str) -> str:
    """Record a calendar entry: "I'm busy Friday 5pm-8pm" / "I'm free Saturday".

    Stores {date, status, detail} so Jarvis can answer "are you free?"
    from the calendar instead of guessing.
    """
    from backend.services.dm_store import calendar as cal_store
    from backend.services.dm_time import parse_time

    rest = (rest or "").strip()
    when = parse_time(rest)
    if not when:
        return (
            "I could not understand the day. Try 'I'm busy Friday 5pm-8pm' "
            "or 'I'm free Saturday'."
        )
    day_key = when.astimezone().date().isoformat()
    cal_store.set(day_key, {
        "date": day_key,
        "status": status.lower(),
        "detail": rest,
    })
    day_name = when.strftime("%A")
    return f"Noted — you are {status.lower()} on {day_name}."


def _pending_meeting_awaiting_times() -> dict[str, Any] | None:
    """The pending meeting that is waiting for Sir to offer times."""
    from backend.services.dm_store import meetings as meetings_store

    for thread_id, meeting in meetings_store.all().items():
        if meeting.get("awaiting_times"):
            return {"thread_id": thread_id, **meeting}
    return None


def _format_offered_times(slots: list[str]) -> str:
    """Turn parsed time slots into the message sent to the person."""
    from datetime import datetime

    parts = []
    for slot in slots:
        try:
            dt = datetime.fromisoformat(slot)
            parts.append(dt.strftime("%A %H:%M"))
        except (TypeError, ValueError):
            continue
    if len(parts) == 1:
        return f"How about {parts[0]}? Let me know if that works for you."
    if len(parts) == 2:
        return f"How about {parts[0]} or {parts[1]}? Let me know which works for you."
    joined = ", ".join(parts[:-1]) + f", or {parts[-1]}"
    return f"How about {joined}? Let me know which works for you."


@router.get("/status")
async def telegram_status() -> dict[str, Any]:
    """Whether the Telegram bot is configured (never returns the token)."""
    return {
        "configured": bool(settings.telegram_bot_token.strip())
        and bool(settings.telegram_chat_id.strip()),
        "bot_token_set": bool(settings.telegram_bot_token.strip()),
        "chat_id_set": bool(settings.telegram_chat_id.strip()),
    }


@router.post("/setup")
async def telegram_setup(request: Request) -> dict[str, Any]:
    """Register the Telegram webhook (called once after the token is set)."""
    if not settings.telegram_bot_token.strip():
        return {"ok": False, "error": "TELEGRAM_BOT_TOKEN is not set."}
    base_url = ""
    # Use the backend's own public host when no override is given.
    host = request.headers.get("host", "")
    if host:
        base_url = f"https://{host}"
    ok = await set_telegram_webhook(base_url=base_url)
    return {"ok": ok}


@router.post("/test")
async def telegram_test() -> dict[str, Any]:
    """Send Sir a test Telegram message to confirm the bot reaches him."""
    ok = await send_telegram_message(
        "Hello Sir, this is Jarvis on Telegram. Your bot is working — "
        "I can reach you here whenever I answer a DM or have something "
        "to tell you."
    )
    if not ok:
        return {
            "ok": False,
            "error": "Telegram is not configured (set TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID).",
        }
    return {"ok": True}


@router.post("/webhook")
async def telegram_webhook(payload: dict[str, Any]) -> dict[str, Any]:
    """Receive a Telegram update and answer Sir when it is from him.

    Before the normal chat, three special intents are handled:
    * A pending tricky-message draft: "send" sends the draft as-is,
      any other text is sent as Sir's own reply instead.
    * "tell <name> <message>": Jarvis sends that DM for Sir.
    * "summarize ... with <name>": Jarvis summarizes the recent
      conversation with that person from the DM activity feed.
    Otherwise the message goes to the chat LLM, with the recent DM
    activity included as context so Sir can ask about his DMs.
    """
    try:
        message = payload.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id", ""))
        text = (message.get("text") or "").strip()
        if not text or not chat_id:
            return {"ok": True}
        expected = (settings.telegram_chat_id or "").strip()
        if not expected or chat_id != expected:
            # Not Sir — ignore silently (the bot is his private line).
            log.debug("telegram_webhook_ignored_stranger", chat_id=chat_id)
            return {"ok": True}
        from backend.services.dm_responder import dm_responder

        # --- Pending draft (feature 8): Sir approves or replaces it. ---
        draft = dm_responder.get_pending_draft()
        if draft:
            if text.lower() in ("send", "send it", "yes", "ok", "okay", "ارسل", "أرسل"):
                result = await dm_responder.send_draft_reply(
                    draft["thread_id"], draft["draft_reply"]
                )
                if result.get("ok"):
                    await send_telegram_message(
                        f"Sent to {result.get('sender_name', '')}."
                    )
                else:
                    await send_telegram_message(
                        "I could not send that draft — the account may need reconnecting."
                    )
            else:
                result = await dm_responder.send_draft_reply(draft["thread_id"], text)
                if result.get("ok"):
                    await send_telegram_message(
                        f"Sent your reply to {result.get('sender_name', '')}."
                    )
                else:
                    await send_telegram_message(
                        "I could not send that reply — the account may need reconnecting."
                    )
            return {"ok": True}

        # --- Pending meeting (awaiting times from Sir): send the times. ---
        meeting = _pending_meeting_awaiting_times()
        if meeting:
            from backend.services.dm_time import parse_time

            # Rayyan's reply lists the times ("Friday 5pm or Saturday 10am").
            # Split on " or " / "," and parse each slot.
            slots: list[str] = []
            for part in re.split(r"\s+or\s+|,\s*", text):
                when = parse_time(part)
                if when:
                    slots.append(when.astimezone().isoformat())
            if slots:
                from backend.services.dm_store import meetings as meetings_store

                thread_id = meeting["thread_id"]
                meetings_store.set(thread_id, {
                    "platform": meeting["platform"],
                    "sender_name": meeting["sender_name"],
                    "offered": slots,
                    "awaiting_times": False,
                })
                from backend.services.dm_responder import dm_responder as _mr

                # Send the offered times to the person via their DM thread.
                offered_text = _format_offered_times(slots)
                blob = None
                try:
                    from backend.services import dm_auth as _dma

                    blob = _dma.load_connector(meeting["platform"])
                except Exception:
                    blob = None
                if blob:
                    data = blob.get("data") or {}
                    try:
                        client = _mr._build_client(
                            meeting["platform"], blob.get("method"), data
                        )
                        await client.send(thread_id, offered_text)
                        await send_telegram_message(
                            f"Sent the times to {meeting['sender_name']}."
                        )
                    except Exception as e:
                        log.warning("dm_meeting_offer_failed", error=str(e))
                        await send_telegram_message(
                            "I could not send the times — the account may need reconnecting."
                        )
                else:
                    await send_telegram_message(
                        "I could not send the times — no account is connected."
                    )
            else:
                await send_telegram_message(
                    "I could not understand those times. Try 'Friday 5pm or Saturday 10am'."
                )
            return {"ok": True}

        # --- "add a rule: if <person> asks about <topic>, reply <text>". ---
        add_rule_match = _ADD_RULE_RE.match(text)
        if add_rule_match:
            import uuid

            from backend.services.dm_store import rules as rules_store
            person = add_rule_match.group(1).strip()
            topic = add_rule_match.group(2).strip()
            reply_text = add_rule_match.group(3).strip()
            rule_id = f"rule_{uuid.uuid4().hex[:6]}"
            rules_store.set(rule_id, {
                "person": person, "topic": topic, "reply": reply_text,
            })
            await send_telegram_message(
                f"Rule added: if {person} asks about '{topic}', I will reply: {reply_text}"
            )
            return {"ok": True}

        # --- "list my rules" / "delete rule <number>". ---
        if _LIST_RULES_RE.match(text):
            from backend.services.dm_store import rules as rules_store

            all_rules = rules_store.all()
            if not all_rules:
                await send_telegram_message("You have no custom rules yet.")
            else:
                lines = ["Your rules:"]
                for i, rule in enumerate(all_rules.values(), 1):
                    lines.append(
                        f"{i}. If {rule.get('person', '')} asks about "
                        f"'{rule.get('topic', '')}', reply: {rule.get('reply', '')}"
                    )
                await send_telegram_message("\n".join(lines))
            return {"ok": True}
        delete_rule_match = _DELETE_RULE_RE.match(text)
        if delete_rule_match:
            from backend.services.dm_store import rules as rules_store

            idx = int(delete_rule_match.group(1)) - 1
            keys = list(rules_store.all().keys())
            if 0 <= idx < len(keys):
                rules_store.delete(keys[idx])
                await send_telegram_message(f"Deleted rule {idx + 1}.")
            else:
                await send_telegram_message("There is no rule with that number.")
            return {"ok": True}

        # --- "unmute <name>" — resume a muted thread. ---
        unmute_match = _UNMUTE_RE.match(text)
        if unmute_match:
            if dm_responder.unmute_thread(unmute_match.group(1)):
                await send_telegram_message(
                    f"Unmuted {unmute_match.group(1)} — I will reply to them again."
                )
            else:
                await send_telegram_message(
                    f"{unmute_match.group(1)} is not muted."
                )
            return {"ok": True}

        # --- "remember that <name> <fact>" — contact memory / birthday. ---
        remember_match = _REMEMBER_RE.match(text)
        if remember_match:
            reply = _handle_remember(remember_match.group(1))
            await send_telegram_message(reply)
            return {"ok": True}

        # --- "I'm busy/free <day> ..." — Jarvis calendar entry. ---
        busy_match = _BUSY_RE.match(text)
        if busy_match:
            reply = _handle_busy_free(busy_match.group(1), busy_match.group(2))
            await send_telegram_message(reply)
            return {"ok": True}

        # --- "remind me to <thing> <time>" — reminder for Sir. ---
        remind_match = _REMIND_RE.match(text)
        if remind_match:
            from backend.services.dm_time import describe_time, parse_time

            when = parse_time(remind_match.group(2))
            if when:
                dm_responder.add_reminder(remind_match.group(1), when)
                await send_telegram_message(
                    f"Got it — I will remind you to {remind_match.group(1)} "
                    f"{describe_time(when)}."
                )
            else:
                await send_telegram_message(
                    "I could not understand the time. Try 'remind me to call "
                    "Omar tomorrow at 5pm'."
                )
            return {"ok": True}

        # --- "send <name> a message <time>: <text>" — scheduled DM. ---
        schedule_match = _SCHEDULE_RE.match(text)
        if schedule_match and ":" in text:
            from backend.services.dm_time import describe_time, parse_time

            name = schedule_match.group(1)
            when = parse_time(schedule_match.group(2))
            message_text = schedule_match.group(3)
            if when and message_text.strip():
                dm_responder.schedule_dm(name, message_text.strip(), when)
                await send_telegram_message(
                    f"Scheduled — I will send that to {name} "
                    f"{describe_time(when)}."
                )
            else:
                await send_telegram_message(
                    "I could not understand the time. Try 'send Omar a message "
                    "tomorrow at 5pm: I will be there'."
                )
            return {"ok": True}

        # --- "find/search ... where <name> mentioned <query>" — DM search. ---
        search_match = _SEARCH_RE.match(text)
        if search_match and ("find" in text.lower() or "search" in text.lower()):
            name = search_match.group(1)
            query = search_match.group(2)
            results = await dm_responder.search_dms(query, name=name)
            if results:
                lines = [f"Found {len(results)} match(es):"]
                for r in results[:5]:
                    lines.append(
                        f"- {r.get('sender_name', '')} ({r.get('platform', '')}): "
                        f"{r.get('text', '')[:120]}"
                    )
                await send_telegram_message("\n".join(lines))
            else:
                await send_telegram_message(
                    f"I could not find '{query}' in your recent DMs."
                )
            return {"ok": True}

        # --- "tell <name> <message>" (feature 6): send a DM for Sir. ---
        send_match = _SEND_RE.match(text)
        if send_match:
            name, message_text = send_match.group(1), send_match.group(2)
            result = await dm_responder.send_dm_to_name(name, message_text)
            if result.get("reason") == "not_found" and " " in name:
                # The name regex is greedy (up to two words) and may have
                # swallowed the first word of the message ("tell Omar I
                # will..." -> name "Omar I"). Retry with one-word name.
                first, rest = name.split(" ", 1)
                message_text = f"{rest} {message_text}"
                result = await dm_responder.send_dm_to_name(first, message_text)
                name = first
            if result.get("ok"):
                await send_telegram_message(
                    f"Sent to {result.get('sender_name', name)}."
                )
            else:
                await send_telegram_message(
                    f"I could not find a conversation with {name}."
                )
            return {"ok": True}

        # --- "summarize ... with <name>" (feature 9): summarize the thread. ---
        summary_match = _SUMMARIZE_RE.search(text)
        if summary_match:
            name = summary_match.group(1)
            summary = await _summarize_conversation(name)
            await send_telegram_message(summary)
            return {"ok": True}

        # --- Normal chat, with recent DM activity as context (feature 5). ---
        from backend.services.llm_service import llm_service

        activity = dm_responder.get_activity(limit=10)
        context = ""
        if activity:
            lines = []
            for entry in reversed(activity):
                lines.append(
                    f"- {entry.get('sender_name', '')} "
                    f"({entry.get('platform', '')}): "
                    f"{entry.get('text', '')[:120]} "
                    f"-> Jarvis: {entry.get('reply', '')[:120]}"
                )
            context = (
                "[Recent DM activity — use this when Sir asks about his DMs]\n"
                + "\n".join(lines)
                + "\n\n"
            )
        reply = await llm_service.get_response(
            user_message=f"{context}Rayyan (Telegram): {text}",
            system_instructions=_TELEGRAM_SYSTEM,
            inject_memory=True,
        )
        await send_telegram_message(reply or "Sorry Sir, I could not answer that.")
    except Exception as e:
        log.warning("telegram_webhook_failed", error=str(e))
    return {"ok": True}
