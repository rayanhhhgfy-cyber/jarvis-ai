# ====================================================================
# JARVIS OMEGA - Agency Orchestrator (Phase 11) - THE MASTER PLUGIN
# ====================================================================
"""
Master coordinator that drives the whole agency end-to-end. Give JARVIS a
niche and clearance, and this plugin runs the full funnel:

  1. biz.scan_opportunities      - find what's hot in the niche
  2. biz.research_market         - size the market + pick a monetization path
  3. website.generate_landing_page - build the offering
  4. website.deploy_*            - publish to a free host
  5. marketing.create_content   - generate social posts
  6. marketing.schedule         - queue them across platforms
  7. sales.find_leads + write_cold_email - direct outreach
  8. ecommerce / payments        - capture orders + collect money
  9. weekly_report               - what happened, what's next

Plus: ``agency.find_new_business`` (niche scan), ``agency.onboard_client``,
``agency.weekly_report``.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.tools import tool, RiskTier
from backend import business_db
from backend.config import settings
from shared.logger import get_logger

log = get_logger("agency_orchestrator")


def _json_salvage(text: str) -> Dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        if start == -1:
            return {}
        depth = 0
        for i in range(start, len(cleaned)):
            if cleaned[i] == "{":
                depth += 1
            elif cleaned[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(cleaned[start:i + 1])
                    except json.JSONDecodeError:
                        return {}
        return {}


# --------------------------------------------------------------------
# Find new business
# --------------------------------------------------------------------

@tool(
    name="agency.find_new_business",
    description="Scan for the top N business opportunities in a niche. Returns a ranked list with monetization suggestions.",
    parameters={
        "type": "object",
        "properties": {
            "niche_keywords": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Keywords describing the niche (e.g. ['AI tools', 'small business', 'marketing']).",
            },
            "limit": {"type": "integer", "default": 10},
        },
        "required": ["niche_keywords"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="agency",
)
async def agency_find_new_business(niche_keywords: List[str], limit: int = 10) -> Dict[str, Any]:
    from plugins.business_intel.plugin import biz_scan_opportunities, biz_list_opportunities
    # Scan now.
    scan = await biz_scan_opportunities(niche_keywords=niche_keywords)
    # Read top N.
    top = await biz_list_opportunities(status="new", limit=limit, min_score=10)
    return {
        "ok": True,
        "niche": niche_keywords,
        "scanned": scan.get("scanned", 0),
        "new_added": scan.get("added", 0),
        "top_opportunities": top.get("opportunities", []),
    }


# --------------------------------------------------------------------
# Onboard a client
# --------------------------------------------------------------------

@tool(
    name="agency.onboard_client",
    description="Onboard a new client into the CRM. Creates a campaign, content calendar, and welcome email draft.",
    parameters={
        "type": "object",
        "properties": {
            "client_name": {"type": "string"},
            "niche": {"type": "string"},
            "website": {"type": "string", "default": ""},
            "contact_email": {"type": "string", "default": ""},
            "goals": {"type": "string", "default": "Awareness + lead gen"},
            "platforms": {"type": "array", "items": {"type": "string"}, "default": ["twitter", "linkedin"]},
        },
        "required": ["client_name", "niche"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="agency",
)
async def agency_onboard_client(
    client_name: str, niche: str, website: str = "", contact_email: str = "",
    goals: str = "Awareness + lead gen", platforms: Optional[List[str]] = None,
) -> Dict[str, Any]:
    platforms = platforms or ["twitter", "linkedin"]
    from plugins.sales.plugin import sales_add_client, sales_add_contact, sales_create_deal
    from plugins.marketing.plugin import marketing_create_campaign, marketing_create_content

    # 1. Create client row.
    client_resp = await sales_add_client(
        name=client_name, niche=niche, website=website, email=contact_email,
        status="active", notes=goals,
    )
    client_id = client_resp["client_id"]

    # 2. Contact (if email provided).
    contact_id = None
    if contact_email:
        c_resp = await sales_add_contact(client_id=client_id, name=client_name, email=contact_email)
        contact_id = c_resp.get("contact_id")

    # 3. Deal
    deal_resp = await sales_create_deal(
        client_id=client_id, title=f"{client_name} retainer", value=0,
        stage="qualified", probability=50,
    )

    # 4. Initial campaign
    campaign_ids: List[int] = []
    for plat in platforms:
        camp = await marketing_create_campaign(
            client_id=client_id, name=f"{client_name} - {plat} campaign",
            platform=plat, objective="awareness", notes=goals,
        )
        if camp.get("campaign_id"):
            campaign_ids.append(camp["campaign_id"])

    # 5. Welcome email draft
    welcome_subject = f"Welcome to {client_name} marketing, Sir/Madam"
    welcome_body = (
        f"Hello {client_name} team,\n\n"
        f"I'm JARVIS, your autonomous marketing operator. "
        f"I've set up your CRM entry, created {len(campaign_ids)} campaign(s) on "
        f"{', '.join(platforms)}, and I'll start scanning for opportunities in "
        f"the {niche} niche today. Expect a weekly report every Monday.\n\n"
        f"Goals for this engagement: {goals}.\n\n"
        f"Reply with any constraints (brand voice, must-avoid topics, etc.) and I'll adapt.\n\n"
        f"- JARVIS OMEGA"
    )

    business_db.audit("onboard_client", "agency", target=client_name,
                      details={"client_id": client_id, "campaign_ids": campaign_ids})
    return {
        "ok": True,
        "client_id": client_id,
        "contact_id": contact_id,
        "deal_id": deal_resp.get("deal_id"),
        "campaign_ids": campaign_ids,
        "welcome_email_subject": welcome_subject,
        "welcome_email_body": welcome_body,
    }


# --------------------------------------------------------------------
# Build a money-making project from scratch
# --------------------------------------------------------------------

@tool(
    name="agency.build_project",
    description="End-to-end: pick a product for a niche, build the landing page, deploy to a free host, set up an order pipeline. Returns URLs + next steps.",
    parameters={
        "type": "object",
        "properties": {
            "niche": {"type": "string", "description": "Target niche, e.g. 'AI tools for solo lawyers'."},
            "deploy_target": {
                "type": "string", "enum": ["vercel", "netlify", "github_pages", "local_only"],
                "default": "local_only",
                "description": "Where to deploy. Free tier on all three. local_only = just generate files.",
            },
            "product_name_override": {"type": "string", "default": ""},
            "client_id": {"type": "integer", "default": 0},
        },
        "required": ["niche"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="agency",
)
async def agency_build_project(
    niche: str, deploy_target: str = "local_only",
    product_name_override: str = "", client_id: int = 0,
) -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    from plugins.website.plugin import (
        website_generate_landing_page, website_deploy_vercel,
        website_deploy_netlify, website_deploy_github_pages,
    )
    from plugins.ecommerce.plugin import ecommerce_add_product

    # 1. Ask the LLM for a product idea in this niche.
    try:
        reply = await llm_service.get_response(
            user_message=f"Niche: {niche}",
            system_instructions=(
                "You are a senior product strategist. Output STRICT JSON with a single, "
                "shippable-in-a-day product idea: "
                "{"
                "\"product_name\": string,"
                "\"tagline\": string (<80 chars),"
                "\"description\": string (1-paragraph),"
                "\"features\": [string, string, string],"
                "\"pricing\": [{\"name\": string, \"price\": string, \"features\": [string, ...]}],"
                "\"monetization\": \"saas\" | \"digital_product\" | \"affiliate\" | \"lead_gen\" | \"newsletter\" | \"service\","
                "\"suggested_price_usd\": number"
                "}"
            ),
            inject_memory=False,
        )
        spec = _json_salvage(reply)
        if not spec:
            return {"ok": False, "error": "LLM did not return a product spec", "raw": reply[:300]}
    except Exception as e:
        return {"ok": False, "error": f"LLM failed: {e}"}

    product_name = product_name_override or spec.get("product_name", "Untitled Product")
    tagline = spec.get("tagline", "")
    description = spec.get("description", "")
    features = spec.get("features", [])
    pricing = spec.get("pricing", [])
    monetization = spec.get("monetization", "service")
    suggested_price = spec.get("suggested_price_usd", 0)

    # 2. Generate landing page.
    site = await website_generate_landing_page(
        product_name=product_name, tagline=tagline, description=description,
        features=features, pricing=pricing,
        cta_text="Buy Now" if monetization in {"digital_product", "saas"} else "Get in Touch",
        cta_url="#contact",
        output_dir=f"./storage/website/{product_name.lower().replace(' ', '_')}",
    )
    if not site.get("ok"):
        return {"ok": False, "error": "landing page generation failed", "detail": site}

    # 3. Add product to catalog (if pricing exists).
    product_id = None
    if pricing and monetization in {"digital_product", "saas"}:
        try:
            first_price = float(str(pricing[0]["price"]).replace("$", "").replace("/mo", "").replace("/yr", "").strip() or 0)
        except Exception:
            first_price = suggested_price or 19.0
        prod = await ecommerce_add_product(
            client_id=client_id, name=product_name, price=first_price,
            description=description, inventory=9999,
        )
        if prod.get("ok"):
            product_id = prod["product_id"]

    # 4. Deploy if requested.
    deploy_info: Dict[str, Any] = {"deploy_target": deploy_target}
    if deploy_target != "local_only":
        site_dir = str(Path(site["path"]).parent)
        if deploy_target == "vercel":
            deploy = await website_deploy_vercel(
                site_dir=site_dir, project_name=product_name.lower().replace(" ", "-"),
            )
        elif deploy_target == "netlify":
            deploy = await website_deploy_netlify(site_dir=site_dir)
        elif deploy_target == "github_pages":
            deploy = await website_deploy_github_pages(
                site_dir=site_dir,
                gh_repo=product_name.lower().replace(" ", "-"),  # assumes repo already exists
            )
        else:
            deploy = {"ok": False, "error": f"unknown deploy target: {deploy_target}"}
        deploy_info["result"] = deploy

    business_db.audit("build_project", "agency", target=product_name,
                      details={"niche": niche, "deploy_target": deploy_target,
                               "product_id": product_id, "monetization": monetization})

    return {
        "ok": True,
        "niche": niche,
        "product_name": product_name,
        "tagline": tagline,
        "monetization": monetization,
        "landing_page": site["path"],
        "product_id": product_id,
        "deploy": deploy_info,
        "next_steps": [
            "Set up a Stripe Payment Link for the new product (payments.create_stripe_link).",
            "Generate 5+ social posts about the product (marketing.create_content).",
            "Schedule posts across the week (marketing.schedule).",
            "Find 50 leads in this niche (sales.find_leads) and cold-email them.",
        ],
    }


# --------------------------------------------------------------------
# Weekly report
# --------------------------------------------------------------------

@tool(
    name="agency.weekly_report",
    description="Aggregate the last 7 days of activity into a single markdown report. Covers pipeline, posts, orders, revenue, opportunities.",
    parameters={
        "type": "object",
        "properties": {
            "days": {"type": "integer", "default": 7},
            "output_path": {"type": "string", "default": "./storage/sales/weekly_report.md"},
        },
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="agency",
)
async def agency_weekly_report(days: int = 7, output_path: str = "./storage/sales/weekly_report.md") -> Dict[str, Any]:
    since = (datetime.utcnow() - timedelta(days=days)).isoformat()

    clients = business_db.query("SELECT COUNT(*) as n FROM clients WHERE created_at >= ?", (since,))[0]["n"]
    deals = business_db.rows_to_dicts(business_db.query(
        "SELECT stage, COUNT(*) as n, COALESCE(SUM(value), 0) as v FROM deals WHERE created_at >= ? GROUP BY stage",
        (since,),
    ))
    posts = business_db.rows_to_dicts(business_db.query(
        "SELECT status, COUNT(*) as n FROM posts WHERE created_at >= ? GROUP BY status", (since,)
    ))
    orders = business_db.rows_to_dicts(business_db.query(
        "SELECT status, COUNT(*) as n, COALESCE(SUM(total), 0) as v FROM orders WHERE created_at >= ? GROUP BY status",
        (since,),
    ))
    invoices = business_db.query(
        "SELECT COUNT(*) as n, COALESCE(SUM(amount), 0) as v FROM invoices WHERE status = 'paid' AND paid_at >= ?",
        (since,),
    )[0]
    new_opps = business_db.query(
        "SELECT COUNT(*) as n FROM opportunities WHERE discovered_at >= ?", (since,)
    )[0]["n"]
    acted_opps = business_db.query(
        "SELECT COUNT(*) as n FROM opportunities WHERE status = 'acted_on' AND reviewed_at >= ?",
        (since,),
    )[0]["n"]

    md = f"""# JARVIS Weekly Report

