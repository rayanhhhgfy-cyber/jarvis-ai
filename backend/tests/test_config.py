# ====================================================================
# JARVIS OMEGA — Config Unit Tests
# ====================================================================
"""
Unit tests for backend configuration and settings initialization.
"""

from pathlib import Path
from backend.config import settings


def test_settings_initialization():
    """Verify that settings default values and type conversions are correct."""
    assert settings.backend_port == 8000
    assert isinstance(settings.backend_cors_origins, list)
    assert settings.log_level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


def test_directory_creation(tmp_path):
    """Verify directories can be created correctly if they don't exist."""
    # Use a temporary directory for test storage paths
    old_storage = settings.storage_dir
    old_logs = settings.logs_dir
    old_workspace = settings.workspace_dir
    old_memory = settings.memory_dir
    old_cache = settings.cache_dir
    old_backups = settings.backups_dir
    old_chroma = settings.chroma_persist_dir

    settings.storage_dir = str(tmp_path / "storage")
    settings.logs_dir = str(tmp_path / "logs")
    settings.workspace_dir = str(tmp_path / "workspace")
    settings.memory_dir = str(tmp_path / "memory")
    settings.cache_dir = str(tmp_path / "cache")
    settings.backups_dir = str(tmp_path / "backups")
    settings.chroma_persist_dir = str(tmp_path / "chromadb")
    
    settings.ensure_directories()
    
    assert (tmp_path / "storage").exists()
    assert (tmp_path / "logs").exists()
    assert (tmp_path / "workspace").exists()
    assert (tmp_path / "memory").exists()
    assert (tmp_path / "cache").exists()
    assert (tmp_path / "backups").exists()
    assert (tmp_path / "chromadb").exists()
    
    # Restore original settings
    settings.storage_dir = old_storage
    settings.logs_dir = old_logs
    settings.workspace_dir = old_workspace
    settings.memory_dir = old_memory
    settings.cache_dir = old_cache
    settings.backups_dir = old_backups
    settings.chroma_persist_dir = old_chroma

