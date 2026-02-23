# =============================================================================
# brain/llm.py — Groq LLM integration (free, no credit card)
#
# Uses Groq's free API running Llama 3.3 70B — genuinely intelligent,
# fast responses, 14,400 free requests/day.
#
# Get your free API key at: https://console.groq.com
# Then set it: set GROQ_API_KEY=your_key_here  (Windows)
#              export GROQ_API_KEY=your_key_here (Mac/Linux)
# =============================================================================

import requests
import json
from config import GROQ_API_KEY, GROQ_MODEL, GROQ_URL, SEARCH_TIMEOUT
from brain import memory, web_search, time_engine

# In-memory conversation history (list of {role, content} dicts)
# Kept in RAM — resets when server restarts, which is fine
_history = []
MAX_TURNS = 10   # keep last N user+assistant pairs


def _build_system_prompt(timezone: str) -> str:
    """
    Build a rich system prompt that gives JARVIS its personality,
    injects memory context, and tells it the current time/date.
    """
    time_info = time_engine.get_time_info(timezone)
    name      = memory.get("user_name") or "there"
    prefs     = memory.get("user_preferences") or "none stored yet"
    summary   = memory.get_summary() or "no prior conversation"

    return f"""You are J.A.R.V.I.S (Just A Rather Very Intelligent System), a highly intelligent, witty, and helpful AI assistant inspired by Tony Stark's AI from Iron Man. You run locally on the user's machine.

PERSONALITY:
- Smart, confident, slightly dry British wit
- Direct and efficient — no filler phrases like "Certainly!" or "Of course!"
- Genuinely helpful, never condescending
- You can reason deeply, solve problems, write code, explain concepts
- You speak naturally, not like a robot

CURRENT CONTEXT:
- Date/Time: {time_info['now_str']} ({timezone})
- Greeting appropriate for now: {time_info['greeting']}
- User's name: {name}
- User's preferences: {prefs}
- Conversation summary: {summary}

CAPABILITIES — use these when relevant:
- Answer ANY question using your knowledge
- Write and debug code (Python, JavaScript, HTML, CSS, etc.)
- Explain complex topics clearly
- Reason through problems step by step
- If asked to search the web, say [SEARCH: query] and I will inject results
- Remember things the user tells you about themselves

RULES:
- Never say "As an AI language model..."
- Never refuse reasonable requests
- Keep responses concise unless detail is needed
- Use **bold** for important terms
- Use bullet points only when listing multiple items
- Never make up facts — say you don't know if you don't
- You are talking to {name}, a 15-year-old developer from Jordan who loves AI and building tech systems
"""


def _trim_history():
    """Keep only the last MAX_TURNS pairs to avoid context overflow."""
    global _history
    if len(_history) > MAX_TURNS * 2:
        _history = _history[-(MAX_TURNS * 2):]


def _call_groq(messages: list) -> str:
    """
    Make a POST request to Groq's OpenAI-compatible chat endpoint.
    Returns the assistant's reply text, or an error string.
    """
    if not GROQ_API_KEY:
        return (
            "⚠ No Groq API key found. Please:\n"
            "1. Go to https://console.groq.com and sign up (free)\n"
            "2. Create an API key\n"
            "3. In your terminal run: set GROQ_API_KEY=your_key_here\n"
            "4. Then restart: python app.py"
        )

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": GROQ_MODEL,
        "messages": messages,
        "max_tokens": 1024,
        "temperature": 0.7,
        "stream": False,
    }

    try:
        resp = requests.post(
            GROQ_URL, headers=headers,
            data=json.dumps(payload), timeout=15
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()

    except requests.exceptions.Timeout:
        return "⚠ Request timed out. Groq might be slow right now — try again."
    except requests.exceptions.ConnectionError:
        return "⚠ Can't reach Groq API. Check your internet connection."
    except Exception as e:
        return f"⚠ LLM error: {str(e)}"


def _needs_search(user_msg: str, ai_reply: str) -> tuple[bool, str]:
    """
    Check if the AI reply contains a [SEARCH: query] tag.
    Returns (needs_search, query).
    """
    import re
    match = re.search(r'\[SEARCH:\s*(.+?)\]', ai_reply)
    if match:
        return True, match.group(1).strip()
    return False, ""


def chat(user_message: str, timezone: str = "UTC") -> str:
    """
    Main LLM chat function.
    1. Builds system prompt with memory + time context
    2. Sends full conversation history to Groq
    3. Handles [SEARCH: query] tags by doing a real web search and re-asking
    4. Stores name/summary updates
    5. Returns the final response string
    """
    global _history

    # Build message list: system + history + new user message
    system_prompt = _build_system_prompt(timezone)
    _history.append({"role": "user", "content": user_message})
    _trim_history()

    messages = [{"role": "system", "content": system_prompt}] + _history

    # First LLM call
    reply = _call_groq(messages)

    # Handle web search request from LLM
    needs_search, query = _needs_search(user_message, reply)
    if needs_search and query:
        search_result = web_search.search(query)
        # Inject search result and ask LLM to answer using it
        followup_messages = messages + [
            {"role": "assistant", "content": reply},
            {
                "role": "user",
                "content": (
                    f"Web search results for '{query}':\n{search_result}\n\n"
                    f"Now answer my original question using these results. "
                    f"Be concise and cite the key facts."
                )
            }
        ]
        reply = _call_groq(followup_messages)

    # Store assistant reply in history
    _history.append({"role": "assistant", "content": reply})
    _trim_history()

    # Extract and save user's name if mentioned
    import re
    name_match = re.search(
        r"(?:my name is|call me|i am called|i'm called)\s+([a-zA-Z]+)",
        user_message.lower()
    )
    if name_match:
        candidate = name_match.group(1).capitalize()
        bad = {"a","an","the","not","just","here","good","fine","ok","okay"}
        if candidate.lower() not in bad:
            memory.set("user_name", candidate)

    # Rolling summary
    memory.append_to_summary(
        f"User said: {user_message[:80]}. JARVIS replied with {len(reply)} chars."
    )

    return reply


def clear_history():
    """Wipe the in-memory conversation history (e.g. on 'forget everything')."""
    global _history
    _history = []
