from __future__ import annotations

from typing import Optional, Dict, Any

from backend.services.vision_service import vision_service
from shared.logger import get_logger

log = get_logger("captcha_solver")


class CaptchaSolver:
    """
    Vision-based CAPTCHA solver using Qwen-VL.
    Supports text CAPTCHAs, image selection, and reCAPTCHA analysis.
    """

    DETECTION_PROMPT = (
        "Analyze this image and tell me if it contains a CAPTCHA challenge. "
        "Respond with exactly one word: 'TEXT' for text-based CAPTCHA, "
        "'IMAGE' for image-selection CAPTCHA, 'RECAPTCHA' for reCAPTCHA, "
        "or 'NONE' if no CAPTCHA is present, followed by your confidence 0-100."
    )

    TEXT_SOLVE_PROMPT = (
        "This image contains a text-based CAPTCHA. "
        "Read the distorted text characters carefully and "
        "respond with ONLY the exact characters you see, no explanation."
    )

    async def detect(self, image_bytes: bytes) -> Dict[str, Any]:
        result = await vision_service.analyze_image_bytes(
            image_bytes, self.DETECTION_PROMPT
        )
        result = result.strip().upper()
        captcha_type = "NONE"
        confidence = 0
        for t in ["TEXT", "IMAGE", "RECAPTCHA", "NONE"]:
            if t in result:
                captcha_type = t
                break
        for part in result.split():
            try:
                confidence = int(part)
                break
            except ValueError:
                continue
        return {"type": captcha_type, "confidence": confidence, "raw": result}

    async def solve_text(self, image_bytes: bytes) -> Optional[str]:
        return await vision_service.analyze_image_bytes(
            image_bytes, self.TEXT_SOLVE_PROMPT
        )

    async def solve(self, image_bytes: bytes) -> Dict[str, Any]:
        detection = await self.detect(image_bytes)
        if detection["type"] == "TEXT" and detection["confidence"] > 50:
            solution = await self.solve_text(image_bytes)
            detection["solution"] = solution
        return detection


captcha_solver = CaptchaSolver()
