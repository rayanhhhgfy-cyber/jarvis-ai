# ====================================================================
# JARVIS OMEGA — Hardware Scanner
# ====================================================================
"""
Specialized tool to scan local hardware specs and recommend/download LLMs.
Allows JARVIS to operate fully locally on the user's machine.
"""

from __future__ import annotations

import psutil
import platform
import time
from typing import Dict, Any
from shared.logger import get_logger

log = get_logger("hardware_scanner")

class HardwareScanner:
    def get_specs(self) -> Dict[str, Any]:
        """Returns the hardware specifications of the machine."""
        ram_gb = psutil.virtual_memory().total / (1024**3)
        cpu_count = psutil.cpu_count()

        gpu_info = "N/A"
        try:
            import subprocess
            res = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"], capture_output=True, text=True)
            if res.returncode == 0:
                gpu_info = res.stdout.strip()
        except:
            pass

        return {
            "os": platform.system(),
            "ram": round(ram_gb, 2),
            "cpu_cores": cpu_count,
            "gpu": gpu_info
        }

    def recommend_model(self, specs: Dict[str, Any]) -> Dict[str, str]:
        """Recommends a local model based on hardware specs."""
        ram = specs["ram"]
        gpu = specs["gpu"]

        if ram < 8:
            return {"name": "Gemma-2b-it", "reason": "Low RAM detect. Optimal for performance.", "size": "1.5GB"}
        elif ram < 16:
            return {"name": "Mistral-7b-v0.3", "reason": "Standard RAM. Best balance of speed and logic.", "size": "4.5GB"}
        elif ram < 32 or "NVIDIA" not in gpu:
            return {"name": "Llama-3-8b-Instruct", "reason": "High RAM. Advanced reasoning capability.", "size": "5.5GB"}
        else:
            return {"name": "Llama-3-70b-Instruct-Q4", "reason": "Workstation detected. Maximum intelligence mode.", "size": "40GB"}

    async def download_model(self, model_name: str):
        """Simulates downloading the model."""
        log.info("downloading_local_model", model=model_name)
        # In real implementation: subprocess.run(["ollama", "pull", model_name])
        return True

scanner = HardwareScanner()
