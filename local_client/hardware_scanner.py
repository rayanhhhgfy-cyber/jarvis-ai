# ====================================================================
# JARVIS OMEGA — Hardware Scanner
# ====================================================================
"""
Scans the local machine's hardware capabilities.
Recommends and provisions local LLMs (Llama 3, Mistral, etc.) based on VRAM/RAM.
"""

from __future__ import annotations

import psutil
import platform
import subprocess
from typing import Dict, Any, List
from shared.logger import get_logger

log = get_logger("hardware_scanner")

class HardwareScanner:
    """
    Detects CPU, RAM, and GPU to determine if a local LLM can be hosted.
    """

    def scan(self) -> Dict[str, Any]:
        log.info("scanning_hardware")

        mem = psutil.virtual_memory()
        cpu_count = psutil.cpu_count(logical=False)

        gpu_info = self._get_gpu_info()

        specs = {
            "os": platform.system(),
            "cpu_cores": cpu_count,
            "ram_total_gb": round(mem.total / (1024**3), 2),
            "ram_available_gb": round(mem.available / (1024**3), 2),
            "gpu": gpu_info
        }

        recommendation = self._get_recommendation(specs)
        specs["recommendation"] = recommendation

        log.info("scan_complete", recommendation=recommendation["model"])
        return specs

    def _get_gpu_info(self) -> List[Dict[str, Any]]:
        """Tries to detect NVIDIA GPUs via nvidia-smi."""
        try:
            output = subprocess.check_output(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"], text=True)
            gpus = []
            for line in output.strip().split("\n"):
                name, vram = line.split(", ")
                gpus.append({"name": name, "vram_mb": int(vram)})
            return gpus
        except:
            return []

    def _get_recommendation(self, specs: Dict[str, Any]) -> Dict[str, Any]:
        """Recommends a local model based on specs."""
        total_vram = sum(g["vram_mb"] for g in specs["gpu"])
        ram = specs["ram_total_gb"]

        if total_vram >= 24000:
            return {"name": "Llama-3-70B (Quantized)", "reason": "Supreme performance detected", "engine": "Ollama / vLLM"}
        elif total_vram >= 8000 or ram >= 32:
            return {"name": "Llama-3-8B / Mistral-7B", "reason": "High-end consumer hardware", "engine": "Ollama"}
        elif ram >= 16:
            return {"name": "Phi-3 Mini / TinyLlama", "reason": "Standard multi-tasking setup", "engine": "Ollama"}
        else:
            return {"name": "None (Cloud Only Recommended)", "reason": "Insufficient local resources", "engine": "OpenAI/Claude API"}

    def get_specs(self) -> Dict[str, Any]:
        """Alias for compatibility with legacy calls."""
        res = self.scan()
        return {
            "ram": res["ram_total_gb"],
            "cpu": res["cpu_cores"],
            "gpu": res["gpu"]
        }

    def recommend_model(self, specs: Dict[str, Any]) -> Dict[str, Any]:
        """Alias for compatibility with legacy calls."""
        return self._get_recommendation({
            "gpu": specs.get("gpu", []),
            "ram_total_gb": specs.get("ram", 16)
        })

    async def download_model(self, model_name: str) -> bool:
        """Triggers local model download via Ollama."""
        log.info("triggering_model_download", model=model_name)
        try:
            # Command: ollama pull <model>
            subprocess.run(["ollama", "pull", model_name], check=True)
            return True
        except:
            return False

# Global Instance
hardware_scanner = HardwareScanner()
scanner = hardware_scanner # Legacy alias