**Period:** last {days} days (since {since[:10]})

## Pipeline
- New clients: **{clients}**
- Deals by stage:
{chr(10).join(f'  - {d["stage"]}: {d["n"]} (${d["v"]})' for d in deals) or '  - (none)'}

## Marketing
- Posts: {posts or '(none)'}

## Orders
{chr(10).join(f'  - {o["status"]}: {o["n"]} (${o["v"]})' for o in orders) or '  - (none)'}

## Revenue
- Paid invoices: **{invoices["n"]}** totaling **${invoices["v"]}**

## Opportunities
- New discovered: **{new_opps}**
- Acted on: **{acted_opps}**

## Audit Log (last 25 external actions)
"""
    last_actions = business_db.query(
        "SELECT timestamp, action, category, target FROM audit_log ORDER BY id DESC LIMIT 25"
    )
    for a in last_actions:
        md += f"- `{a['timestamp'][:19]}` **{a['action']}** ({a['category']}) — {a['target']}\n"

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(md, encoding="utf-8")
    return {
        "ok": True,
        "path": output_path,
        "summary": {
            "clients": clients,
            "deals": deals,
            "posts": posts,
            "orders": orders,
            "paid_invoices": invoices["n"],
            "revenue": invoices["v"],
            "new_opportunities": new_opps,
            "acted_opportunities": acted_opps,
        },
    }


# --------------------------------------------------------------------
# Full-funnel execution (the "give me clearance" tool)
# --------------------------------------------------------------------

@tool(
    name="agency.run_full_funnel",
    description="Master tool: given a niche + clearance, run end-to-end — find idea, build landing page, deploy, post to social, find leads, send outreach. Returns a complete report. Respects ALLOW_AUTONOMOUS_BUSINESS.",
    parameters={
        "type": "object",
        "properties": {
            "niche": {"type": "string", "description": "Target niche for the new business."},
            "deploy_target": {
                "type": "string", "enum": ["vercel", "netlify", "github_pages", "local_only"],
                "default": "local_only",
            },
            "post_count": {"type": "integer", "default": 5, "description": "How many social posts to schedule."},
            "lead_count": {"type": "integer", "default": 25, "description": "How many leads to find."},
            "platforms": {"type": "array", "items": {"type": "string"}, "default": ["mastodon", "reddit"]},
        },
        "required": ["niche"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="agency",
)
async def agency_run_full_funnel(
    niche: str, deploy_target: str = "local_only", post_count: int = 5,
    lead_count: int = 25, platforms: Optional[List[str]] = None,
) -> Dict[str, Any]:
    platforms = platforms or ["mastodon", "reddit"]
    report: Dict[str, Any] = {"niche": niche, "steps": []}

    # 1. Build the project.
    build = await agency_build_project(niche=niche, deploy_target=deploy_target)
    report["steps"].append({"step": "build_project", "ok": build.get("ok"), "detail": build})
    if not build.get("ok"):
        return {"ok": False, "report": report, "error": "build step failed"}

    # 2. Generate social posts.
    from plugins.marketing.plugin import marketing_create_content, marketing_schedule
    post_results = []
    for plat in platforms:
        content = await marketing_create_content(
            topic=f"{build['product_name']} - {build['tagline']}",
            platform=plat, variants=1,
        )
        if content.get("ok"):
            # Schedule one per day for the next N days.
            for variant in content.get("variants", [])[:1]:
                sched_time = (datetime.utcnow() + timedelta(days=1 + len(post_results))).isoformat()
                sched = await marketing_schedule(
                    platform=plat, content=variant.get("content", ""),
                    scheduled_at=sched_time,
                )
                post_results.append({"platform": plat, "scheduled_at": sched_time, "ok": sched.get("ok")})
        if len(post_results) >= post_count:
            break
    report["steps"].append({"step": "schedule_posts", "scheduled": post_results})

    # 3. Find leads (skip if autonomous business is off — would be intrusive).
    leads_found = 0
    if settings.allow_autonomous_business:
        from plugins.sales.plugin import sales_find_leads
        leads = await sales_find_leads(niche=niche.split()[0].lower(), location="United States", limit=lead_count)
        leads_found = leads.get("count", 0) if leads.get("ok") else 0
        report["steps"].append({"step": "find_leads", "count": leads_found, "sample": leads.get("leads", [])[:3]})

    # 4. Persist the opportunity.
    business_db.execute(
        """INSERT INTO opportunities (source, title, summary, url, niche, score, monetization, status, action_taken, discovered_at, reviewed_at)
           VALUES ('manual', ?, ?, '', ?, 100, ?, 'acted_on', ?, ?, ?)""",
        (build["product_name"], f"Built project for niche: {niche}",
         niche, build["monetization"],
         f"Deployed {deploy_target}; scheduled {len(post_results)} posts; found {leads_found} leads",
         datetime.utcnow().isoformat(), datetime.utcnow().isoformat()),
    )

    business_db.audit("run_full_funnel", "agency", target=niche,
                      details={"product": build["product_name"], "posts": len(post_results), "leads": leads_found})

    report["ok"] = True
    report["summary"] = {
        "product": build["product_name"],
        "deploy": build.get("deploy", {}).get("deploy_target"),
        "posts_scheduled": len(post_results),
        "leads_found": leads_found,
        "landing_page": build["landing_page"],
    }
    return report


PLUGIN_NAME = "agency_orchestrator"
PLUGIN_VERSION = "2.0.0"
PLUGIN_DESCRIPTION = (
    "Master agency coordinator — find opportunities, onboard clients, build projects "
    "(multi-product, multi-business, continuous-mode), run full funnels, weekly reports."
)


# --------------------------------------------------------------------
# Phase 12: multi-product builder (5-10 products per niche)
# --------------------------------------------------------------------

@tool(
    name="agency.build_multi_product",
    description="Build N products in one niche in a single call (default 7). Each gets its own landing page + product catalog entry.",
    parameters={
        "type": "object",
        "properties": {
            "niche": {"type": "string"},
            "product_count": {"type": "integer", "default": 7, "description": "How many distinct products to build (1-15)."},
            "language": {"type": "string", "default": "ar", "enum": ["ar", "en", "both"]},
            "deploy_target": {
                "type": "string", "enum": ["vercel", "netlify", "github_pages", "local_only"],
                "default": "local_only",
            },
            "business_id": {"type": "integer", "default": 0, "description": "Optional portfolio business to attach to."},
        },
        "required": ["niche"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="agency",
)
async def agency_build_multi_product(
    niche: str, product_count: int = 7, language: str = "ar",
    deploy_target: str = "local_only", business_id: int = 0,
) -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    from plugins.website.plugin import (
        website_generate_landing_page, website_deploy_vercel,
        website_deploy_netlify, website_deploy_github_pages,
    )
    from plugins.ecommerce.plugin import ecommerce_add_product
    from plugins.l10n.plugin import l10n_convert_currency

    product_count = max(1, min(15, product_count))

    # Ask the LLM for N product ideas in this niche.
    sys_prompt = (
        f"You are a senior product strategist. Generate {product_count} distinct, "
        f"non-overlapping product ideas for the niche: '{niche}'. "
        f"Language for product names + descriptions: {language} "
        f"({'Arabic' if language == 'ar' else 'English' if language == 'en' else 'both Arabic and English'}). "
        "Output STRICT JSON: "
        "{\"products\": ["
        "  {\"name_ar\": string, \"name_en\": string, \"tagline_ar\": string, \"tagline_en\": string, "
        "   \"description_ar\": string, \"description_en\": string, "
        "   \"features_ar\": [string], \"features_en\": [string], "
        "   \"pricing_tier_usd\": number, \"monetization\": string}"
        "]}"
    )
    try:
        reply = await llm_service.get_response(
            user_message=f"Niche: {niche}",
            system_instructions=sys_prompt,
            inject_memory=False,
        )
        spec = _json_salvage(reply)
        products = spec.get("products", [])
        if not products:
            return {"ok": False, "error": "LLM returned no products", "raw": reply[:300]}
    except Exception as e:
        return {"ok": False, "error": f"LLM failed: {e}"}

    # Convert prices to JOD once (Phase 12 default).
    from backend.config import settings as cfg

    results: List[Dict[str, Any]] = []
    for idx, prod in enumerate(products[:product_count], start=1):
        name = prod.get("name_en") or prod.get("name_ar") or f"Product {idx}"
        # Build display fields per language.
        is_ar = language in ("ar", "both")
        is_en = language in ("en", "both")

        display_name = prod.get("name_en") or name
        tagline = prod.get("tagline_en") or prod.get("tagline_ar") or ""
        description = prod.get("description_en") or prod.get("description_ar") or ""
        features = prod.get("features_en") or prod.get("features_ar") or []

        # Convert USD → JOD
        price_usd = float(prod.get("pricing_tier_usd", 19) or 19)
        conv = await l10n_convert_currency(amount=price_usd, from_currency="USD", to_currency=cfg.default_currency)
        price_local = conv.get("converted_amount", price_usd)

        pricing = [{
            "name": "Basic",
            "price": f"{price_local} {cfg.default_currency}",
            "features": features[:3] if features else [],
        }]

        site = await website_generate_landing_page(
            product_name=display_name,
            tagline=tagline,
            description=description,
            features=features,
            pricing=pricing,
            cta_text=("اشترِ الآن" if is_ar and not is_en else "Buy Now"),
            cta_url="#contact",
            output_dir=f"./storage/website/{display_name.lower().replace(' ', '_')}",
        )
        if not site.get("ok"):
            results.append({"product": name, "ok": False, "error": "landing page failed"})
            continue

        # Add to product catalog.
        prod_resp = await ecommerce_add_product(
            client_id=0, name=display_name, price=price_local,
            currency=cfg.default_currency, inventory=9999, description=description,
        )

        # Localize landing page HTML for Arabic + RTL.
        if is_ar:
            await _inject_arabic_and_rtl(site["path"], prod)

        # Deploy if requested.
        deploy_info: Dict[str, Any] = {}
        if deploy_target != "local_only":
            site_dir = str(Path(site["path"]).parent)
            if deploy_target == "vercel":
                d = await website_deploy_vercel(site_dir=site_dir, project_name=display_name.lower().replace(" ", "-"))
            elif deploy_target == "netlify":
                d = await website_deploy_netlify(site_dir=site_dir)
            elif deploy_target == "github_pages":
                d = await website_deploy_github_pages(site_dir=site_dir, gh_repo=display_name.lower().replace(" ", "-"))
            else:
                d = {"ok": False, "error": "unknown"}
            deploy_info = d

        results.append({
            "ok": True,
            "product": display_name,
            "name_ar": prod.get("name_ar"),
            "tagline_ar": prod.get("tagline_ar"),
            "price_local": price_local,
            "price_usd": price_usd,
            "currency": cfg.default_currency,
            "monetization": prod.get("monetization", "service"),
            "landing_path": site["path"],
            "product_id": prod_resp.get("product_id") if prod_resp.get("ok") else None,
            "deploy": deploy_info,
        })

    # Update the parent business if provided.
    if business_id:
        first_path = next((r.get("landing_path") for r in results if r.get("ok")), None)
        first_url = next((r.get("deploy", {}).get("url") for r in results if r.get("deploy", {}).get("url")), "")
        if first_path or first_url:
            from plugins.portfolio.plugin import portfolio_update_business
            await portfolio_update_business(
                business_id=business_id, status="live",
                landing_path=first_path or "", deployed_url=first_url or "",
            )

    business_db.audit("build_multi_product", "agency", target=niche,
                      details={"count": len(results), "ok_count": sum(1 for r in results if r.get("ok"))})

    succeeded = [r for r in results if r.get("ok")]
    return {
        "ok": bool(succeeded),
        "niche": niche,
        "language": language,
        "products_requested": product_count,
        "products_built": len(succeeded),
        "products": results,
    }


async def _inject_arabic_and_rtl(html_path: str, prod_spec: Dict[str, Any]) -> None:
    """Rewrite a landing page HTML to be Arabic-first + RTL."""
    try:
        from plugins.l10n.plugin import arabicize_number
    except Exception:
        return
    try:
        html = Path(html_path).read_text(encoding="utf-8")
    except Exception:
        return

    # Inject <html dir="rtl" lang="ar"> if not already.
    import re
    html = re.sub(r"<html(?![^>]*\bdir=)[^>]*>", '<html dir="rtl" lang="ar">', html, count=1)
    # Inject an Arabic webfont + base CSS.
    inject_head = (
        '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Tajawal:wght@400;700&display=swap">'
        '<style>body{font-family:"Tajawal",system-ui,Arial,sans-serif;direction:rtl}</style>'
    )
    html = html.replace("</head>", f"{inject_head}</head>", 1)
    # Replace English product_name + tagline + description with Arabic if available.
    if prod_spec.get("name_ar"):
        # Replace the H1 with the Arabic name if it currently shows the English name.
        en_name = prod_spec.get("name_en", "")
        if en_name:
            html = html.replace(f">{en_name}<", f">{prod_spec['name_ar']}<", 1)
    if prod_spec.get("tagline_ar"):
        en_tag = prod_spec.get("tagline_en", "")
        if en_tag:
            html = html.replace(f">{en_tag}<", f">{prod_spec['tagline_ar']}<", 1)
    if prod_spec.get("description_ar"):
        en_desc = prod_spec.get("description_en", "")
        if en_desc:
            html = html.replace(f">{en_desc}<", f">{prod_spec['description_ar']}<", 1)
    try:
        Path(html_path).write_text(html, encoding="utf-8")
    except Exception:
        pass


# --------------------------------------------------------------------
# Phase 12: continuous-mode (never-stop builder)
# --------------------------------------------------------------------

@tool(
    name="agency.run_continuous",
    description="Never-stop mode: keeps building new businesses in new niches forever. Uses the background scheduler (every 24h by default). One call activates the loop.",
    parameters={
        "type": "object",
        "properties": {
            "activate": {"type": "boolean", "default": True, "description": "True = activate continuous mode; False = pause."},
            "products_per_business": {"type": "integer", "default": 7},
            "deploy_target": {"type": "string", "default": "local_only", "enum": ["vercel", "netlify", "github_pages", "local_only"]},
        },
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="agency",
)
async def agency_run_continuous(
    activate: bool = True, products_per_business: int = 7,
    deploy_target: str = "local_only",
) -> Dict[str, Any]:
    from backend.scheduler import scheduler
    from backend.config import settings as cfg

    mode = "always_on" if activate else "paused"
    now_iso = datetime.utcnow().isoformat()
    next_iso = (datetime.utcnow() + timedelta(hours=cfg.continuous_build_interval_hours)).isoformat()

    # Upsert continuous_state row.
    existing = business_db.query_one("SELECT id FROM continuous_state ORDER BY id DESC LIMIT 1")
    if existing:
        business_db.execute(
            "UPDATE continuous_state SET mode = ?, next_build_at = ?, updated_at = ? WHERE id = ?",
            (mode, next_iso if activate else None, now_iso, existing["id"]),
        )
    else:
        business_db.execute(
            "INSERT INTO continuous_state (mode, next_build_at, updated_at) VALUES (?, ?, ?)",
            (mode, next_iso if activate else None, now_iso),
        )

    # Register or cancel the scheduler job.
    JOB_ID = "continuous_business_builder"
    try:
        scheduler.cancel_job(JOB_ID)
    except Exception:
        pass

    if activate:
        async def _continuous_job():
            try:
                await _continuous_build_step(products_per_business, deploy_target)
            except Exception as e:
                log.warning("continuous_build_step_failed", error=str(e))

        scheduler.schedule_interval(
            job_id=JOB_ID,
            func=_continuous_job,
            hours=cfg.continuous_build_interval_hours,
            description=f"Continuous business builder (every {cfg.continuous_build_interval_hours}h)",
        )
        msg = (
            f"Continuous mode ACTIVATED. JARVIS will build a new {products_per_business}-product "
            f"business every {cfg.continuous_build_interval_hours}h until paused."
        )
    else:
        msg = "Continuous mode PAUSED. JARVIS will not start new businesses until reactivated."

    business_db.audit("run_continuous", "agency", target=mode, details={"products": products_per_business})
    return {"ok": True, "mode": mode, "message": msg, "next_build_at": next_iso if activate else None}


async def _continuous_build_step(products_per_business: int, deploy_target: str) -> None:
    """One iteration of the never-stop loop. Picks a fresh niche and builds."""
    from plugins.business_intel.plugin import biz_list_opportunities

    # Pull top un-actioned opportunity.
    opps = await biz_list_opportunities(status="new", limit=1, min_score=15)
    items = opps.get("opportunities", []) if opps.get("ok") else []
    if not items:
        log.info("continuous_no_opportunities_yet")
        # Update state and return.
        business_db.execute(
            "UPDATE continuous_state SET last_build_at = ?, updated_at = ? WHERE mode = 'always_on'",
            (datetime.utcnow().isoformat(), datetime.utcnow().isoformat()),
        )
        return

    niche_opp = items[0]
    niche = niche_opp.get("niche") or niche_opp.get("title") or "general"

    # Cap check.
    cap = await portfolio_cap_available_safe()
    if cap <= 0:
        log.warning("continuous_portfolio_full_pausing")
        await agency_run_continuous(activate=False)
        return

    # Add a business entry.
    from plugins.portfolio.plugin import portfolio_add_business
    biz_name = niche_opp.get("title", "Untitled Business")[:80]
    add = await portfolio_add_business(name=biz_name, niche=niche, language="ar", country="JO",
                                        currency="JOD", city="Amman",
                                        monetization=niche_opp.get("monetization", "service"))
    if not add.get("ok"):
        log.warning("continuous_add_business_failed", error=add.get("error"))
        return

    # Build products.
    build = await agency_build_multi_product(
        niche=niche, product_count=products_per_business,
        language="ar", deploy_target=deploy_target, business_id=add["business_id"],
    )

    # Mark opportunity acted-on.
    business_db.execute(
        "UPDATE opportunities SET status = 'acted_on', reviewed_at = ?, action_taken = ? WHERE id = ?",
        (datetime.utcnow().isoformat(),
         f"Built {build.get('products_built', 0)} products",
         niche_opp.get("id")),
    )

    # Update state.
    business_db.execute(
        """UPDATE continuous_state
           SET last_build_at = ?, last_niche = ?,
               total_businesses_built = total_businesses_built + 1,
               next_build_at = ?,
               updated_at = ?""",
        (datetime.utcnow().isoformat(), niche,
         (datetime.utcnow() + timedelta(hours=settings.continuous_build_interval_hours)).isoformat(),
         datetime.utcnow().isoformat()),
    )
    log.info("continuous_business_built", niche=niche, business_id=add["business_id"])


async def portfolio_cap_available_safe() -> int:
    """Helper — returns remaining slots without going through tool executor."""
    from plugins.portfolio.plugin import portfolio_cap_available
    result = await portfolio_cap_available()
    return result.get("remaining", 0)


# --------------------------------------------------------------------
# Phase 12: mass lead gen (50+ per call, region-aware)
# --------------------------------------------------------------------

@tool(
    name="agency.mass_lead_gen",
    description="Find 50+ leads for a niche in a specific region (defaults to Amman, Jordan). Paginates through OpenStreetMap results. Optionally writes them as deals + sends cold emails.",
    parameters={
        "type": "object",
        "properties": {
            "niche": {"type": "string"},
            "location": {"type": "string", "default": "Amman, Jordan"},
            "target_count": {"type": "integer", "default": 50},
            "client_id": {"type": "integer", "default": 0},
            "auto_email": {"type": "boolean", "default": False, "description": "If True + ALLOW_AUTONOMOUS_BUSINESS, send a cold email to every lead with an email address."},
        },
        "required": ["niche"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="agency",
)
async def agency_mass_lead_gen(
    niche: str, location: str = "Amman, Jordan", target_count: int = 50,
    client_id: int = 0, auto_email: bool = False,
) -> Dict[str, Any]:
    from plugins.sales.plugin import sales_find_leads, sales_add_contact
    from backend.config import settings as cfg

    target_count = max(1, min(500, target_count))
    # Walk neighborhoods / nearby cities to find enough leads.
    neighborhoods = [
        location,                          # exact
        "Zarqa, Jordan", "Irbid, Jordan", "Aqaba, Jordan", "Salt, Jordan",
        "Madaba, Jordan", "Karak, Jordan", "Jerash, Jordan", "Ajloun, Jordan",
        "Mafraq, Jordan", "Tafilah, Jordan",
    ]
    found: List[Dict[str, Any]] = []
    seen_names = set()

    for loc in neighborhoods:
        if len(found) >= target_count:
            break
        remaining = target_count - len(found)
        batch_size = min(remaining, 60)
        try:
            res = await sales_find_leads(niche=niche, location=loc, limit=batch_size)
        except Exception as e:
            continue
        if not res.get("ok"):
            continue
        for lead in res.get("leads", []):
            nm = lead.get("name")
            if not nm or nm in seen_names:
                continue
            seen_names.add(nm)
            found.append({**lead, "search_location": loc})
            if len(found) >= target_count:
                break

    # Persist as contacts + deals when a client_id is provided.
    persisted = 0
    emailed = 0
    if client_id:
        from plugins.sales.plugin import sales_create_deal
        for lead in found:
            try:
                contact_resp = await sales_add_contact(
                    client_id=client_id, name=lead.get("name", "?"),
                    email=lead.get("email") or "", phone=lead.get("phone") or "",
                )
                await sales_create_deal(
                    client_id=client_id, title=f"Lead: {lead.get('name','?')}",
                    value=0, stage="lead", probability=10,
                )
                persisted += 1
            except Exception:
                pass

    # Auto-email if requested + autonomous mode is on + email creds exist.
    if auto_email and cfg.allow_autonomous_business:
        from plugins.marketing.plugin import marketing_post
        from plugins.sales.plugin import sales_write_cold_email
        for lead in found:
            email = lead.get("email")
            if not email:
                continue
            try:
                cold = await sales_write_cold_email(
                    prospect_name=lead.get("name", "Sir/Madam"),
                    prospect_company=lead.get("name", ""),
                    service_offered=niche,
                )
                if cold.get("ok"):
                    send = await marketing_post(
                        platform="email", content=cold["body"],
                        title=cold["subject"], to=email,
                    )
                    if send.get("ok"):
                        emailed += 1
            except Exception:
                pass

    business_db.audit("mass_lead_gen", "agency", target=niche,
                      details={"found": len(found), "persisted": persisted, "emailed": emailed,
                               "location": location})

    return {
        "ok": True,
        "niche": niche,
        "location": location,
        "target_count": target_count,
        "found": len(found),
        "persisted_to_crm": persisted,
        "auto_emailed": emailed,
        "leads": found,
    }


# --------------------------------------------------------------------
# Phase 12: portfolio-wide status report
# --------------------------------------------------------------------

@tool(
    name="agency.portfolio_status",
    description="Roll up portfolio-wide KPIs: how many businesses live, total monthly revenue, top 5 niches, leads in pipeline.",
    parameters={"type": "object"},
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="agency",
)
async def agency_portfolio_status() -> Dict[str, Any]:
    from plugins.portfolio.plugin import portfolio_dashboard
    dash = await portfolio_dashboard(days=30)
    return dash
