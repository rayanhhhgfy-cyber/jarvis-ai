# ====================================================================
# JARVIS OMEGA - Multi-Agent Council (Phase 14)
# ====================================================================
"""
5-persona decision council. For any major strategic decision, spawn a
council of distinct perspectives to debate before Sir commits.

  council.assemble    - define 5 personas
  council.debate      - multi-round deliberation
  council.vote        - each persona votes
  council.synthesize  - final decision + dissent
  council.red_team    - adversarial persona tries to break the plan
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List

from backend.tools import tool, RiskTier
from backend import business_db


_PERSONAS = {
    "ceo": {
        "name": "Strategist (CEO)",
        "instruction": "You are the CEO. Focus on vision, market positioning, and long-term value. 1 paragraph max.",
    },
    "cfo": {
        "name": "CFO",
        "instruction": "You are the CFO. Focus on unit economics, cash flow, and financial risk. 1 paragraph max.",
    },
    "cmo": {
        "name": "CMO",
        "instruction": "You are the CMO. Focus on audience, channels, brand, and go-to-market. 1 paragraph max.",
    },
    "engineer": {
        "name": "Engineer",
        "instruction": "You are a senior engineer. Focus on technical feasibility, scalability, and complexity. 1 paragraph max.",
    },
    "skeptic": {
        "name": "Skeptic",
        "instruction": "You are the Skeptic. Find every hole in this plan. Be brutal but constructive. 1 paragraph max.",
    },
}


@tool(
    name="council.assemble",
    description="Return the list of council personas available for a debate.",
    parameters={"type": "object"},
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="council",
)
async def council_assemble() -> Dict[str, Any]:
    return {
        "ok": True,
        "personas": [{"id": pid, "name": p["name"]} for pid, p in _PERSONAS.items()],
    }


async def _llm_persona_call(persona_id: str, question: str, context: str = "") -> str:
    from backend.services.llm_service import llm_service
    persona = _PERSONAS[persona_id]
    msg = f"Question: {question}\n"
    if context:
        msg += f"\nOther perspectives so far:\n{context}\n"
    msg += "\nGive your perspective now."
    return await llm_service.get_response(
        user_message=msg,
        system_instructions=persona["instruction"],
        inject_memory=False,
    )


@tool(
    name="council.debate",
    description="Run a multi-round council debate on a question. Each persona gives its take. Returns full transcript.",
    parameters={
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "The decision to debate (e.g. 'should JARVIS enter the food delivery niche?')"},
            "rounds": {"type": "integer", "default": 1, "description": "1-3 rounds. More = deeper but slower."},
        },
        "required": ["question"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="council",
)
async def council_debate(question: str, rounds: int = 1) -> Dict[str, Any]:
    rounds = max(1, min(3, rounds))
    transcript: List[Dict[str, Any]] = []
    try:
        for round_n in range(rounds):
            context_for_next = ""
            for pid in _PERSONAS:
                response = await _llm_persona_call(pid, question, context_for_next)
                transcript.append({
                    "round": round_n + 1,
                    "persona": pid,
                    "name": _PERSONAS[pid]["name"],
                    "position": response,
                })
                context_for_next += f"\n[{_PERSONAS[pid]['name']}]: {response[:300]}"
        return {"ok": True, "question": question, "transcript": transcript}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="council.vote",
    description="Each persona votes on the proposal. Returns Yes/No/Abstain + brief reason.",
    parameters={
        "type": "object",
        "properties": {
            "proposal": {"type": "string"},
        },
        "required": ["proposal"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="council",
)
async def council_vote(proposal: str) -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    votes = {}
    for pid, persona in _PERSONAS.items():
        try:
            reply = await llm_service.get_response(
                user_message=f"Proposal: {proposal}\n\nVote YES, NO, or ABSTAIN. Output STRICT JSON: {{\"vote\": \"YES|NO|ABSTAIN\", \"reason\": string}}.",
                system_instructions=persona["instruction"],
                inject_memory=False,
            )
            text = reply.strip().lstrip("`").rstrip("`")
            if text.startswith("json"):
                text = text[4:]
            try:
                parsed = json.loads(text)
            except Exception:
                # Salvage.
                start = text.find("{")
                if start >= 0:
                    depth = 0
                    for i in range(start, len(text)):
                        if text[i] == "{":
                            depth += 1
                        elif text[i] == "}":
                            depth -= 1
                            if depth == 0:
                                try:
                                    parsed = json.loads(text[start:i + 1])
                                    break
                                except Exception:
                                    parsed = {"vote": "UNKNOWN", "reason": reply[:200]}
                                break
                    else:
                        parsed = {"vote": "UNKNOWN", "reason": reply[:200]}
                else:
                    parsed = {"vote": "UNKNOWN", "reason": reply[:200]}
            votes[pid] = {"name": persona["name"], "vote": parsed.get("vote"), "reason": parsed.get("reason")}
        except Exception as e:
            votes[pid] = {"name": persona["name"], "vote": "ERROR", "reason": str(e)[:200]}
    return {"ok": True, "proposal": proposal, "votes": votes}


@tool(
    name="council.synthesize",
    description="Combine a debate transcript + votes into a final decision document.",
    parameters={
        "type": "object",
        "properties": {
            "question": {"type": "string"},
            "transcript": {"type": "array", "items": {"type": "object"}},
            "votes": {"type": "object"},
        },
        "required": ["question"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="council",
)
async def council_synthesize(question: str, transcript: List[Dict[str, Any]] = None, votes: Dict[str, Any] = None) -> Dict[str, Any]:
    transcript = transcript or []
    votes = votes or {}
    from backend.services.llm_service import llm_service
    summary_input = json.dumps({"question": question, "transcript": transcript, "votes": votes}, indent=2)[:6000]
    try:
        decision = await llm_service.get_response(
            user_message=f"Council deliberation:\n{summary_input}",
            system_instructions=(
                "You are the council chair. Synthesize the deliberation into a final recommendation. "
                "Output Markdown with: ## Decision, ## Rationale, ## Dissent (any concerns raised), "
                "## Next Steps. Be decisive — pick a clear direction."
            ),
            inject_memory=False,
        )
        # Persist.
        cid = business_db.execute(
            "INSERT INTO council_decisions (question, transcripts_json, votes_json, final_decision, created_at) VALUES (?, ?, ?, ?, ?)",
            (question, json.dumps(transcript)[:10000], json.dumps(votes)[:10000], decision,
             datetime.utcnow().isoformat()),
        )
        return {"ok": True, "decision_id": cid, "decision": decision}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="council.red_team",
    description="Run an adversarial persona that tries to break the plan. Returns list of vulnerabilities found.",
    parameters={
        "type": "object",
        "properties": {
            "plan": {"type": "string"},
        },
        "required": ["plan"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="council",
)
async def council_red_team(plan: str) -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    try:
        reply = await llm_service.get_response(
            user_message=f"Plan to red-team:\n{plan}",
            system_instructions=(
                "You are an elite red-team attacker. Find 5 specific ways this plan could fail: "
                "market risks, technical risks, financial risks, regulatory risks, founder-psychology risks. "
                "Output STRICT JSON: {\"vulnerabilities\": [{\"severity\": \"high|medium|low\", \"issue\": string, \"mitigation\": string}]}"
            ),
            inject_memory=False,
        )
        text = reply.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        try:
            parsed = json.loads(text)
        except Exception:
            start = text.find("{")
            if start >= 0:
                depth = 0
                for i in range(start, len(text)):
                    if text[i] == "{":
                        depth += 1
                    elif text[i] == "}":
                        depth -= 1
                        if depth == 0:
                            parsed = json.loads(text[start:i + 1])
                            break
                else:
                    parsed = {"vulnerabilities": []}
            else:
                parsed = {"vulnerabilities": []}
        return {"ok": True, "vulnerabilities": parsed.get("vulnerabilities", [])}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="council.run_full",
    description="One-shot: debate + vote + synthesize + red-team. Returns the complete decision package.",
    parameters={
        "type": "object",
        "properties": {
            "question": {"type": "string"},
            "rounds": {"type": "integer", "default": 1},
        },
        "required": ["question"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="council",
)
async def council_run_full(question: str, rounds: int = 1) -> Dict[str, Any]:
    debate = await council_debate(question=question, rounds=rounds)
    if not debate.get("ok"):
        return debate
    votes = await council_vote(proposal=question)
    synthesis = await council_synthesize(
        question=question,
        transcript=debate.get("transcript", []),
        votes=votes.get("votes", {}),
    )
    red_team = await council_red_team(plan=synthesis.get("decision", question))
    return {
        "ok": True,
        "question": question,
        "transcript": debate.get("transcript"),
        "votes": votes.get("votes"),
        "decision": synthesis.get("decision"),
        "vulnerabilities": red_team.get("vulnerabilities"),
    }


PLUGIN_NAME = "council"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Multi-agent council: 5 personas debate, vote, synthesize, red-team major decisions."
