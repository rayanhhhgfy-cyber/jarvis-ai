# =============================================================================
# brain/reasoning.py — JARVIS Intent Engine (Fixed Version)
# Fixes:
#   - "hi" no longer triggers web search
#   - Name detection no longer stores wrong names
#   - Preferences no longer trigger web search
#   - Intent priority is correct
# =============================================================================

import re
from brain import memory, time_engine, web_search
from config import ASSISTANT_NAME

_JOKES = [
    "Why do programmers prefer dark mode? Because light attracts bugs.",
    "I told my computer I needed a break. Now it won't stop sending me Kit-Kat ads.",
    "Why don't scientists trust atoms? Because they make up everything.",
    "Parallel lines have so much in common — it's a shame they'll never meet.",
    "Why did the AI go to therapy? It had too many deep issues.",
    "A SQL query walks into a bar, walks up to two tables and asks: 'Can I join you?'",
]
_joke_index = 0


def _lower(text):
    return text.lower().strip()


def _sw(text, prefixes):
    """Check if text starts with any of the given prefixes."""
    t = _lower(text)
    return any(t.startswith(p) for p in prefixes)


def _has(text, keywords):
    """Check if any keyword appears in text."""
    t = _lower(text)
    return any(kw in t for kw in keywords)


def _extract_name(text):
    """
    Safely extract a name only from explicit name-stating phrases.
    Returns capitalised name or empty string.
    """
    patterns = [
        r"(?:my name is|call me|i am called|i'm called)\s+([a-zA-Z]+)",
    ]
    BAD = {"a","an","the","not","just","here","good","fine","ok","okay",
           "what","how","why","when","where","who","also","and","but"}
    for pat in patterns:
        m = re.search(pat, _lower(text))
        if m:
            name = m.group(1).capitalize()
            if name.lower() not in BAD:
                return name
    return ""


def _classify(text):
    """
    Classify user input into an intent.
    Checks from most specific to least specific.
    Returns intent string.
    """
    t = _lower(text)
    words = t.split()
    word_count = len(words)

    # ── 1. Greetings — ONLY if message is short (1-4 words) ─────────────────
    GREET_WORDS = {"hi","hello","hey","howdy","greetings","sup","yo","hiya"}
    if word_count <= 4 and any(w in GREET_WORDS for w in words):
        return "greeting"

    # ── 2. Farewell ──────────────────────────────────────────────────────────
    FARE_WORDS = {"bye","goodbye","cya","later","farewell","see you","take care"}
    if word_count <= 5 and _has(t, FARE_WORDS):
        return "farewell"

    # ── 3. Thanks ────────────────────────────────────────────────────────────
    if word_count <= 6 and _has(t, ["thank you","thanks","cheers","appreciate"]):
        return "thanks"

    # ── 4. Joke ──────────────────────────────────────────────────────────────
    if _has(t, ["tell me a joke","say something funny","make me laugh","joke"]):
        return "joke"

    # ── 5. Time / date ───────────────────────────────────────────────────────
    if _has(t, ["what time","current time","what's the time","what is the time",
                "what day","what date","today's date","what year","what month",
                "time is it","date is it","day is it"]):
        return "time"

    # ── 6. System / about ────────────────────────────────────────────────────
    if _has(t, ["who are you","what are you","your name","your version",
                "what can you do","how do you work","capabilities","about you"]):
        return "system"

    # ── 7. Memory — store name (MUST come before preference) ─────────────────
    if _has(t, ["my name is","call me","i am called","i'm called"]):
        return "memory_store_name"

    # ── 8. Memory — recall ───────────────────────────────────────────────────
    if _has(t, ["do you remember","what do you know about me",
                "what have i told","my preferences","recall my","remember me"]):
        return "memory_recall"

    # ── 9. Memory — clear ────────────────────────────────────────────────────
    if _has(t, ["forget everything","clear memory","reset memory",
                "delete memory","wipe memory","forget me"]):
        return "memory_clear"

    # ── 10. Memory — store preference ────────────────────────────────────────
    # Only if message is fairly short and doesn't look like a question
    if word_count <= 12 and not t.endswith("?") and _has(t, [
        "i prefer ","i like ","i love ","i enjoy ","i hate ","i dislike ",
        "my favourite","my favorite","i'm into","i am into"
    ]):
        return "memory_store_pref"

    # ── 11. Explicit search request ──────────────────────────────────────────
    if _has(t, ["search for","look up","search the web","search online",
                "find info","google "]):
        return "search"

    # ── 12. Questions that clearly need a web search ─────────────────────────
    if _has(t, ["what is ","what are ","who is ","who was ","who are ",
                "when did ","when was ","where is ","where are ",
                "how does ","how do ","how did ","why does ","why did ",
                "explain ","tell me about ","latest news","news about",
                "define ","meaning of "]):
        return "search"

    # ── 13. Default: conversational reply — NOT a search ─────────────────────
    return "chat"


# ── Intent handlers ───────────────────────────────────────────────────────────

def _handle_greeting(timezone):
    greeting = time_engine.get_greeting(timezone)
    name = memory.get("user_name")
    suffix = f", {name}" if name else ""
    return (
        f"{greeting}{suffix}! I am {ASSISTANT_NAME}, your personal AI assistant. "
        f"How can I help you today?"
    )


