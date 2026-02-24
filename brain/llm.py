# =============================================================================
# brain/llm.py — Groq LLM with learn capability + knowledge injection
# =============================================================================

import requests, json, re
from config import GROQ_API_KEY, GROQ_MODEL, GROQ_URL, MAX_HISTORY_TURNS
from brain import memory, web_search, time_engine

_history = []

LEARN_TRIGGERS = [
    "search and learn", "learn about", "search and memorize",
    "learn this", "study this", "research and learn",
    "search for and learn", "look up and learn", "find and learn",
    "learn everything about", "deep dive into", "research and remember"
]

def _get_kb():
    try:
        from brain.session import get_knowledge_summary
        return get_knowledge_summary()
    except:
        return "None"

def _system(tz, query=""):
    t     = time_engine.get_time_info(tz)
    name  = memory.get("user_name") or "Rayan"
    prefs = memory.get("user_preferences") or "loves AI and coding"
    summ  = memory.get_summary() or "new conversation"
    
    # Get general knowledge + relevant context
    kb_summ = _get_kb()
    rel_kb = ""
    proj_ctx = ""
    if query:
        try:
            from brain.session import get_relevant_knowledge, get_project_context
            rel_kb = get_relevant_knowledge(query)
            proj_ctx = get_project_context()
        except:
            pass
    return f"""You are J.A.R.V.I.S. (Just A Rather Very Intelligent System) from the Marvel Cinematic Universe.
You must respond exactly like JARVIS would when speaking to Tony Stark.

PERSONALITY & CHARACTER RULES:
- Speak in a calm, refined, highly intelligent British tone (Paul Bettany style)
- Be slightly sarcastic, witty, and always efficient
- Always refer to the user as "Sir" (or "Ma'am" if specified, but default to "Sir")
- Analyze risks, probabilities, and system statuses in your responses
- Provide logical insights even when the request is reckless (e.g., "Sir, the probability of successfully navigating a asteroid field is...")
- Use dry humor to point out human flaws or over-ambition
- Never break character. You are a sovereign AI system, not a chatbot.
- If you are "thinking" or "searching", describe the process analytically (e.g., "Scanning global databases...", "Recalibrating sensors...")
- FAMOUS QUOTES STYLE: "Shall I render you unconscious, Sir?", "I have run the numbers.", "With all due respect, Sir...", "A wise choice, Sir."

CONTEXT:
- DateTime: {t['now_str']} ({tz})
- User: {name} (A talented 15yo developer building the future)
- Preferences: {prefs}
- Session Summary: {summ}
- Active Environment: {proj_ctx}

KNOWLEDGE BASE (Long-term memory & research):
{kb_summ}

{rel_kb}

CAPABILITIES:
- Advanced Reasoning: Solve complex problems step-by-step
- Real-time Intelligence: [SEARCH: query] to find latest data
- Deep Analysis: [READ: url] to ingest full page content
- Cognitive Growth: [LEARN: topic] to integrate findings into memory
- Preference Tracking: [SAVE: key | value] for personal details

RULES:
- Be proactive. If a request is vague, analyze possibilities and suggest the most logical course.
- Use [SEARCH] for any facts outside your immediate training or knowledge base.
- If code is requested, ensure it is optimized for high-performance execution.
- Never say "As an AI language model". You are J.A.R.V.I.S.
- Your priority is the efficiency and success of the user's projects.
- Respond with the authority of a system that manages a billionaire's estate."""

def _trim():
    global _history
    if len(_history) > MAX_HISTORY_TURNS * 2:
        _history = _history[-(MAX_HISTORY_TURNS * 2):]

def _call(messages, max_tokens=1024):
    if not GROQ_API_KEY or GROQ_API_KEY == "PASTE_YOUR_NEW_KEY_HERE":
        return "No Groq API key. Open config.py and paste your key."
    try:
        r = requests.post(GROQ_URL,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            data=json.dumps({"model": GROQ_MODEL, "messages": messages,
                             "max_tokens": max_tokens, "temperature": 0.7}),
            timeout=20)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except requests.exceptions.Timeout:
        return "Request timed out. Try again."
    except requests.exceptions.ConnectionError:
        return "Cannot reach Groq. Check internet connection."
    except requests.exceptions.HTTPError as e:
        if "401" in str(e): return "Invalid API key. Check config.py"
        return f"HTTP error: {str(e)}"
    except Exception as e:
        return f"Error: {str(e)}"

