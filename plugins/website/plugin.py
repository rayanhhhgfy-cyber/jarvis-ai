# ====================================================================
# JARVIS OMEGA - Website Plugin (Phase 11)
# ====================================================================
"""
Generate, preview, and deploy marketing websites — all free.

  website.generate_landing_page  - one-shot HTML + Tailwind via CDN
  website.deploy_github_pages    - push to a gh-pages branch (needs git + GH PAT)
  website.deploy_vercel          - drop a project folder to Vercel (needs vercel_token)
  website.deploy_netlify         - drag-drop deploy to Netlify (needs netlify_token)
  website.seo_audit              - basic on-page SEO check
  website.generate_sitemap       - XML sitemap from a URL list
  website.generate_robots        - robots.txt
"""

from __future__ import annotations

import asyncio
import base64
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from backend.tools import tool, RiskTier


# --------------------------------------------------------------------
# Landing-page generator
# --------------------------------------------------------------------

_LANDING_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{description}">
<script src="https://cdn.tailwindcss.com"></script>
{extra_head}
</head>
<body class="bg-gray-50 text-gray-900">
{body_html}
</body>
</html>"""


@tool(
    name="website.generate_landing_page",
    description="Generate a complete, mobile-responsive landing page in HTML + Tailwind (CDN). Phase 12: supports Arabic + RTL + multi-currency.",
    parameters={
        "type": "object",
        "properties": {
            "product_name": {"type": "string"},
            "tagline": {"type": "string"},
            "description": {"type": "string", "default": ""},
            "features": {"type": "array", "items": {"type": "string"}, "default": []},
            "cta_text": {"type": "string", "default": "Get Started"},
            "cta_url": {"type": "string", "default": "#"},
            "testimonials": {"type": "array", "items": {"type": "string"}, "default": []},
            "pricing": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "price": {"type": "string"},
                        "features": {"type": "array", "items": {"type": "string"}}
                    },
                },
                "default": [],
            },
            "language": {"type": "string", "default": "en", "enum": ["ar", "en"]},
            "rtl": {"type": "boolean", "default": False},
            "output_dir": {"type": "string", "default": "./storage/website"},
        },
        "required": ["product_name", "tagline"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="website",
)
async def website_generate_landing_page(
    product_name: str, tagline: str, description: str = "",
    features: Optional[List[str]] = None, cta_text: str = "Get Started",
    cta_url: str = "#", testimonials: Optional[List[str]] = None,
    pricing: Optional[List[Dict[str, Any]]] = None,
    language: str = "en", rtl: bool = False,
    output_dir: str = "./storage/website",
) -> Dict[str, Any]:
    features = features or []
    testimonials = testimonials or []
    pricing = pricing or []

    features_html = "".join(
        f'<div class="bg-white p-6 rounded-lg shadow"><h3 class="font-semibold text-lg mb-2">{f}</h3></div>'
        for f in features
    )
    testimonials_html = "".join(
        f'<blockquote class="bg-white p-6 rounded-lg shadow italic">"{t}"</blockquote>'
        for t in testimonials
    )
    pricing_html = ""
    if pricing:
        cards = []
        for p in pricing:
            feats = "".join(f"<li>{x}</li>" for x in p.get("features", []))
            cards.append(
                f'<div class="bg-white p-6 rounded-lg shadow text-center">'
                f'<h3 class="font-semibold text-xl mb-2">{p.get("name","")}</h3>'
                f'<div class="text-3xl font-bold mb-4">{p.get("price","")}</div>'
                f'<ul class="text-left list-disc list-inside mb-4">{feats}</ul>'
                f'<a href="{cta_url}" class="bg-indigo-600 text-white px-4 py-2 rounded inline-block">{cta_text}</a>'
                f'</div>'
            )
        pricing_html = (
            '<section class="py-16"><div class="max-w-6xl mx-auto px-4">'
            '<h2 class="text-3xl font-bold mb-8 text-center">Pricing</h2>'
            f'<div class="grid md:grid-cols-{min(4, len(cards))} gap-6">{"".join(cards)}</div>'
            '</div></section>'
        )

    html_dir = 'rtl' if rtl else 'ltr'
    html_lang = language
    body = f"""
<!-- Hero -->
<section class="bg-gradient-to-br from-indigo-600 to-purple-700 text-white py-20">
  <div class="max-w-4xl mx-auto px-4 text-center">
    <h1 class="text-5xl font-extrabold mb-4">{product_name}</h1>
    <p class="text-2xl mb-8">{tagline}</p>
    <a href="{cta_url}" class="bg-white text-indigo-700 px-8 py-3 rounded-full font-semibold hover:bg-gray-100">{cta_text}</a>
  </div>
</section>

{'' if not description else f'<section class="py-16"><div class="max-w-3xl mx-auto px-4 prose prose-lg"><p>{description}</p></div></section>'}

