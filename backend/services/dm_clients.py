# ====================================================================
# JARVIS OMEGA — DM Platform Clients (Messenger + Instagram)
# ====================================================================
"""
Low-level clients that speak to Messenger and Instagram as Sir's own
account, using the credentials stored by ``dm_auth``.

* Instagram — the ``instagrapi`` library (maintained, mimics the official
  mobile app API). Login by session id or by username/password; list
  direct threads; send a DM.
* Messenger — a cookie-based web client grounded in the public
  ``facebook-chat-api`` project (Schmavery/facebook-chat-api, master):
  thread list via ``POST https://www.facebook.com/api/graphqlbatch/``
  (doc_id 1349387578499440) and send via
  ``POST https://www.facebook.com/messaging/send/`` (the "mercury"
  form). Meta's web endpoints change without notice: if a response no
  longer matches the expected shape, the client raises
  ``DMClientError`` and the responder marks the platform degraded —
  it never pretends a reply was sent when it was not.

Both clients are best-effort against undocumented endpoints. Only the
session probe (``validate``) can be proven without real credentials;
sending and polling are verified structurally (see tests) and will be
proven live the first time Sir connects a real account.
"""

from __future__ import annotations

import asyncio
import json
import random
import re
import time
from typing import Any

import httpx

from shared.logger import get_logger

log = get_logger("dm_clients")

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
        "Mobile/15E148 Safari/604.1"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
}


class DMClientError(Exception):
    """A platform client failed (login, poll, or send)."""


class DMMessage(dict[str, Any]):
    """One incoming DM, normalized across platforms."""


def _new_message(
    platform: str,
    thread_id: str,
    sender_id: str,
    sender_name: str,
    text: str,
    message_id: str,
    is_group: bool = False,
    media_url: str | None = None,
    media_type: str | None = None,
) -> DMMessage:
    """``media_type`` is "photo" or "voice" when the message carries media
    instead of (or in addition to) text; ``media_url`` is its direct URL."""
    return DMMessage(
        platform=platform,
        thread_id=str(thread_id),
        sender_id=str(sender_id),
        sender_name=sender_name or "Unknown",
        text=text or "",
        message_id=str(message_id),
        is_group=is_group,
        media_url=media_url,
        media_type=media_type,
    )


def _instagram_media(last: Any) -> tuple[str | None, str | None]:
    """(media_url, media_type) for an instagrapi DirectMessage, else (None, None).

    Photos arrive as item_type "media" with image_versions2 candidates;
    voice notes as item_type "voice_media" with an audio source URL.
    Everything is defensive — instagrapi's shape varies by version.
    """
    item_type = getattr(last, "item_type", "") or ""
    if item_type == "media":
        media = getattr(last, "media", None)
        versions = getattr(media, "image_versions2", None) if media else None
        candidates = (versions or {}).get("candidates") if isinstance(versions, dict) else None
        if candidates:
            url = (candidates[0] or {}).get("url")
            if url:
                return url, "photo"
        # A video message: fall back to its thumbnail.
        video_versions = getattr(media, "video_versions", None) if media else None
        if video_versions:
            url = (video_versions[0] or {}).get("url")
            if url:
                return url, "photo"
        return None, None
    if item_type == "voice_media":
        voice = getattr(last, "voice_media", None)
        media = getattr(voice, "media", None) if voice else None
        audio = getattr(media, "audio", None) if media else None
        if isinstance(audio, dict):
            url = audio.get("audio_src")
            if url:
                return url, "voice"
        return None, None
    return None, None


def _messenger_media(node: dict[str, Any]) -> tuple[str | None, str | None]:
    """Best-effort (media_url, media_type) from a Messenger thread-list node.

    The thread list only carries a text snippet, so a photo or voice note
    usually arrives with no usable URL here — the responder then treats
    it as a text-less message and replies generically. Returns (None, None)
    unless the node happens to carry an attachment URL.
    """
    attachments = node.get("attachments") or []
    for att in attachments:
        if not isinstance(att, dict):
            continue
        mime = (att.get("mime_type") or att.get("mimeType") or "").lower()
        url = att.get("url") or (att.get("image") or {}).get("uri") or ""
        if not url:
            continue
        if mime.startswith("image") or "image" in mime:
            return url, "photo"
        if mime.startswith("audio") or "audio" in mime:
            return url, "voice"
    return None, None


