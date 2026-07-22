# Phase 19: WhatsApp Catalog Sync (REAL)
from __future__ import annotations
import csv, io, json
from pathlib import Path
from typing import Any, Dict
from backend.tools import tool, RiskTier
from backend import business_db

@tool(name="wa_catalog.sync", description="Pull all products from DB and generate a WhatsApp Business catalog CSV.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="whatsapp_catalog")
async def sync() -> Dict[str, Any]:
    products = business_db.rows_to_dicts(business_db.query("SELECT name, price, currency, description FROM products WHERE active = 1"))
    if not products: return {"ok": False, "error": "No products in catalog."}
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["name", "price", "currency", "description", "url", "image_url"])
    for p in products:
        writer.writerow([p["name"], p.get("price",0), p.get("currency","JOD"), p.get("description",""), "", ""])
    out = Path("./storage/whatsapp_catalog.csv"); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(buf.getvalue(), encoding="utf-8")
    return {"ok": True, "products": len(products), "csv_path": str(out), "instructions": "WhatsApp Business > Settings > Business Tools > Catalog > Import CSV"}

@tool(name="wa_catalog.update_prices", description="Regenerate catalog CSV with updated prices from DB.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="whatsapp_catalog")
async def update_prices() -> Dict[str, Any]:
    return await sync()

PLUGIN_NAME = "whatsapp_catalog"; PLUGIN_VERSION = "1.0.0"
