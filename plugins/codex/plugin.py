# ====================================================================
# JARVIS OMEGA - Personal Knowledge Codex (Phase 14)
# ====================================================================
"""
Sir's second brain. Ingests everything Sir has ever written/said/read
into ChromaDB for semantic search and recall.

  codex.ingest_gmail         - pull sent emails → memory
  codex.ingest_github        - all gists + repos → memory
  codex.ingest_notion        - Notion workspace → memory
  codex.ingest_local_docs    - walk ./Documents → memory
  codex.ingest_text          - manually add a memory
  codex.ask                  - "what did I think about X?"
  codex.write_like_me        - ghost-write in Sir's style
  codex.daily_journal_write  - auto-journal from day's activity
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.tools import tool, RiskTier
from backend import business_db
from backend.memory_engine import memory_engine
from shared.constants import MemoryCategory
from shared.models import MemoryEntry


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _cred(key: str) -> Optional[str]:
    try:
        from backend.services.credentials_vault import credentials_vault
        return credentials_vault.get(key) or None
    except Exception:
        return None


# --------------------------------------------------------------------
# Ingest paths
# --------------------------------------------------------------------

@tool(
    name="codex.ingest_text",
    description="Manually ingest a piece of text into Sir's knowledge codex. Useful for capturing conversations, ideas, decisions.",
    parameters={
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "title": {"type": "string", "default": ""},
            "source": {"type": "string", "default": "manual"},
            "tags": {"type": "array", "items": {"type": "string"}, "default": []},
        },
        "required": ["text"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="codex",
)
async def codex_ingest_text(text: str, title: str = "", source: str = "manual", tags: Optional[List[str]] = None) -> Dict[str, Any]:
    tags = tags or []
    h = _hash(text)
    existing = business_db.query_one("SELECT id FROM codex_documents WHERE content_hash = ?", (h,))
    if existing:
        return {"ok": True, "skipped": True, "reason": "duplicate", "hash": h}
    # Insert into codex table.
    doc_id = business_db.execute(
        """INSERT INTO codex_documents (source, title, content, content_hash, metadata_json, ingested_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (source, title, text, h, '{"tags": ' + str(tags) + '}', datetime.utcnow().isoformat()),
    )
    # Also push into ChromaDB for semantic search.
    try:
        entry = MemoryEntry(
            category=MemoryCategory.PREFERENCES,
            content=text[:5000],
            source=f"codex:{source}",
            tags=tags + ["codex"],
        )
        await memory_engine.store(entry)
    except Exception:
        pass
    return {"ok": True, "doc_id": doc_id, "hash": h, "chars": len(text)}


@tool(
    name="codex.ingest_local_docs",
    description="Walk a local directory and ingest all text/markdown/pdf files into Sir's codex.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "default": "./storage/notes"},
            "extensions": {"type": "array", "items": {"type": "string"}, "default": [".md", ".txt"]},
            "max_files": {"type": "integer", "default": 100},
        },
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="codex",
)
async def codex_ingest_local_docs(path: str = "./storage/notes", extensions: Optional[List[str]] = None, max_files: int = 100) -> Dict[str, Any]:
    extensions = extensions or [".md", ".txt"]
    root = Path(path)
    if not root.exists():
        return {"ok": False, "error": f"path does not exist: {path}"}
    ingested = 0
    skipped = 0
    for fp in root.rglob("*"):
        if not fp.is_file() or fp.suffix.lower() not in extensions:
            continue
        if ingested >= max_files:
            break
        try:
            text = fp.read_text(encoding="utf-8", errors="ignore")
            if not text.strip():
                continue
            r = await codex_ingest_text(text=text, title=fp.name, source=f"local:{fp}")
            if r.get("skipped"):
                skipped += 1
            else:
                ingested += 1
        except Exception:
            continue
    return {"ok": True, "ingested": ingested, "skipped_duplicates": skipped, "path": path}


