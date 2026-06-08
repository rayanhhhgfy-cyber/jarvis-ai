from __future__ import annotations

import asyncio
import hashlib
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx

from backend.config import settings
from backend.services.llm_service import llm_service
from shared.logger import get_logger

log = get_logger("media_generation_service")

GENERATED_DIR = Path(settings.storage_dir) / "media" / "generated"
GENERATED_DIR.mkdir(parents=True, exist_ok=True)

IMAGE_MODELS = [
    "black-forest-labs/flux-schnell",
    "black-forest-labs/flux-pro",
    "stabilityai/stable-diffusion-3.5-large",
    "stabilityai/stable-diffusion-3.5-medium",
    "openai/dall-e-3",
]

VIDEO_MODELS = [
    "luma/ray",
    "minimax/video-01",
    "kuaishou/kling-video",
]

REPLICATE_MODEL_MAP = {
    "luma/ray": "luma/ray:bedc4ff26038f5a5a11a8c38ab5721430d957c2d6e9b5f5c2ce87f1b4b1b4c1",
    "minimax/video-01": "minimax/video-01:abc123",
    "kuaishou/kling-video": "kuaishou/kling-video:def456",
}


async def generate_image(
    prompt: str,
    model: Optional[str] = None,
    size: Optional[str] = None,
) -> dict:
    model = model or IMAGE_MODELS[0]
    size = size or "1024x1024"

    log.info("generating_image", prompt=prompt[:80], model=model, size=size)

    keys = settings.get_openrouter_keys()
    if not keys:
        return {"success": False, "error": "No OpenRouter API keys configured"}

    api_key = keys[0]
    headers = {
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "https://github.com/google-deepmind/jarvis-omega",
        "X-Title": "JARVIS OMEGA Command Station",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
        "max_tokens": 2000,
    }

    if size:
        payload["size"] = size

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=payload,
            )

            if response.status_code != 200:
                log.error("image_generation_failed", status=response.status_code, body=response.text)
                return {"success": False, "error": f"OpenRouter returned {response.status_code}: {response.text[:200]}"}

            result = response.json()
            choices = result.get("choices", [])
            if not choices:
                return {"success": False, "error": "No choices in response"}

            content = choices[0].get("message", {}).get("content", "")

            image_url = _extract_image_url(content)
            if not image_url:
                return {"success": False, "error": "No image URL found in response", "content": content[:500]}

            saved = await _download_and_save(image_url, "img", prompt)
            if saved:
                return {**saved, "success": True, "prompt": prompt, "model": model}
            return {"success": False, "error": "Failed to download generated image"}

    except Exception as e:
        log.error("image_generation_exception", error=str(e))
        return {"success": False, "error": str(e)}


async def generate_video(
    prompt: str,
    model: Optional[str] = None,
    duration: Optional[int] = None,
) -> dict:
    model = model or VIDEO_MODELS[0]
    duration = duration or 5

    log.info("generating_video", prompt=prompt[:80], model=model, duration=duration)

    replicate_key = settings.replicate_api_key
    if not replicate_key:
        return {"success": False, "error": "No Replicate API key configured. Set REPLICATE_API_KEY in .env"}

    try:
        import replicate

        client = replicate.Client(api_token=replicate_key)
        model_id = REPLICATE_MODEL_MAP.get(model, REPLICATE_MODEL_MAP["luma/ray"])

        input_data = {"prompt": prompt}
        if duration:
            input_data["duration"] = duration

        loop = asyncio.get_running_loop()

        def _run_replicate():
            return client.run(model_id, input=input_data)

        output = await loop.run_in_executor(None, _run_replicate)

        video_url = None
        if isinstance(output, str):
            video_url = output
        elif isinstance(output, list):
            for item in output:
                if isinstance(item, str) and (item.startswith("http://") or item.startswith("https://")):
                    video_url = item
                    break
        elif hasattr(output, "url"):
            video_url = output.url

        if not video_url:
            return {"success": False, "error": "No video URL in Replicate response", "raw": str(output)[:300]}

        saved = await _download_and_save(video_url, "vid", prompt)
        if saved:
            return {**saved, "success": True, "prompt": prompt, "model": model, "duration": duration}
        return {"success": False, "error": "Failed to download generated video"}

    except ImportError:
        return {"success": False, "error": "Replicate package not installed. Run: pip install replicate"}
    except Exception as e:
        log.error("video_generation_exception", error=str(e))
        return {"success": False, "error": str(e)}


def _extract_image_url(content: str) -> Optional[str]:
    import re

    url_match = re.search(r"https?://[^\s\"'<>)]+\.(?:png|jpg|jpeg|gif|webp)", content, re.IGNORECASE)
    if url_match:
        return url_match.group(0)

    bracket_match = re.search(r"!\[.*?\]\((https?://[^\s\"'<>)]+)\)", content)
    if bracket_match:
        return bracket_match.group(1)

    json_match = re.search(r'"url"\s*:\s*"(https?://[^"]+)"', content)
    if json_match:
        return json_match.group(1)

    data_match = re.search(r"data:image/(?:png|jpg|jpeg|gif|webp);base64,([A-Za-z0-9+/=]+)", content)
    if data_match:
        b64_data = data_match.group(1)
        ext = "png"
        filepath = GENERATED_DIR / f"img_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.{ext}"
        import base64
        image_bytes = base64.b64decode(b64_data)
        filepath.write_bytes(image_bytes)
        log.info("saved_inline_image", path=str(filepath))
        return str(filepath)

    return None


async def _download_and_save(url: str, prefix: str, prompt: str) -> Optional[dict]:
    ext = _guess_extension(url, prefix)
    prompt_hash = hashlib.md5(prompt.encode()).hexdigest()[:8]
    filename = f"{prefix}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{prompt_hash}{ext}"
    filepath = GENERATED_DIR / filename

    try:
        async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
            response = await client.get(url)
            if response.status_code != 200:
                log.error("download_failed", url=url, status=response.status_code)
                return None
            filepath.write_bytes(response.content)
    except Exception as e:
        log.error("download_exception", url=url, error=str(e))
        return None

    mime = "image/png" if prefix == "img" else "video/mp4"
    log.info("media_saved", path=str(filepath), size=filepath.stat().st_size)
    return {
        "file_path": str(filepath),
        "url": f"/api/media/generated/{filename}",
        "mime_type": mime,
        "filename": filename,
        "size_bytes": filepath.stat().st_size,
    }


def _guess_extension(url: str, prefix: str) -> str:
    url_lower = url.lower()
    for ext in [".png", ".jpg", ".jpeg", ".gif", ".webp", ".mp4", ".webm"]:
        if ext in url_lower:
            return ext
    if prefix == "img":
        return ".png"
    return ".mp4"


async def list_generated() -> list[dict]:
    files = []
    if not GENERATED_DIR.exists():
        return files
    for f in sorted(GENERATED_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if f.is_file() and f.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".mp4", ".webm"}:
            files.append({
                "filename": f.name,
                "url": f"/api/media/generated/{f.name}",
                "size_bytes": f.stat().st_size,
                "mime_type": "image/png" if f.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp"} else "video/mp4",
                "created_at": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
            })
    return files
