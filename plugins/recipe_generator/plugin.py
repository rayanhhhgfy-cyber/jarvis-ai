# Phase 19: AI Recipe Generator (REAL)
from __future__ import annotations
import json
from typing import Any, Dict
from backend.tools import tool, RiskTier

@tool(name="recipe.generate", description="Generate a unique recipe from ingredients or constraints.", parameters={"type":"object","properties":{"ingredients":{"type":"array","items":{"type":"string"},"default":[]},"cuisine":{"type":"string","default":"middle eastern"},"servings":{"type":"integer","default":4}}}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="recipe_generator")
async def generate(ingredients: list = None, cuisine: str = "middle eastern", servings: int = 4) -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    try:
        reply = await llm_service.get_response(user_message=f"Ingredients: {ingredients}, Cuisine: {cuisine}, Servings: {servings}", system_instructions='Create a unique recipe in Arabic. Include: name, prep time, cook time, ingredients with quantities, step-by-step instructions, serving suggestions. Output STRICT JSON: {name, prep_minutes, cook_minutes, ingredients:[{name, amount}], steps:[string], tips:[string]}', inject_memory=False)
        text = reply.strip().lstrip("`").rstrip("`")
        if text.startswith("json"): text = text[4:]
        return {"ok": True, **json.loads(text)}
    except Exception as e: return {"ok": False, "error": str(e)}

@tool(name="recipe.cost_analysis", description="Calculate cost per serving for a recipe.", parameters={"type":"object","properties":{"ingredients_with_costs":{"type":"array","items":{"type":"object"},"description":"[{name, cost_jod}]","default":[]},"servings":{"type":"integer","default":4}}}, risk_tier=RiskTier.TIER_0_OBSERVE, category="recipe_generator")
async def cost_analysis(ingredients_with_costs: list = None, servings: int = 4) -> Dict[str, Any]:
    ingredients_with_costs = ingredients_with_costs or []
    total = sum(float(i.get("cost_jod", 0)) for i in ingredients_with_costs)
    per_serving = total / servings if servings else 0
    suggested_price = per_serving * 3  # 3x markup is standard for restaurants
    return {"ok": True, "total_cost_jod": round(total, 2), "cost_per_serving_jod": round(per_serving, 2), "suggested_menu_price_jod": round(suggested_price, 2), "profit_margin_pct": 67}

PLUGIN_NAME = "recipe_generator"; PLUGIN_VERSION = "1.0.0"
