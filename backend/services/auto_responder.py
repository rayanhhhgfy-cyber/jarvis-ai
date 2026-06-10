# ====================================================================
# JARVIS OMEGA — Smart AutoResponder Service
# ====================================================================
"""
Smart AutoResponder: when Sir doesn't reply to a DM within a
configurable timeout, Jarvis steps in — sends a heads-up, then
engages in the conversation topic naturally using LLM context.

Handles:
- Text DMs (full conversation engagement)
- Voice/video calls (text + voice message reply)
- Incoming voice messages (acknowledge + redirect to text)
- Group chats (multi-participant awareness)
- Image generation requests (generate + send photo)
- Video generation requests (generate + send video)
- Voice message requests (generate gTTS Arabic voice + send)
- Focus Mode end notifications
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set

from backend.services.llm_service import llm_service
from shared.logger import get_logger

log = get_logger("auto_responder")

# Item types that represent calls
CALL_ITEM_TYPES = {"raven_media", "felix_media", "video_call_media", "voice_media"}
# Item types that represent voice messages (not calls)
VOICE_ITEM_TYPES = {"voice_media"}


class AutoResponderService:
    def __init__(self) -> None:
        self._active: bool = False
        self._timeout_minutes: int = 5
        self._max_replies: int = 50
        self._poll_task: Optional[asyncio.Task] = None

        # Thread tracking: thread_id -> state
        self._threads: Dict[str, dict] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_active(self) -> bool:
        return self._active

    def get_settings(self) -> dict:
        return {
            "active": self._active,
            "timeout_minutes": self._timeout_minutes,
            "max_replies": self._max_replies,
            "tracked_threads": len(self._threads),
        }

    def update_settings(self, *, timeout_minutes: Optional[int] = None, active: Optional[bool] = None) -> dict:
        if timeout_minutes is not None:
            self._timeout_minutes = max(1, min(timeout_minutes, 120))
        if active is not None:
            if active and not self._active:
                self._start_polling()
            elif not active and self._active:
                self._stop_polling()
        return self.get_settings()

    # ------------------------------------------------------------------
    # Polling lifecycle
    # ------------------------------------------------------------------

    def _start_polling(self) -> None:
        if self._poll_task and not self._poll_task.done():
            return
        self._active = True
        self._poll_task = asyncio.create_task(self._poll_loop())
        log.info("auto_responder_started", timeout=self._timeout_minutes)

    def _stop_polling(self) -> None:
        self._active = False
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
            self._poll_task = None
        self._threads.clear()
        log.info("auto_responder_stopped")

    async def _poll_loop(self) -> None:
        from backend.services.instagram_service import instagram_service

        # Track whether this is the first poll (to avoid treating old messages as new)
        is_first_poll = True

        while self._active:
            try:
                if not instagram_service.available:
                    await asyncio.sleep(15)
                    continue

                inbox = instagram_service.read_inbox(limit=20)
                if not inbox.get("success"):
                    await asyncio.sleep(15)
                    continue

                convos = inbox.get("conversations", [])
                now = datetime.utcnow()

                # ---- PASS 1: Record all thread states (baseline on first poll) ----
                if is_first_poll:
                    for c in convos:
                        tid = c.get("thread_id", "")
                        if not tid:
                            continue
                        last_msg = (c.get("last_message") or "").strip()
                        is_from_me = c.get("is_from_me", False)
                        if is_from_me or not last_msg:
                            continue
                        # Record message WITHOUT starting the timer
                        self._threads[tid] = {
                            "first_seen": None,       # timer only starts on a REAL new message
                            "last_msg": last_msg,
                            "reply_count": 0,
                            "is_group": c.get("is_group", False),
                            "users": c.get("users") or [],
                            "user_ids": c.get("user_ids") or [],
                            "engaged": False,
                            "last_auto_reply_at": None,
                            "last_item_type": c.get("last_item_type", ""),
                        }
                    is_first_poll = False
                    await asyncio.sleep(15)
                    continue

                # ---- PASS 2: Process each thread ----
                for c in convos:
                    tid = c.get("thread_id", "")
                    if not tid:
                        continue

                    users = c.get("users") or []
                    user_ids = c.get("user_ids") or []
                    is_from_me = c.get("is_from_me", False)
                    last_msg = (c.get("last_message") or "").strip()
                    last_item_type = c.get("last_item_type", "") or ""
                    is_group = c.get("is_group", False)

                    # --- Thread where Sir has responded ---
                    if is_from_me:
                        # Sir sent the last message — stop auto-engaging
                        if tid in self._threads:
                            del self._threads[tid]
                        continue

                    # --- Call detection (raven_media, video_call_media, etc.) ---
                    if last_item_type in CALL_ITEM_TYPES:
                        await self._handle_call_thread(tid, c, now)
                        continue

                    # --- Nothing to respond to ---
                    if not last_msg and not last_item_type:
                        continue

                    state = self._threads.get(tid)

                    # --- New thread (never seen before) — just record, don't start timer ---
                    if state is None:
                        self._threads[tid] = {
                            "first_seen": None,
                            "last_msg": last_msg,
                            "reply_count": 0,
                            "is_group": is_group,
                            "users": users,
                            "user_ids": user_ids,
                            "engaged": False,
                            "last_auto_reply_at": None,
                            "last_item_type": last_item_type,
                        }
                        continue

                    # --- Existing thread: check for new message ---
                    msg_changed = last_msg != state["last_msg"]
                    if msg_changed:
                        state["last_msg"] = last_msg
                        state["last_item_type"] = last_item_type
                        # Start the timer NOW (first genuinely new message since we started)
                        if state["first_seen"] is None and not state["engaged"]:
                            state["first_seen"] = now

                    # --- Engaged: respond to every new message ---
                    if state["engaged"]:
                        if state["reply_count"] >= self._max_replies:
                            continue
                        if state.get("last_auto_reply_at") and (now - state["last_auto_reply_at"]).total_seconds() < 20:
                            continue
                        target_id = (user_ids or [None])[0] or (users or [None])[0]
                        if not target_id:
                            continue

                        # Check for media/voice intent first
                        reply = await self._handle_media_request(tid, target_id, state, last_msg)
                        if reply:
                            # Media/voice was handled — send follow-up text
                            instagram_service.send_dm(target_id, reply)
                            state["reply_count"] += 1
                            state["last_auto_reply_at"] = now
                            log.info("auto_responder_media_reply", thread=tid[:8], intent=reply[:20])
                        else:
                            # Normal text reply
                            reply = await self._generate_contextual_reply(tid, state)
                            if reply:
                                instagram_service.send_dm(target_id, reply)
                                state["reply_count"] += 1
                                state["last_auto_reply_at"] = now
                                log.info("auto_responder_engaged_reply", thread=tid[:8])
                        continue

                    # --- Not engaged yet: check timeout ---
                    if state["first_seen"] is None:
                        continue
                    elapsed = (now - state["first_seen"]).total_seconds() / 60.0
                    if elapsed < self._timeout_minutes:
                        continue

                    # --- Timeout reached: auto-engage ---
                    target_id = (user_ids or [None])[0] or (users or [None])[0]
                    if not target_id:
                        continue

                    # Send text + voice introduction
                    text_reply = await self._generate_heads_up(tid, state)
                    if text_reply:
                        instagram_service.send_dm(target_id, text_reply)
                        state["reply_count"] += 1

                    # Also send a voice message
                    voice_text = self._heads_up_voice_text(state)
                    if voice_text:
                        lang = "ar" if any("\u0600" <= ch <= "\u06FF" for ch in voice_text) else "en"
                        instagram_service.send_voice_message([target_id], voice_text, lang=lang)

                    state["engaged"] = True
                    state["last_auto_reply_at"] = now
                    log.info("auto_responder_engaged", thread=tid[:8], timeout=self._timeout_minutes)

                    # If the original message was a media/voice request, handle it now
                    if last_msg and last_item_type in ("text", ""):
                        follow_up = await self._handle_media_request(tid, target_id, state, last_msg)
                        if follow_up:
                            instagram_service.send_dm(target_id, follow_up)
                            state["reply_count"] += 1
                            state["last_auto_reply_at"] = now
                            log.info("auto_responder_initial_media", thread=tid[:8])

                # --- Housekeeping: clean stale threads (>24h idle) ---
                stale = [tid for tid, s in self._threads.items()
                         if s.get("last_auto_reply_at") and (now - s["last_auto_reply_at"]).total_seconds() > 86400]
                for tid in stale:
                    del self._threads[tid]

            except asyncio.CancelledError:
                break
            except Exception as e:
                log.warning("auto_responder_poll_error", error=str(e))

            await asyncio.sleep(15)

    # ------------------------------------------------------------------
    # Call handling
    # ------------------------------------------------------------------

    async def _handle_call_thread(self, thread_id: str, convo: dict, now: datetime) -> None:
        """Handle incoming voice/video calls: send text + voice reply."""
        from backend.services.instagram_service import instagram_service

        # Avoid duplicate call replies (only once per 5 min per thread)
        state = self._threads.get(thread_id)
        if state and state.get("last_auto_reply_at"):
            if (now - state["last_auto_reply_at"]).total_seconds() < 300:
                return

        users = convo.get("users") or []
        user_ids = convo.get("user_ids") or []
        target_id = (user_ids or [None])[0] or (users or [None])[0]
        if not target_id:
            return

        is_group = convo.get("is_group", False)
        if is_group:
            text = "السيد مشغول حالياً. يرجى إرسال رسالة نصية بدلاً من الاتصال."
            voice_text = "السيد مشغول حالياً. أرجو إرسال رسالة نصية وسيتم الرد عليها."
        else:
            text = "السيد مشغول حالياً ولا يستطيع الرد على المكالمة. يرجى إرسال رسالة نصية وسيرد عليك في أقرب وقت."
            voice_text = "السيد مشغول حالياً ولا يمكنه الرد على المكالمة. أرجو إرسال رسالة نصية وسيتم الرد عليك قريباً."

        # Send text reply
        instagram_service.send_dm(target_id, text)

        # Send voice message
        instagram_service.send_voice_message([target_id], voice_text, lang="ar")

        # Track
        if state is None:
            self._threads[thread_id] = {
                "first_seen": now,
                "last_msg": "",
                "reply_count": 1,
                "is_group": is_group,
                "users": users,
                "user_ids": user_ids,
                "engaged": True,
                "last_auto_reply_at": now,
                "last_item_type": convo.get("last_item_type", ""),
            }
        else:
            state["reply_count"] += 1
            state["last_auto_reply_at"] = now
            state["engaged"] = True

        log.info("auto_responder_call_handled", thread=thread_id[:8], item_type=convo.get("last_item_type", ""))

    # ------------------------------------------------------------------
    # Reply generation
    # ------------------------------------------------------------------

    def _heads_up_voice_text(self, state: dict) -> str:
        """Short voice message for the initial heads-up."""
        if state["is_group"]:
            return "السيد مشغول حالياً. سيرد على الرسائل قريباً."
        return "السيد مشغول حالياً. سيرد عليك قريباً. أنا جارفيس، المساعد الشخصي."

    async def _generate_heads_up(self, thread_id: str, state: dict) -> Optional[str]:
        """Generate a first-contact message: intro + Sir is busy + offer help."""
        from backend.services.instagram_service import instagram_service

        thread_data = instagram_service.read_thread(thread_id, amount=10)
        context = self._format_context(thread_data, state)
        is_arabic = self._is_arabic_context(context)
        group_note = ""
        if state["is_group"]:
            group_note = " (المجموعة)" if is_arabic else " (group chat)"

        if is_arabic:
            prompt = (
                "أنت جارفيس، المساعد الشخصي للسيد. هذه أول مرة ترد في هذه المحادثة"
                f"{group_note}.\n"
                "قل مرحباً وعرف عن نفسك بإختصار: أنت جارفيس، مساعد السيد الآلي. "
                "اشرح أن السيد مشغول حالياً لكنه سيرد قريباً. "
                "اعرض المساعدة بأدب. كن طبيعياً وودوداً. جملة إلى ثلاث جمل.\n"
                f"سياق المحادثة:\n{context}"
            )
        else:
            prompt = (
                f"You are JARVIS, Sir's AI assistant. This is your first reply in this conversation{group_note}.\n"
                "Briefly introduce yourself, explain Sir is busy but will respond soon, "
                "and offer polite help. Keep it natural and friendly. 1-3 sentences.\n"
                f"Conversation context:\n{context}"
            )

        try:
            reply = await llm_service.get_response(
                user_message=prompt,
                system_instructions="You are JARVIS, a helpful AI assistant. Reply in the same language as the conversation.",
                inject_memory=False,
            )
            return reply.strip()
        except Exception as e:
            log.error("auto_responder_heads_up_failed", error=str(e))
            return None

    async def _generate_contextual_reply(self, thread_id: str, state: dict) -> Optional[str]:
        """Generate a natural, engaging reply — Sir is NOT mentioned again."""
        from backend.services.instagram_service import instagram_service

        thread_data = instagram_service.read_thread(thread_id, amount=30)
        context = self._format_context(thread_data, state)
        is_arabic = self._is_arabic_context(context)
        group_instruction = ""

        if state["is_group"]:
            if is_arabic:
                group_instruction = (
                    "\nهذه محادثة جماعية. خاطب المجموعة بشكل طبيعي. "
                    "تفاعل مع الموضوع. استخدم أسماء المستخدمين من السياق "
                    "لمخاطبة الأشخاص بشكل مناسب."
                )
            else:
                group_instruction = (
                    "\nThis is a group chat. Address the group naturally. "
                    "Engage with the topic being discussed. "
                    "Use usernames from the context to address people appropriately."
                )

        lang = "ARABIC" if is_arabic else "the conversation's language"
        prompt = (
            f"Respond in {lang} ONLY.\n"
            f"You are JARVIS, Sir's AI assistant. You are already in an ongoing conversation "
            f"and the person you're talking to knows who you are.\n"
            f"DO NOT mention that Sir is unavailable — this was already communicated. "
            f"Just be a natural conversation participant.\n"
            f"Engage with the current topic — ask questions, share thoughts, keep it flowing naturally. "
            f"Be helpful, thoughtful, and conversational."
            f"{group_instruction}\n"
            f"Keep it concise (1-3 sentences).\n"
            f"Conversation history:\n{context}\n"
            f"---\n"
            f"Your response:"
        )

        try:
            reply = await llm_service.get_response(
                user_message=prompt,
                system_instructions="You are JARVIS, a conversational AI assistant.",
                inject_memory=False,
            )
            return reply.strip()
        except Exception as e:
            log.error("auto_responder_contextual_reply_failed", error=str(e))
            return None

    # ------------------------------------------------------------------
    # Media / Voice intent detection and handling
    # ------------------------------------------------------------------

    async def _classify_intent(self, message: str, state: dict) -> str:
        """Classify user message intent: image, video, voice, or text."""
        prompt = (
            f"Message: {message}\n"
            f"Classify the intent. Respond with EXACTLY one word only.\n"
            f"- image: user wants me to generate/create a picture, photo, or image\n"
            f"- video: user wants me to generate/create a video or clip\n"
            f"- voice: user wants me to record/send a voice message or audio\n"
            f"- text: anything else — general chat, questions, etc.\n"
            f"Intent:"
        )
        try:
            reply = await llm_service.get_response(
                user_message=prompt,
                system_instructions="You classify intent. Reply with exactly one word: image, video, voice, or text.",
                inject_memory=False,
            )
            intent = reply.strip().lower().rstrip(".")
            if intent in ("image", "video", "voice", "text"):
                return intent
            return "text"
        except Exception:
            return "text"

    async def _extract_generation_prompt(self, message: str, intent: str) -> str:
        """Extract the generation prompt from a user's media/voice request."""
        prompt = (
            f"User message: {message}\n"
            f"Extract ONLY the {'image' if intent == 'image' else 'video' if intent == 'video' else 'voice message'} "
            f"description/prompt from this request. Return just the description, nothing else. "
            f"Keep it in the same language as the user's message."
        )
        try:
            reply = await llm_service.get_response(
                user_message=prompt,
                system_instructions="Extract and return only the generation prompt.",
                inject_memory=False,
            )
            return reply.strip()
        except Exception:
            return message

    async def _handle_media_request(self, thread_id: str, target_id: str, state: dict, message: str) -> Optional[str]:
        """Handle image/video/voice request. Returns the follow-up text reply or None."""
        intent = await self._classify_intent(message, state)
        if intent == "text":
            return None

        gen_prompt = await self._extract_generation_prompt(message, intent)

        if intent == "image":
            return await self._handle_image_request(target_id, message, gen_prompt, state)
        elif intent == "video":
            return await self._handle_video_request(target_id, message, gen_prompt, state)
        elif intent == "voice":
            return await self._handle_voice_request(target_id, message, gen_prompt, state)
        return None

    async def _handle_image_request(self, target_id: str, message: str, gen_prompt: str, state: dict) -> Optional[str]:
        """Generate image, send as DM, return follow-up text."""
        from backend.services.instagram_service import instagram_service
        from backend.services.media_generation_service import generate_image

        is_arabic = self._is_arabic_context(message)
        try:
            result = generate_image(gen_prompt, model="flux", size="1024x1024")
            if result.get("success"):
                file_path = result["file_path"]
                if os.path.exists(file_path):
                    instagram_service.send_photo([target_id], file_path)
                    log.info("auto_responder_image_sent", thread=target_id[:8])
                    return ("تم إنشاء الصورة وإرسالها! 🎨 أتمنى أن تنال إعجابك."
                            if is_arabic else
                            "Image created and sent! 🎨 Hope you like it.")
            return ("عذراً، فشل إنشاء الصورة. حاول مرة أخرى لاحقاً."
                    if is_arabic else
                    "Sorry, image generation failed. Try again later.")
        except Exception as e:
            log.error("auto_responder_image_error", error=str(e))
            return ("عذراً، حدث خطأ أثناء إنشاء الصورة."
                    if is_arabic else
                    "Sorry, an error occurred while creating the image.")

    async def _handle_video_request(self, target_id: str, message: str, gen_prompt: str, state: dict) -> Optional[str]:
        """Generate video, send as DM, return follow-up text."""
        from backend.services.instagram_service import instagram_service
        from backend.services.media_generation_service import generate_video

        is_arabic = self._is_arabic_context(message)
        try:
            result = generate_video(gen_prompt, model="deforum", duration=5)
            if result.get("success"):
                file_path = result["file_path"]
                if os.path.exists(file_path):
                    instagram_service.send_video([target_id], file_path)
                    log.info("auto_responder_video_sent", thread=target_id[:8])
                    return ("تم إنشاء الفيديو وإرساله! 🎬 أتمنى أن ينال إعجابك."
                            if is_arabic else
                            "Video created and sent! 🎬 Hope you like it.")
            return ("عذراً، فشل إنشاء الفيديو. حاول مرة أخرى لاحقاً."
                    if is_arabic else
                    "Sorry, video generation failed. Try again later.")
        except Exception as e:
            log.error("auto_responder_video_error", error=str(e))
            return ("عذراً، حدث خطأ أثناء إنشاء الفيديو."
                    if is_arabic else
                    "Sorry, an error occurred while creating the video.")

    async def _handle_voice_request(self, target_id: str, message: str, gen_prompt: str, state: dict) -> Optional[str]:
        """Generate voice content via LLM, convert to speech with gTTS, send as voice message."""
        from backend.services.instagram_service import instagram_service
        from backend.services.voice_service import voice_service

        is_arabic = self._is_arabic_context(message)
        try:
            # LLM generates the content to speak
            llm_prompt = (
                f"Write a short{' Arabic' if is_arabic else ' English'} voice message response "
                f"based on: {gen_prompt}\n"
                f"Keep it natural, conversational, and 1-3 sentences.\n"
                f"Voice message text:"
            )
            voice_content = await llm_service.get_response(
                user_message=llm_prompt,
                system_instructions=f"Write a {'Arabic' if is_arabic else 'English'} voice message. Concise, natural.",
                inject_memory=False,
            )
            voice_text = voice_content.strip()

            # Generate gTTS audio and send
            lang = "ar" if is_arabic else "en"
            instagram_service.send_voice_message([target_id], voice_text, lang=lang)
            log.info("auto_responder_voice_sent", thread=target_id[:8])

            return (f"تم إرسال الرسالة الصوتية! 🔊\n\nالرسالة: {voice_text}"
                    if is_arabic else
                    f"Voice message sent! 🔊\n\nMessage: {voice_text}")
        except Exception as e:
            log.error("auto_responder_voice_error", error=str(e))
            return ("عذراً، حدث خطأ أثناء إنشاء الرسالة الصوتية."
                    if is_arabic else
                    "Sorry, an error occurred while creating the voice message.")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _format_context(self, thread_data: dict, state: dict) -> str:
        if not thread_data.get("success"):
            return f"Last message: {state.get('last_msg', '')}"
        messages = thread_data.get("messages", [])
        if not messages:
            return f"Last message: {state.get('last_msg', '')}"
        lines = []
        for m in messages[-20:]:
            sender = "Sir (me)" if m.get("is_from_me") else m.get("sender_id", "?")[:8]
            text = m.get("text", "") or ""
            if text.strip():
                lines.append(f"[{sender}]: {text}")
        return "\n".join(lines)

    def _is_arabic_context(self, context: str) -> bool:
        import re
        return bool(re.search(r"[\u0600-\u06FF]", context))


auto_responder_service = AutoResponderService()
