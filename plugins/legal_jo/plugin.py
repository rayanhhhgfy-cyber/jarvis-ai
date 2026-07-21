# ====================================================================
# JARVIS OMEGA - Legal & Government Plugin - Jordan (Phase 13)
# ====================================================================
"""
Jordan-specific tax, customs, and legal document generators.

  jo_tax.calc_income_tax      - Jordan 2024 income tax brackets
  jo_tax.calc_sales_tax       - 16% general VAT + special rates
  jo_tax.calc_social_security - SSC contributions 7.5% / 14.25%
  jo_customs.duty_estimator   - HS code → duty rate
  jo_business.name_check      - Companies Registry search (public)
  legal.nda_generator         - LLM NDA (Arabic + English)
  legal.tos_generator         - Terms of Service
  legal.privacy_policy_generator
  legal.contract_analyzer     - LLM red-flags risky clauses
  legal.trademark_search_wipo - WIPO Global Brand Database
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import httpx

from backend.tools import tool, RiskTier


# --------------------------------------------------------------------
# Jordan income tax 2024 (annual, JOD)
# --------------------------------------------------------------------
# Source: Jordan Income Tax Law (non-business individual brackets simplified).
# Business tax rates differ; the brackets below are for non-business income.
_JO_INCOME_BRACKETS_2024 = [
    # (up_to_jod, rate_pct)
    (5000,    0.0),   # first 5k exempt
    (10000,   0.05),  # 5001-10000 @ 5%
    (15000,   0.10),  # 10001-15000 @ 10%
    (20000,   0.15),  # 15001-20000 @ 15%
    (1000000, 0.20),  # 20001-1M @ 20%
    (float("inf"), 0.25),  # above 1M @ 25%
]


@tool(
    name="jo_tax.calc_income_tax",
    description="Calculate Jordanian personal income tax (2024 brackets). Returns JOD due per bracket.",
    parameters={
        "type": "object",
        "properties": {
            "annual_income_jod": {"type": "number"},
            "deductions_jod": {"type": "number", "default": 0, "description": "Allowable deductions."},
        },
        "required": ["annual_income_jod"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="legal_jo",
)
async def jo_tax_calc_income_tax(annual_income_jod: float, deductions_jod: float = 0) -> Dict[str, Any]:
    taxable = max(0, annual_income_jod - deductions_jod)
    breakdown: List[Dict[str, Any]] = []
    remaining = taxable
    prev_cap = 0
    total_tax = 0.0
    for cap, rate in _JO_INCOME_BRACKETS_2024:
        if remaining <= 0:
            break
        bracket_width = cap - prev_cap if cap != float("inf") else remaining
        taxed_in_bracket = min(remaining, bracket_width)
        bracket_tax = taxed_in_bracket * rate
        breakdown.append({
            "from_jod": prev_cap,
            "to_jod": prev_cap + taxed_in_bracket,
            "rate_pct": rate * 100,
            "amount_in_bracket_jod": round(taxed_in_bracket, 2),
            "tax_jod": round(bracket_tax, 2),
        })
        total_tax += bracket_tax
        remaining -= taxed_in_bracket
        prev_cap = cap
        if cap == float("inf"):
            break
    effective_rate = (total_tax / annual_income_jod * 100) if annual_income_jod > 0 else 0
    return {
        "ok": True,
        "annual_income_jod": round(annual_income_jod, 2),
        "deductions_jod": round(deductions_jod, 2),
        "taxable_income_jod": round(taxable, 2),
        "total_tax_jod": round(total_tax, 2),
        "effective_rate_pct": round(effective_rate, 2),
        "bracket_breakdown": breakdown,
        "year": 2024,
        "currency": "JOD",
        "note": "Personal income tax brackets. Business tax rates differ.",
    }


# --------------------------------------------------------------------
# Sales tax (VAT)
# --------------------------------------------------------------------

_JO_VAT_GENERAL = 0.16
_JO_VAT_SPECIAL = {
    # Special rates for essential goods (lower than 16%).
    "bread": 0.0, "flour": 0.0, "medicines": 0.0, "printing_quran": 0.0,
    "education_services": 0.0, "medical_services": 0.0, "financial_services": 0.0,
    "insurance": 0.0, "rent_residential": 0.0, "international_transport": 0.0,
    "tea": 0.04, "coffee": 0.04, "sugar": 0.04, "rice": 0.04,
    "cooking_oil": 0.04, "infant_formula": 0.04, "electricity_residential": 0.08,
    "water_residential": 0.05,
}


@tool(
    name="jo_tax.calc_sales_tax",
    description="Calculate Jordanian sales tax (VAT). 16% general, special rates for essentials.",
    parameters={
        "type": "object",
        "properties": {
            "amount_jod": {"type": "number"},
            "category": {"type": "string", "default": "general", "description": "general | bread | tea | electricity_residential | etc."},
        },
        "required": ["amount_jod"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="legal_jo",
)
async def jo_tax_calc_sales_tax(amount_jod: float, category: str = "general") -> Dict[str, Any]:
    rate = _JO_VAT_SPECIAL.get(category.lower(), _JO_VAT_GENERAL)
    tax = amount_jod * rate
    return {
        "ok": True,
        "amount_jod": round(amount_jod, 2),
        "category": category,
        "rate_pct": rate * 100,
        "tax_jod": round(tax, 2),
        "total_with_tax_jod": round(amount_jod + tax, 2),
    }


# --------------------------------------------------------------------
# Social Security
# --------------------------------------------------------------------

@tool(
    name="jo_tax.calc_social_security",
    description="Calculate Jordanian Social Security Corporation contributions. Employee 7.5%, Employer 14.25% (2024).",
    parameters={
        "type": "object",
        "properties": {
            "monthly_salary_jod": {"type": "number"},
        },
        "required": ["monthly_salary_jod"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="legal_jo",
)
async def jo_tax_calc_social_security(monthly_salary_jod: float) -> Dict[str, Any]:
    employee_rate = 0.075
    employer_rate = 0.1425
    return {
        "ok": True,
        "monthly_salary_jod": round(monthly_salary_jod, 2),
        "employee_contribution_jod": round(monthly_salary_jod * employee_rate, 2),
        "employer_contribution_jod": round(monthly_salary_jod * employer_rate, 2),
        "total_monthly_jod": round(monthly_salary_jod * (employee_rate + employer_rate), 2),
        "annual_total_jod": round(monthly_salary_jod * (employee_rate + employer_rate) * 12, 2),
        "employee_rate_pct": employee_rate * 100,
        "employer_rate_pct": employer_rate * 100,
    }


# --------------------------------------------------------------------
# Customs duty estimator
# --------------------------------------------------------------------

# Simplified HS chapter → JO duty rate. Real schedule is per-8-digit HS code.
_JO_CUSTOMS_BY_CHAPTER = {
    "01-05": (0.05, "Live animals & products"),
    "06-14": (0.10, "Plant products"),
    "15": (0.10, "Fats and oils"),
    "16-24": (0.20, "Prepared food, beverages, tobacco"),
    "25-27": (0.05, "Mineral products, fuel"),
    "28-38": (0.05, "Chemicals"),
    "39-40": (0.20, "Plastics, rubber"),
    "41-43": (0.20, "Leather"),
    "44-49": (0.20, "Wood, paper"),
    "50-63": (0.20, "Textiles, clothing"),
    "64-67": (0.20, "Footwear, headgear"),
    "68-71": (0.20, "Stone, glass, jewelry"),
    "72-83": (0.05, "Metals"),
    "84-85": (0.10, "Machinery, electronics"),
    "86-89": (0.10, "Vehicles"),
    "90": (0.05, "Optical, medical instruments"),
    "91-92": (0.20, "Clocks, musical instruments"),
    "93": (0.20, "Arms"),
    "94-96": (0.20, "Furniture, toys, misc"),
    "97-99": (0.0, "Works of art, special transactions"),
}


@tool(
    name="jo_customs.duty_estimator",
    description="Estimate Jordanian import duty. Provide HS chapter (2-digit) or category keyword.",
    parameters={
        "type": "object",
        "properties": {
            "hs_chapter": {"type": "string", "default": "", "description": "2-digit HS chapter (01-99)."},
            "category_keyword": {"type": "string", "default": "", "description": "e.g. 'electronics', 'clothing'."},
            "goods_value_jod": {"type": "number", "default": 0, "description": "CIF value in JOD."},
        },
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="legal_jo",
)
async def jo_customs_duty_estimator(
    hs_chapter: str = "", category_keyword: str = "", goods_value_jod: float = 0,
) -> Dict[str, Any]:
    rate = None
    description = None
    # Lookup by chapter.
    if hs_chapter:
        try:
            ch = int(hs_chapter)
            for rng, (r, desc) in _JO_CUSTOMS_BY_CHAPTER.items():
                lo, hi = rng.split("-")
                if int(lo) <= ch <= int(hi):
                    rate = r
                    description = desc
                    break
        except Exception:
            pass
    # Lookup by keyword (very simplified).
    if rate is None and category_keyword:
        kw = category_keyword.lower()
        if any(w in kw for w in ["cloth", "apparel", "shirt", "dress", "fabric", "textile"]):
            rate, description = _JO_CUSTOMS_BY_CHAPTER["50-63"]
        elif any(w in kw for w in ["phone", "laptop", "computer", "electronic", "machine", "appliance"]):
            rate, description = _JO_CUSTOMS_BY_CHAPTER["84-85"]
        elif any(w in kw for w in ["car", "vehicle", "truck", "auto", "motorcycle"]):
            rate, description = _JO_CUSTOMS_BY_CHAPTER["86-89"]
        elif any(w in kw for w in ["food", "drink", "beverage", "snack"]):
            rate, description = _JO_CUSTOMS_BY_CHAPTER["16-24"]
        elif any(w in kw for w in ["toy", "furniture", "game"]):
            rate, description = _JO_CUSTOMS_BY_CHAPTER["94-96"]
    if rate is None:
        return {"ok": False, "error": "could not resolve HS chapter or category; provide hs_chapter 01-99"}

    duty = goods_value_jod * rate
    # Add general 16% sales tax on imported goods (separate from customs duty).
    sales_tax = (goods_value_jod + duty) * _JO_VAT_GENERAL
    return {
        "ok": True,
        "hs_chapter": hs_chapter or "(by keyword)",
        "category": description,
        "customs_duty_rate_pct": rate * 100,
        "goods_value_jod": round(goods_value_jod, 2),
        "estimated_customs_duty_jod": round(duty, 2),
        "estimated_sales_tax_jod": round(sales_tax, 2),
        "estimated_total_jod": round(goods_value_jod + duty + sales_tax, 2),
        "disclaimer": "Estimate only. Confirm with your customs broker for the actual 8-digit HS code.",
    }


# --------------------------------------------------------------------
# Business name check
# --------------------------------------------------------------------

@tool(
    name="jo_business.name_check",
    description="Check if a business name is available in Jordan. Note: this uses search engines; for official check use the Companies Comptroller website.",
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string"},
        },
        "required": ["name"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="legal_jo",
)
async def jo_business_name_check(name: str) -> Dict[str, Any]:
    # Use a search engine to check public references.
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                "https://www.google.com/search",
                params={"q": f'"{name}" Jordan site:jo'},
                headers={"User-Agent": "Mozilla/5.0"},
            )
        # Rough heuristic: if Google finds many results, name likely taken.
        text = resp.text.lower()
        result_count_estimate = resp.text.count(name.lower())
        verdict = "likely taken" if result_count_estimate > 10 else "likely available"
        return {
            "ok": True,
            "name": name,
            "search_mentions": result_count_estimate,
            "verdict": verdict,
            "official_check_url": "https://www.ctc.gov.jo",
            "note": "This is a heuristic based on search results. For official status check the Companies Comptroller website.",
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


# --------------------------------------------------------------------
# Legal document generators (LLM-powered)
# --------------------------------------------------------------------

async def _llm_generate(system_prompt: str, user_msg: str) -> str:
    from backend.services.llm_service import llm_service
    return await llm_service.get_response(
        user_message=user_msg,
        system_instructions=system_prompt,
        inject_memory=False,
    )


@tool(
    name="legal.nda_generator",
    description="Generate a Non-Disclosure Agreement. Bilingual Arabic + English by default.",
    parameters={
        "type": "object",
        "properties": {
            "discloser_name": {"type": "string"},
            "recipient_name": {"type": "string"},
            "purpose": {"type": "string"},
            "duration_months": {"type": "integer", "default": 24},
            "jurisdiction": {"type": "string", "default": "Hashemite Kingdom of Jordan"},
            "language": {"type": "string", "default": "both", "enum": ["ar", "en", "both"]},
        },
        "required": ["discloser_name", "recipient_name", "purpose"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="legal_jo",
)
async def legal_nda_generator(
    discloser_name: str, recipient_name: str, purpose: str,
    duration_months: int = 24, jurisdiction: str = "Hashemite Kingdom of Jordan",
    language: str = "both",
) -> Dict[str, Any]:
    sys_prompt = (
        f"You are a senior Jordanian corporate lawyer. Draft a mutual NDA in "
        f"{('Arabic and then English' if language == 'both' else 'Arabic' if language == 'ar' else 'English')}. "
        f"Use clear, formal legal language. Include: definition of confidential information, "
        "permitted uses, term, return/destruction obligations, remedies, jurisdiction clause. "
        "Output Markdown only — no preamble."
    )
    user_msg = (
        f"Disclosing Party: {discloser_name}\n"
        f"Receiving Party: {recipient_name}\n"
        f"Purpose: {purpose}\n"
        f"Duration: {duration_months} months\n"
        f"Jurisdiction: {jurisdiction}\n"
    )
    try:
        nda_text = await _llm_generate(sys_prompt, user_msg)
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {
        "ok": True,
        "nda_markdown": nda_text,
        "language": language,
        "disclaimer": "Generated draft. Have a licensed Jordanian lawyer review before signing.",
    }


@tool(
    name="legal.tos_generator",
    description="Generate a Terms of Service agreement for a website/app.",
    parameters={
        "type": "object",
        "properties": {
            "company_name": {"type": "string"},
            "service_description": {"type": "string"},
            "website_url": {"type": "string", "default": ""},
            "jurisdiction": {"type": "string", "default": "Hashemite Kingdom of Jordan"},
            "language": {"type": "string", "default": "both", "enum": ["ar", "en", "both"]},
        },
        "required": ["company_name", "service_description"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="legal_jo",
)
async def legal_tos_generator(
    company_name: str, service_description: str, website_url: str = "",
    jurisdiction: str = "Hashemite Kingdom of Jordan", language: str = "both",
) -> Dict[str, Any]:
    sys_prompt = (
        f"You are a senior technology lawyer. Draft Terms of Service in "
        f"{('Arabic and then English' if language == 'both' else 'Arabic' if language == 'ar' else 'English')}. "
        "Include: acceptance, account registration, user obligations, prohibited conduct, "
        "intellectual property, disclaimers, limitation of liability, termination, "
        "governing law, dispute resolution. Output Markdown only."
    )
    user_msg = (
        f"Company: {company_name}\nService: {service_description}\n"
        f"Website: {website_url or '(not specified)'}\nJurisdiction: {jurisdiction}\n"
    )
    try:
        return {"ok": True, "tos_markdown": await _llm_generate(sys_prompt, user_msg), "disclaimer": "Draft — have a lawyer review."}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="legal.privacy_policy_generator",
    description="Generate a Privacy Policy compliant with JO PDPL #24 of 2023 and GDPR.",
    parameters={
        "type": "object",
        "properties": {
            "company_name": {"type": "string"},
            "data_collected": {"type": "string", "description": "What user data the service collects."},
            "purpose": {"type": "string", "description": "Why data is collected."},
            "third_party_sharing": {"type": "string", "default": "None"},
            "contact_email": {"type": "string", "default": ""},
            "language": {"type": "string", "default": "both", "enum": ["ar", "en", "both"]},
        },
        "required": ["company_name", "data_collected", "purpose"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="legal_jo",
)
async def legal_privacy_policy_generator(
    company_name: str, data_collected: str, purpose: str,
    third_party_sharing: str = "None", contact_email: str = "",
    language: str = "both",
) -> Dict[str, Any]:
    sys_prompt = (
        f"You are a privacy lawyer. Draft a Privacy Policy compliant with the Jordan "
        f"Personal Data Protection Law No. 24 of 2023 and GDPR. Output in "
        f"{('Arabic and then English' if language == 'both' else 'Arabic' if language == 'ar' else 'English')}. "
        "Include: data collected, purpose, legal basis, retention, third-party sharing, "
        "user rights (access, correction, deletion, portability), contact for DPO. Markdown only."
    )
    user_msg = (
        f"Company: {company_name}\nData: {data_collected}\nPurpose: {purpose}\n"
        f"Third-party sharing: {third_party_sharing}\nContact: {contact_email or '(not specified)'}\n"
    )
    try:
        return {"ok": True, "policy_markdown": await _llm_generate(sys_prompt, user_msg), "disclaimer": "Draft — have a lawyer review."}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="legal.contract_analyzer",
    description="Red-flag risky clauses in a contract. Returns list of findings.",
    parameters={
        "type": "object",
        "properties": {
            "contract_text": {"type": "string"},
            "language": {"type": "string", "default": "ar", "enum": ["ar", "en"]},
        },
        "required": ["contract_text"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="legal_jo",
)
async def legal_contract_analyzer(contract_text: str, language: str = "ar") -> Dict[str, Any]:
    sys_prompt = (
        f"You are a Jordanian contract lawyer. Analyze this contract for risky clauses "
        f"in {'Arabic' if language == 'ar' else 'English'}. Output STRICT JSON: "
        "{\"findings\": [{\"severity\": \"high|medium|low\", \"clause_summary\": string, "
        "\"issue\": string, \"recommendation\": string}]}"
    )
    try:
        reply = await _llm_generate(sys_prompt, contract_text[:8000])
        # Salvage JSON.
        text = reply.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        parsed = json.loads(text)
        return {"ok": True, "findings": parsed.get("findings", []), "language": language}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# --------------------------------------------------------------------
# Trademark search (WIPO)
# --------------------------------------------------------------------

@tool(
    name="legal.trademark_search_wipo",
    description="Search the WIPO Global Brand Database for a trademark.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer", "default": 10},
        },
        "required": ["query"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="legal_jo",
)
async def legal_trademark_search_wipo(query: str, limit: int = 10) -> Dict[str, Any]:
    # WIPO Global Brand public search uses an HTML endpoint. We just open the search URL.
    base = "https://www3.wipo.int/branddb/en/"
    search_url = f"{base}quicksearch?q={query}"
    return {
        "ok": True,
        "query": query,
        "search_url": search_url,
        "note": "Open the URL in a browser — WIPO's API is HTML-only and not officially machine-readable.",
        "jo_trademark_search_url": "https://www.moi.gov.jo",
    }


PLUGIN_NAME = "legal_jo"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Jordan tax/customs calculators + Arabic/English legal document generators."
