# =============================================================================
# brain/session.py — Smart session management
# - Tracks what the user wants to permanently save
# - Auto-deletes everything else when session ends
# - "Save this" / "Remember this" = kept forever in DB
# - Everything else = deleted on session end
# =============================================================================

import os, time, json
from brain import memory

# Files uploaded this session — deleted at end unless user says save
_session_files = []
_session_start = time.time()

# Things learned this session (search+learn results)
_learned_knowledge = {}

UPLOADS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "uploads")


def track_file(filepath: str):
    """Register a file as session-temporary."""
    if filepath not in _session_files:
        _session_files.append(filepath)


def save_permanently(key: str, value: str):
    """User explicitly asked to save this — store in SQLite forever."""
    memory.set(f"saved_{key}", value)


def get_saved(key: str) -> str:
    return memory.get(f"saved_{key}") or ""


def learn_and_store(topic: str, knowledge: str):
    """
    Store learned knowledge from web search permanently in SQLite.
    This is what makes JARVIS actually learn — it writes to memory
    and the LLM system prompt injects it on every future request.
    """
    _learned_knowledge[topic] = knowledge
    # Append to the persistent knowledge base in SQLite
    existing = memory.get("learned_knowledge") or "{}"
    try:
        kb = json.loads(existing)
    except:
        kb = {}
    kb[topic] = {
        "content": knowledge[:1000],  # store up to 1000 chars per topic
        "learned_at": time.strftime("%Y-%m-%d %H:%M")
    }
    # Keep only last 50 topics to avoid DB bloat
    if len(kb) > 50:
        oldest = sorted(kb.keys())[0]
        del kb[oldest]
    memory.set("learned_knowledge", json.dumps(kb))


def get_knowledge_base() -> dict:
    """Return all learned knowledge as a dict."""
    raw = memory.get("learned_knowledge") or "{}"
    try:
        return json.loads(raw)
    except:
        return {}


def get_knowledge_summary() -> str:
    """Return a short summary of what JARVIS has learned, for the system prompt."""
    kb = get_knowledge_base()
    if not kb:
        return "No topics learned yet."
    lines = []
    # Default to last 5 topics for general context
    for topic, data in list(kb.items())[-5:]:
        lines.append(f"- {topic}: {data['content'][:200]}")
    return "\n".join(lines)


def get_relevant_knowledge(query: str, limit: int = 5) -> str:
    """Search for relevant topics in the knowledge base."""
    kb = get_knowledge_base()
    if not kb: return ""
    
    # Simple keyword match
    keywords = [w.lower() for w in query.split() if len(w) > 3]
    matches = []
    for topic, data in kb.items():
        score = 0
        topic_l = topic.lower()
        content_l = data['content'].lower()
        for kw in keywords:
            if kw in topic_l: score += 5
            if kw in content_l: score += 1
        if score > 0:
            matches.append((score, topic, data['content']))
    
    # Sort by score and take top matches
    matches.sort(key=lambda x: x[0], reverse=True)
    results = matches[:limit]
    
    if not results: return ""
    
    lines = [f"RELEVANT KNOWLEDGE FOUND:"]
    for _, topic, content in results:
        lines.append(f"- {topic}: {content[:400]}")
    return "\n".join(lines)


def forget_topic(topic: str):
    """Remove a specific learned topic."""
    kb = get_knowledge_base()
    # Try to match partial topic name
    matched = [k for k in kb.keys() if topic.lower() in k.lower()]
    if matched:
        for k in matched:
            del kb[k]
        memory.set("learned_knowledge", json.dumps(kb))
        return f"Forgot everything about: {', '.join(matched)}"
    return f"No knowledge found about '{topic}'"


def get_project_context() -> str:
    """List the contents of the projects directory to give JARVIS context."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    projects_dir = os.path.join(base_dir, "projects")
    if not os.path.exists(projects_dir): return "No projects directory found."
    
    lines = ["CURRENT PROJECTS STRUCTURE:"]
    try:
        for root, dirs, files in os.walk(projects_dir):
            level = root.replace(projects_dir, '').count(os.sep)
            indent = ' ' * 4 * (level)
            folder = os.path.basename(root)
            if folder and not folder.startswith('.'):
                lines.append(f"{indent}📁 {folder}/")
            
            sub_indent = ' ' * 4 * (level + 1)
            for f in files:
                if not f.startswith('.'):
                    lines.append(f"{sub_indent}📄 {f}")
            if level > 2: break # Don't go too deep
    except: pass
    return "\n".join(lines[:30]) # Limit length


def cleanup_session():
    """
    Called when session ends or user says 'clear session'.
    Deletes all temporary uploaded files.
    Keeps only explicitly saved items and learned knowledge.
    """
    deleted = []
    for filepath in _session_files:
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
                deleted.append(os.path.basename(filepath))
        except:
            pass
    _session_files.clear()

    # Also clear conversation summary (not learned knowledge)
    memory.delete("short_conversation_summary")

    return deleted


def cleanup_old_uploads():
    """
    Auto-cleanup uploads older than 1 hour even without explicit session end.
    Called on app startup and periodically.
    """
    if not os.path.exists(UPLOADS_DIR):
        return
    now = time.time()
    for fname in os.listdir(UPLOADS_DIR):
        fpath = os.path.join(UPLOADS_DIR, fname)
        try:
            if os.path.isfile(fpath) and (now - os.path.getmtime(fpath)) > 3600:
                os.remove(fpath)
        except:
            pass