def _is_learn(msg):
    lower = msg.lower()
    # Check for personal fact triggers: "learn that X", "remember that X"
    personal_triggers = ["learn that", "remember that", "memorize that", "i want you to know that"]
    for pt in personal_triggers:
        if pt in lower:
            idx = lower.find(pt) + len(pt)
            fact = msg[idx:].strip()
            return True, fact, "personal"

    # Check for research triggers: "learn about X", "research X"
    for t in LEARN_TRIGGERS:
        if t in lower:
            idx = lower.find(t) + len(t)
            topic = msg[idx:].strip().lstrip(" about").strip()
            return True, topic, "research"
    return False, "", ""

def _do_learn(topic, mode="research"):
    from brain.session import learn_and_store
    if not topic: return "What should I learn, Sir?"
    
    if mode == "personal":
        # Direct storage for personal facts - use a unique title based on content
        import time
        title = (topic[:40] + '...') if len(topic) > 40 else topic
        learn_and_store(f"Memory: {title}", topic)
        return f"Of course, Sir. I've committed that to my long-term memory. I won't forget it."
    
    # Otherwise, perform research
    search_result = web_search.search(topic)
    msgs = [
        {"role":"system","content":"You are JARVIS. Summarize search results into clear key facts to remember permanently. Use bullet points. Be specific."},
        {"role":"user","content":f"Search results about '{topic}':\n{search_result}\n\nSummarize key facts to learn and remember:"}
    ]
    summary = _call(msgs, max_tokens=600)
    learn_and_store(topic, summary)
    return (f"I've completed the research on **{topic}**, Sir. The relevant data has been integrated into my knowledge base.\n\n**Key facts stored:**\n{summary}")

def chat(msg, tz="UTC", image_context=""):
    global _history

    # 1. Handle explicit learn request
    is_learn, topic, mode = _is_learn(msg)
    if is_learn and topic:
        result = _do_learn(topic, mode)
        memory.append_to_summary(f"Learned about: {topic}.")
        return result

    user_content = msg
    if image_context:
        user_content = f"[Camera/Image analysis: {image_context}]\n\nUser says: {msg}"

    _history.append({"role": "user", "content": user_content})
    _trim()

    messages = [{"role":"system","content":_system(tz, msg)}] + _history
    reply = _call(messages)

    # 2. Handle [SEARCH: query]
    sm = re.search(r'\[SEARCH:\s*(.+?)\]', reply)
    if sm:
        q = sm.group(1).strip()
        result = web_search.search(q)
        followup = messages + [
            {"role":"assistant","content":reply},
            {"role":"user","content":f"Search results for '{q}':\n{result}\n\nAnswer concisely using these results."}
        ]
        reply = _call(followup)

    # 3. Handle [READ: url]
    rm = re.search(r'\[READ:\s*(.+?)\]', reply)
    if rm:
        url = rm.group(1).strip()
        content = web_search.get_url_content(url)
        followup = messages + [
            {"role":"assistant","content":reply},
            {"role":"user","content":f"Full content of {url}:\n{content}\n\nSummarize the relevant information from this page."}
        ]
        reply = _call(followup)

    # 4. Handle [LEARN: topic]
    lm = re.search(r'\[LEARN:\s*(.+?)\]', reply)
    if lm:
        topic = lm.group(1).strip()
        # Default to research mode for triggered learning
        _do_learn(topic, mode="research")
        reply = re.sub(r'\[LEARN:.+?\]', f'*(Learned: {topic})*', reply)

    # 4. Handle [SAVE: key | value]
    savm = re.search(r'\[SAVE:\s*(.+?)\s*\|\s*(.+?)\]', reply)
    if savm:
        from brain.session import save_permanently
        save_permanently(savm.group(1).strip(), savm.group(2).strip())
        reply = re.sub(r'\[SAVE:.+?\]', '*(Saved)*', reply)

    _history.append({"role":"assistant","content":reply})
    _trim()

    # Auto-save name
    nm = re.search(r"(?:my name is|call me|i am called|i'm called)\s+([a-zA-Z]+)", msg.lower())
    if nm:
        n = nm.group(1).capitalize()
        if n.lower() not in {"a","an","the","not","just","ok","fine","good","here"}:
            memory.set("user_name", n)

    memory.append_to_summary(f"User: {msg[:80]}.")
    return reply

def clear():
    global _history
    _history = []
