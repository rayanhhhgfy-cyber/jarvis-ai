# ====================================================================
# JARVIS OMEGA — Free IMAP Email Plugin (read inbox)
# ====================================================================
"""
Phase 10 plugin: read emails via IMAP. Pairs with the existing
``email.send`` (SMTP) tool from ``plugins.communication``.

Credentials come from the credentials vault:
  * ``imap_host``        — e.g. imap.gmail.com
  * ``imap_port``        — usually 993
  * ``imap_user``        — email address
  * ``imap_password``    — account password OR app-specific password

For Gmail, enable IMAP and generate an App Password at
https://myaccount.google.com/apppasswords — regular passwords no longer work.
"""

from __future__ import annotations

import asyncio
import email
from email.header import decode_header
from typing import Any, Dict, List, Optional

from backend.tools import tool, RiskTier


def _cred(key: str) -> Optional[str]:
    try:
        from backend.services.credentials_vault import credentials_vault
        return credentials_vault.get(key) or None
    except Exception:
        return None


def _decode_str(s) -> str:
    """Decode RFC 2047 encoded headers."""
    if not s:
        return ""
    parts = decode_header(str(s))
    out = []
    for text, enc in parts:
        if isinstance(text, bytes):
            out.append(text.decode(enc or "utf-8", errors="replace"))
        else:
            out.append(text)
    return "".join(out)


def _body_text(msg) -> str:
    """Extract plain-text body from an email.message.Message."""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                try:
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        return payload.decode(charset, errors="replace")[:5000]
                except Exception:
                    continue
        return ""
    try:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            return payload.decode(charset, errors="replace")[:5000]
    except Exception:
        return ""
    return ""


def _connect_sync(host: str, port: int, user: str, pw: str):
    import imaplib
    conn = imaplib.IMAP4_SSL(host, port)
    conn.login(user, pw)
    return conn


# --------------------------------------------------------------------
# Tools
# --------------------------------------------------------------------

@tool(
    name="email.list",
    description="List the most recent emails in a folder (INBOX by default). Requires imap_* credentials in the vault.",
    parameters={
        "type": "object",
        "properties": {
            "folder": {"type": "string", "default": "INBOX"},
            "limit": {"type": "integer", "default": 10},
            "unseen_only": {"type": "boolean", "default": False},
        },
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="email",
)
async def email_list(folder: str = "INBOX", limit: int = 10, unseen_only: bool = False) -> Dict[str, Any]:
    host = _cred("imap_host")
    port = _cred("imap_port")
    user = _cred("imap_user")
    pw = _cred("imap_password")
    if not (host and port and user and pw):
        return {"ok": False, "error": "imap_host / imap_port / imap_user / imap_password not set in vault"}

    def _fetch():
        conn = _connect_sync(host, int(port), user, pw)
        try:
            conn.select(folder, readonly=True)
            criterion = "(UNSEEN)" if unseen_only else "ALL"
            typ, data = conn.search(None, criterion)
            if typ != "OK":
                return {"ok": False, "error": f"imap search failed: {typ}"}
            ids = data[0].split()[-limit:]
            results = []
            for mid in reversed(ids):
                typ, msg_data = conn.fetch(mid, "(RFC822.HEADER)")
                if typ != "OK" or not msg_data or not msg_data[0]:
                    continue
                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)
                results.append({
                    "id": mid.decode(),
                    "from": _decode_str(msg.get("From")),
                    "to": _decode_str(msg.get("To")),
                    "subject": _decode_str(msg.get("Subject")),
                    "date": msg.get("Date", ""),
                })
            return {"ok": True, "folder": folder, "count": len(results), "messages": results}
        finally:
            try:
                conn.logout()
            except Exception:
                pass

    return await asyncio.to_thread(_fetch)


