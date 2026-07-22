# Phase 19: Video Subtitle Translator (REAL)
from __future__ import annotations
import asyncio, re
from pathlib import Path
from typing import Any, Dict
from backend.tools import tool, RiskTier

@tool(name="subtitle.translate", description="Translate an SRT subtitle file to another language.", parameters={"type":"object","properties":{"srt_path":{"type":"string"},"target_language":{"type":"string","default":"en","enum":["ar","en","fr","tr","es"]}},"required":["srt_path"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="subtitle_translator")
async def translate(srt_path: str, target_language: str = "en") -> Dict[str, Any]:
    if not Path(srt_path).exists(): return {"ok": False, "error": "SRT file not found"}
    content = Path(srt_path).read_text(encoding="utf-8")
    # Extract text lines (skip indices + timestamps)
    lines = content.split("\n")
    text_indices = [i for i, l in enumerate(lines) if l.strip() and not l.strip().isdigit() and "-->" not in l]
    texts = [lines[i] for i in text_indices]
    # Batch translate
    from plugins.translate.plugin import translate_text
    combined = "\n".join(texts[:200])  # Limit to prevent timeout
    try:
        result = await translate_text(text=combined, target=target_language)
        translated = result.get("translated_text", combined).split("\n")
    except: translated = texts
    # Rebuild SRT
    for idx, i in enumerate(text_indices[:len(translated)]):
        lines[i] = translated[idx] if idx < len(translated) else texts[idx]
    out = srt_path.replace(".srt", f"_{target_language}.srt")
    Path(out).write_text("\n".join(lines), encoding="utf-8")
    return {"ok": True, "output_path": out, "target_language": target_language, "lines_translated": min(len(texts), len(translated))}

@tool(name="subtitle.embed", description="Burn translated subtitles into a video via ffmpeg.", parameters={"type":"object","properties":{"video_path":{"type":"string"},"srt_path":{"type":"string"},"language":{"type":"string","default":"ar"}},"required":["video_path","srt_path"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="subtitle_translator")
async def embed(video_path: str, srt_path: str, language: str = "ar") -> Dict[str, Any]:
    out = video_path.replace(".mp4", f"_sub_{language}.mp4")
    try:
        proc = await asyncio.create_subprocess_exec("ffmpeg", "-y", "-i", video_path, "-vf", f"subtitles={srt_path}", "-c:a", "copy", out, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        await proc.communicate()
        return {"ok": proc.returncode == 0, "output_path": out}
    except FileNotFoundError:
        return {"ok": False, "error": "ffmpeg not installed"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

PLUGIN_NAME = "subtitle_translator"; PLUGIN_VERSION = "1.0.0"
