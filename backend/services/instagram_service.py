"""Instagram API service using instagrapi — bypasses browser anti-bot entirely.

Logs in via Instagram's private API (same as the mobile app), persists session
to disk, and provides DM send/read methods without needing a browser.
"""
import os
import json
import time
from typing import Any, Dict, List, Optional

from shared.logger import get_logger

log = get_logger("instagram_service")

_SESSION_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "storage", "instagram_session.json")
)


class InstagramService:
    def __init__(self):
        self._client = None

    @property
    def available(self) -> bool:
        return self._client is not None

    def login(self, username: str, password: str, verification_code: str = "") -> Dict[str, Any]:
        from instagrapi import Client
        from instagrapi.exceptions import (
            LoginRequired, BadPassword, PleaseWaitFewMinutes,
            ChallengeError, ReloginAttemptExceeded, ClientError,
        )

        cl = Client()
        cl.delay_range = [1, 3]
        cl.set_user_agent(
            "Instagram 276.0.0.18.103 Android (29/10; 440dpi; 1440x3040; "
            "OnePlus; GM1913; OnePlus7Pro; qcom; en_US; 487311349)"
        )

        if os.path.isfile(_SESSION_PATH):
            try:
                with open(_SESSION_PATH) as f:
                    settings = json.load(f)
                cl.set_settings(settings)
                log.info("instagram_loaded_saved_device_settings")
            except Exception as e:
                log.warning("instagram_settings_load_failed", error=str(e))
        else:
            self._save_client_settings(cl)

        if os.path.isfile(_SESSION_PATH):
            try:
                cl.login(username, password)
                log.info("instagram_relogin_session_ok")
                self._client = cl
                self._save_client_settings(cl)
                return {"success": True, "message": "Logged in via saved session."}
            except LoginRequired:
                log.info("instagram_session_expired_relogin")
                cl = Client()
                cl.delay_range = [1, 3]
                cl.set_user_agent(
                    "Instagram 276.0.0.18.103 Android (29/10; 440dpi; 1440x3040; "
                    "OnePlus; GM1913; OnePlus7Pro; qcom; en_US; 487311349)"
                )
                if os.path.isfile(_SESSION_PATH):
                    try:
                        with open(_SESSION_PATH) as f:
                            cl.set_settings(json.load(f))
                    except Exception:
                        pass
            except Exception as e:
                log.warning("instagram_session_replay_failed", error=str(e))

        try:
            if verification_code:
                cl.challenge_code_handler = lambda cl, code: verification_code
            cl.login(username, password)
        except BadPassword:
            return {"success": False, "error": "Invalid Instagram credentials."}
        except PleaseWaitFewMinutes as e:
            return {"success": False, "error": f"Instagram rate-limited: {e}"}
        except ChallengeError as e:
            self._save_client_settings(cl)
            return {
                "success": False,
                "error": "Instagram needs verification. Check your Instagram app or email for a login code, "
                         "then reconnect with the format: username:password:verification_code",
                "needs_verification": True,
            }
        except Exception as e:
            self._save_client_settings(cl)
            return {"success": False, "error": f"Login failed: {e}"}

        self._client = cl
        self._save_client_settings(cl)
        log.info("instagram_login_ok")
        return {"success": True, "message": "Instagram logged in via API."}

    def login_by_sessionid(self, sessionid: str) -> Dict[str, Any]:
        from instagrapi import Client
        cl = Client()
        cl.delay_range = [1, 3]
        cl.set_user_agent(
            "Instagram 276.0.0.18.103 Android (29/10; 440dpi; 1440x3040; "
            "OnePlus; GM1913; OnePlus7Pro; qcom; en_US; 487311349)"
        )
        try:
            cl.login_by_sessionid(sessionid)
        except Exception as e:
            return {"success": False, "error": str(e)}
        self._client = cl
        self._save_client_settings(cl)
        log.info("instagram_login_by_sessionid_ok", user=cl.username)
        return {"success": True, "message": f"Logged in as {cl.username} via session."}

    def logout(self) -> Dict[str, Any]:
        self._client = None
        if os.path.isfile(_SESSION_PATH):
            os.remove(_SESSION_PATH)
        log.info("instagram_logged_out")
        return {"success": True, "message": "Instagram disconnected."}

    def send_dm(self, username_or_id: str, message: str) -> Dict[str, Any]:
        """Send a DM. `username_or_id` is either an IG username or numeric user ID.
        If it looks numeric (>5 digits), it's treated as a user_id directly,
        bypassing the username-to-ID lookup which can fail on display names.
        """
        if not self._client:
            return {"success": False, "error": "Instagram not logged in. Connect first."}
        try:
            # If the value looks like a numeric user_id, use it directly
            if username_or_id.isdigit() and len(username_or_id) > 5:
                user_id = int(username_or_id)
            else:
                user_id = self._client.user_id_from_username(username_or_id)
            dm = self._client.direct_send(text=message, user_ids=[user_id])
            return {"success": True, "thread_id": str(dm.thread_id), "message": f"DM sent."}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def send_voice_message(self, user_ids: list, text: str, lang: str = "ar") -> Dict[str, Any]:
        """Generate a voice message via gTTS and send it to the given user_ids.

        Args:
            user_ids: List of numeric user IDs (int or str).
            text: Text to speak in the voice message.
            lang: Language code ('ar' or 'en').

        Returns:
            {"success": True, "message": "..."} or {"success": False, "error": "..."}
        """
        if not self._client:
            return {"success": False, "error": "Instagram not logged in. Connect first."}
        try:
            from backend.services.voice_service import voice_service
            audio_path = voice_service.generate_voice(text, lang=lang)
            if not audio_path:
                return {"success": False, "error": "Failed to generate voice audio"}
            from pathlib import Path
            int_ids = [int(uid) for uid in user_ids if str(uid).isdigit()]
            if not int_ids:
                return {"success": False, "error": "No valid numeric user_ids provided"}
            dm = self._client.direct_send_voice(path=Path(audio_path), user_ids=int_ids)
            log.info("voice_dm_sent", user_ids=user_ids, chars=len(text))
            return {"success": True, "thread_id": str(getattr(dm, "thread_id", "")), "message": "Voice message sent."}
        except Exception as e:
            log.warning("voice_dm_send_failed", error=str(e))
            return {"success": False, "error": str(e)}

    def send_photo(self, user_ids: list, file_path: str) -> Dict[str, Any]:
        """Send a photo file via DM. file_path must be a local path to an image."""
        if not self._client:
            return {"success": False, "error": "Instagram not logged in. Connect first."}
        try:
            from pathlib import Path
            int_ids = [int(uid) for uid in user_ids if str(uid).isdigit()]
            if not int_ids:
                return {"success": False, "error": "No valid numeric user_ids provided"}
            p = Path(file_path)
            if not p.is_file():
                return {"success": False, "error": f"Photo file not found: {file_path}"}
            dm = self._client.direct_send_photo(path=p, user_ids=int_ids)
            log.info("photo_dm_sent", user_ids=user_ids, file=file_path)
            return {"success": True, "thread_id": str(getattr(dm, "thread_id", "")), "message": "Photo sent."}
        except Exception as e:
            log.warning("photo_dm_send_failed", error=str(e))
            return {"success": False, "error": str(e)}

    def send_video(self, user_ids: list, file_path: str) -> Dict[str, Any]:
        """Send a video file via DM. file_path must be a local path to an MP4."""
        if not self._client:
            return {"success": False, "error": "Instagram not logged in. Connect first."}
        try:
            from pathlib import Path
            int_ids = [int(uid) for uid in user_ids if str(uid).isdigit()]
            if not int_ids:
                return {"success": False, "error": "No valid numeric user_ids provided"}
            p = Path(file_path)
            if not p.is_file():
                return {"success": False, "error": f"Video file not found: {file_path}"}
            dm = self._client.direct_send_video(path=p, user_ids=int_ids)
            log.info("video_dm_sent", user_ids=user_ids, file=file_path)
            return {"success": True, "thread_id": str(getattr(dm, "thread_id", "")), "message": "Video sent."}
        except Exception as e:
            log.warning("video_dm_send_failed", error=str(e))
            return {"success": False, "error": str(e)}

    def read_thread(self, thread_id: str, amount: int = 20) -> Dict[str, Any]:
        """Read full message history for a specific thread."""
        if not self._client:
            return {"success": False, "error": "Instagram not logged in. Connect first."}
        my_id = str(getattr(self._client, "user_id", ""))
        try:
            thread = self._client.direct_thread(thread_id, amount=amount)
            messages = []
            for m in reversed(getattr(thread, "messages", []) or []):
                sender_id = str(getattr(m, "user_id", ""))
                text = ""
                if hasattr(m, "text") and m.text:
                    text = m.text
                elif hasattr(m, "item_type") and m.item_type == "text":
                    text = getattr(m, "text", "") or ""
                messages.append({
                    "sender_id": sender_id,
                    "text": text,
                    "is_from_me": bool(my_id) and sender_id == my_id,
                    "timestamp": str(getattr(m, "timestamp", "")),
                })
            return {
                "success": True,
                "thread_id": str(getattr(thread, "id", thread_id)),
                "messages": messages,
            }
        except Exception as e:
            log.warning("read_thread_failed", error=str(e), thread_id=thread_id)
            return {"success": False, "error": str(e)}

    def read_inbox(self, limit: int = 20) -> Dict[str, Any]:
        if not self._client:
            return {"success": False, "error": "Instagram not logged in. Connect first."}
        my_id = str(getattr(self._client, "user_id", ""))
        try:
            threads = self._client.direct_threads(amount=limit, thread_message_limit=1)
            result = []
            for t in threads:
                try:
                    user_ids = [str(u.pk) for u in (t.users or [])]
                    users = [u.username for u in (t.users or [])]
                except Exception:
                    user_ids = []
                    users = []
                last_text = ""
                last_sender_id = ""
                last_item_type = ""
                try:
                    if t.messages and len(t.messages) > 0:
                        last_msg = t.messages[-1]
                        last_sender_id = str(getattr(last_msg, "user_id", ""))
                        last_item_type = str(getattr(last_msg, "item_type", "") or "")
                        if hasattr(last_msg, "text"):
                            last_text = (last_msg.text or "")
                        elif hasattr(last_msg, "item_type") and last_msg.item_type == "text":
                            last_text = (getattr(last_msg, "text", "") or "")
                except Exception:
                    pass
                result.append({
                    "thread_id": str(t.id),
                    "title": t.title or "",
                    "users": users,
                    "user_ids": user_ids,
                    "last_message": last_text,
                    "last_sender_id": last_sender_id,
                    "last_item_type": last_item_type,
                    "is_from_me": bool(my_id) and last_sender_id == my_id,
                    "is_group": getattr(t, "is_group", False) or bool(getattr(t, "thread_type", "") == "group"),
                })
            return {"success": True, "conversations": result}
        except Exception as e:
            log.warning("read_inbox_fallback_raw", error=str(e))
            try:
                resp = self._client.private_request("direct_v2/inbox/?")
                threads_raw = resp.get("inbox", {}).get("threads", [])
                result = []
                for t in threads_raw:
                    user_ids = [str(u.get("pk", "")) for u in (t.get("users") or [])]
                    users = [u.get("username", "") for u in (t.get("users") or [])]
                    last_text = ""
                    last_sender_id = ""
                    last_item_type = ""
                    last_permanent = t.get("last_permanent_item", {})
                    last_item_type = str(last_permanent.get("item_type", "") or "")
                    if last_permanent.get("item_type") == "text":
                        last_text = last_permanent.get("text", "")
                        last_sender_id = str(last_permanent.get("user_id", ""))
                    result.append({
                        "thread_id": str(t.get("thread_id", "")),
                        "title": t.get("thread_title", ""),
                        "users": users,
                        "user_ids": user_ids,
                        "last_message": last_text,
                        "last_sender_id": last_sender_id,
                        "last_item_type": last_item_type,
                        "is_from_me": bool(my_id) and last_sender_id == my_id,
                        "is_group": bool(t.get("is_group", False)) or t.get("thread_type") == "group",
                    })
                return {"success": True, "conversations": result}
            except Exception as e2:
                return {"success": False, "error": str(e2)}

    def _save_client_settings(self, cl):
        try:
            os.makedirs(os.path.dirname(_SESSION_PATH), exist_ok=True)
            with open(_SESSION_PATH, "w") as f:
                json.dump(cl.get_settings(), f, indent=2)
        except Exception as e:
            log.warning("instagram_client_settings_save_failed", error=str(e))


instagram_service = InstagramService()


# Auto-load saved session on import
if os.path.isfile(_SESSION_PATH):
    try:
        from instagrapi import Client
        cl = Client()
        cl.set_user_agent(
            "Instagram 276.0.0.18.103 Android (29/10; 440dpi; 1440x3040; "
            "OnePlus; GM1913; OnePlus7Pro; qcom; en_US; 487311349)"
        )
        with open(_SESSION_PATH) as f:
            settings = json.load(f)
        if settings.get("authorization"):
            cl.set_settings(settings)
            cl.login_by_sessionid(settings.get("authorization"))
            instagram_service._client = cl
            log.info("instagram_auto_loaded_session", user=cl.username)
        elif settings.get("cookies", {}).get("sessionid"):
            cl.set_settings(settings)
            cl.login_by_sessionid(settings["cookies"]["sessionid"])
            instagram_service._client = cl
            log.info("instagram_auto_loaded_session", user=cl.username)
    except Exception as e:
        log.warning("instagram_auto_load_failed", error=str(e))