@tool(
    name="email.read",
    description="Read a single email by its message ID. Returns full body text.",
    parameters={
        "type": "object",
        "properties": {
            "message_id": {"type": "string"},
            "folder": {"type": "string", "default": "INBOX"},
            "mark_read": {"type": "boolean", "default": False},
        },
        "required": ["message_id"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="email",
)
async def email_read(message_id: str, folder: str = "INBOX", mark_read: bool = False) -> Dict[str, Any]:
    host = _cred("imap_host")
    port = _cred("imap_port")
    user = _cred("imap_user")
    pw = _cred("imap_password")
    if not (host and port and user and pw):
        return {"ok": False, "error": "imap credentials not set in vault"}

    def _read():
        conn = _connect_sync(host, int(port), user, pw)
        try:
            conn.select(folder, readonly=not mark_read)
            typ, msg_data = conn.fetch(message_id.encode() if isinstance(message_id, str) else message_id, "(RFC822)")
            if typ != "OK":
                return {"ok": False, "error": f"fetch failed: {typ}"}
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)
            return {
                "ok": True,
                "message_id": message_id,
                "from": _decode_str(msg.get("From")),
                "to": _decode_str(msg.get("To")),
                "subject": _decode_str(msg.get("Subject")),
                "date": msg.get("Date", ""),
                "body": _body_text(msg),
            }
        finally:
            try:
                conn.logout()
            except Exception:
                pass

    return await asyncio.to_thread(_read)


@tool(
    name="email.search",
    description="Search emails by sender, subject, or body keyword.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search term (matched against FROM, SUBJECT, BODY by IMAP)."},
            "folder": {"type": "string", "default": "INBOX"},
            "limit": {"type": "integer", "default": 10},
        },
        "required": ["query"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="email",
)
async def email_search(query: str, folder: str = "INBOX", limit: int = 10) -> Dict[str, Any]:
    host = _cred("imap_host")
    port = _cred("imap_port")
    user = _cred("imap_user")
    pw = _cred("imap_password")
    if not (host and port and user and pw):
        return {"ok": False, "error": "imap credentials not set in vault"}

    def _search():
        conn = _connect_sync(host, int(port), user, pw)
        try:
            conn.select(folder, readonly=True)
            typ, data = conn.search(None, "TEXT", f'"{query}"')
            if typ != "OK":
                return {"ok": False, "error": f"imap search failed: {typ}"}
            ids = data[0].split()[-limit:]
            results = []
            for mid in reversed(ids):
                typ, msg_data = conn.fetch(mid, "(RFC822.HEADER)")
                if typ != "OK" or not msg_data or not msg_data[0]:
                    continue
                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)
                results.append({
                    "id": mid.decode(),
                    "from": _decode_str(msg.get("From")),
                    "subject": _decode_str(msg.get("Subject")),
                    "date": msg.get("Date", ""),
                })
            return {"ok": True, "query": query, "count": len(results), "messages": results}
        finally:
            try:
                conn.logout()
            except Exception:
                pass

    return await asyncio.to_thread(_search)


@tool(
    name="email.mark_read",
    description="Mark an email as read by message ID.",
    parameters={
        "type": "object",
        "properties": {
            "message_id": {"type": "string"},
            "folder": {"type": "string", "default": "INBOX"},
        },
        "required": ["message_id"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="email",
)
async def email_mark_read(message_id: str, folder: str = "INBOX") -> Dict[str, Any]:
    host = _cred("imap_host")
    port = _cred("imap_port")
    user = _cred("imap_user")
    pw = _cred("imap_password")
    if not (host and port and user and pw):
        return {"ok": False, "error": "imap credentials not set in vault"}

    def _mark():
        conn = _connect_sync(host, int(port), user, pw)
        try:
            conn.select(folder, readonly=False)
            typ, _ = conn.store(message_id.encode() if isinstance(message_id, str) else message_id, "+FLAGS", "\\Seen")
            return {"ok": typ == "OK", "message_id": message_id}
        finally:
            try:
                conn.logout()
            except Exception:
                pass

    return await asyncio.to_thread(_mark)


@tool(
    name="email.delete",
    description="Move an email to trash by message ID (sets \\Deleted flag and expunges).",
    parameters={
        "type": "object",
        "properties": {
            "message_id": {"type": "string"},
            "folder": {"type": "string", "default": "INBOX"},
        },
        "required": ["message_id"],
    },
    risk_tier=RiskTier.TIER_3_DESTRUCTIVE,
    category="email",
)
async def email_delete(message_id: str, folder: str = "INBOX") -> Dict[str, Any]:
    host = _cred("imap_host")
    port = _cred("imap_port")
    user = _cred("imap_user")
    pw = _cred("imap_password")
    if not (host and port and user and pw):
        return {"ok": False, "error": "imap credentials not set in vault"}

    def _delete():
        conn = _connect_sync(host, int(port), user, pw)
        try:
            conn.select(folder, readonly=False)
            conn.store(message_id.encode() if isinstance(message_id, str) else message_id, "+FLAGS", "\\Deleted")
            conn.expunge()
            return {"ok": True, "message_id": message_id, "deleted": True}
        finally:
            try:
                conn.logout()
            except Exception:
                pass

    return await asyncio.to_thread(_delete)


PLUGIN_NAME = "email_imap"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Read emails via IMAP. Pairs with the existing email.send (SMTP) tool."
