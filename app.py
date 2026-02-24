from flask import Flask, render_template, request, jsonify
import requests, os, base64
from brain import time_engine, memory, llm, code_agent, vision, model3d_agent, tripo_agent
from brain import session as sess
from config import SECRET_KEY, DEBUG, HOST, PORT, SEARCH_TIMEOUT

app = Flask(__name__)
app.secret_key = SECRET_KEY

# Use /tmp for Vercel (read-only filesystem), otherwise use local directories
if os.environ.get('VERCEL'):
    PROJECTS_DIR = "/tmp/projects"
    PROJECTS_3D_DIR = "/tmp/projects/3d"
    UPLOADS_DIR = "/tmp/uploads"
else:
    PROJECTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "projects")
    PROJECTS_3D_DIR = os.path.join(PROJECTS_DIR, "3d")
    UPLOADS_DIR  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")

os.makedirs(PROJECTS_DIR, exist_ok=True)
os.makedirs(PROJECTS_3D_DIR, exist_ok=True)
os.makedirs(UPLOADS_DIR,  exist_ok=True)

# Cleanup old uploads on startup
sess.cleanup_old_uploads()

ALLOWED_EXTENSIONS = {
    "image": {"jpg","jpeg","png","gif","webp","bmp"},
    "video": {"mp4","avi","mov","mkv","webm"},
    "doc":   {"pdf","txt","md","py","js","html","css","json","csv"}
}

def detect_tz(ip):
    if not ip or ip in ("127.0.0.1","::1","localhost"): return "UTC"
    try:
        r = requests.get(f"http://ip-api.com/json/{ip}?fields=timezone,status", timeout=SEARCH_TIMEOUT)
        d = r.json()
        if d.get("status") == "success": return d.get("timezone","UTC")
    except: pass
    return "UTC"

def get_file_type(filename):
    ext = filename.rsplit(".",1)[-1].lower() if "." in filename else ""
    for ftype, exts in ALLOWED_EXTENSIONS.items():
        if ext in exts: return ftype
    return "unknown"

# ── Main routes ───────────────────────────────────────────────────────────────
@app.route("/")
def index(): return render_template("index.html")

@app.route("/chat", methods=["POST"])
def chat():
    b   = request.get_json(silent=True) or {}
    msg = b.get("message","").strip()
    tz  = b.get("timezone","UTC")
    img = b.get("image_context","")  # from camera analysis

    if not msg: return jsonify({"response":"Please send a message."})

    # Clear session
    if any(p in msg.lower() for p in ["clear session","end session","forget session","new session"]):
        deleted = sess.cleanup_session()
        llm.clear()
        memory.delete("short_conversation_summary")
        return jsonify({"response":f"Session cleared. Deleted {len(deleted)} temporary files. Learned knowledge is kept."})

    # Clear all memory including learned knowledge
    if any(p in msg.lower() for p in ["forget everything","clear all memory","reset everything","wipe everything"]):
        memory.delete("user_name")
        memory.delete("user_preferences")
        memory.delete("short_conversation_summary")
        memory.delete("learned_knowledge")
        llm.clear()
        return jsonify({"response":"Everything cleared including learned knowledge. Completely fresh start."})

    # Forget specific topic
    if "forget" in msg.lower() and "about" in msg.lower():
        topic = msg.lower().split("about",1)[-1].strip()
        result = sess.forget_topic(topic)
        return jsonify({"response": result})

    response = llm.chat(msg, tz=tz, image_context=img)
    return jsonify({"response": response})

@app.route("/region")
def region():
    fwd = request.headers.get("X-Forwarded-For","")
    ip  = fwd.split(",")[0].strip() if fwd else request.remote_addr
    return jsonify({"timezone": detect_tz(ip)})

@app.route("/time")
def current_time():
    return jsonify(time_engine.get_time_info(request.args.get("tz","UTC")))

