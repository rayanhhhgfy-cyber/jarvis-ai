# Phase 18: Email Parser (REAL)
from __future__ import annotations
import email
from email.header import decode_header
from typing import Any, Dict
from backend.tools import tool, RiskTier

@tool(name="email_parse.extract", description="Parse a raw email: extract sender, subject, body, and detect if it's an order/invoice/lead.", parameters={"type":"object","properties":{"raw_email":{"type":"string","description":"Raw email content (RFC 822 format)."}},"required":["raw_email"]}, risk_tier=RiskTier.TIER_0_OBSERVE, category="email_parser")
async def extract(raw_email: str) -> Dict[str, Any]:
    try:
        msg = email.message_from_string(raw_email)
        subject = msg.get("Subject", "")
        sender = msg.get("From", "")
        # Extract body
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    payload = part.get_payload(decode=True)
                    if payload: body = payload.decode(part.get_content_charset() or "utf-8", errors="replace")[:2000]
                    break
        else:
            payload = msg.get_payload(decode=True)
            if payload: body = payload.decode(msg.get_content_charset() or "utf-8", errors="replace")[:2000]
        # Detect type
        email_type = "general"
        lower = (subject + " " + body).lower()
        if any(w in lower for w in ["invoice", "factura", "فاتورة"]): email_type = "invoice"
        elif any(w in lower for w in ["order", "pedido", "طلب"]): email_type = "order"
        elif any(w in lower for w in ["inquiry", "interested", "استفسار"]): email_type = "lead"
        elif any(w in lower for w in ["support", "help", "مشكلة"]): email_type = "support"
        return {"ok": True, "from": sender, "subject": subject, "body_preview": body[:500], "detected_type": email_type}
    except Exception as e:
        return {"ok": False, "error": str(e)}
