# ====================================================================
# JARVIS OMEGA — Vision Service (Qwen 2.5 VL via OpenRouter)
# ====================================================================
"""
Vision Service using Qwen 2.5 VL via OpenRouter. Handles image encoding,
screenshot upload processing, structural element detection, and OCR.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Optional, Dict, Any

import httpx

from backend.config import settings
from shared.logger import get_logger

log = get_logger("vision_service")


class VisionService:
    """
    Communicates with OpenRouter Cloud to route visual inspection requests
    to Qwen 2.5 VL. Enables screen/window OCR and UI layout analysis.
    """

    def __init__(self) -> None:
        self._api_url = "https://openrouter.ai/api/v1/chat/completions"

    async def analyze_image_file(self, file_path: str | Path, prompt: str) -> str:
        """Analyze a local screenshot/image file on disk."""
        path = Path(file_path)
        if not path.exists():
            log.error("vision_image_not_found", path=str(path))
            return "Error: Image file not found"

        try:
            image_bytes = path.read_bytes()
            return await self.analyze_image_bytes(image_bytes, prompt)
        except Exception as e:
            log.error("analyze_image_file_failed", file=str(path), error=str(e))
            return f"Error: Image analysis failed: {str(e)}"

    async def analyze_image_bytes(self, image_bytes: bytes, prompt: str) -> str:
        """Encode raw bytes to base64 and analyze via Qwen 2.5 VL on OpenRouter."""
        try:
            base64_image = base64.b64encode(image_bytes).decode("utf-8")
            return await self._call_openrouter_vision(base64_image, prompt)
        except Exception as e:
            log.error("analyze_image_bytes_failed", error=str(e))
            return f"Error: Image analysis failed: {str(e)}"

    async def _call_openrouter_vision(self, base64_image: str, prompt: str) -> str:
        """Performs the POST request to OpenRouter Chat API with key rotation."""
        keys = settings.get_openrouter_keys()
        if not keys:
            log.warning("openrouter_api_key_missing_mocking_vision")
            return "[Mock Vision Output: Please configure OPENROUTER_API_KEY in your environment]"

        # Format according to OpenRouter's vision specification
        payload = {
            "model": settings.qwen_vision_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt,
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{base64_image}"
                            }
                        }
                    ]
                }
            ],
            "temperature": 0.2,
        }

        last_error = ""
        for api_key in keys:
            headers = {
                "Authorization": f"Bearer {api_key}",
                "HTTP-Referer": "https://github.com/google-deepmind/jarvis-omega",
                "X-Title": "JARVIS OMEGA Command Station",
                "Content-Type": "application/json",
            }

            async with httpx.AsyncClient(timeout=90.0) as client:
                try:
                    response = await client.post(
                        self._api_url,
                        headers=headers,
                        json=payload,
                    )

                    if response.status_code == 401:
                        log.warning("openrouter_vision_key_401_rotating")
                        last_error = "All vision API keys returned 401"
                        continue

                    if response.status_code != 200:
                        log.error("openrouter_vision_error", status_code=response.status_code, body=response.text)
                        continue

                    result_json = response.json()
                    choices = result_json.get("choices", [])
                    if not choices:
                        log.error("openrouter_vision_empty_choices", response=result_json)
                        continue

                    analysis = choices[0].get("message", {}).get("content", "").strip()
                    log.info("image_analysis_successful", length=len(analysis))
                    return analysis

                except httpx.HTTPError as he:
                    log.error("openrouter_vision_http_failed", error=str(he))
                    continue

        log.error("openrouter_vision_all_keys_failed", error=last_error)
        if last_error:
            return f"Error: {last_error}"
        return "Error: All OpenRouter keys failed for vision request"


# Global vision service instance
vision_service = VisionService()
