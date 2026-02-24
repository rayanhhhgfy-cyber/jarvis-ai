import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, "database", "memory.db")

SECRET_KEY = "jarvis-rayan-2025"
DEBUG      = True
HOST       = "0.0.0.0"
PORT       = 5000

# ── GROQ KEY (set via environment variable or Railway) ─────────────────
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
# ─────────────────────────────────────────────────────────────────────────────

GROQ_MODEL = "llama-3.3-70b-versatile"
GROQ_URL   = "https://api.groq.com/openai/v1/chat/completions"

MAX_HISTORY_TURNS   = 10
SEARCH_MAX_RESULTS  = 4
SEARCH_TIMEOUT      = 8
SUMMARY_MAX_LENGTH  = 800
SUMMARY_TRIM_LENGTH = 400
MORNING_START       = 5
AFTERNOON_START     = 12
EVENING_START       = 17
NIGHT_START         = 21
ASSISTANT_NAME      = "J.A.R.V.I.S"
TRIPO_API_KEY       = os.environ.get("TRIPO_API_KEY", "") # Get from tripo3d.ai