{'' if not features_html else f'<section class="py-16 bg-gray-100"><div class="max-w-6xl mx-auto px-4"><h2 class="text-3xl font-bold mb-8 text-center">Features</h2><div class="grid md:grid-cols-3 gap-6">{features_html}</div></div></section>'}

{pricing_html}

{'' if not testimonials_html else f'<section class="py-16"><div class="max-w-4xl mx-auto px-4"><h2 class="text-3xl font-bold mb-8 text-center">What People Say</h2><div class="grid gap-6">{testimonials_html}</div></div></section>'}

<footer class="bg-gray-900 text-gray-400 py-8 text-center">
  <div class="max-w-6xl mx-auto px-4">
    <p>&copy; {datetime.utcnow().year} {product_name}. All rights reserved.</p>
    <p class="mt-2 text-sm">Built and deployed by JARVIS OMEGA.</p>
  </div>
</footer>
"""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    extra_head = ""
    if language == "ar" or rtl:
        extra_head = (
            '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Tajawal:wght@400;700&display=swap">'
            '<style>body{font-family:"Tajawal",system-ui,Arial,sans-serif;direction:rtl}</style>'
        )
    html = _LANDING_TEMPLATE.format(
        title=f"{product_name} - {tagline}",
        description=description or tagline,
        body_html=body,
        extra_head=extra_head,
    )
    # Override <html> tag for RTL.
    if rtl:
        import re
        html = re.sub(r"<html(?![^>]*\bdir=)[^>]*>", '<html dir="rtl" lang="ar">', html, count=1)
    elif language == "ar":
        import re
        html = re.sub(r"<html(?![^>]*\blang=)[^>]*>", '<html lang="ar">', html, count=1)

    index = out / "index.html"
    index.write_text(html, encoding="utf-8")
    return {"ok": True, "path": str(index), "size_bytes": len(html), "language": language, "rtl": rtl}


# --------------------------------------------------------------------
# GitHub Pages deploy
# --------------------------------------------------------------------

@tool(
    name="website.deploy_github_pages",
    description="Deploy a folder to GitHub Pages. Needs gh_repo (owner/name), a github_pat with repo scope, and git on PATH.",
    parameters={
        "type": "object",
        "properties": {
            "site_dir": {"type": "string", "description": "Folder containing index.html to publish."},
            "gh_repo": {"type": "string", "description": "owner/repo-name (must already exist)."},
            "branch": {"type": "string", "default": "gh-pages"},
            "commit_message": {"type": "string", "default": "Deploy from JARVIS"},
            "author_name": {"type": "string", "default": "JARVIS OMEGA"},
            "author_email": {"type": "string", "default": "jarvis@local"},
        },
        "required": ["site_dir", "gh_repo"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="website",
)
async def website_deploy_github_pages(
    site_dir: str, gh_repo: str, branch: str = "gh-pages",
    commit_message: str = "Deploy from JARVIS",
    author_name: str = "JARVIS OMEGA", author_email: str = "jarvis@local",
) -> Dict[str, Any]:
    try:
        from backend.services.credentials_vault import credentials_vault
        pat = credentials_vault.get("github_pat")
    except Exception:
        pat = None
    if not pat:
        return {"ok": False, "error": "github_pat not in vault"}

    src = Path(site_dir)
    if not src.is_dir():
        return {"ok": False, "error": f"site_dir does not exist: {site_dir}"}

    repo_url = f"https://x-access-token:{pat}@github.com/{gh_repo}.git"

    async def _git(args: List[str], cwd: Optional[str] = None):
        proc = await asyncio.create_subprocess_exec(
            "git", *args,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()
        return proc.returncode or 0, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")

    # Work in a temp clone.
    with tempfile.TemporaryDirectory() as tmpdir:
        rc, out, err = await _git(["clone", "--no-checkout", repo_url, "."], cwd=tmpdir)
        if rc != 0:
            return {"ok": False, "error": f"git clone failed: {err}"}

        # Try to checkout the branch (or create orphan).
        rc, out, err = await _git(["checkout", branch], cwd=tmpdir)
        if rc != 0:
            rc, out, err = await _git(["checkout", "--orphan", branch], cwd=tmpdir)
            if rc != 0:
                return {"ok": False, "error": f"git checkout failed: {err}"}

        # Clear existing tracked files and copy in the new content.
        try:
            for p in Path(tmpdir).glob("*"):
                if p.name == ".git":
                    continue
                if p.is_dir():
                    shutil.rmtree(p)
                else:
                    p.unlink()
        except Exception:
            pass
        for item in src.iterdir():
            if item.name.startswith(".git"):
                continue
            if item.is_dir():
                shutil.copytree(item, Path(tmpdir) / item.name)
            else:
                shutil.copy2(item, Path(tmpdir) / item.name)

        # Configure author + commit + push.
        await _git(["config", "user.name", author_name], cwd=tmpdir)
        await _git(["config", "user.email", author_email], cwd=tmpdir)
        await _git(["add", "-A"], cwd=tmpdir)
        rc, out, err = await _git(["commit", "-m", commit_message], cwd=tmpdir)
        # (commit failing because nothing changed is fine)
        rc, out, err = await _git(["push", "-f", "origin", branch], cwd=tmpdir)
        if rc != 0:
            return {"ok": False, "error": f"git push failed: {err}"}

    # The published URL (works for most repos once Pages is enabled on this branch).
    owner, name = gh_repo.split("/", 1)
    return {
        "ok": True,
        "url": f"https://{owner}.github.io/{name}/",
        "branch": branch,
        "note": "Make sure GitHub Pages is enabled in repo Settings → Pages → Source: this branch.",
    }


# --------------------------------------------------------------------
# Vercel deploy
# --------------------------------------------------------------------

@tool(
    name="website.deploy_vercel",
    description="Deploy a static site to Vercel. Needs vercel_token in the vault. Free tier covers ~100 deploys/day.",
    parameters={
        "type": "object",
        "properties": {
            "site_dir": {"type": "string"},
            "project_name": {"type": "string", "description": "Lowercase, hyphen-separated."},
        },
        "required": ["site_dir", "project_name"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="website",
)
async def website_deploy_vercel(site_dir: str, project_name: str) -> Dict[str, Any]:
    try:
        from backend.services.credentials_vault import credentials_vault
        token = credentials_vault.get("vercel_token")
    except Exception:
        token = None
    if not token:
        return {"ok": False, "error": "vercel_token not in vault"}

    src = Path(site_dir)
    if not src.is_dir():
        return {"ok": False, "error": f"site_dir does not exist: {site_dir}"}

    # Step 1: zip the project so we can ship it as a single payload.
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tf:
        with zipfile.ZipFile(tf, "w", zipfile.ZIP_DEFLATED) as zf:
            for fp in src.rglob("*"):
                if fp.is_file():
                    zf.write(fp, arcname=str(fp.relative_to(src)))
        zip_path = tf.name
    try:
        with open(zip_path, "rb") as fh:
            zip_b64 = base64.b64encode(fh.read()).decode("ascii")
    finally:
        Path(zip_path).unlink(missing_ok=True)

    payload = {
        "name": project_name,
        "files": [{"file": "deploy.zip", "data": zip_b64, "encoding": "base64"}],
        "projectSettings": {"framework": None},
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post("https://api.vercel.com/v13/deployments", json=payload, headers=headers)
        if resp.status_code >= 400:
            return {"ok": False, "status": resp.status_code, "error": resp.text[:400]}
        data = resp.json()
        return {
            "ok": True,
            "deployment_id": data.get("id"),
            "url": data.get("url"),
            "alias": data.get("alias", []),
            "inspector_url": data.get("inspectorUrl"),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


# --------------------------------------------------------------------
# Netlify deploy (drag-drop API)
# --------------------------------------------------------------------

@tool(
    name="website.deploy_netlify",
    description="Deploy a folder to Netlify via the free drag-drop API. Needs netlify_token in the vault.",
    parameters={
        "type": "object",
        "properties": {
            "site_dir": {"type": "string"},
            "site_id": {"type": "string", "description": "Existing Netlify site ID. Empty = create new."},
        },
        "required": ["site_dir"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="website",
)
async def website_deploy_netlify(site_dir: str, site_id: str = "") -> Dict[str, Any]:
    try:
        from backend.services.credentials_vault import credentials_vault
        token = credentials_vault.get("netlify_token")
    except Exception:
        token = None
    if not token:
        return {"ok": False, "error": "netlify_token not in vault"}

    src = Path(site_dir)
    if not src.is_dir():
        return {"ok": False, "error": f"site_dir does not exist: {site_dir}"}

    # Step 1: zip
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tf:
        with zipfile.ZipFile(tf, "w", zipfile.ZIP_DEFLATED) as zf:
            for fp in src.rglob("*"):
                if fp.is_file():
                    zf.write(fp, arcname=str(fp.relative_to(src)))
        zip_path = tf.name
    try:
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/zip",
        }
        # Netlify's drag-drop deploy endpoint takes a raw zip body.
        url = f"https://api.netlify.com/api/v1/sites/{site_id}/deploys" if site_id else "https://api.netlify.com/api/v1/deploys"
        with open(zip_path, "rb") as fh:
            data = fh.read()
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(url, headers=headers, content=data)
        if resp.status_code >= 400:
            return {"ok": False, "status": resp.status_code, "error": resp.text[:400]}
        result = resp.json()
        return {
            "ok": True,
            "deploy_id": result.get("id"),
            "url": result.get("ssl_url") or result.get("url"),
            "site_id": result.get("site_id"),
        }
    finally:
        Path(zip_path).unlink(missing_ok=True)


# --------------------------------------------------------------------
# SEO audit + sitemap + robots
# --------------------------------------------------------------------

@tool(
    name="website.seo_audit",
    description="Quick on-page SEO audit on a URL. Checks <title>, <meta description>, <h1>, alt-text presence.",
    parameters={
        "type": "object",
        "properties": {"url": {"type": "string"}},
        "required": ["url"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="website",
)
async def website_seo_audit(url: str) -> Dict[str, Any]:
    import re as _re
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "JARVIS-SEO-Auditor/1.0"})
        if resp.status_code >= 400:
            return {"ok": False, "status": resp.status_code, "error": resp.text[:300]}
        html = resp.text
    except Exception as e:
        return {"ok": False, "error": str(e)}

    title_m = _re.search(r"<title[^>]*>([^<]+)</title>", html, _re.IGNORECASE)
    desc_m = _re.search(r'<meta\s+name=["\']description["\']\s+content=["\']([^"\']+)["\']', html, _re.IGNORECASE)
    h1_count = len(_re.findall(r"<h1[^>]*>", html, _re.IGNORECASE))
    img_count = len(_re.findall(r"<img[^>]+>", html, _re.IGNORECASE))
    img_alt_count = len(_re.findall(r"<img[^>]+alt=['\"]", html, _re.IGNORECASE))
    word_count = len(_re.sub(r"<[^>]+>", " ", html).split())

    findings: List[str] = []
    if not title_m:
        findings.append("Missing <title> tag.")
    elif len(title_m.group(1)) < 30:
        findings.append(f"Title is short ({len(title_m.group(1))} chars); aim for 50-60.")
    if not desc_m:
        findings.append("Missing meta description.")
    elif not (120 <= len(desc_m.group(1)) <= 160):
        findings.append(f"Meta description length {len(desc_m.group(1))}; aim for 120-160.")
    if h1_count == 0:
        findings.append("Missing H1.")
    elif h1_count > 1:
        findings.append(f"Multiple H1s ({h1_count}); use only one.")
    if img_count > 0 and img_alt_count < img_count:
        findings.append(f"{img_count - img_alt_count} images missing alt text.")
    if word_count < 300:
        findings.append(f"Low word count ({word_count}); aim for 300+.")

    return {
        "ok": True,
        "url": url,
        "title": title_m.group(1) if title_m else None,
        "meta_description": desc_m.group(1) if desc_m else None,
        "h1_count": h1_count,
        "image_count": img_count,
        "images_with_alt": img_alt_count,
        "word_count": word_count,
        "findings": findings,
        "score": max(0, 100 - 10 * len(findings)),
    }


@tool(
    name="website.generate_sitemap",
    description="Generate an XML sitemap from a list of URLs. Saves to sitemap.xml.",
    parameters={
        "type": "object",
        "properties": {
            "urls": {"type": "array", "items": {"type": "string"}},
            "output_path": {"type": "string", "default": "./storage/website/sitemap.xml"},
        },
        "required": ["urls"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="website",
)
async def website_generate_sitemap(urls: List[str], output_path: str = "./storage/website/sitemap.xml") -> Dict[str, Any]:
    today = datetime.utcnow().date().isoformat()
    urls_xml = "".join(
        f"<url><loc>{u}</loc><lastmod>{today}</lastmod></url>"
        for u in urls
    )
    xml = f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls_xml}</urlset>'
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(xml, encoding="utf-8")
    return {"ok": True, "path": output_path, "urls": len(urls)}


@tool(
    name="website.generate_robots",
    description="Generate a robots.txt file.",
    parameters={
        "type": "object",
        "properties": {
            "sitemap_url": {"type": "string"},
            "disallow_paths": {"type": "array", "items": {"type": "string"}, "default": []},
            "output_path": {"type": "string", "default": "./storage/website/robots.txt"},
        },
        "required": ["sitemap_url"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="website",
)
async def website_generate_robots(
    sitemap_url: str, disallow_paths: Optional[List[str]] = None,
    output_path: str = "./storage/website/robots.txt",
) -> Dict[str, Any]:
    disallow_paths = disallow_paths or []
    lines = ["User-agent: *"]
    for p in disallow_paths:
        lines.append(f"Disallow: {p}")
    lines.append("")
    lines.append(f"Sitemap: {sitemap_url}")
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text("\n".join(lines), encoding="utf-8")
    return {"ok": True, "path": output_path}


PLUGIN_NAME = "website"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Landing-page generator + free deploys (GitHub Pages, Vercel, Netlify) + SEO audit."