# --------------------------------------------------------------------
# Messenger (cookie-based web client)
# --------------------------------------------------------------------

class MessengerClient:
    """Messenger as Sir, via session cookies + the web endpoints."""

    # doc_id from facebook-chat-api's getThreadList (valid 2018-04-04;
    # Meta rotates these — a mismatch surfaces as DMClientError).
    _THREAD_LIST_DOC_ID = "1349387578499440"

    def __init__(
        self,
        cookies: dict[str, str],
        transport: httpx.AsyncHTTPTransport | None = None,
    ) -> None:
        self._cookies = dict(cookies)
        self._transport = transport
        self.user_id: str | None = self._cookies.get("c_user")
        self._fb_dtsg: str | None = None

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            headers=_BROWSER_HEADERS,
            cookies=self._cookies,
            transport=self._transport,
            follow_redirects=True,
            timeout=30.0,
        )

    async def validate(self) -> bool:
        """True when the session is live; also scrapes the fb_dtsg token."""
        async with self._client() as client:
            try:
                resp = await client.get("https://www.messenger.com/")
            except Exception as e:
                log.warning("messenger_validate_failed", error=str(e))
                return False
        if resp.status_code != 200 or "login" in str(resp.url):
            return False
        m = re.search(r'"fb_dtsg"\s*:\s*"([^"]+)"', resp.text) or re.search(
            r'name="fb_dtsg"\s+value="([^"]+)"', resp.text
        )
        if m:
            self._fb_dtsg = m.group(1)
        if not self.user_id:
            m_uid = re.search(r'"USER_ID"\s*:\s*"(\d+)"', resp.text)
            if m_uid:
                self.user_id = m_uid.group(1)
        return True

    async def list_recent(self, limit: int = 10) -> list[DMMessage]:
        """Latest message of each recent thread (responder dedups by id)."""
        form = {
            "queries": json.dumps({
                "o0": {
                    "doc_id": self._THREAD_LIST_DOC_ID,
                    "query_params": {
                        "limit": limit,
                        "before": None,
                        "tags": [""],
                        "includeDeliveryReceipts": True,
                        "includeSeqID": False,
                    },
                }
            }),
        }
        if self._fb_dtsg:
            form["fb_dtsg"] = self._fb_dtsg
        async with self._client() as client:
            resp = await client.post(
                "https://www.facebook.com/api/graphqlbatch/", data=form
            )
        if resp.status_code != 200:
            raise DMClientError(f"Thread list returned HTTP {resp.status_code}")
        try:
            data = resp.json()
            nodes = data[0]["o0"]["data"]["viewer"]["message_threads"]["nodes"]
        except Exception as e:
            raise DMClientError(
                "Messenger thread-list shape changed (Meta rotated the "
                f"endpoint). Raw error: {e}"
            ) from e
        out: list[DMMessage] = []
        for t in nodes:
            try:
                last = (t.get("last_message") or {}).get("nodes") or []
                if not last:
                    continue
                node = last[0]
                thread_key = t.get("thread_key") or {}
                thread_id = thread_key.get("thread_fbid") or thread_key.get("other_user_id")
                sender = (node.get("message_sender") or {}).get("messaging_actor") or {}
                media_url, media_type = _messenger_media(node)
                out.append(_new_message(
                    platform="messenger",
                    thread_id=thread_id,
                    sender_id=sender.get("id", ""),
                    sender_name=sender.get("name", ""),
                    text=node.get("snippet", ""),
                    message_id=node.get("message_id", "") or node.get("id", ""),
                    is_group=(t.get("thread_type") == "GROUP"),
                    media_url=media_url,
                    media_type=media_type,
                ))
            except Exception as parse_err:
                # One malformed thread must not kill the whole list.
                log.warning("messenger_thread_parse_failed", error=str(parse_err))
                continue
        return out

    async def send(self, thread_id: str, text: str) -> dict[str, Any]:
        """Send a text message to an existing thread."""
        if not self.user_id:
            raise DMClientError("Messenger user id unknown — validate first.")
        otid = str(random.randint(10**18, 10**19 - 1))
        form: dict[str, Any] = {
            "client": "mercury",
            "action_type": "ma-type:user-generated-message",
            "author": f"fbid:{self.user_id}",
            "timestamp": str(int(time.time() * 1000)),
            "timestamp_absolute": "Today",
            "timestamp_relative": "now",
            "timestamp_time_passed": "0",
            "is_unread": "false",
            "is_cleared": "false",
            "is_forward": "false",
            "is_filtered_content": "false",
            "is_filtered_content_bh": "false",
            "is_filtered_content_account": "false",
            "is_filtered_content_quasar": "false",
            "is_filtered_content_invalid_app": "false",
            "is_spoof_warning": "false",
            "source": "source:chat:web",
            "source_tags[0]": "source:chat",
            "body": text,
            "html_body": "false",
            "ui_push_phase": "V3",
            "status": "0",
            "offline_threading_id": otid,
            "message_id": otid,
            "threading_id": f"{int(time.time() * 1000)}:{otid}",
            "ephemeral_ttl_mode:": "0",
            "manual_retry_cnt": "0",
            "thread_fbid": str(thread_id),
        }
        if self._fb_dtsg:
            form["fb_dtsg"] = self._fb_dtsg
        async with self._client() as client:
            resp = await client.post(
                "https://www.facebook.com/messaging/send/", data=form
            )
        if resp.status_code != 200:
            raise DMClientError(f"Messenger send returned HTTP {resp.status_code}")
        try:
            payload = resp.json()
        except Exception as e:
            raise DMClientError(f"Messenger send returned non-JSON: {e}") from e
        if payload.get("error"):
            raise DMClientError(f"Messenger send error: {payload['error']}")
        actions = (payload.get("payload") or {}).get("actions") or []
        if not actions:
            raise DMClientError("Messenger send returned no action (not delivered).")
        return {"ok": True, "message_id": actions[0].get("message_id", otid)}


