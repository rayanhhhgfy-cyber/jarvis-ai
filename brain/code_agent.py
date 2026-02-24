import requests, json, re
from config import GROQ_API_KEY, GROQ_MODEL, GROQ_URL

_SYS = """You are JARVIS, an expert software engineer AI inside a code editor.
When generating code:
1. Output ONLY the raw file content — no markdown fences, no backticks, no explanation text
2. The code must be complete and fully working
3. Add clear comments explaining what each part does
4. Follow best practices for the language

When explaining code, be concise, clear, and point out any issues."""

def _call(messages, max_tokens=2048):
    if not GROQ_API_KEY or GROQ_API_KEY == "PASTE_YOUR_NEW_KEY_HERE":
        return None, "No API key in config.py"
    try:
        r = requests.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            data=json.dumps({
                "model": GROQ_MODEL,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": 0.2
            }),
            timeout=25
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip(), None
    except Exception as e:
        return None, str(e)

def generate(prompt, current_file="", filename=""):
    ctx = ""
    if filename:     ctx += f"File: {filename}\n"
    if current_file: ctx += f"Current content:\n{current_file}\n\n"
    msg = f"{ctx}Task: {prompt}\n\nOutput the complete file content now:"
    code, err = _call([{"role":"system","content":_SYS},{"role":"user","content":msg}])
    if err:
        return {"code": "", "explanation": err, "success": False}
    code = re.sub(r'^```[\w]*\n?', '', code)
    code = re.sub(r'\n?```$', '', code)
    return {"code": code, "explanation": "Generated successfully.", "success": True}

def explain(code, filename=""):
    msg = f"Explain this code from '{filename}' clearly and concisely:\n\n{code[:3000]}"
    result, err = _call(
        [{"role":"system","content":"You are JARVIS. Explain code clearly and concisely."},
         {"role":"user","content":msg}],
        max_tokens=600
    )
    return result or f"Error: {err}"
