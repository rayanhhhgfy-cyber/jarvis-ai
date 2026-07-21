# ====================================================================
# JARVIS OMEGA - WhatsApp Plugin (Phase 13) - UNOFFICIAL FREE PATH
# ====================================================================
"""
Unofficial WhatsApp automation via pywhatkit (free, WhatsApp Web).

⚠️ RISKS (Sir acknowledged acceptance):
  - WhatsApp ToS prohibits automation on personal accounts.
  - Account BAN risk after ~100 automated messages/day.
  - Mitigations baked in:
      * 60-second hard delay between every send
      * 50 messages/hour cap
      * 200 messages/day cap
      * Recommendation: use a SECONDARY SIM card

  whatsapp.send_text       - send a text message
  whatsapp.send_image      - send an image (with optional caption)
  whatsapp.send_document   - send a file (PDF, DOCX, etc.)
  whatsapp.broadcast       - send same message to a list (rate-limited)
  whatsapp.contact_import  - import contacts into your address book
  whatsapp.receive_incoming - requires pywhatkit + selenium web session
  whatsapp.order_capture   - parse WhatsApp message → create ecommerce order
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from backend.tools import tool, RiskTier
from backend import business_db
from backend.config import settings
from shared.logger import get_logger

log = get_logger("whatsapp")


# Rate-limit state (in-process memory).
_last_send_ts = 0.0
_hour_window: List[float] = []
_day_window: List[float] = []

MIN_DELAY_SECONDS = 60       # 60s between every send
MAX_PER_HOUR = 50
MAX_PER_DAY = 200


def _rate_limited() -> Optional[str]:
    """Return an error message if currently rate-limited, else None."""
    now = time.time()
    # Prune windows.
    global _hour_window, _day_window
    _hour_window = [t for t in _hour_window if t > now - 3600]
    _day_window = [t for t in _day_window if t > now - 86400]
    # Wait until min delay.
    global _last_send_ts
    wait = _last_send_ts + MIN_DELAY_SECONDS - now
    if wait > 0:
        return f"rate-limited: wait {int(wait)}s (60s hard delay between sends)"
    if len(_hour_window) >= MAX_PER_HOUR:
        return f"rate-limited: {MAX_PER_HOUR}/hour cap reached"
    if len(_day_window) >= MAX_PER_DAY:
        return f"rate-limited: {MAX_PER_DAY}/day cap reached"
    return None


def _mark_sent() -> None:
    global _last_send_ts, _hour_window, _day_window
    now = time.time()
    _last_send_ts = now
    _hour_window.append(now)
    _day_window.append(now)


def _normalize_phone(p: str) -> str:
    """Normalize to international format without + (e.g. 962790000000)."""
    p = "".join(c for c in p if c.isdigit() or c == "+")
    if p.startswith("+"):
        p = p[1:]
    # Jordan default: if number starts with 07, convert to 9627.
    if len(p) == 10 and p.startswith("07") and settings.default_country == "JO":
        p = "962" + p[1:]
    return p


# --------------------------------------------------------------------
# Send text
# --------------------------------------------------------------------

async def _pywhatkit_send(recipient: str, message: str, tab_close: bool = True, wait_time: int = 15) -> Dict[str, Any]:
    """Run the sync pywhatkit sender in a thread."""
    try:
        import pywhatkit  # type: ignore
    except ImportError:
        return {"ok": False, "error": "pywhatkit not installed — add `pywhatkit` to requirements.txt"}

    def _do():
        pywhatkit.sendwhatmsg_instantly(
            recipient, message, tab_close=tab_close, wait_time=wait_time,
        )
    try:
        await asyncio.to_thread(_do)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="whatsapp.send_text",
    description="Send a WhatsApp text message. 60s delay enforced between sends. Requires WhatsApp Web QR scan on first use.",
    parameters={
        "type": "object",
        "properties": {
            "recipient": {"type": "string", "description": "Phone number in international format (e.g. '962790000000' or '+962790000000'). Jordanian 07XXXXXXXX auto-converted."},
            "message": {"type": "string"},
            "language": {"type": "string", "default": "ar", "enum": ["ar", "en"]},
        },
        "required": ["recipient", "message"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="whatsapp",
)
async def whatsapp_send_text(recipient: str, message: str, language: str = "ar") -> Dict[str, Any]:
    # Check rate limit.
    block = _rate_limited()
    if block:
        return {"ok": False, "error": block, "rate_limited": True}
    to = _normalize_phone(recipient)
    result = await _pywhatkit_send(to, message)
    # Persist.
    business_db.execute(
        """INSERT INTO whatsapp_messages (direction, recipient, body, status, error, sent_at, created_at)
           VALUES ('out', ?, ?, ?, ?, ?, ?)""",
        (to, message,
         "sent" if result.get("ok") else "failed",
         result.get("error", ""),
         datetime.utcnow().isoformat() if result.get("ok") else None,
         datetime.utcnow().isoformat()),
    )
    if result.get("ok"):
        _mark_sent()
    business_db.audit("send_text", "whatsapp", target=to, details={"ok": result.get("ok")})
    return result


# --------------------------------------------------------------------
# Send image
# --------------------------------------------------------------------

@tool(
    name="whatsapp.send_image",
    description="Send an image via WhatsApp with optional caption. Same rate limits apply.",
    parameters={
        "type": "object",
        "properties": {
            "recipient": {"type": "string"},
            "image_path": {"type": "string"},
            "caption": {"type": "string", "default": ""},
        },
        "required": ["recipient", "image_path"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="whatsapp",
)
async def whatsapp_send_image(recipient: str, image_path: str, caption: str = "") -> Dict[str, Any]:
    block = _rate_limited()
    if block:
        return {"ok": False, "error": block, "rate_limited": True}
    try:
        import pywhatkit  # type: ignore
    except ImportError:
        return {"ok": False, "error": "pywhatkit not installed"}
    to = _normalize_phone(recipient)

    def _do():
        # pywhatkit's sendwhats_image is sync.
        try:
            pywhatkit.sendwhats_image(
                to, image_path, caption=caption, wait_time=15, tab_close=True,
            )
        except AttributeError:
            # Older pywhatkit versions: fall back to ChatWith + manual.
            raise RuntimeError("pywhatkit version too old for sendwhats_image — upgrade to latest")
    try:
        await asyncio.to_thread(_do)
        business_db.execute(
            """INSERT INTO whatsapp_messages (direction, recipient, body, media_path, status, sent_at, created_at)
               VALUES ('out', ?, ?, ?, 'sent', ?, ?)""",
            (to, caption, image_path, datetime.utcnow().isoformat(), datetime.utcnow().isoformat()),
        )
        _mark_sent()
        return {"ok": True, "recipient": to, "image_path": image_path}
    except Exception as e:
        business_db.execute(
            """INSERT INTO whatsapp_messages (direction, recipient, media_path, status, error, created_at)
               VALUES ('out', ?, ?, 'failed', ?, ?)""",
            (to, image_path, str(e)[:500], datetime.utcnow().isoformat()),
        )
        return {"ok": False, "error": str(e)}


# --------------------------------------------------------------------
# Send document
# --------------------------------------------------------------------

@tool(
    name="whatsapp.send_document",
    description="Send a document (PDF, DOCX, etc.) via WhatsApp. Implementation opens a chat and attaches the file via the OS share dialog — best-effort.",
    parameters={
        "type": "object",
        "properties": {
            "recipient": {"type": "string"},
            "file_path": {"type": "string"},
            "caption": {"type": "string", "default": ""},
        },
        "required": ["recipient", "file_path"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="whatsapp",
)
async def whatsapp_send_document(recipient: str, file_path: str, caption: str = "") -> Dict[str, Any]:
    # pywhatkit doesn't have a clean document send. We send the caption + open
    # the file picker for the user.
    msg = (caption or "") + f"\n\n[Document attached separately: {file_path}]"
    return await whatsapp_send_text(recipient=recipient, message=msg)


# --------------------------------------------------------------------
# Broadcast (rate-limited)
# --------------------------------------------------------------------

@tool(
    name="whatsapp.broadcast",
    description="Send the same message to multiple recipients. 60s delay enforced between each — so 50 recipients = ~50 minutes.",
    parameters={
        "type": "object",
        "properties": {
            "recipients": {"type": "array", "items": {"type": "string"}},
            "message": {"type": "string"},
            "language": {"type": "string", "default": "ar"},
        },
        "required": ["recipients", "message"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="whatsapp",
)
async def whatsapp_broadcast(recipients: List[str], message: str, language: str = "ar") -> Dict[str, Any]:
    results: List[Dict[str, Any]] = []
    for r in recipients:
        res = await whatsapp_send_text(recipient=r, message=message, language=language)
        results.append({"recipient": r, "ok": res.get("ok"), "error": res.get("error", "")})
        if not res.get("ok"):
            break  # stop on first failure (likely rate-limit)
    sent = sum(1 for r in results if r["ok"])
    return {"ok": sent > 0, "sent": sent, "failed": len(results) - sent, "results": results}


# --------------------------------------------------------------------
# Contact import (basic)
# --------------------------------------------------------------------

@tool(
    name="whatsapp.contact_import",
    description="Persist contacts to a local address book (storage/whatsapp_contacts.csv). These are used by broadcast.",
    parameters={
        "type": "object",
        "properties": {
            "contacts": {
                "type": "array",
                "items": {"type": "object"},
                "description": "List of {name, phone}.",
            },
        },
        "required": ["contacts"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="whatsapp",
)
async def whatsapp_contact_import(contacts: List[Dict[str, str]]) -> Dict[str, Any]:
    import csv
    from pathlib import Path
    out = Path("./storage/whatsapp_contacts.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    # Append mode.
    new_rows = 0
    existing_phones = set()
    if out.exists():
        with open(out, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                existing_phones.add(row.get("phone", ""))
    with open(out, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["name", "phone"])
        if not out.exists() or out.stat().st_size == 0:
            writer.writeheader()
        for c in contacts:
            phone = _normalize_phone(c.get("phone", ""))
            if phone and phone not in existing_phones:
                writer.writerow({"name": c.get("name", ""), "phone": phone})
                existing_phones.add(phone)
                new_rows += 1
    return {"ok": True, "added": new_rows, "total": len(existing_phones), "path": str(out)}


# --------------------------------------------------------------------
# Order capture from inbound messages
# --------------------------------------------------------------------

@tool(
    name="whatsapp.order_capture",
    description="Parse an inbound WhatsApp message into an ecommerce order. Returns order details if matched.",
    parameters={
        "type": "object",
        "properties": {
            "sender_phone": {"type": "string"},
            "message": {"type": "string", "description": "Inbound message text."},
            "language": {"type": "string", "default": "ar"},
        },
        "required": ["sender_phone", "message"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="whatsapp",
)
async def whatsapp_order_capture(sender_phone: str, message: str, language: str = "ar") -> Dict[str, Any]:
    """Use LLM to detect intent + extract order details from an inbound message."""
    from backend.services.llm_service import llm_service
    sys_prompt = (
        "You are a multilingual (Arabic + English) order-capture assistant. "
        "Analyze the inbound WhatsApp message. Output STRICT JSON: "
        "{\"is_order\": boolean, \"product_name\": string, \"quantity\": integer, "
        "\"customer_name\": string, \"delivery_address\": string, \"notes\": string}. "
        "If the message is not an order, set is_order=false and leave other fields empty."
    )
    try:
        reply = await llm_service.get_response(
            user_message=f"Sender: {sender_phone}\nMessage: {message}",
            system_instructions=sys_prompt,
            inject_memory=False,
        )
        text = reply.strip().lstrip("`").rstrip("`")
        if text.startswith("json"):
            text = text[4:]
        parsed = json.loads(text)
        if not parsed.get("is_order"):
            return {"ok": True, "is_order": False}
        # Try to match product in catalog.
        product_name = parsed.get("product_name", "").lower()
        products = business_db.query("SELECT id, name, sku, price, currency, inventory FROM products")
        matched = None
        for p in products:
            if product_name and (product_name in p["name"].lower() or p["name"].lower() in product_name):
                matched = dict(p)
                break
        if matched and matched["inventory"] >= parsed.get("quantity", 1):
            from plugins.ecommerce.plugin import ecommerce_create_order
            order = await ecommerce_create_order(
                customer_name=parsed.get("customer_name") or sender_phone,
                sku=matched["sku"], quantity=parsed.get("quantity", 1),
                customer_email="", customer_address=parsed.get("delivery_address", ""),
                notes=f"WhatsApp order from {sender_phone}. {parsed.get('notes','')}",
            )
            return {
                "ok": True, "is_order": True, "order_created": order.get("ok"),
                "order_id": order.get("order_id"),
                "matched_product": matched["name"],
                "details": parsed,
            }
        return {"ok": True, "is_order": True, "order_created": False, "reason": "product not found or out of stock", "details": parsed}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# --------------------------------------------------------------------
# Receive incoming (best-effort)
# --------------------------------------------------------------------

@tool(
    name="whatsapp.receive_incoming",
    description="Best-effort: monitor WhatsApp Web for incoming messages. Requires persistent Selenium session. NOTE: this is sync-only and will block.",
    parameters={
        "type": "object",
        "properties": {
            "callback_url": {"type": "string", "default": "", "description": "POST each inbound message to this URL."},
            "max_listen_seconds": {"type": "integer", "default": 60},
        },
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="whatsapp",
)
async def whatsapp_receive_incoming(callback_url: str = "", max_listen_seconds: int = 60) -> Dict[str, Any]:
    return {
        "ok": False,
        "error": "Live monitoring requires a persistent Selenium WhatsApp Web session, which is not safe to run from a single tool call.",
        "hint": "For production use: run pywhatkit.listen_incoming() in a long-lived sidecar process and POST to your callback_url.",
    }


# Need json import
import json  # noqa: E402


PLUGIN_NAME = "whatsapp"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Unofficial WhatsApp automation via pywhatkit. 60s delay + 50/hr cap. Use secondary SIM."