# --------------------------------------------------------------------
# Instagram (instagrapi)
# --------------------------------------------------------------------

class InstagramClient:
    """Instagram DMs as Sir, via instagrapi (official mobile-app API).

    Session restore prefers the full instagrapi settings (from
    ``dump_settings()`` after a password login) via ``set_settings()``.
    A bare browser ``sessionid`` is NOT enough: Instagram rejects a
    browser/web session for the private mobile API with ``login_required``
    (instagrapi's own docs). ``login_by_sessionid()`` is kept only as a
    fallback for cookies-only connections, which are unreliable for the
    private API.
    """

    def __init__(
        self,
        session_cookies: dict[str, str] | None = None,
        settings: dict[str, Any] | None = None,
    ) -> None:
        self._session_cookies = dict(session_cookies or {})
        self._settings = dict(settings or {})
        self._cl = None  # instagrapi.Client, created lazily
        self.user_id: str | None = self._session_cookies.get("ds_user_id")

    def _require_client(self):
        try:
            from instagrapi import Client
        except ImportError as e:
            raise DMClientError(
                "instagrapi is not installed, so Instagram DMs are "
                "unavailable. Install it (pip install instagrapi) or "
                "connect with cookies after installing."
            ) from e
        if self._cl is None:
            self._cl = Client()
            if self._settings:
                # Full session restore (device UUIDs + auth + cookies):
                # the documented long-lived flow.
                try:
                    self._cl.set_settings(self._settings)
                except Exception as e:
                    raise DMClientError(f"Instagram session restore failed: {e}") from e
            elif self._session_cookies.get("sessionid"):
                try:
                    self._cl.login_by_sessionid(self._session_cookies["sessionid"])
                except Exception as e:
                    raise DMClientError(f"Instagram session login failed: {e}") from e
        return self._cl

    def login_with_password(self, username: str, password: str) -> dict[str, Any]:
        """Blocking login; returns fresh session cookies + full settings."""
        cl = self._require_client()
        cl.login(username, password)
        cookies = {
            k: v
            for k, v in cl.private.cookies.items()
            if k in ("sessionid", "ds_user_id", "csrftoken", "mid", "ig_did")
        }
        try:
            settings = cl.dump_settings()
        except Exception:
            settings = {}
        return {"cookies": cookies, "settings": settings}

    def validate(self) -> bool:
        # NOTE: do NOT call get_timeline_feed(amount=...) here — instagrapi
        # 3.2.8's get_timeline_feed takes no `amount` kwarg (it takes
        # reason/max_id/seen_posts/feed_view_info), so passing amount=
        # raises TypeError and validate() wrongly reports the session as
        # expired. account_info() alone is the real session check: it
        # fetches the authenticated user's info and raises if the session
        # is invalid.
        try:
            cl = self._require_client()
            info = cl.account_info()
            if info and getattr(info, "pk", None):
                self.user_id = str(info.pk)
            return True
        except Exception as e:
            log.warning("instagram_validate_failed", error=str(e))
            return False

    async def list_recent(self, limit: int = 10) -> list[DMMessage]:
        cl = self._require_client()
        threads = await asyncio.to_thread(cl.direct_threads, amount=limit)
        out: list[DMMessage] = []
        for th in threads or []:
            try:
                msgs = getattr(th, "messages", None) or []
                if not msgs:
                    continue
                last = msgs[0]
                sender = getattr(last, "user", None)
                media_url, media_type = _instagram_media(last)
                out.append(_new_message(
                    platform="instagram",
                    thread_id=getattr(th, "id", ""),
                    sender_id=str(getattr(sender, "pk", "") or ""),
                    sender_name=getattr(sender, "full_name", "") or getattr(sender, "username", ""),
                    text=getattr(last, "text", "") or "",
                    message_id=str(getattr(last, "id", "")),
                    is_group=len(getattr(th, "users", []) or []) > 1,
                    media_url=media_url,
                    media_type=media_type,
                ))
            except Exception as parse_err:
                # One malformed thread must not kill the whole list.
                log.warning("instagram_thread_parse_failed", error=str(parse_err))
                continue
        return out

    async def send(self, thread_id: str, text: str) -> dict[str, Any]:
        cl = self._require_client()
        result = await asyncio.to_thread(cl.direct_send, text, thread_ids=[str(thread_id)])
        return {"ok": True, "message_id": str(getattr(result, "id", "") or "")}

    async def send_voice(self, thread_id: str, audio_path: Any) -> dict[str, Any]:
        """Send a voice message (.m4a/AAC) to a thread. Instagram only."""
        cl = self._require_client()
        try:
            tid = int(thread_id)
        except (TypeError, ValueError):
            return {"ok": False, "reason": "bad_thread_id"}
        result = await asyncio.to_thread(
            cl.direct_send_voice, audio_path, thread_ids=[tid]
        )
        return {"ok": True, "message_id": str(getattr(result, "id", "") or "")}

    async def get_thread_messages(
        self, thread_id: str, amount: int = 20
    ) -> list[dict[str, Any]]:
        """Recent messages of one thread (for DM search). Text only."""
        cl = self._require_client()
        try:
            tid = int(thread_id)
        except (TypeError, ValueError):
            return []
        thread = await asyncio.to_thread(cl.direct_thread, tid, amount=amount)
        out: list[dict[str, Any]] = []
        for msg in getattr(thread, "messages", None) or []:
            text = getattr(msg, "text", "") or ""
            sender = getattr(msg, "user", None)
            out.append({
                "text": text,
                "sender_name": (
                    getattr(sender, "full_name", "") or getattr(sender, "username", "")
                ),
                "message_id": str(getattr(msg, "id", "")),
            })
        return out
