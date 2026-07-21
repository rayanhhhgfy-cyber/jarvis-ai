# ====================================================================
# JARVIS OMEGA — Local State Manager
# ====================================================================
"""
Manages local client daemon settings, authentication credentials (tokens),
cached tasks, process states, and persistent configuration.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Any

from shared.logger import get_logger

log = get_logger("local_state_manager")


class LocalStateManager:
    """
    Handles local state persistence: auth tokens, device identity,
    offline tasks caching, and configuration parameters.
    """

    def __init__(self, config_dir: str = "./config") -> None:
        self._config_path = Path(config_dir) / "client_config.json"
        self._state: Dict[str, Any] = {
            "device_id": "local_daemon_client",
            "device_name": "Sir's Workstation",
            "device_secret": "",
            "access_token": "",
            "refresh_token": "",
            "paired": False,
            "backend_url": "http://localhost:8000",
            "ws_url": "ws://localhost:8000/ws",
            "workspace_path": "./workspace",
        }
        self.running_tasks: Dict[str, Any] = {}
        self.initialize()

    def initialize(self) -> None:
        """Loads client configuration from disk."""
        if self._config_path.exists():
            try:
                data = json.loads(self._config_path.read_text(encoding="utf-8"))
                self._state.update(data)
                log.info("local_client_config_loaded", device_id=self.device_id)
            except Exception as e:
                log.error("local_config_load_failed", error=str(e))
        else:
            self.save()

    def save(self) -> None:
        """Saves current state variables to disk."""
        try:
            self._config_path.parent.mkdir(parents=True, exist_ok=True)
            self._config_path.write_text(json.dumps(self._state, indent=2), encoding="utf-8")
            log.debug("local_client_config_saved")
        except Exception as e:
            log.error("local_config_save_failed", error=str(e))

    @property
    def device_id(self) -> str:
        return self._state["device_id"]

    @device_id.setter
    def device_id(self, val: str) -> None:
        self._state["device_id"] = val
        self.save()

    @property
    def device_name(self) -> str:
        return self._state["device_name"]

    @property
    def device_secret(self) -> str:
        return self._state["device_secret"]

    @device_secret.setter
    def device_secret(self, val: str) -> None:
        self._state["device_secret"] = val
        self.save()

    @property
    def access_token(self) -> str:
        return self._state["access_token"]

    @access_token.setter
    def access_token(self, val: str) -> None:
        self._state["access_token"] = val
        self.save()

    @property
    def refresh_token(self) -> str:
        return self._state["refresh_token"]

    @refresh_token.setter
    def refresh_token(self, val: str) -> None:
        self._state["refresh_token"] = val
        self.save()

    @property
    def paired(self) -> bool:
        return self._state["paired"]

    @paired.setter
    def paired(self, val: bool) -> None:
        self._state["paired"] = val
        self.save()

    @property
    def backend_url(self) -> str:
        return self._state["backend_url"]

    @property
    def ws_url(self) -> str:
        return self._state["ws_url"]

    @property
    def workspace_path(self) -> str:
        return self._state["workspace_path"]


# Global local state manager
local_state_manager = LocalStateManager()
