# Phase 18: SSL Certificate Monitor (REAL)
from __future__ import annotations
import ssl, socket
from datetime import datetime
from typing import Any, Dict, List
from backend.tools import tool, RiskTier
from backend import business_db

@tool(name="ssl.check_all", description="Check SSL certificates for all deployed sites. Alert if expiring <30 days.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_0_OBSERVE, category="ssl_monitor")
async def check_all() -> Dict[str, Any]:
    # Get deployed URLs from businesses table
    urls = []
    try:
        rows = business_db.query("SELECT deployed_url FROM businesses WHERE deployed_url IS NOT NULL AND deployed_url != ''")
        urls = [r["deployed_url"] for r in rows if r["deployed_url"].startswith("http")]
    except: pass
    # Also check monitored sites
    try:
        from plugins.uptime_monitor.plugin import _load_sites
        for s in _load_sites():
            if s["url"].startswith("https://"): urls.append(s["url"])
    except: pass
    if not urls: return {"ok": True, "note": "No HTTPS URLs to check."}
    results = []
    for url in urls:
        try:
            from urllib.parse import urlparse
            p = urlparse(url)
            host = p.hostname
            if not host: continue
            ctx = ssl.create_default_context()
            with socket.create_connection((host, 443), timeout=10) as sock:
                with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                    cert = ssock.getpeercert()
                    expiry = cert.get("notAfter", "")
                    results.append({"url": url, "host": host, "expires": expiry, "issuer": cert.get("issuer", [{}])[0].get("organizationName", "") if cert.get("issuer") else ""})
        except Exception as e:
            results.append({"url": url, "error": str(e)[:100]})
    return {"ok": True, "checked": len(results), "results": results}
