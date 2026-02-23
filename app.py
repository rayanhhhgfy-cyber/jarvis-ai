# =============================================================================
# app.py — JARVIS Flask Server
# =============================================================================

from flask import Flask, render_template, request, jsonify
import requests

from brain import time_engine, memory
from brain import llm
from config import SECRET_KEY, DEBUG, HOST, PORT, SEARCH_TIMEOUT

app = Flask(__name__)
app.secret_key = SECRET_KEY


def _detect_timezone(ip):
    if not ip or ip in ("127.0.0.1", "::1", "localhost"):
        return "UTC"
    try:
        resp = requests.get(
            f"http://ip-api.com/json/{ip}?fields=timezone,status",
            timeout=SEARCH_TIMEOUT
        )
        data = resp.json()
        if data.get("status") == "success":
            return data.get("timezone", "UTC")
    except Exception:
        pass
    return "UTC"


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/chat", methods=["POST"])
def chat():
    """Main chat endpoint — routes all messages through Groq LLM."""
    body     = request.get_json(silent=True) or {}
    user_msg = body.get("message", "").strip()
    timezone = body.get("timezone", "UTC")

    if not user_msg:
        return jsonify({"response": "Please send a message."})

    # Clear memory/history if user asks
    if any(p in user_msg.lower() for p in ["forget everything","clear memory","reset memory","wipe memory"]):
        memory.delete("user_name")
        memory.delete("user_preferences")
        memory.delete("short_conversation_summary")
        llm.clear_history()
        return jsonify({"response": "Memory and conversation history cleared. Fresh start!"})

    response = llm.chat(user_msg, timezone=timezone)
    return jsonify({"response": response})


@app.route("/region")
def region():
    forwarded = request.headers.get("X-Forwarded-For", "")
    ip        = forwarded.split(",")[0].strip() if forwarded else request.remote_addr
    timezone  = _detect_timezone(ip)
    return jsonify({"timezone": timezone, "ip": ip})


@app.route("/time")
def current_time():
    tz   = request.args.get("tz", "UTC")
    info = time_engine.get_time_info(tz)
    return jsonify(info)


if __name__ == "__main__":
    app.run(host=HOST, port=PORT, debug=DEBUG)
