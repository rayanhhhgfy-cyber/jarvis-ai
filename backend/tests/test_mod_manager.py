# ====================================================================
# JARVIS OMEGA — Universal Smart Modder Unit Tests
# ====================================================================
"""
Unit tests for ModManagerService, testing paths, database serialization,
and mod downloading/installation/uninstallation simulations.
"""

import io
import json
import os
import pytest
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch
from backend.services.mod_manager_service import ModManagerService, GAME_PRESETS

TEST_STORAGE_DIR = Path("./storage/test_mods_temp")
TEST_WORKSPACE_DIR = Path("./workspace/test_mods_temp")

@pytest.fixture
def anyio_backend():
    return "asyncio"

@pytest.fixture
def mod_service():
    # Setup test directories
    if TEST_STORAGE_DIR.exists():
        shutil.rmtree(TEST_STORAGE_DIR)
    if TEST_WORKSPACE_DIR.exists():
        shutil.rmtree(TEST_WORKSPACE_DIR)
        
    TEST_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    TEST_WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    
    # Patch DB and workspace settings
    with patch("backend.services.mod_manager_service.MODS_DB_PATH", TEST_STORAGE_DIR / "mods_db.json"):
        with patch("backend.services.mod_manager_service.settings") as mock_settings:
            mock_settings.storage_dir = str(TEST_STORAGE_DIR)
            mock_settings.workspace_dir = str(TEST_WORKSPACE_DIR)
            
            service = ModManagerService()
            yield service
            
    # Teardown test directories
    if TEST_STORAGE_DIR.exists():
        shutil.rmtree(TEST_STORAGE_DIR)
    if TEST_WORKSPACE_DIR.exists():
        shutil.rmtree(TEST_WORKSPACE_DIR)

def test_preset_detection(mod_service):
    """Test game preset definitions and custom path overriding."""
    minecraft_dir = mod_service.get_game_dir("minecraft")
    assert minecraft_dir is not None
    assert str(minecraft_dir).endswith(".minecraft")
    
    # Custom override
    custom_path = r"C:\Custom\Minecraft"
    mod_service.set_game_dir("minecraft", custom_path)
    assert mod_service.get_game_dir("minecraft") == Path(custom_path)
    
    # Verify saved to DB
    assert mod_service.db["config_minecraft_dir"] == custom_path

@pytest.mark.anyio
@patch("urllib.request.urlopen")
async def test_mod_install_uninstall(mock_urlopen, mod_service):
    """Test mod installation (copy unzip behavior) and uninstallation."""
    # 1. Setup mock URL download
    mock_response = MagicMock()
    mock_response.headers = {}
    mock_response.read.side_effect = [b"dummy jar content", b""]
    # open uses context manager protocol
    mock_urlopen.return_value.__enter__.return_value = mock_response
    
    # Override directories to test sandbox path
    game_dir = TEST_WORKSPACE_DIR / "game_sandbox"
    game_dir.mkdir(parents=True, exist_ok=True)
    mod_service.set_game_dir("minecraft", str(game_dir))
    
    # Install Minecraft mod (unzip_behavior = copy)
    install_res = await mod_service.install_mod("minecraft", "https://example.com/optifine.jar")
    assert install_res["success"] is True
    assert "optifine" in install_res["message"]
    
    # Verify files created on disk
    mod_file = game_dir / "mods" / "optifine.jar"
    assert mod_file.exists() is True
    
    # Check database status
    games = mod_service.scan_installed_games()
    minecraft_status = next(g for g in games if g["game_id"] == "minecraft")
    assert minecraft_status["detected"] is True
    assert len(minecraft_status["installed_mods"]) == 1
    assert minecraft_status["installed_mods"][0]["name"] == "optifine"
    
    # 2. Uninstall mod
    uninstall_res = await mod_service.uninstall_mod("minecraft", "optifine")
    assert uninstall_res["success"] is True
    assert mod_file.exists() is False
    
    # Check database status again
    games_after = mod_service.scan_installed_games()
    minecraft_status_after = next(g for g in games_after if g["game_id"] == "minecraft")
    assert len(minecraft_status_after["installed_mods"]) == 0
