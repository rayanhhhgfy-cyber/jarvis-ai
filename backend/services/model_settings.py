# ====================================================================
# JARVIS OMEGA — model switch (2026-11-11)
# ====================================================================
"""
Which brain Jarvis is using. Sir switches it with /model — the choice
lives in a Turso-backed store, so it survives redeploys.

Models (all free, no card):
* groq-120b — Groq gpt-oss-120b. The default. Smartest on Groq,
  1,000 requests/day, 8,000 TPM.
* groq-20b — Groq gpt-oss-20b. Smaller and faster, higher TPM
  allowance — the fallback when 120b rate-limits.
* gemini — Gemini 2.5 Flash (Google AI Studio). 1,500 requests/day.
  Needs GEMINI_API_KEY (a free key from aistudio.google.com).
* deepseek — DeepSeek R1 via OpenRouter (free tier). The strongest
  reasoning of the free models, but only 50 requests/day on a free
  OpenRouter account. Needs OPENROUTER_API_KEY (a free key from
  openrouter.ai) — the model id is deepseek/deepseek-r1:free.

The brains read the active model on every call, so a switch takes
effect immediately, no restart. A model whose key is missing is
skipped and the brain falls through to the next one.
"""

from __future__ import annotations

from backend.services import dm_store
from shared.logger import get_logger

log = get_logger("model_settings")

DEFAULT_MODEL = "groq-120b"

MODELS: dict[str, dict[str, str]] = {
    "groq-120b": {
        "provider": "groq",
        "label": "Groq 120b",
        "description": "gpt-oss-120b — the smartest on Groq, 1,000/day.",
    },
    "groq-20b": {
        "provider": "groq",
        "label": "Groq 20b",
        "description": "gpt-oss-20b — smaller, faster, higher token limit.",
    },
    "gemini": {
        "provider": "gemini",
        "label": "Gemini 2.5 Flash",
        "description": "Google AI Studio free tier, 1,500/day. Needs a free Gemini key.",
    },
    "deepseek": {
        "provider": "openrouter",
        "label": "DeepSeek R1 (OpenRouter free)",
        "description": "The strongest free reasoning model, but only 50/day. Needs a free OpenRouter key.",
    },
}


def get_active_model() -> str:
    """The model id Jarvis is using right now (default groq-120b)."""
    try:
        active = dm_store.model_settings.get("active", DEFAULT_MODEL)
    except (OSError, RuntimeError, ValueError) as e:
        log.debug("model_settings_read_failed", error=str(e))
        return DEFAULT_MODEL
    if active not in MODELS:
        return DEFAULT_MODEL
    return active


def set_active_model(model_id: str) -> str | None:
    """Switch Jarvis to a model. Returns the id, or None if unknown."""
    model_id = (model_id or "").strip().lower()
    if model_id not in MODELS:
        return None
    try:
        dm_store.model_settings.set("active", model_id)
    except (OSError, RuntimeError, ValueError) as e:
        log.warning("model_settings_save_failed", error=str(e))
        return None
    log.info("model_switched", model=model_id)
    return model_id


def list_models_text() -> str:
    """The model list, for /model with no argument."""
    active = get_active_model()
    lines = ["Pick a brain for Jarvis (all free, no card):"]
    for model_id, info in MODELS.items():
        mark = " ← current" if model_id == active else ""
        lines.append(
            f"- {model_id} ({info['label']}): {info['description']}{mark}"
        )
    lines.append("Switch with: /model <name>")
    return "\n".join(lines)
