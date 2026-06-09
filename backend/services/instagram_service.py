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

    def send_dm(self, username: str, message: str) -> Dict[str, Any]:
        if not self._client:
            return {"success": False, "error": "Instagram not logged in. Connect first."}
        try:
            user_id = self._client.user_id_from_username(username)
            dm = self._client.direct_send(text=message, user_ids=[user_id])
            return {"success": True, "thread_id": str(dm.thread_id), "message": f"DM sent to {username}."}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def read_inbox(self, limit: int = 20) -> Dict[str, Any]:
        if not self._client:
            return {"success": False, "error": "Instagram not logged in. Connect first."}
        try:
            threads = self._client.direct_threads(amount=limit, thread_message_limit=0)
            result = []
            for t in threads:
                try:
                    users = [u.username for u in (t.users or [])]
                except Exception:
                    users = []
                result.append({
                    "thread_id": str(t.id),
                    "title": t.title or "",
                    "users": users,
                    "last_message": str(t.last_activity_at or ""),
                })
            return {"success": True, "conversations": result}
        except Exception as e:
            log.warning("read_inbox_fallback_raw", error=str(e))
            try:
                resp = self._client.private_request("direct_v2/inbox/?")
                threads_raw = resp.get("inbox", {}).get("threads", [])
                result = []
                for t in threads_raw:
                    users = [u.get("username", "") for u in (t.get("users") or [])]
                    result.append({
                        "thread_id": str(t.get("thread_id", "")),
                        "title": t.get("thread_title", ""),
                        "users": users,
                        "last_message": str(t.get("last_activity_at", "")),
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
