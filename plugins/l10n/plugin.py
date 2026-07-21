# ====================================================================
# JARVIS OMEGA - Localization Plugin (Phase 12)
# ====================================================================
"""
Localization layer: language, currency, date format, RTL layout.

Sir is based in Amman, Jordan → Arabic-first, JD currency, RTL layout.
This plugin is the single source of truth every other plugin consults
when generating user-facing content.

Tools:
  l10n.profile                - return the active locale profile
  l10n.convert_currency       - convert between JOD/USD/SAR/EUR
  l10n.translate              - translate EN→AR or AR→EN
  l10n.format_money           - format a number in the active currency
  l10n.arabicize_number       - render Western digits as Arabic-Indic
  l10n.detect_language        - detect the language of a text
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from backend.tools import tool, RiskTier
from backend.config import settings


# --------------------------------------------------------------------
# Locale profile
# --------------------------------------------------------------------

_ARABIC_INDIC = "٠١٢٣٤٥٦٧٨٩"


@tool(
    name="l10n.profile",
    description="Return the active locale profile (language, country, currency, RTL, timezone).",
    parameters={"type": "object"},
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="l10n",
)
async def l10n_profile() -> Dict[str, Any]:
    return {
        "ok": True,
        "language": settings.default_language,
        "country": settings.default_country,
        "country_name": settings.default_country_name,
        "city": settings.default_city,
        "currency": settings.default_currency,
        "currency_symbol": settings.default_currency_symbol,
        "exchange_rate_to_usd": settings.default_currency_exchange_rate,
        "timezone": settings.default_timezone,
        "rtl": settings.rtl_layout,
        "writing_direction": "rtl" if settings.rtl_layout else "ltr",
    }


# --------------------------------------------------------------------
# Currency conversion
# --------------------------------------------------------------------

# Approximate static rates (1 unit = X USD). Update via l10n.set_rates.
_STATIC_RATES_TO_USD: Dict[str, float] = {
    "USD": 1.0,
    "JOD": 1.41,    # 1 JOD ≈ 1.41 USD
    "SAR": 0.27,
    "AED": 0.27,
    "EUR": 1.08,
    "GBP": 1.27,
    "EGP": 0.021,
}


@tool(
    name="l10n.convert_currency",
    description="Convert an amount between currencies using static rates.",
    parameters={
        "type": "object",
        "properties": {
            "amount": {"type": "number"},
            "from_currency": {"type": "string", "default": "USD"},
            "to_currency": {"type": "string", "default": "JOD"},
        },
        "required": ["amount"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="l10n",
)
async def l10n_convert_currency(amount: float, from_currency: str = "USD", to_currency: str = "JOD") -> Dict[str, Any]:
    fr = from_currency.upper()
    to = to_currency.upper()
    fr_rate = _STATIC_RATES_TO_USD.get(fr)
    to_rate = _STATIC_RATES_TO_USD.get(to)
    if not fr_rate or not to_rate:
        return {"ok": False, "error": f"unsupported currency pair {fr}→{to}"}
    usd = amount * fr_rate
    converted = usd / to_rate
    return {
        "ok": True,
        "original_amount": amount,
        "original_currency": fr,
        "converted_amount": round(converted, 2),
        "converted_currency": to,
        "rate_used": round(fr_rate / to_rate, 4),
    }


# --------------------------------------------------------------------
# Formatting helpers
# --------------------------------------------------------------------

def arabicize_number(value) -> str:
    """Render Western digits in a string as Arabic-Indic digits."""
    s = str(value)
    out = []
    for ch in s:
        if ch.isdigit():
            out.append(_ARABIC_INDIC[int(ch)])
        else:
            out.append(ch)
    return "".join(out)


@tool(
    name="l10n.arabicize_number",
    description="Render Western digits (0-9) in a number/string as Arabic-Indic digits (٠-٩).",
    parameters={
        "type": "object",
        "properties": {"value": {"type": "string"}},
        "required": ["value"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="l10n",
)
async def l10n_arabicize_number(value: str) -> Dict[str, Any]:
    return {"ok": True, "original": value, "arabicized": arabicize_number(value)}


@tool(
    name="l10n.format_money",
    description="Format an amount in the active (or specified) currency, with optional Arabic digits.",
    parameters={
        "type": "object",
        "properties": {
            "amount": {"type": "number"},
            "currency": {"type": "string", "default": ""},
            "arabic_digits": {"type": "boolean", "default": True},
            "locale": {"type": "string", "default": "ar", "enum": ["ar", "en"]},
        },
        "required": ["amount"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="l10n",
)
async def l10n_format_money(
    amount: float, currency: str = "", arabic_digits: bool = True, locale: str = "ar",
) -> Dict[str, Any]:
    cur = (currency or settings.default_currency).upper()
    symbol = settings.default_currency_symbol if cur == settings.default_currency else cur
    rounded = round(amount, 2)
    text = f"{rounded:.2f} {symbol}"
    if locale == "ar" and arabic_digits:
        text = arabicize_number(text)
    return {"ok": True, "amount": rounded, "currency": cur, "formatted": text}


# --------------------------------------------------------------------
# Translation + language detection
# --------------------------------------------------------------------

@tool(
    name="l10n.translate",
    description="Translate text between Arabic and English using the LibreTranslate plugin (free).",
    parameters={
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "to_language": {"type": "string", "default": "ar", "enum": ["ar", "en"]},
        },
        "required": ["text"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="l10n",
)
async def l10n_translate(text: str, to_language: str = "ar") -> Dict[str, Any]:
    # Default source = the opposite language.
    detected_as_ar = any("\u0600" <= ch <= "\u06FF" for ch in text)
    source = "ar" if detected_as_ar else "en"
    if source == to_language:
        return {"ok": True, "source": source, "target": to_language, "translated_text": text}
    from plugins.translate.plugin import translate_text
    result = await translate_text(text=text, target=to_language, source=source)
    return result


@tool(
    name="l10n.detect_language",
    description="Detect whether a text is Arabic, English, or mixed. Simple heuristic - no external call.",
    parameters={
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="l10n",
)
async def l10n_detect_language(text: str) -> Dict[str, Any]:
    if not text:
        return {"ok": True, "language": "unknown"}
    ar_chars = sum(1 for ch in text if "\u0600" <= ch <= "\u06FF")
    en_chars = sum(1 for ch in text if ch.isascii() and ch.isalpha())
    total = ar_chars + en_chars
    if total == 0:
        return {"ok": True, "language": "unknown"}
    ar_ratio = ar_chars / total
    if ar_ratio > 0.7:
        lang = "ar"
    elif ar_ratio < 0.3:
        lang = "en"
    else:
        lang = "mixed"
    return {"ok": True, "language": lang, "arabic_ratio": round(ar_ratio, 2)}


@tool(
    name="l10n.localized_content",
    description="Generate marketing/social content in the active language (Arabic by default). Wraps marketing.create_content with locale awareness.",
    parameters={
        "type": "object",
        "properties": {
            "topic": {"type": "string"},
            "language": {"type": "string", "default": "ar", "enum": ["ar", "en", "both"]},
            "platform": {"type": "string", "default": "twitter"},
            "tone": {"type": "string", "default": "professional"},
            "variants": {"type": "integer", "default": 3},
        },
        "required": ["topic"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="l10n",
)
async def l10n_localized_content(
    topic: str, language: str = "ar", platform: str = "twitter",
    tone: str = "professional", variants: int = 3,
) -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    import json

    languages = ["ar", "en"] if language == "both" else [language]
    out: Dict[str, Any] = {"ok": True, "topic": topic, "by_language": {}}
    for lang in languages:
        lang_name = "Arabic" if lang == "ar" else "English"
        sys_prompt = (
            f"You are a senior content marketer. Generate {variants} social posts "
            f"in {lang_name}. Platform: {platform}. Tone: {tone}. "
            f"Output STRICT JSON: {{\"variants\": [{{\"content\": string, \"hashtags\": [string, ...]}}]}}. "
            f"{'Hashtags in Arabic where appropriate.' if lang == 'ar' else ''}"
            "Do NOT wrap in markdown fences."
        )
        try:
            reply = await llm_service.get_response(
                user_message=f"Topic: {topic}",
                system_instructions=sys_prompt,
                inject_memory=False,
            )
            cleaned = reply.strip()
            if cleaned.startswith("```"):
                lines = cleaned.splitlines()
                if lines and lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                cleaned = "\n".join(lines).strip()
            try:
                parsed = json.loads(cleaned)
            except json.JSONDecodeError:
                start = cleaned.find("{")
                depth = 0
                salvaged = None
                for i in range(start, len(cleaned)) if start >= 0 else []:
                    if cleaned[i] == "{":
                        depth += 1
                    elif cleaned[i] == "}":
                        depth -= 1
                        if depth == 0:
                            try:
                                salvaged = json.loads(cleaned[start:i + 1])
                            except json.JSONDecodeError:
                                pass
                            break
                parsed = salvaged or {"variants": [{"content": reply, "hashtags": []}]}
            out["by_language"][lang] = parsed.get("variants", [])
        except Exception as e:
            out["by_language"][lang] = {"error": str(e)}
    return out


PLUGIN_NAME = "l10n"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Localization: language, currency (JOD/USD/SAR), RTL, Arabic digits, bilingual content."
