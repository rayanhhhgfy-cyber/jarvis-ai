# ====================================================================
# JARVIS OMEGA — Focus Mode Service
# ====================================================================
"""
Focus Mode Service.
Keeps track of DND status, queues incoming messages,
generates conversational auto-replies via LLM, and
summarizes missed messages when Focus Mode is deactivated.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set

from backend.services.llm_service import llm_service
from shared.logger import get_logger

log = get_logger("focus_mode")


class FocusModeService:
    def __init__(self) -> None:
        self._active: bool = False
        self._focus_note: str = ""
        self._expires_at: Optional[datetime] = None
        self._auto_reply_enabled: bool = True
        self._queued_messages: List[Dict[str, Any]] = []
        self._excluded_contacts: Set[str] = set()

    def activate(self, note: str, duration_minutes: Optional[int] = None, auto_reply: bool = True) -> None:
        """Activate Focus Mode with a custom note and optional duration."""
        self._active = True
        self._focus_note = note
        self._auto_reply_enabled = auto_reply
        self._queued_messages = []
        
        if duration_minutes:
            self._expires_at = datetime.utcnow() + timedelta(minutes=duration_minutes)
        else:
            self._expires_at = None

        log.info("focus_mode_activated", note=note, duration=duration_minutes, auto_reply=auto_reply)

    def deactivate(self) -> Dict[str, Any]:
        """Deactivate Focus Mode and return a summary of queued messages."""
        if not self._active:
            return {"active": False, "summary": "Focus Mode was not active."}

        self._active = False
        self._expires_at = None
        queued = list(self._queued_messages)
        self._queued_messages = []

        log.info("focus_mode_deactivated", queued_count=len(queued))

        return {
            "active": False,
            "queued_count": len(queued),
            "queued_messages": queued,
        }

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
            "queued_count": len(self._queued_messages) if active else 0,
            "excluded_contacts": list(self._excluded_contacts),
        }

    def add_exclude_contact(self, contact_id: str) -> None:
        """Exclude a contact chat ID from DND auto-replies."""
        self._excluded_contacts.add(str(contact_id))
        log.info("contact_excluded_from_focus", contact_id=contact_id)

    def remove_exclude_contact(self, contact_id: str) -> None:
        """Remove a contact from DND exclusion."""
        self._excluded_contacts.discard(str(contact_id))
        log.info("contact_removed_from_focus_exclusion", contact_id=contact_id)

    def is_excluded(self, contact_id: str) -> bool:
        """Check if a contact chat ID is excluded from Focus DND."""
        return str(contact_id) in self._excluded_contacts

    def queue_message(self, sender: str, platform: str, text: str) -> None:
        """Log a message received while focus mode is active."""
        if not self.is_active():
            return

        msg_entry = {
            "sender": sender,
            "platform": platform,
            "text": text,
            "received_at": datetime.utcnow().isoformat(),
        }
        self._queued_messages.append(msg_entry)
        log.info("message_queued_during_focus", sender=sender, platform=platform)

    async def get_auto_reply(self, sender: str, incoming_message: str) -> Optional[str]:
        """Generate a polite, contextual auto-reply based on the focus note."""
        if not self.is_active() or not self._auto_reply_enabled:
            return None

        # Build prompt for LLM to paraphrase the focus reason in Jarvis' persona
        system_prompt = (
            "You are JARVIS, a highly sophisticated AI butler and assistant. "
            "Sir has enabled Focus Mode. Your task is to reply politely to an incoming message from a contact.\n"
            "Explain that Sir is currently busy, paraphrasing the reason he gave, without quoting it verbatim.\n"
            "Keep the reply brief, helpful, and natural (1-3 sentences). Speak as his AI assistant.\n"
            f"Sir's Focus Reason/Note: '{self._focus_note}'"
        )
        user_prompt = f"Message from {sender}: '{incoming_message}'"

        try:
            reply = await llm_service.get_response(
                user_message=user_prompt,
                system_instructions=system_prompt,
                inject_memory=False,
            )
            return reply.strip()
        except Exception as e:
            log.error("failed_to_generate_focus_auto_reply", error=str(e))
            # Direct fallback
            return f"Hello. I am JARVIS. Sir is currently occupied and focusing. I will notify him of your message when he is available."

    async def generate_queued_summary(self) -> str:
        """Generate an LLM summary of all missed messages during the focus session."""
        if not self._queued_messages:
            return "No messages were queued during this Focus session, Sir."

        system_prompt = (
            "You are JARVIS. Sir has just finished a Focus session. "
            "Summarize the following list of incoming messages he missed while focusing. "
            "Group them by sender or platform, highlight anything urgent, and keep the summary clean and highly readable."
        )

        messages_text = ""
        for i, m in enumerate(self._queued_messages, 1):
            messages_text += f"[{i}] {m['sender']} ({m['platform']}): {m['text']}\n"

        try:
            summary = await llm_service.get_response(
                user_message=messages_text,
                system_instructions=system_prompt,
                inject_memory=False,
            )
            return summary.strip()
        except Exception as e:
            log.error("failed_to_summarize_focus_queue", error=str(e))
            return f"Sir, you missed {len(self._queued_messages)} messages from: " + ", ".join(
                set(m["sender"] for m in self._queued_messages)
            )


# Singleton
focus_mode_service = FocusModeService()