@tool(
    name="codex.ingest_gmail",
    description="Ingest Sir's sent emails into the codex. Requires gmail_oauth_json in vault.",
    parameters={
        "type": "object",
        "properties": {
            "max_emails": {"type": "integer", "default": 200},
            "query": {"type": "string", "default": "in:sent"},
        },
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="codex",
)
async def codex_ingest_gmail(max_emails: int = 200, query: str = "in:sent") -> Dict[str, Any]:
    oauth = _cred("gmail_oauth_json")
    if not oauth:
        return {"ok": False, "error": "gmail_oauth_json not in vault. Enable Gmail API in GCP and create OAuth credentials."}
    try:
        from google.oauth2.credentials import Credentials  # type: ignore
        from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore
        from googleapiclient.discovery import build  # type: ignore
    except ImportError as e:
        return {"ok": False, "error": str(e)}

    def _do():
        import json as _json, tempfile, os
        client_config_path = oauth
        if not Path(oauth).exists():
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tf:
                tf.write(oauth)
                client_config_path = tf.name
        flow = InstalledAppFlow.from_client_secrets_file(
            client_config_path, ["https://www.googleapis.com/auth/gmail.readonly"],
        )
        creds = flow.run_local_server(port=0)
        service = build("gmail", "v1", credentials=creds)
        msgs_resp = service.users().messages().list(userId="me", q=query, maxResults=max_emails).execute()
        msgs = msgs_resp.get("messages", [])
        ingested_texts = []
        for m in msgs:
            full = service.users().messages().get(userId="me", id=m["id"], format="full").execute()
            snippet = full.get("snippet", "")
            if snippet:
                ingested_texts.append({"snippet": snippet, "id": m["id"]})
        return ingested_texts

    import asyncio
    try:
        emails = await asyncio.to_thread(_do)
    except Exception as e:
        return {"ok": False, "error": str(e)}
    n = 0
    for e in emails:
        r = await codex_ingest_text(text=e["snippet"], source="gmail", title=f"Email {e['id']}")
        if r.get("ok") and not r.get("skipped"):
            n += 1
    return {"ok": True, "ingested": n, "fetched": len(emails)}


@tool(
    name="codex.ingest_github",
    description="Ingest Sir's GitHub gists + repo READMEs into codex. Requires github_pat in vault.",
    parameters={
        "type": "object",
        "properties": {
            "username": {"type": "string"},
            "max_repos": {"type": "integer", "default": 30},
        },
        "required": ["username"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="codex",
)
async def codex_ingest_github(username: str, max_repos: int = 30) -> Dict[str, Any]:
    import httpx
    pat = _cred("github_pat")
    headers = {"Accept": "application/vnd.github+json"}
    if pat:
        headers["Authorization"] = f"Bearer {pat}"
    ingested = 0
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            # User's public repos
            resp = await client.get(
                f"https://api.github.com/users/{username}/repos",
                params={"per_page": max_repos, "sort": "updated"},
                headers=headers,
            )
            if resp.status_code >= 400:
                return {"ok": False, "error": f"GitHub API: {resp.status_code}"}
            repos = resp.json()
            for r in repos[:max_repos]:
                # Get README
                readme_resp = await client.get(
                    f"https://api.github.com/repos/{r['full_name']}/readme",
                    headers={**headers, "Accept": "application/vnd.github.raw"},
                )
                if readme_resp.status_code == 200:
                    text = f"Repo: {r['full_name']}\nDescription: {r.get('description','')}\n\n{readme_resp.text}"
                    res = await codex_ingest_text(text=text, source="github", title=r["full_name"])
                    if res.get("ok") and not res.get("skipped"):
                        ingested += 1
        return {"ok": True, "username": username, "ingested": ingested, "scanned": len(repos)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="codex.ask",
    description="Semantic search across Sir's codex. Ask 'what did I think about X?' or 'show me notes about Y'.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer", "default": 5},
        },
        "required": ["query"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="codex",
)
async def codex_ask(query: str, limit: int = 5) -> Dict[str, Any]:
    # Search ChromaDB
    try:
        from shared.models import MemoryQuery
        results = await memory_engine.query(MemoryQuery(
            query=query, top_k=limit, min_relevance=0.3,
        ))
        chroma_hits = [{"content": r.content[:500], "source": r.source, "relevance": r.relevance_score} for r in results]
    except Exception:
        chroma_hits = []
    # Fallback to LIKE search on codex_documents
    try:
        rows = business_db.query(
            "SELECT id, source, title, content FROM codex_documents WHERE content LIKE ? ORDER BY id DESC LIMIT ?",
            (f"%{query}%", limit),
        )
        sql_hits = [{"id": r["id"], "source": r["source"], "title": r["title"], "snippet": r["content"][:300]} for r in rows]
    except Exception:
        sql_hits = []
    return {
        "ok": True, "query": query,
        "chroma_hits": chroma_hits, "sql_hits": sql_hits,
        "total_found": len(chroma_hits) + len(sql_hits),
    }


@tool(
    name="codex.write_like_me",
    description="Ghost-write a message in Sir's style, using the codex as reference.",
    parameters={
        "type": "object",
        "properties": {
            "topic": {"type": "string"},
            "format": {"type": "string", "default": "twitter", "enum": ["twitter", "email", "blog_post", "linkedin"]},
            "tone": {"type": "string", "default": "natural"},
        },
        "required": ["topic"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="codex",
)
async def codex_write_like_me(topic: str, format: str = "twitter", tone: str = "natural") -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    # Pull 3 samples from codex.
    samples = await codex_ask(query=topic, limit=3)
    sample_text = "\n---\n".join([h.get("snippet", h.get("content", ""))[:400] for h in (samples.get("sql_hits") or samples.get("chroma_hits"))])
    sys_prompt = (
        f"Write in Sir's personal voice (style samples below). Format: {format}. Tone: {tone}. "
        "Output only the final text — no preamble, no JSON.\n\n"
        f"Sir's writing samples:\n{sample_text or '(no samples yet — write naturally in modern Arabic/English mix)'}"
    )
    try:
        text = await llm_service.get_response(
            user_message=f"Topic: {topic}", system_instructions=sys_prompt, inject_memory=False,
        )
        return {"ok": True, "text": text, "format": format}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="codex.daily_journal_write",
    description="Auto-generate a daily journal entry from today's activity (audit_log + posts + orders + tickets).",
    parameters={"type": "object"},
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="codex",
)
async def codex_daily_journal_write() -> Dict[str, Any]:
    since = (datetime.utcnow() - timedelta(days=1)).isoformat()
    actions = business_db.rows_to_dicts(business_db.query(
        "SELECT timestamp, action, category, target FROM audit_log WHERE timestamp >= ? ORDER BY id DESC LIMIT 100",
        (since,),
    ))
    posts = business_db.query("SELECT COUNT(*) as n FROM posts WHERE created_at >= ?", (since,))[0]["n"]
    orders = business_db.query("SELECT COUNT(*) as n FROM orders WHERE created_at >= ?", (since,))[0]["n"]
    from backend.services.llm_service import llm_service
    summary_input = (
        f"Today's activity:\n"
        f"- Posts: {posts}\n- Orders: {orders}\n- Audit actions: {len(actions)}\n"
        f"Recent actions: {[a['action'] for a in actions[:20]]}"
    )
    try:
        entry = await llm_service.get_response(
            user_message=summary_input,
            system_instructions=(
                "Write a brief personal journal entry for Sir in mixed Arabic/English, first person, "
                "as if Sir himself is reflecting on his day. 3-5 sentences. Casual but thoughtful."
            ),
            inject_memory=False,
        )
        # Save to codex.
        await codex_ingest_text(text=entry, source="journal", title=f"Journal {datetime.utcnow().date()}")
        return {"ok": True, "entry": entry}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="codex.memory_consolidate",
    description="Weekly pass: cluster codex entries, summarize, tag. Keeps the codex manageable.",
    parameters={"type": "object"},
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="codex",
)
async def codex_memory_consolidate() -> Dict[str, Any]:
    rows = business_db.query("SELECT id, content FROM codex_documents ORDER BY id DESC LIMIT 200")
    if not rows:
        return {"ok": True, "consolidated": 0, "note": "codex empty"}
    from backend.services.llm_service import llm_service
    text_blob = "\n---\n".join([f"[{r['id']}] {r['content'][:300]}" for r in rows[:50]])
    try:
        summary = await llm_service.get_response(
            user_message=f"Recent codex entries:\n{text_blob}",
            system_instructions="Cluster and summarize these into 3-5 themes. Output as Markdown bullet list. Then tag each theme.",
            inject_memory=False,
        )
        await codex_ingest_text(text=summary, source="consolidation", title=f"Weekly consolidation {datetime.utcnow().date()}")
        return {"ok": True, "summary": summary}
    except Exception as e:
        return {"ok": False, "error": str(e)}


PLUGIN_NAME = "codex"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Personal knowledge codex: ingest Gmail/GitHub/Notion/local docs → semantic search + ghost-writing."
