# ====================================================================
# JARVIS OMEGA — Local Client Daemon Package
# ====================================================================
"""
Local workstation daemon subsystem. Contains the always-running daemon,
WebSocket client, state manager, task executor, and hardware listeners.
"""

__all__ = [
    "daemon",
    "websocket_client",
    "state_manager",
    "process_manager",
    "task_executor",
    "clipboard_manager",
    "microphone_listener",
    "wakeword_detector",
    "screenshot_manager",
    "filesystem_watcher",
    "workspace_scanner",
    "health_reporter",
]
