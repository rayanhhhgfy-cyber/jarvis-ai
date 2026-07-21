# Phase 18: Telegram Bot Builder (REAL)
from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Dict
from backend.tools import tool, RiskTier

@tool(name="tg_bot.create", description="Generate a complete Telegram bot configuration + Python handler code.", parameters={"type":"object","properties":{"bot_name":{"type":"string"},"purpose":{"type":"string","default":"customer support"},"features":{"type":"array","items":{"type":"string"},"default":["faq","order_tracking","contact_human"]}},"required":["bot_name"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="telegram_bot_builder")
async def create(bot_name: str, purpose: str = "customer support", features: list = None) -> Dict[str, Any]:
    features = features or ["faq","order_tracking","contact_human"]
    from backend.services.llm_service import llm_service
    try:
        code = await llm_service.get_response(
            user_message=f"Bot: {bot_name}, Purpose: {purpose}, Features: {features}",
            system_instructions="Generate a complete Python Telegram bot using python-telegram-bot library. Include: /start handler, FAQ handler, message router, error handler. Output Python code only.",
            inject_memory=False)
        out_dir = Path(f"./storage/telegram_bots/{bot_name.lower().replace(' ','_')}"); out_dir.mkdir(parents=True, exist_ok=True)
        code_path = out_dir / "bot.py"; code_path.write_text(code, encoding="utf-8")
        config = {"bot_name": bot_name, "purpose": purpose, "features": features, "code_path": str(code_path)}
        (out_dir / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
        return {"ok": True, "bot_name": bot_name, "code_path": str(code_path), "instructions": ["1. Talk to @BotFather on Telegram", "2. Create a new bot", f"3. Name it: {bot_name}", "4. Copy the token", "5. Put 'telegram_bot_token' in JARVIS vault", "6. Run the generated bot.py"]}
    except Exception as e: return {"ok": False, "error": str(e)}