def _handle_farewell():
    name = memory.get("user_name")
    suffix = f", {name}" if name else ""
    return f"Farewell{suffix}! It was a pleasure assisting you. Until next time."


def _handle_thanks():
    return "You're welcome! That's exactly what I'm here for. Anything else I can help with?"


def _handle_joke():
    global _joke_index
    joke = _JOKES[_joke_index % len(_JOKES)]
    _joke_index += 1
    return joke


def _handle_time(timezone):
    return time_engine.format_response(timezone)


def _handle_system():
    return (
        f"I am **{ASSISTANT_NAME}** — Just A Rather Very Intelligent System. "
        "I run entirely on your local machine with no cloud or paid APIs. "
        "I can search the web (DuckDuckGo), tell you the time, remember your "
        "name and preferences, answer questions, and hold a conversation. "
        "All data is stored locally on your device."
    )


def _handle_store_name(text):
    name = _extract_name(text)
    if name:
        memory.set("user_name", name)
        memory.append_to_summary(f"User's name is {name}.")
        return f"Got it! I'll remember your name is **{name}** from now on."
    return (
        "I couldn't catch your name clearly. "
        "Try saying: **My name is [your name]**"
    )


def _handle_store_pref(text):
    existing = memory.get("user_preferences") or ""
    new_pref = text.strip().rstrip(".")
    updated = (existing + "; " + new_pref).strip("; ")
    memory.set("user_preferences", updated)
    memory.append_to_summary(f"User preference: {new_pref}.")
    return f"Noted! I've saved your preference: '{new_pref}'."


def _handle_recall():
    name = memory.get("user_name")
    prefs = memory.get("user_preferences")
    summary = memory.get_summary()
    parts = []
    if name:
        parts.append(f"Your name: **{name}**")
    if prefs:
        parts.append(f"Your preferences: {prefs}")
    if summary:
        parts.append(f"Conversation notes: {summary}")
    if not parts:
        return "I don't have anything stored about you yet. Tell me your name or preferences!"
    return "Here's what I remember about you:\n\n" + "\n".join(parts)


def _handle_clear():
    for key in ("user_name", "user_preferences", "short_conversation_summary"):
        memory.delete(key)
    return "Memory cleared! I've forgotten everything — fresh start."


def _handle_search(text):
    # Strip common question preambles to get the core search query
    preambles = [
        "search for","search the web for","search online for","look up",
        "find info on","find info about","tell me about","what is",
        "what are","who is","who was","who are","when did","when was",
        "where is","where are","how does","how do","how did",
        "why does","why did","explain","define","latest news about",
        "news about","google","meaning of",
    ]
    query = _lower(text)
    for p in preambles:
        if query.startswith(p):
            query = query[len(p):].strip()
            break

    if not query:
        query = text

    result = web_search.search(query)
    return result


def _handle_chat(text):
    """
    Conversational fallback for messages that don't fit other intents.
    Gives a natural JARVIS-style response.
    """
    name = memory.get("user_name")
    n = f" {name}" if name else ""

    t = _lower(text)

    if _has(t, ["how are you","how do you do","you okay","you good"]):
        return f"I'm operating at full capacity{n}, thank you for asking! How can I assist you?"

    if _has(t, ["what's up","what up","wassup"]):
        return f"All systems nominal{n}. Ready to assist. What do you need?"

    if _has(t, ["can you help","help me","i need help"]):
        return (
            f"Of course{n}! I can help you with:\n"
            "• **Web search** — ask me anything\n"
            "• **Time & date** — 'what time is it?'\n"
            "• **Memory** — 'my name is Rayan'\n"
            "• **Jokes** — 'tell me a joke'\n"
            "What do you need?"
        )

    if _has(t, ["are you real","are you human","are you ai","are you a bot"]):
        return (
            f"I am an AI assistant{n} — not human, but designed to be as helpful as possible. "
            "I run completely locally on your machine."
        )

    # Generic fallback
    return (
        f"I received your message{n}. If you have a question, try asking me directly — "
        "for example: 'Search for [topic]', 'What time is it?', or 'Tell me a joke'."
    )


# ── Public entry point ────────────────────────────────────────────────────────

def process(user_input: str, timezone: str = "UTC") -> dict:
    """
    Main reasoning entry point.
    Returns dict: { intent: str, response: str }
    """
    if not user_input or not user_input.strip():
        return {"intent": "empty", "response": "I didn't catch that. Could you repeat?"}

    intent = _classify(user_input)

    handlers = {
        "greeting"         : lambda: _handle_greeting(timezone),
        "farewell"         : _handle_farewell,
        "thanks"           : _handle_thanks,
        "joke"             : _handle_joke,
        "time"             : lambda: _handle_time(timezone),
        "system"           : _handle_system,
        "memory_store_name": lambda: _handle_store_name(user_input),
        "memory_store_pref": lambda: _handle_store_pref(user_input),
        "memory_recall"    : _handle_recall,
        "memory_clear"     : _handle_clear,
        "search"           : lambda: _handle_search(user_input),
        "chat"             : lambda: _handle_chat(user_input),
    }

    handler = handlers.get(intent, lambda: _handle_chat(user_input))
    response = handler()

    memory.append_to_summary(f"User: {user_input[:60]}. Intent: {intent}.")

    return {"intent": intent, "response": response}
