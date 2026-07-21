# Phase 18: Quality Assurance Auditor (REAL)
from __future__ import annotations
import json, random
from datetime import datetime, timedelta
from typing import Any, Dict
from backend.tools import tool, RiskTier
from backend import business_db

@tool(name="qa.audit_content", description="Random audit of JARVIS's generated social posts for quality.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_0_OBSERVE, category="quality_auditor")
async def audit_content() -> Dict[str, Any]:
    posts = business_db.rows_to_dicts(business_db.query("SELECT id, platform, content FROM posts ORDER BY RANDOM() LIMIT 5"))
    if not posts: return {"ok": True, "note": "No posts to audit yet."}
    from backend.services.llm_service import llm_service
    findings = []
    for p in posts:
        try:
            reply = await llm_service.get_response(user_message=f"Post: {p['content'][:300]}", system_instructions='Score this content 0-100 for quality. Check: grammar, engagement, brand safety, factual accuracy. Output JSON: {"score":int,"issues":[string],"verdict":"pass|needs_edit|reject"}', inject_memory=False)
            text = reply.strip().lstrip("`").rstrip("`")
            if text.startswith("json"): text = text[4:]
            findings.append({"post_id": p["id"], "platform": p["platform"], **json.loads(text)})
        except: pass
    avg = sum(f.get("score",0) for f in findings) / len(findings) if findings else 0
    return {"ok": True, "audited": len(findings), "avg_score": round(avg,1), "findings": findings}

@tool(name="qa.audit_code", description="Random audit of Python files for common bugs.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_0_OBSERVE, category="quality_auditor")
async def audit_code() -> Dict[str, Any]:
    import ast
    from pathlib import Path
    issues = []
    for py in Path("plugins").rglob("*.py"):
        try:
            code = py.read_text(encoding="utf-8")
            tree = ast.parse(code)
            # Check for bare except
            for node in ast.walk(tree):
                if isinstance(node, ast.ExceptHandler) and node.type is None:
                    issues.append({"file": str(py), "line": node.lineno, "issue": "bare except (catches everything including KeyboardInterrupt)"})
                if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and node.value.value is ... :
                    pass  # Ellipsis is fine in stubs
        except SyntaxError as e:
            issues.append({"file": str(py), "line": e.lineno, "issue": f"syntax error: {e.msg}"})
    return {"ok": True, "files_scanned": len(list(Path("plugins").rglob("*.py"))), "issues_found": len(issues), "issues": issues[:20]}