# ── File upload ───────────────────────────────────────────────────────────────
@app.route("/upload", methods=["POST"])
def upload():
    if "file" not in request.files:
        return jsonify({"error":"No file provided"}), 400

    f       = request.files["file"]
    question= request.form.get("question","Describe this in detail.")
    save_it = request.form.get("save","false").lower() == "true"

    if not f.filename:
        return jsonify({"error":"Empty filename"}), 400

    ftype = get_file_type(f.filename)
    fname = f.filename.replace(" ","_")
    fpath = os.path.join(UPLOADS_DIR, fname)
    f.save(fpath)

    # Track for session cleanup unless user wants to save
    if not save_it:
        sess.track_file(fpath)

    result = ""
    if ftype == "image":
        result = vision.analyze_image(fpath, question)
    elif ftype == "video":
        result = vision.analyze_video_frames(fpath, question)
    elif ftype == "doc":
        try:
            with open(fpath, "r", encoding="utf-8", errors="replace") as tf:
                content = tf.read(4000)
            msgs = [
                {"role":"system","content":"You are JARVIS. Answer questions about this document concisely."},
                {"role":"user","content":f"Document content:\n{content}\n\nQuestion: {question}"}
            ]
            import json as _json
            r = requests.post("https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization":f"Bearer {__import__('config').GROQ_API_KEY}","Content-Type":"application/json"},
                data=_json.dumps({"model":__import__('config').GROQ_MODEL,"messages":msgs,"max_tokens":512}),
                timeout=15)
            result = r.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            result = f"Error reading document: {str(e)}"
    else:
        result = f"File '{fname}' received but type not supported for analysis."

    return jsonify({"response": result, "filename": fname, "type": ftype, "saved": save_it})

# ── Camera frame analysis ─────────────────────────────────────────────────────
@app.route("/analyze_frame", methods=["POST"])
def analyze_frame():
    """Receive a base64 frame from the browser webcam and analyze it."""
    b = request.get_json(silent=True) or {}
    frame_b64 = b.get("frame","")
    question  = b.get("question","What do you see? Describe in detail.")

    if not frame_b64:
        return jsonify({"description":"No frame received."})

    try:
        # Remove data URL prefix if present
        if "," in frame_b64:
            frame_b64 = frame_b64.split(",",1)[1]
        image_bytes = base64.b64decode(frame_b64)
        description = vision.analyze_image_bytes(image_bytes, question)
        return jsonify({"description": description})
    except Exception as e:
        return jsonify({"description": f"Frame analysis error: {str(e)}"})

# ── Knowledge base routes ─────────────────────────────────────────────────────
@app.route("/knowledge")
def get_knowledge():
    """Return what JARVIS has learned."""
    kb = sess.get_knowledge_base()
    return jsonify({"knowledge": kb, "count": len(kb)})

@app.route("/knowledge/forget", methods=["POST"])
def forget_knowledge():
    b = request.get_json(silent=True) or {}
    topic = b.get("topic","")
    result = sess.forget_topic(topic)
    return jsonify({"result": result})

# ── Studio routes ─────────────────────────────────────────────────────────────
@app.route("/studio")
def studio(): return render_template("studio.html")

@app.route("/studio3d")
def studio3d(): return render_template("studio3d.html")

@app.route("/studio3d/generate", methods=["POST"])
def studio3d_generate():
    b = request.get_json(silent=True) or {}
    prompt = b.get("prompt", "").strip()
    if not prompt:
        return jsonify({"error": "No prompt provided", "success": False}), 400
    result = model3d_agent.generate(prompt)
    return jsonify(result)

@app.route("/studio3d/modify", methods=["POST"])
def studio3d_modify():
    b = request.get_json(silent=True) or {}
    prompt = b.get("prompt", "").strip()
    scene = b.get("scene_objects", [])
    if not prompt:
        return jsonify({"error": "No prompt provided", "success": False}), 400
    result = model3d_agent.modify(prompt, scene)
    return jsonify(result)

@app.route("/studio3d/save", methods=["POST"])
def studio3d_save():
    b = request.get_json(silent=True) or {}
    name = b.get("name", "").strip()
    scene = b.get("scene", [])
    if not name: return jsonify({"error": "No project name", "success": False}), 400
    if not name.endswith(".json"): name += ".json"
    full_path = os.path.join(PROJECTS_3D_DIR, name)
    try:
        with open(full_path, "w", encoding="utf-8") as f:
            json.dump(scene, f, indent=2)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e), "success": False}), 500

