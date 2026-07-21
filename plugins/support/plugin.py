# ====================================================================
# JARVIS OMEGA - Customer Support Plugin (Phase 11)
# ====================================================================
"""
Ticketing, FAQ generation, response suggestions, sentiment scoring.

Tools:
  support.create_ticket / list_tickets / respond_to_ticket / resolve_ticket
  support.suggest_response    - LLM proposes a reply
  support.sentiment_analyze   - rule-based (no external API)
  support.generate_faq        - generate FAQ.md from resolved tickets
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from backend.tools import tool, RiskTier
from backend import business_db


_POSITIVE_WORDS = {
    "great", "love", "excellent", "amazing", "fantastic", "wonderful", "perfect",
    "awesome", "happy", "thanks", "thank", "appreciate", "fast", "easy", "good",
    "best", "recommend", "brilliant", "superb", "delighted",
}
_NEGATIVE_WORDS = {
    "bad", "terrible", "awful", "hate", "broken", "broken", "fail", "fail",
    "angry", "frustrated", "slow", "useless", "worst", "horrible", "disappointed",
    "refund", "scam", "complain", "issue", "bug", "crash", "stuck", "wrong",
    "lost", "damage", "delay", "rude", "ignore",
}


@tool(
    name="support.create_ticket",
    description="Open a new support ticket.",
    parameters={
        "type": "object",
        "properties": {
            "client_id": {"type": "integer", "default": 0},
            "subject": {"type": "string"},
            "body": {"type": "string", "default": ""},
            "channel": {"type": "string", "default": "web"},
            "requester_name": {"type": "string", "default": ""},
            "requester_email": {"type": "string", "default": ""},
            "priority": {"type": "string", "enum": ["low", "normal", "high", "urgent"], "default": "normal"},
        },
        "required": ["subject"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="support",
)
async def support_create_ticket(
    subject: str, body: str = "", channel: str = "web",
    requester_name: str = "", requester_email: str = "",
    priority: str = "normal", client_id: int = 0,
) -> Dict[str, Any]:
    tid = business_db.execute(
        """INSERT INTO tickets (client_id, channel, subject, body, requester_name, requester_email,
                                priority, status, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)""",
        (client_id or None, channel, subject, body, requester_name, requester_email,
         priority, datetime.utcnow().isoformat(), datetime.utcnow().isoformat()),
    )
    return {"ok": True, "ticket_id": tid, "subject": subject}


@tool(
    name="support.list_tickets",
    description="List tickets. Filter by status.",
    parameters={
        "type": "object",
        "properties": {
            "status": {"type": "string", "default": ""},
            "limit": {"type": "integer", "default": 50},
        },
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="support",
)
async def support_list_tickets(status: str = "", limit: int = 50) -> Dict[str, Any]:
    sql = "SELECT * FROM tickets"
    params: tuple = ()
    if status:
        sql += " WHERE status = ?"
        params = (status,)
    sql += " ORDER BY id DESC LIMIT ?"
    params = params + (limit,)
    rows = business_db.rows_to_dicts(business_db.query(sql, params))
    return {"ok": True, "count": len(rows), "tickets": rows}


@tool(
    name="support.respond_to_ticket",
    description="Post a response to a ticket. Does NOT email the customer — call marketing.post or email.send separately for that.",
    parameters={
        "type": "object",
        "properties": {
            "ticket_id": {"type": "integer"},
            "response": {"type": "string"},
            "new_status": {"type": "string", "default": "pending", "enum": ["open", "pending", "resolved", "closed"]},
        },
        "required": ["ticket_id", "response"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="support",
)
async def support_respond_to_ticket(
    ticket_id: int, response: str, new_status: str = "pending",
) -> Dict[str, Any]:
    business_db.execute(
        """UPDATE tickets SET response = ?, status = ?, updated_at = ?,
                               resolved_at = CASE WHEN ? IN ('resolved','closed') THEN ? ELSE resolved_at END
           WHERE id = ?""",
        (response, new_status, datetime.utcnow().isoformat(),
         new_status, datetime.utcnow().isoformat(), ticket_id),
    )
    return {"ok": True, "ticket_id": ticket_id, "status": new_status}


@tool(
    name="support.suggest_response",
    description="Suggest a response to a ticket using the LLM.",
    parameters={
        "type": "object",
        "properties": {
            "subject": {"type": "string"},
            "body": {"type": "string"},
            "tone": {"type": "string", "default": "professional-empathetic"},
        },
        "required": ["subject", "body"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="support",
)
async def support_suggest_response(subject: str, body: str, tone: str = "professional-empathetic") -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    try:
        reply = await llm_service.get_response(
            user_message=f"Ticket subject: {subject}\nTicket body: {body}",
            system_instructions=(
                f"You are a customer-support specialist. Tone: {tone}. "
                "Write a concise reply that resolves or moves the ticket forward. "
                "Acknowledge the issue, propose a clear next step, sign as 'JARVIS Support'. "
                "Output the email body only — no JSON, no markdown."
            ),
            inject_memory=False,
        )
        return {"ok": True, "suggested_response": reply}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="support.sentiment_analyze",
    description="Rule-based sentiment scoring of a support message. Returns 'positive' | 'neutral' | 'negative' + a score.",
    parameters={
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="support",
)
async def support_sentiment_analyze(text: str) -> Dict[str, Any]:
    tokens = [t.strip(".,!?;:\"'()[]").lower() for t in text.split()]
    if not tokens:
        return {"ok": True, "sentiment": "neutral", "score": 0.0}
    pos = sum(1 for t in tokens if t in _POSITIVE_WORDS)
    neg = sum(1 for t in tokens if t in _NEGATIVE_WORDS)
    score = (pos - neg) / len(tokens)
    label = "positive" if score > 0.05 else ("negative" if score < -0.05 else "neutral")
    return {
        "ok": True,
        "sentiment": label,
        "score": round(score, 3),
        "positive_words": pos,
        "negative_words": neg,
    }


@tool(
    name="support.generate_faq",
    description="Generate a FAQ.md document from resolved tickets.",
    parameters={
        "type": "object",
        "properties": {
            "output_path": {"type": "string", "default": "./storage/sales/FAQ.md"},
            "limit": {"type": "integer", "default": 100},
        },
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="support",
)
async def support_generate_faq(output_path: str = "./storage/sales/FAQ.md", limit: int = 100) -> Dict[str, Any]:
    rows = business_db.query(
        "SELECT subject, body, response FROM tickets WHERE status IN ('resolved','closed') AND response IS NOT NULL LIMIT ?",
        (limit,),
    )
    if not rows:
        return {"ok": False, "error": "no resolved tickets to mine"}
    from backend.services.llm_service import llm_service
    pairs = "\n\n".join(
        f"Q: {r['subject']}\nA: {r['response']}" for r in rows
    )
    try:
        reply = await llm_service.get_response(
            user_message=f"Resolved tickets:\n{pairs}",
            system_instructions=(
                "Convert these resolved tickets into a concise FAQ in Markdown. "
                "Group by theme. Each Q/A 2-3 sentences. Output only Markdown."
            ),
            inject_memory=False,
        )
    except Exception as e:
        return {"ok": False, "error": str(e)}
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(reply, encoding="utf-8")
    return {"ok": True, "path": output_path, "chars": len(reply)}


PLUGIN_NAME = "support"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Support tickets, LLM response suggestions, sentiment, FAQ generation."
