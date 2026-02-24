# =============================================================================
# brain/vision.py — Image and video frame analysis using Groq vision
# Groq supports llama-4-scout which can see images (free)
# =============================================================================

import requests, json, base64, os
from config import GROQ_API_KEY

# Groq vision model — free, sees images
VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
GROQ_URL     = "https://api.groq.com/openai/v1/chat/completions"


def _encode_image(image_path: str) -> tuple[str, str]:
    """
    Read an image file and return (base64_string, mime_type).
    Supports jpg, png, gif, webp.
    """
    ext = image_path.split(".")[-1].lower()
    mime_map = {"jpg": "image/jpeg", "jpeg": "image/jpeg",
                "png": "image/png", "gif": "image/gif", "webp": "image/webp"}
    mime = mime_map.get(ext, "image/jpeg")
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    return b64, mime


def _encode_image_bytes(image_bytes: bytes, mime: str = "image/jpeg") -> str:
    """Encode raw bytes to base64."""
    return base64.b64encode(image_bytes).decode("utf-8")


def analyze_image(image_path: str, question: str = "Describe what you see in detail.") -> str:
    """
    Send an image to Groq vision model and get a description/answer.
    Works with any image file path.
    """
    if not GROQ_API_KEY or GROQ_API_KEY == "PASTE_YOUR_NEW_KEY_HERE":
        return "No API key configured."

    try:
        b64, mime = _encode_image(image_path)
        messages = [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                {"type": "text", "text": question}
            ]
        }]
        r = requests.post(GROQ_URL,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            data=json.dumps({"model": VISION_MODEL, "messages": messages, "max_tokens": 1024}),
            timeout=20)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"Vision analysis error: {str(e)}"


def analyze_image_bytes(image_bytes: bytes, question: str = "Describe what you see in detail.", mime: str = "image/jpeg") -> str:
    """
    Analyze raw image bytes — used for camera frame analysis.
    """
    if not GROQ_API_KEY or GROQ_API_KEY == "PASTE_YOUR_NEW_KEY_HERE":
        return "No API key configured."

    try:
        b64 = _encode_image_bytes(image_bytes, mime)
        messages = [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                {"type": "text", "text": question}
            ]
        }]
        r = requests.post(GROQ_URL,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            data=json.dumps({"model": VISION_MODEL, "messages": messages, "max_tokens": 512}),
            timeout=15)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"Camera analysis error: {str(e)}"


def analyze_video_frames(video_path: str, question: str = "Describe what happens in this video.") -> str:
    """
    Extract frames from a video and analyze them.
    Uses opencv if available, otherwise extracts first frame only.
    """
    try:
        import cv2
        cap = cv2.VideoCapture(video_path)
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps   = cap.get(cv2.CAP_PROP_FPS) or 30
        # Sample up to 4 frames evenly across the video
        sample_frames = [0, total//3, (2*total)//3, total-1]
        frames_b64 = []
        for idx in sample_frames:
            cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, idx))
            ret, frame = cap.read()
            if ret:
                _, buf = cv2.imencode(".jpg", frame)
                frames_b64.append(base64.b64encode(buf).decode("utf-8"))
        cap.release()

        if not frames_b64:
            return "Could not extract frames from video."

        # Build multi-image message
        content = [{"type": "text", "text": f"These are {len(frames_b64)} frames from a video. {question}"}]
        for b64 in frames_b64:
            content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})

        r = requests.post(GROQ_URL,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            data=json.dumps({"model": VISION_MODEL, "messages": [{"role":"user","content":content}], "max_tokens": 1024}),
            timeout=25)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()

    except ImportError:
        # opencv not available — analyze just the file info
        size = os.path.getsize(video_path)
        return f"Video file received ({size//1024}KB). Install opencv-python for frame analysis: pip install opencv-python"
    except Exception as e:
        return f"Video analysis error: {str(e)}"