@app.route("/studio3d/list")
def studio3d_list():
    files = [f for f in os.listdir(PROJECTS_3D_DIR) if f.endswith(".json")]
    return jsonify({"projects": files, "success": True})

@app.route("/studio3d/load", methods=["POST"])
def studio3d_load():
    b = request.get_json(silent=True) or {}
    name = b.get("name", "").strip()
    if not name: return jsonify({"error": "No project name", "success": False}), 400
    full_path = os.path.join(PROJECTS_3D_DIR, name)
    try:
        with open(full_path, "r", encoding="utf-8") as f:
            scene = json.load(f)
        return jsonify({"scene": scene, "success": True})
    except Exception as e:
        return jsonify({"error": str(e), "success": False}), 500

@app.route("/studio3d/generate_highpoly", methods=["POST"])
def studio3d_generate_highpoly():
    b = request.get_json(silent=True) or {}
    prompt = b.get("prompt", "").strip()
    if not prompt:
        return jsonify({"error": "No prompt provided", "success": False}), 400
    result = tripo_agent.create_task(prompt)
    return jsonify(result)

@app.route("/studio3d/task_status/<task_id>")
def studio3d_task_status(task_id):
    result = tripo_agent.get_status(task_id)
    return jsonify(result)

    def build(path, base):
        tree = []
        try:
            for e in sorted(os.scandir(path), key=lambda x:(not x.is_dir(),x.name)):
                rel = os.path.relpath(e.path, base).replace("\\","/")
                if e.name.startswith("."): continue
                if e.is_dir():
                    tree.append({"name":e.name,"path":rel,"type":"folder","children":build(e.path,base)})
                else:
                    tree.append({"name":e.name,"path":rel,"type":"file"})
        except: pass
        return tree
    return jsonify({"tree": build(PROJECTS_DIR, PROJECTS_DIR)})

@app.route("/studio/read", methods=["POST"])
def studio_read():
    b    = request.get_json(silent=True) or {}
    full = os.path.normpath(os.path.join(PROJECTS_DIR, b.get("path","")))
    if not full.startswith(PROJECTS_DIR): return jsonify({"error":"Access denied"}),403
    try:    return jsonify({"content": open(full,encoding="utf-8",errors="replace").read()})
    except: return jsonify({"error":"File not found"}),404

@app.route("/studio/write", methods=["POST"])
def studio_write():
    b    = request.get_json(silent=True) or {}
    full = os.path.normpath(os.path.join(PROJECTS_DIR, b.get("path","")))
    if not full.startswith(PROJECTS_DIR): return jsonify({"error":"Access denied"}),403
    os.makedirs(os.path.dirname(full), exist_ok=True)
    open(full,"w",encoding="utf-8").write(b.get("content",""))
    return jsonify({"success":True})

@app.route("/studio/delete", methods=["POST"])
def studio_delete():
    b    = request.get_json(silent=True) or {}
    full = os.path.normpath(os.path.join(PROJECTS_DIR, b.get("path","")))
    if not full.startswith(PROJECTS_DIR): return jsonify({"error":"Access denied"}),403
    try:
        os.rmdir(full) if os.path.isdir(full) else os.remove(full)
        return jsonify({"success":True})
    except Exception as e: return jsonify({"error":str(e)}),400

@app.route("/studio/ai", methods=["POST"])
def studio_ai():
    b = request.get_json(silent=True) or {}
    if not b.get("prompt"): return jsonify({"error":"No prompt"}),400
    return jsonify(code_agent.generate(b.get("prompt",""),b.get("current_file",""),b.get("filename","")))

@app.route("/studio/explain", methods=["POST"])
def studio_explain():
    b = request.get_json(silent=True) or {}
    return jsonify({"explanation": code_agent.explain(b.get("code",""),b.get("filename",""))})

if __name__ == "__main__":
    app.run(host=HOST, port=PORT, debug=DEBUG)
