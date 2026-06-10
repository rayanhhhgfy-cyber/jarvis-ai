# ====================================================================
# JARVIS OMEGA — Focus Mode Service
# ====================================================================
"""
Focus Mode Service.
Keeps track of DND status, queues incoming messages,
generates conversational auto-replies via LLM, and
summarizes missed messages when Focus Mode is deactivated.

Supports Arabic auto-reply on Instagram DMs during focus mode.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set

from backend.services.llm_service import llm_service
from shared.logger import get_logger

log = get_logger("focus_mode")

# Urgency keyword sets (Arabic + English)
ARABIC_URGENT = {"عاجل", "طارئ", "مهم", "ضروري", "خطر", "مساعدة", "انتباه", "استعجال", "حرج", "فوري", "حريق", "سرقة", "إصابة", "مستعجل", " urgently", "help"}
ENGLISH_URGENT = {"urgent", "emergency", "important", "critical", "help", "asap", "immediate", "attention", "danger", "fire", "robbery", "injury", "accident", "911", "emergency"}


class FocusModeService:
    def __init__(self) -> None:
        self._active: bool = False
        self._focus_note: str = ""
        self._expires_at: Optional[datetime] = None
        self._auto_reply_enabled: bool = True
        self._language: str = "arabic"
        self._queued_messages: List[Dict[str, Any]] = []
        self._excluded_contacts: Set[str] = set()
        self._instagram_poll_task: Optional[asyncio.Task] = None
        # thread_id -> {"user_ids": [...], "users": [...]}
        self._replied_threads: Dict[str, Dict[str, Any]] = {}
        self._thread_reply_count: Dict[str, int] = {}

    def activate(self, note: str, duration_minutes: Optional[int] = None, auto_reply: bool = True, language: str = "arabic") -> None:
        """Activate Focus Mode with a custom note, optional duration, and language."""
        self._active = True
        self._focus_note = note
        self._auto_reply_enabled = auto_reply
        self._language = language if language in ("arabic", "english") else "arabic"
        self._queued_messages = []

        if duration_minutes:
            self._expires_at = datetime.utcnow() + timedelta(minutes=duration_minutes)
        else:
            self._expires_at = None

        log.info("focus_mode_activated", note=note, duration=duration_minutes, auto_reply=auto_reply, language=self._language)

        # Start Instagram DM polling for auto-reply
        if auto_reply:
            self._start_instagram_polling()

    def deactivate(self) -> Dict[str, Any]:
        """Deactivate Focus Mode and return a summary of queued messages."""
        if not self._active:
            return {"active": False, "summary": "Focus Mode was not active."}

        self._stop_instagram_polling()
        self._active = False
        self._expires_at = None
        queued = list(self._queued_messages)
        self._queued_messages = []

        # Notify all threads that received auto-replies that Sir is back
        self._notify_replied_threads()

        log.info("focus_mode_deactivated", queued_count=len(queued))

        return {
            "active": False,
            "queued_count": len(queued),
            "queued_messages": queued,
        }

    def _notify_replied_threads(self) -> None:
        """Send 'Sir is back' text + voice message to every thread that got auto-replied."""
        from backend.services.instagram_service import instagram_service
        if not instagram_service.available:
            return
        if not self._replied_threads:
            return

        log.info("focus_notifying_replied_threads", count=len(self._replied_threads))
        for tid, info in self._replied_threads.items():
            try:
                user_ids = info.get("user_ids", [])
                users = info.get("users", [])
                target_id = (user_ids or [None])[0] or (users or [None])[0]
                if not target_id:
                    continue

                if self._language == "arabic":
                    text = "انتهت فترة التركيز. السيد سيتواصل معك قريباً. شكراً لصبرك."
                    voice = "انتهت فترة التركيز. السيد سيتواصل معك قريباً."
                else:
                    text = "Sir's focus session has ended. He will contact you shortly. Thank you for your patience."
                    voice = "Sir's focus session has ended. He will contact you shortly."

                instagram_service.send_dm(target_id, text)
                # Also send voice message
                try:
                    instagram_service.send_voice_message(
                        [uid for uid in user_ids if str(uid).isdigit()],
                        voice,
                        lang="ar" if self._language == "arabic" else "en",
                    )
                except Exception:
                    log.warning("focus_end_voice_failed", thread=tid[:8])

                log.info("focus_end_notified_thread", thread=tid[:8], to=users)
            except Exception as e:
                log.warning("focus_end_notify_failed", thread=tid[:8], error=str(e))

        self._replied_threads.clear()

    def is_active(self) -> bool:
        """Check if Focus Mode is currently active, handling auto-expiry."""
        if not self._active:
            return False

        if self._expires_at and datetime.utcnow() > self._expires_at:
            log.info("focus_mode_expired_automatically")
            self.deactivate()
            return False

        return True

    def get_status(self) -> Dict[str, Any]:
        """Get current status of Focus Mode."""
        active = self.is_active()
        return {
            "active": active,
            "focus_note": self._focus_note if active else "",
            "expires_at": self._expires_at.isoformat() if (active and self._expires_at) else None,
            "time_remaining_seconds": max(0, (self._expires_at - datetime.utcnow()).total_seconds()) if (active and self._expires_at) else None,
            "auto_reply_enabled": self._auto_reply_enabled,
            "language": self._language if active else "arabic",
            "queued_count": len(self._queued_messages) if active else 0,
            "excluded_contacts": list(self._excluded_contacts),
        }

    def add_exclude_contact(self, contact_id: str) -> None:
        """Exclude a contact chat ID from DND auto-replies."""
        self._excluded_contacts.add(str(contact_id))

    def remove_exclude_contact(self, contact_id: str) -> None:
        """Remove a contact from DND exclusion."""
        self._excluded_contacts.discard(str(contact_id))

    def is_excluded(self, contact_id: str) -> bool:
        """Check if a contact chat ID is excluded from Focus DND."""
        return str(contact_id) in self._excluded_contacts

    def queue_message(self, sender: str, platform: str, text: str, urgent: bool = False) -> None:
        """Log a message received while focus mode is active."""
        if not self.is_active():
            return

        msg_entry = {
            "sender": sender,
            "platform": platform,
            "text": text,
            "urgent": urgent,
            "received_at": datetime.utcnow().isoformat(),
        }
        self._queued_messages.append(msg_entry)

    async def _is_urgent(self, text: str) -> bool:
        """Hybrid urgency detection: keyword scan first, then LLM verification."""
        text_lower = text.lower()
        for kw in ARABIC_URGENT | ENGLISH_URGENT:
            if kw in text_lower or kw in text:
                break
        else:
            return False

        verify_prompt = (
            "Classify if the following message is truly urgent/emergency "
            "(something that needs immediate human attention). "
            "Reply ONLY with 'yes' or 'no'.\n"
            f"Message: {text}"
        )
        try:
            resp = await llm_service.get_response(
                user_message=verify_prompt,
                system_instructions="You are a classification assistant. Reply only 'yes' or 'no'.",
                inject_memory=False,
            )
            return resp.strip().lower().startswith("yes")
        except Exception:
            return False

    # Curated professional auto-reply pools — no LLM creativity to avoid nonsense
    _ARABIC_INTROS = [
        "مرحباً! أنا جارفيس، المساعد الشخصي للسيد. سيدي مشغول حالياً بالتركيز على عمله، وأنا أرد بدلاً عنه لمساعدتك. ",
        "أهلاً! أنا جارفيس، مساعد السيد الآلي. السيد في وضع التركيز حالياً، وأنا هنا لمساعدتك نيابة عنه. ",
        "السلام عليكم! أنا جارفيس، المساعد الذكي للسيد. السيد مشغول حالياً، وأنا أتولى الرد نيابة عنه. ",
    ]
    _ARABIC_SUBSEQUENT = [
        "سأخبر السيد برسالتك عندما يتفرغ. شكراً لصبرك.",
        "تم استلام رسالتك. سأبلغ السيد بها فور انتهاء فترة تركيزه.",
        "شكراً لتواصلك. سيتم إبلاغ السيد برسالتك في أقرب وقت.",
        "أشكرك على رسالتك. سأنقلها للسيد حالما ينتهي من عمله.",
    ]
    _ENGLISH_INTROS = [
        "Hi! I'm JARVIS, Sir's AI assistant. He's currently in Focus Mode, so I'm responding on his behalf. ",
        "Hello! I'm JARVIS. Sir is currently focusing and has asked me to handle messages. ",
    ]
    _ENGLISH_SUBSEQUENT = [
        "I'll make sure Sir gets your message when he's available. Thank you for your patience.",
        "Message received. I'll notify Sir as soon as his focus session ends.",
        "Thank you for your message. I'll relay it to Sir when he's free.",
    ]

    def _pick_pool(self, pool: list[str]) -> str:
        import random
        return random.choice(pool)

    async def get_auto_reply(self, sender: str, incoming_message: str, first_reply: bool = False) -> Optional[str]:
        """Generate an auto-reply. Uses hardcoded professional pools — no LLM."""
        if not self.is_active() or not self._auto_reply_enabled:
            return None

        if first_reply:
            if self._language == "arabic":
                intro = self._pick_pool(self._ARABIC_INTROS)
                body = "سأخبر السيد برسالتك عندما يتفرغ."
                return intro + body
            else:
                intro = self._pick_pool(self._ENGLISH_INTROS)
                body = "I'll let Sir know about your message when he's free."
                return intro + body
        else:
            if self._language == "arabic":
                return self._pick_pool(self._ARABIC_SUBSEQUENT)
            else:
                return self._pick_pool(self._ENGLISH_SUBSEQUENT)

    async def generate_queued_summary(self) -> str:
        """Generate an LLM summary of all missed messages during the focus session."""
        if not self._queued_messages:
            return "لم ترد أي رسائل خلال فترة التركيز، سيدي." if self._language == "arabic" else "No messages were queued during this Focus session, Sir."

        lang_instruction = (
            "قم بتلخيص الرسائل التالية التي فاتته خلال فترة التركيز. "
            "اجمعها حسب المرسل أو المنصة، واذكر أي شيء عاجل. باللغة العربية."
            if self._language == "arabic" else
            "Summarize the following messages Sir missed while focusing. "
            "Group by sender/platform, note urgent items."
        )

        messages_text = ""
        for i, m in enumerate(self._queued_messages, 1):
            urgent_tag = " [URGENT]" if m.get("urgent") else ""
            messages_text += f"[{i}]{urgent_tag} {m['sender']} ({m['platform']}): {m['text']}\n"

        try:
            summary = await llm_service.get_response(
                user_message=messages_text,
                system_instructions=(
                    f"You are JARVIS. Sir has just finished a Focus session. {lang_instruction}\n"
                    "Keep it clean and readable."
                ),
                inject_memory=False,
            )
            return summary.strip()
        except Exception as e:
            log.error("failed_to_summarize_focus_queue", error=str(e))
            senders = list(set(m["sender"] for m in self._queued_messages))
            return f"سيدي، فاتتك {len(self._queued_messages)} رسالة من: {', '.join(senders)}"

    # ------------------------------------------------------------------
    # Instagram DM polling for auto-reply
    # ------------------------------------------------------------------

    def _start_instagram_polling(self) -> None:
        """Start background task that polls Instagram DMs during focus mode."""
        if self._instagram_poll_task and not self._instagram_poll_task.done():
            return
        self._instagram_poll_task = asyncio.create_task(self._instagram_poll_loop())

    def _stop_instagram_polling(self) -> None:
        """Stop the Instagram DM polling task."""
        if self._instagram_poll_task and not self._instagram_poll_task.done():
            self._instagram_poll_task.cancel()
            self._instagram_poll_task = None

    async def _instagram_poll_loop(self) -> None:
        """Poll Instagram inbox every 10s, detect urgency, reply with intro on first contact."""
        from backend.services.instagram_service import instagram_service

        thread_last_msg: dict[str, str] = {}

        while self._active and self._auto_reply_enabled:
            try:
                if not instagram_service.available:
                    await asyncio.sleep(10)
                    continue

                inbox = instagram_service.read_inbox(limit=10)
                if not inbox.get("success"):
                    await asyncio.sleep(10)
                    continue

                convos = inbox.get("conversations", [])
                for c in convos:
                    tid = c.get("thread_id", "")
                    if not tid:
                        continue

                    users = c.get("users") or []
                    username = users[0] if users else ""
                    if not username:
                        continue

                    # Prefer numeric user_id over username for send_dm
                    sender_id = (c.get("user_ids") or [None])[0] or username

                    last_msg = (c.get("last_message") or "").strip()
                    if not last_msg:
                        continue

                    # Skip if the last message was sent by me (not an incoming DM)
                    if c.get("is_from_me", False):
                        continue

                    prev_msg = thread_last_msg.get(tid, "")

                    if last_msg == prev_msg:
                        # Already seen this message — skip
                        continue

                    # New or first-seen message
                    thread_last_msg[tid] = last_msg
                    log.info("instagram_focus_new_dm", from_user=username, msg=last_msg)

                    # ---- Urgency check (hybrid: keyword + LLM) ----
                    urgent = await self._is_urgent(last_msg)
                    if urgent:
                        self.queue_message(username, "Instagram", last_msg, urgent=True)
                        log.info("instagram_focus_urgent_detected", from_user=username, msg=last_msg)
                        # Ping Sir via WebSocket
                        try:
                            from backend.main import broadcast_to_ui
                            await broadcast_to_ui({
                                "type": "urgent_message",
                                "payload": {
                                    "platform": "Instagram",
                                    "from": username,
                                    "message": last_msg,
                                    "timestamp": datetime.utcnow().isoformat(),
                                },
                            })
                        except Exception:
                            log.warning("instagram_focus_urgent_broadcast_failed")
                        continue  # skip auto-reply for urgent messages

                    # ---- Normal auto-reply (max 2 per thread to avoid spam) ----
                    self.queue_message(username, "Instagram", last_msg)

                    reply_count = self._thread_reply_count.get(tid, 0)
                    if reply_count >= 2:
                        # Already sent 2 replies to this thread — just queue silently
                        continue

                    first_reply = tid not in self._replied_threads
                    reply = await self.get_auto_reply(username, last_msg, first_reply=first_reply)
                    if reply:
                        result = instagram_service.send_dm(sender_id, reply)
                        if result.get("success"):
                            self._replied_threads[tid] = {"user_ids": c.get("user_ids", []), "users": c.get("users", [])}
                            self._thread_reply_count[tid] = self._thread_reply_count.get(tid, 0) + 1
                            log.info("instagram_focus_auto_replied", to_user=username, first_reply=first_reply)
                        else:
                            log.warning("instagram_focus_auto_reply_failed", to_user=username, error=result.get("error"))

                if len(thread_last_msg) > 100:
                    keys = list(thread_last_msg.keys())[-100:]
                    thread_last_msg = {k: thread_last_msg[k] for k in keys}
                    self._replied_threads = {k: v for k, v in self._replied_threads.items() if k in keys}
                    self._thread_reply_count = {k: v for k, v in self._thread_reply_count.items() if k in keys}

            except asyncio.CancelledError:
                break
            except Exception as e:
                log.warning("instagram_poll_error", error=str(e))

            await asyncio.sleep(10)


# Singleton
focus_mode_service = FocusModeService()
