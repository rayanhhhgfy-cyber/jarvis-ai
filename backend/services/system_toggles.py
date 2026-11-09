# ====================================================================
# JARVIS OMEGA — System Toggles (chat-controlled runtime switches)
# ====================================================================
"""
Runtime on/off switches for the major Jarvis subsystems, controllable
from the dashboard chat (and ``/api/toggles``) with Sir's approval.

Design rules:

* **Runtime only, no restart.** Every toggle takes effect immediately
  by calling the subsystem's own start()/stop() (or equivalent) — no
  env-var or ``config.py`` change. The state lives in this module and
  is **in-memory**: a backend restart restores the boot defaults
  (``DM_RESPONDER_ENABLED`` env for the DM responder, autopilot jobs
  unregistered, proactive watcher started by ``main``'s lifespan,
  focus mode off, guardrail from env, notifications unmuted). The one
  exception is upstream autopilot behaviour: ``autopilot.pause()``
  writes ``./storage/autopilot_paused.flag``, which survives restarts.
* **Approval is mandatory.** :func:`request_toggle` creates an
  :class:`~backend.approval_gateway.ApprovalGateway` request (the same
  gateway ``router_chat._dispatch_and_wait`` uses for destructive
  commands) and applies the change **only** when
  ``wait_for_approval`` returns True. Denial or timeout changes
  nothing. A request that would change nothing (already in the
  requested state) returns ``already=True`` without raising an
  approval card.
* **No subsystem code is modified to add a toggle** except the
  notification engine's delivery path, which consults
  :func:`is_notifications_muted` before sending Web Push (history is
  still recorded while muted). The DM responder, autopilot plugin,
  proactive watcher and focus-mode service are driven through their
  existing public APIs, imported lazily so this module never creates
  an import cycle and never pays their import cost until used.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from backend.approval_gateway import ApprovalGateway, approval_gateway
from backend.config import settings
from shared.constants import RiskLevel
from shared.logger import get_logger
from shared.models import ApprovalRequest

log = get_logger("system_toggles")

# ----------------------------------------------------------------------
# Toggle registry
# ----------------------------------------------------------------------
# ``kind`` is informational: "loop" = background poller, "jobs" = scheduler
# jobs, "flag" = an in-memory mute/guard switch, "mode" = a session mode.

TOGGLES: dict[str, dict[str, str]] = {
    "dm_responder": {
        "label": "DM responder",
        "description": "Auto-replies to Messenger + Instagram DMs (one-minute rule).",
        "kind": "loop",
    },
    "autopilot": {
        "label": "Autopilot (all jobs)",
        "description": "Master switch for all seven autonomous autopilot jobs.",
        "kind": "jobs",
    },
    "autopilot_business_builder": {
        "label": "Autopilot: business builder",
        "description": "Builds a new business every 24h (agency orchestrator).",
        "kind": "job",
    },
    "autopilot_sales_loop": {
        "label": "Autopilot: sales loop",
        "description": "Autonomous sales follow-ups + prospecting every 30 min.",
        "kind": "job",
    },
    "autopilot_content_factory": {
        "label": "Autopilot: content factory",
        "description": "Generates marketing content every 6h.",
        "kind": "job",
    },
    "autopilot_digital_product": {
        "label": "Autopilot: digital product",
        "description": "Weekly e-book / digital-product pipeline.",
        "kind": "job",
    },
    "autopilot_daily_briefing": {
        "label": "Autopilot: daily briefing",
        "description": "Morning briefing job every 12h (autopilot's own briefing).",
        "kind": "job",
    },
    "autopilot_uptime_check": {
        "label": "Autopilot: uptime check",
        "description": "Checks monitored sites every 5 min.",
        "kind": "job",
    },
    "autopilot_brand_mention": {
        "label": "Autopilot: brand mention",
        "description": "Scans for brand mentions every 6h.",
        "kind": "job",
    },
    "push_notifications": {
        "label": "Push notifications",
        "description": "Web Push delivery to Sir's devices (muted = held, still logged).",
        "kind": "flag",
    },
    "proactive_watcher": {
        "label": "Proactive watcher",
        "description": "Market / news monitoring + morning-briefing alerts.",
        "kind": "loop",
    },
    "focus_mode": {
        "label": "Focus mode",
        "description": "Do-not-disturb: queues incoming messages, auto-replies, summarises on exit.",
        "kind": "mode",
    },
    "guardrail": {
        "label": "Prompt-injection guardrail",
        "description": "Refuses chat messages matching known jailbreak patterns.",
        "kind": "flag",
    },
}

AUTOPILOT_JOB_IDS: dict[str, str] = {
    "autopilot_business_builder": "autopilot_business_builder",
    "autopilot_sales_loop": "autopilot_sales_loop",
    "autopilot_content_factory": "autopilot_content_factory",
    "autopilot_digital_product": "autopilot_digital_product",
    "autopilot_daily_briefing": "autopilot_daily_briefing",
    "autopilot_uptime_check": "autopilot_uptime_check",
    "autopilot_brand_mention": "autopilot_brand_mention",
}

# ----------------------------------------------------------------------
# Runtime state (in-memory; see module docstring)
# ----------------------------------------------------------------------

_desired: dict[str, bool] = {
    "dm_responder": bool(settings.dm_responder_enabled),
    "autopilot": False,
    "push_notifications": True,
    "proactive_watcher": True,
    "focus_mode": False,
    "guardrail": bool(settings.guardrail_enabled),
}
_desired.update({job_id: False for job_id in AUTOPILOT_JOB_IDS})
# Autopilot jobs individually disabled while the master is on. A job that
# is disabled here is cancelled after every autopilot activate().
_disabled_jobs: set[str] = set()
# Push mute flag (the one piece of state the notification engine reads).
_notifications_muted: bool = False


def reset_state() -> None:
    """Restore boot defaults. Used by tests; not part of the chat API."""
    global _notifications_muted
    _desired["dm_responder"] = bool(settings.dm_responder_enabled)
    _desired["autopilot"] = False
    _desired["push_notifications"] = True
    _desired["proactive_watcher"] = True
    _desired["focus_mode"] = False
    _desired["guardrail"] = bool(settings.guardrail_enabled)
    for job_id in AUTOPILOT_JOB_IDS:
        _desired[job_id] = False
    _disabled_jobs.clear()
    _notifications_muted = False


def is_notifications_muted() -> bool:
    """Read by ``backend.notification_engine`` before Web Push delivery."""
    return _notifications_muted


# ----------------------------------------------------------------------
# Live probes (defensive: never let a state report crash on a subsystem)
# ----------------------------------------------------------------------

def _dm_detail() -> str:
    try:
        from backend.services.dm_responder import dm_responder

        status = dm_responder.get_status()
        running = bool(status.get("running"))
        connected = [
            p for p, info in (status.get("platforms") or {}).items()
            if info.get("connected")
        ]
        if running:
            return f"polling ({', '.join(connected) or 'no platform'} connected)"
        if not connected:
            return "enabled but no DM account connected, loop not running"
        return "enabled but loop not running"
    except Exception as exc:  # noqa: BLE001 - probe must never break state report
        log.debug("dm_detail_probe_failed", error=str(exc))
        return ""


def _autopilot_detail() -> str:
    try:
        from backend.scheduler import scheduler

        jobs = scheduler.get_jobs()
        active = [j["job_id"] for j in jobs if j.get("job_id", "").startswith("autopilot_")]
        if not active:
            return "no autopilot jobs registered"
        return f"{len(active)} job(s) registered: {', '.join(sorted(active))}"
    except Exception as exc:  # noqa: BLE001 - probe must never break state report
        log.debug("autopilot_detail_probe_failed", error=str(exc))
        return ""


def get_state(toggle_id: str | None = None) -> dict[str, Any]:
    """Current on/off state for every toggle (or one toggle).

    ``enabled`` is the desired runtime state this module owns. Individual
    autopilot jobs report ``enabled`` only when the master is on *and*
    the job itself is not disabled — a job cannot run while the master
    is off, even if it was individually enabled first (it starts when
    the master is turned back on).
    """
    details: dict[str, str] = {
        "dm_responder": _dm_detail(),
        "autopilot": _autopilot_detail(),
    }
    state: dict[str, Any] = {}
    for tid, meta in TOGGLES.items():
        if tid in AUTOPILOT_JOB_IDS:
            enabled = bool(_desired["autopilot"] and tid not in _disabled_jobs)
        else:
            enabled = bool(_desired[tid])
        state[tid] = {
            "id": tid,
            "label": meta["label"],
            "description": meta["description"],
            "kind": meta["kind"],
            "enabled": enabled,
            "detail": details.get(tid, ""),
        }
    if toggle_id is not None:
        if toggle_id not in TOGGLES:
            raise KeyError(toggle_id)
        return state[toggle_id]
    return state


def format_state_report(state: dict[str, Any] | None = None) -> str:
    """Human-readable state report for the chat (and the API)."""
    state = state if state is not None else get_state()
    lines = ["Here's what's on and off right now, Sir:"]
    for info in state.values():
        word = "ON" if info["enabled"] else "OFF"
        line = f"• {info['label']}: {word}"
        if info.get("detail"):
            line += f" — {info['detail']}"
        lines.append(line)
    return "\n".join(lines)


# ----------------------------------------------------------------------
# Subsystem drivers (lazy imports; small helpers so tests can patch them)
# ----------------------------------------------------------------------

async def _autopilot_activate() -> dict[str, Any]:
    from plugins.autopilot.plugin import activate

    return await activate(confirm=True)


async def _autopilot_pause() -> dict[str, Any]:
    from plugins.autopilot.plugin import pause

    return await pause()


def _cancel_scheduler_job(job_id: str) -> bool:
    from backend.scheduler import scheduler

    return scheduler.cancel_job(job_id)


async def _dm_start() -> None:
    from backend.services.dm_responder import dm_responder

    await dm_responder.start()


async def _dm_stop() -> None:
    from backend.services.dm_responder import dm_responder

    await dm_responder.stop()


async def _proactive_start() -> None:
    from backend.proactive_watcher import proactive_watcher

    if not getattr(proactive_watcher, "_running", False):
        await proactive_watcher.start()


async def _proactive_stop() -> None:
    from backend.proactive_watcher import proactive_watcher

    await proactive_watcher.stop()


def _focus_activate() -> None:
    from backend.services.focus_mode import focus_mode_service

    focus_mode_service.activate(
        note="Focus mode turned on from chat.",
        auto_reply=True,
        language="arabic",
    )


def _focus_deactivate() -> dict[str, Any]:
    from backend.services.focus_mode import focus_mode_service

    return focus_mode_service.deactivate()


async def apply_toggle(toggle_id: str, desired: bool) -> dict[str, Any]:
    """Apply a toggle **without** approval. Internal only.

    Chat and REST callers must go through :func:`request_toggle` /
    :func:`submit_toggle_request` — calling this directly bypasses the
    approval gate, which is exactly what the tests assert must not
    happen from the public paths.
    """
    if toggle_id not in TOGGLES:
        raise KeyError(toggle_id)
    desired = bool(desired)
    note = ""

    if toggle_id == "dm_responder":
        # dm_responder.start() is gated on settings.dm_responder_enabled,
        # so flip the runtime setting (in memory only — config.py untouched)
        # before starting, and clear it before stopping.
        settings.dm_responder_enabled = desired
        if desired:
            await _dm_start()
            note = _dm_detail()
        else:
            await _dm_stop()
        _desired[toggle_id] = desired
    elif toggle_id == "autopilot":
        if desired:
            await _autopilot_activate()
            for job_id in sorted(_disabled_jobs):
                _cancel_scheduler_job(AUTOPILOT_JOB_IDS[job_id])
            for job_id in AUTOPILOT_JOB_IDS:
                _desired[job_id] = job_id not in _disabled_jobs
            note = _autopilot_detail()
        else:
            await _autopilot_pause()
            for job_id in AUTOPILOT_JOB_IDS.values():
                _cancel_scheduler_job(job_id)
            for job_id in AUTOPILOT_JOB_IDS:
                _desired[job_id] = False
            note = "paused; autopilot jobs cancelled"
        _desired[toggle_id] = desired
    elif toggle_id in AUTOPILOT_JOB_IDS:
        job_id = AUTOPILOT_JOB_IDS[toggle_id]
        if desired:
            _disabled_jobs.discard(toggle_id)
            _desired[toggle_id] = bool(_desired["autopilot"])
            if _desired["autopilot"]:
                # Re-register all jobs, then cancel the still-disabled ones.
                await _autopilot_activate()
                for disabled in sorted(_disabled_jobs):
                    _cancel_scheduler_job(AUTOPILOT_JOB_IDS[disabled])
                note = "job re-registered under the running autopilot"
            else:
                note = "recorded — starts when autopilot is turned on"
        else:
            _disabled_jobs.add(toggle_id)
            _desired[toggle_id] = False
            _cancel_scheduler_job(job_id)
            note = "job cancelled"
    elif toggle_id == "push_notifications":
        global _notifications_muted
        _notifications_muted = not desired
        _desired[toggle_id] = desired
        note = "muted — pushes are logged but not delivered" if not desired else ""
    elif toggle_id == "proactive_watcher":
        if desired:
            await _proactive_start()
        else:
            await _proactive_stop()
        _desired[toggle_id] = desired
    elif toggle_id == "focus_mode":
        if desired:
            _focus_activate()
        else:
            _focus_deactivate()
        _desired[toggle_id] = desired
    elif toggle_id == "guardrail":
        settings.guardrail_enabled = desired
        _desired[toggle_id] = desired
    else:  # pragma: no cover - registry and branches are kept in sync
        raise KeyError(toggle_id)

    log.info("toggle_applied", toggle_id=toggle_id, enabled=desired, note=note)
    return {
        "ok": True,
        "toggle_id": toggle_id,
        "label": TOGGLES[toggle_id]["label"],
        "enabled": bool(_desired[toggle_id]) if toggle_id in AUTOPILOT_JOB_IDS else desired,
        "note": note,
    }


# ----------------------------------------------------------------------
# Approval-gated entry points (the only public ways to change a toggle)
# ----------------------------------------------------------------------

async def _create_approval_request(
    toggle_id: str, desired: bool, gateway: ApprovalGateway
) -> str:
    """Create the gateway request. Mirrors router_chat._dispatch_and_wait."""
    verb = "Turn ON" if desired else "Turn OFF"
    req = ApprovalRequest(
        action=f"toggle_{toggle_id}",
        reason=f"{verb} {TOGGLES[toggle_id]['label']} (requested in chat).",
        risk_level=RiskLevel.MEDIUM,
        affected_resources=[toggle_id],
        expected_result=(
            f"{TOGGLES[toggle_id]['label']} will be "
            f"{'enabled' if desired else 'disabled'} immediately, no restart."
        ),
        undo_possible=True,
        requesting_agent="system_toggles",
    )
    return await gateway.request_approval(req)


async def _await_and_apply(
    toggle_id: str,
    desired: bool,
    approval_id: str,
    gateway: ApprovalGateway,
    timeout: float,
) -> dict[str, Any]:
    approved = await gateway.wait_for_approval(approval_id, timeout=timeout)
    if not approved:
        log.warning("toggle_not_approved", toggle_id=toggle_id, approval_id=approval_id)
        return {
            "ok": False,
            "applied": False,
            "toggle_id": toggle_id,
            "desired": desired,
            "approval_id": approval_id,
            "reason": "Not approved by Sir (denied or timed out) — nothing changed.",
        }
    result = await apply_toggle(toggle_id, desired)
    return {**result, "applied": True, "approval_id": approval_id}


async def request_toggle(
    toggle_id: str,
    desired: bool,
    timeout: float = 300.0,
    gateway: ApprovalGateway | None = None,
) -> dict[str, Any]:
    """Request a toggle change, wait for Sir's approval, apply if approved.

    Same pattern as ``router_chat._dispatch_and_wait``: create the
    approval request, block on ``wait_for_approval`` (300s default),
    apply only on approval. Returns ``applied=False`` — and changes
    nothing — on denial or timeout.
    """
    if toggle_id not in TOGGLES:
        raise KeyError(toggle_id)
    gw = gateway or approval_gateway
    current = get_state(toggle_id)["enabled"]
    if bool(desired) == current:
        return {
            "ok": True,
            "applied": False,
            "already": True,
            "toggle_id": toggle_id,
            "label": TOGGLES[toggle_id]["label"],
            "enabled": current,
            "reason": f"{TOGGLES[toggle_id]['label']} is already {'ON' if current else 'OFF'} — nothing changed.",
        }
    approval_id = await _create_approval_request(toggle_id, bool(desired), gw)
    return await _await_and_apply(toggle_id, bool(desired), approval_id, gw, timeout)


async def submit_toggle_request(
    toggle_id: str,
    desired: bool,
    timeout: float = 300.0,
    gateway: ApprovalGateway | None = None,
) -> dict[str, Any]:
    """Non-blocking variant for the REST router.

    Creates the approval request and returns its id at once; a
    background task waits for the verdict and applies the toggle only
    if approved. Sir approves via the existing
    ``POST /api/approvals/{approval_id}/approve`` endpoint (or the
    dashboard approval card).
    """
    if toggle_id not in TOGGLES:
        raise KeyError(toggle_id)
    gw = gateway or approval_gateway
    current = get_state(toggle_id)["enabled"]
    if bool(desired) == current:
        return {
            "ok": True,
            "applied": False,
            "already": True,
            "toggle_id": toggle_id,
            "label": TOGGLES[toggle_id]["label"],
            "enabled": current,
            "approval_id": None,
            "status": "already_in_state",
            "reason": f"{TOGGLES[toggle_id]['label']} is already {'ON' if current else 'OFF'}.",
        }
    approval_id = await _create_approval_request(toggle_id, bool(desired), gw)
    asyncio.create_task(
        _await_and_apply(toggle_id, bool(desired), approval_id, gw, timeout)
    )
    return {
        "ok": True,
        "applied": False,
        "toggle_id": toggle_id,
        "label": TOGGLES[toggle_id]["label"],
        "desired": bool(desired),
        "approval_id": approval_id,
        "status": "awaiting_approval",
        "reason": "Approval requested — the toggle applies only after Sir approves.",
    }


# ----------------------------------------------------------------------
# Chat parsing — detect toggle requests / state questions in plain text
# ----------------------------------------------------------------------

_ON_VERBS = r"(turn on|switch on|enable|activate|start|resume|unmute)"
_OFF_VERBS = r"(turn off|switch off|disable|deactivate|stop|pause|mute)"
_STATE_PATTERNS = [
    re.compile(r"\bwhat(?:'s| is)\s+(on|off)\b", re.IGNORECASE),
    re.compile(r"\bwhat(?:'s| is)\s+the\s+status\b", re.IGNORECASE),
    re.compile(r"\bshow\s+(?:me\s+)?(?:the\s+)?(?:status|state)\b", re.IGNORECASE),
    re.compile(r"\blist\s+(?:the\s+)?toggles\b", re.IGNORECASE),
    re.compile(r"\bwhich\s+(?:things|systems|services)\s+are\s+(?:on|off|running)\b", re.IGNORECASE),
    re.compile(r"\b(?:is|are)\s+the\s+.+\s+(on|off|running)\b.*\?", re.IGNORECASE),
    # Arabic: "شو شغال؟" / "ما الذي يعمل؟" / "ما هو المفعّل؟"
    re.compile(r"(شو|ما)\s+(شغال|اللي شغال|الذي يعمل|المفعّل|المفعل)", re.IGNORECASE),
    re.compile(r"اعرض\s+(الحالة|الوضع)", re.IGNORECASE),
]

# Checked in order: individual autopilot jobs before the autopilot master,
# DM responder before bare "instagram"/"messenger".
_TOGGLE_PHRASES: list[tuple[str, list[str]]] = [
    ("autopilot_business_builder", ["business builder"]),
    ("autopilot_sales_loop", ["sales loop"]),
    ("autopilot_content_factory", ["content factory"]),
    ("autopilot_digital_product", ["digital product"]),
    ("autopilot_daily_briefing", ["daily briefing", "morning briefing"]),
    ("autopilot_uptime_check", ["uptime check"]),
    ("autopilot_brand_mention", ["brand mention"]),
    ("dm_responder", ["dm responder", "dm auto-reply", "dm auto reply", "auto-reply", "auto reply", "auto-replies", "messenger", "instagram dm", "instagram"]),
    ("autopilot", ["autopilot"]),
    ("push_notifications", ["push notification", "push notifications", "notifications"]),
    ("proactive_watcher", ["proactive watcher", "proactive alerts", "market watcher"]),
    ("focus_mode", ["focus mode"]),
    ("guardrail", ["guardrail", "prompt injection guard"]),
]

_AR_ON = ["شغّل", "شغل", "فعّل", "فعل", "ابدأ"]
_AR_OFF = ["أوقف", "اوقف", "وقف", "عطّل", "عطل", "أطفئ"]


def parse_toggle_request(message: str) -> dict[str, Any] | None:
    """Parse a chat message into a toggle intent, or None.

    Returns ``{"kind": "state"}`` for "what is on?" style questions,
    ``{"kind": "toggle", "toggle_id": ..., "desired": bool}`` for
    "turn off the DM responder" style requests, and None when the
    message is not a toggle request at all. A toggle request needs an
    explicit on/off verb (or an Arabic on/off verb) next to a known
    subsystem name, so ordinary chat mentioning e.g. "notifications"
    is never hijacked.
    """
    text = (message or "").strip()
    if not text:
        return None
    lowered = text.lower()

    for pattern in _STATE_PATTERNS:
        if pattern.search(text):
            return {"kind": "state"}

    toggle_id: str | None = None
    for tid, phrases in _TOGGLE_PHRASES:
        if any(phrase in lowered for phrase in phrases):
            toggle_id = tid
            break
    if toggle_id is None:
        # Arabic subsystem names.
        if "الرد التلقائي" in text or "الرد على الرسائل" in text:
            toggle_id = "dm_responder"
        elif "الطيار الآلي" in text or "القيادة الذاتية" in text:
            toggle_id = "autopilot"
        elif "وضع التركيز" in text:
            toggle_id = "focus_mode"
        elif "الإشعارات" in text:
            toggle_id = "push_notifications"
    if toggle_id is None:
        return None

    if re.search(_ON_VERBS, lowered) or any(w in text for w in _AR_ON):
        return {"kind": "toggle", "toggle_id": toggle_id, "desired": True}
    if re.search(_OFF_VERBS, lowered) or any(w in text for w in _AR_OFF):
        return {"kind": "toggle", "toggle_id": toggle_id, "desired": False}
    return None
