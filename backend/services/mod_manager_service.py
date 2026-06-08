# ====================================================================
# JARVIS OMEGA — Universal Smart Modder Service
# ====================================================================
"""
Universal Smart Modder Service.
Handles auto-detection of game mod directories, downloading mods,
and installing/unzipping them to the correct game paths.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import urllib.request
import urllib.parse
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.config import settings
from shared.logger import get_logger

log = get_logger("mod_manager_service")

# Database of installed mods
MODS_DB_PATH = Path(settings.storage_dir) / "mods_db.json"


@dataclass
class GameInfo:
    game_id: str
    name: str
    default_dir: str  # Path string, can contain env variables
    mod_subfolder: str  # Folder name under default_dir (or empty if root)
    file_types: List[str]  # Supported file extensions
    unzip_behavior: str  # "copy" (place zip/jar directly) or "extract" (unzip files)


# Supported games configuration
GAME_PRESETS: Dict[str, GameInfo] = {
    "minecraft": GameInfo(
        game_id="minecraft",
        name="Minecraft",
        default_dir=os.path.expandvars(r"%APPDATA%\.minecraft"),
        mod_subfolder="mods",
        file_types=[".jar", ".zip"],
        unzip_behavior="copy",
    ),
    "stardew": GameInfo(
        game_id="stardew",
        name="Stardew Valley",
        default_dir=r"C:\Program Files (x86)\Steam\steamapps\common\Stardew Valley",
        mod_subfolder="Mods",
        file_types=[".zip"],
        unzip_behavior="extract",
    ),
    "skyrim": GameInfo(
        game_id="skyrim",
        name="Skyrim Special Edition",
        default_dir=r"C:\Program Files (x86)\Steam\steamapps\common\Skyrim Special Edition",
        mod_subfolder="Data",
        file_types=[".esp", ".esm", ".bsa", ".zip"],
        unzip_behavior="extract",
    ),
    "terraria": GameInfo(
        game_id="terraria",
        name="Terraria (tModLoader)",
        default_dir=os.path.expandvars(r"%USERPROFILE%\Documents\My Games\Terraria\tModLoader"),
        mod_subfolder="Mods",
        file_types=[".tmod", ".zip"],
        unzip_behavior="copy",
    ),
    "gtav": GameInfo(
        game_id="gtav",
        name="Grand Theft Auto V",
        default_dir=r"C:\Program Files (x86)\Steam\steamapps\common\Grand Theft Auto V",
        mod_subfolder="",
        file_types=[".asi", ".dll", ".zip"],
        unzip_behavior="extract",
    ),
}


class ModManagerService:
    def __init__(self) -> None:
        self.db_path = MODS_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.temp_dir = Path(settings.workspace_dir) / "temp" / "mods"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self._load_db()

    def _load_db(self) -> None:
        """Load the installed mods database from disk."""
        if self.db_path.exists():
            try:
                self.db = json.loads(self.db_path.read_text(encoding="utf-8"))
            except Exception as e:
                log.error("load_mods_db_failed", error=str(e))
                self.db = {}
        else:
            self.db = {}

    def _save_db(self) -> None:
        """Save the database to disk."""
        try:
            self.db_path.write_text(json.dumps(self.db, indent=2), encoding="utf-8")
        except Exception as e:
            log.error("save_mods_db_failed", error=str(e))

    def get_game_dir(self, game_id: str) -> Optional[Path]:
        """Get the game's actual directory, allowing custom overrides stored in the DB."""
        preset = GAME_PRESETS.get(game_id)
        if not preset:
            return None

        # Check for custom override path in DB
        custom_path = self.db.get(f"config_{game_id}_dir")
        if custom_path:
            return Path(custom_path)

        return Path(preset.default_dir)

    def set_game_dir(self, game_id: str, custom_path: str) -> None:
        """Store a custom directory override for a game."""
        if game_id in GAME_PRESETS:
            self.db[f"config_{game_id}_dir"] = custom_path
            self._save_db()
            log.info("game_dir_updated", game_id=game_id, path=custom_path)

    def get_mod_dir(self, game_id: str) -> Optional[Path]:
        """Get the full path to the folder where mods should be placed."""
        game_dir = self.get_game_dir(game_id)
        if not game_dir:
            return None

        preset = GAME_PRESETS[game_id]
        if preset.mod_subfolder:
            return game_dir / preset.mod_subfolder
        return game_dir

    def scan_installed_games(self) -> List[Dict[str, Any]]:
        """Scan system to check which games are installed based on default paths."""
        results = []
        for game_id, preset in GAME_PRESETS.items():
            game_dir = self.get_game_dir(game_id)
            mod_dir = self.get_mod_dir(game_id)
            
            detected = game_dir.exists() if game_dir else False
            mods = self.db.get(game_id, [])

            results.append({
                "game_id": game_id,
                "name": preset.name,
                "detected": detected,
                "game_dir": str(game_dir) if game_dir else "",
                "mod_dir": str(mod_dir) if mod_dir else "",
                "installed_mods": mods,
                "file_types": preset.file_types,
            })
        return results

    async def download_file(self, url: str) -> Path:
        """Asynchronously download a file from a URL to the temporary folder."""
        # Simple HTTP client execution inside thread-pool to avoid blocking
        parsed_url = urllib.parse.urlparse(url)
        filename = os.path.basename(parsed_url.path) or "mod_download.zip"
        
        # Clean illegal filename characters
        filename = "".join(c for c in filename if c.isalnum() or c in (".", "-", "_"))
        if not filename:
            filename = "mod_download.zip"
            
        target_path = self.temp_dir / filename

        def _download():
            nonlocal target_path
            log.info("downloading_mod", url=url, target=str(target_path))
            req = urllib.request.Request(
                url, 
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) JarvisOmegaModder"}
            )
            with urllib.request.urlopen(req) as response, open(target_path, "wb") as out_file:
                # Resolve final filename from headers if present
                cd = response.headers.get("Content-Disposition")
                if cd and "filename=" in cd:
                    try:
                        resolved_name = cd.split("filename=")[1].strip('"\'')
                        resolved_name = "".join(c for c in resolved_name if c.isalnum() or c in (".", "-", "_"))
                        if resolved_name:
                            target_path = self.temp_dir / resolved_name
                    except Exception:
                        pass
                shutil.copyfileobj(response, out_file)
            return target_path

        return await asyncio.to_thread(_download)

    async def install_mod(self, game_id: str, mod_url: str) -> Dict[str, Any]:
        """Download and install a mod for a given game."""
        preset = GAME_PRESETS.get(game_id)
        if not preset:
            return {"success": False, "message": f"Unsupported game: {game_id}"}

        mod_dir = self.get_mod_dir(game_id)
        if not mod_dir:
            return {"success": False, "message": f"Could not resolve mod folder for {preset.name}"}

        # Create target mod dir if it doesn't exist
        mod_dir.mkdir(parents=True, exist_ok=True)

        try:
            # 1. Download file
            downloaded_file = await self.download_file(mod_url)
            filename = downloaded_file.name
            
            # Determine mod name from filename
            mod_name = os.path.splitext(filename)[0]

            log.info("installing_mod_files", game=game_id, file=filename, target_dir=str(mod_dir))
            
            installed_files = []

            # 2. Extract or copy depending on game settings
            if preset.unzip_behavior == "extract" and zipfile.is_zipfile(downloaded_file):
                # Unzip to target directory
                with zipfile.ZipFile(downloaded_file, 'r') as zip_ref:
                    # Get list of files
                    namelist = zip_ref.namelist()
                    zip_ref.extractall(mod_dir)
                    
                    # Track files that were extracted
                    for name in namelist:
                        full_path = mod_dir / name
                        if full_path.is_file():
                            installed_files.append(str(full_path.relative_to(mod_dir)))
            else:
                # Copy directly (e.g. Minecraft .jar file)
                dest_path = mod_dir / filename
                shutil.copy2(downloaded_file, dest_path)
                installed_files.append(filename)

            # Cleanup download temp file
            if downloaded_file.exists():
                downloaded_file.unlink()

            # Record in DB
            mod_entry = {
                "name": mod_name,
                "filename": filename,
                "installed_at": asyncio.get_event_loop().time(),
                "url": mod_url,
                "files": installed_files,
            }

            if game_id not in self.db:
                self.db[game_id] = []
            
            # Prevent duplicates in database list
            self.db[game_id] = [m for m in self.db[game_id] if m["name"] != mod_name]
            self.db[game_id].append(mod_entry)
            self._save_db()

            log.info("mod_installed_successfully", game=game_id, name=mod_name)
            return {
                "success": True,
                "message": f"Successfully installed '{mod_name}' to {preset.name}.",
                "mod": mod_entry,
            }

        except Exception as e:
            log.error("mod_install_failed", game=game_id, error=str(e))
            return {"success": False, "message": f"Failed to install mod: {str(e)}"}

    async def uninstall_mod(self, game_id: str, mod_name: str) -> Dict[str, Any]:
        """Delete files associated with an installed mod."""
        preset = GAME_PRESETS.get(game_id)
        if not preset or game_id not in self.db:
            return {"success": False, "message": f"Game or database entry not found."}

        mod_dir = self.get_mod_dir(game_id)
        if not mod_dir:
            return {"success": False, "message": f"Mod folder missing."}

        mods_list = self.db.get(game_id, [])
        target_mod = None
        for m in mods_list:
            if m["name"] == mod_name:
                target_mod = m
                break

        if not target_mod:
            return {"success": False, "message": f"Mod '{mod_name}' not found in installed records."}

        # Delete all files recorded for this mod
        deleted_count = 0
        failed_deletes = []
        for relative_file in target_mod.get("files", []):
            file_path = mod_dir / relative_file
            if file_path.exists():
                try:
                    if file_path.is_file():
                        file_path.unlink()
                        deleted_count += 1
                    elif file_path.is_dir():
                        # Be careful when deleting dirs (e.g. Stardew subfolders)
                        shutil.rmtree(file_path)
                        deleted_count += 1
                except Exception as e:
                    failed_deletes.append(relative_file)
                    log.warning("failed_to_delete_mod_file", file=str(file_path), error=str(e))

        # Update DB
        self.db[game_id] = [m for m in mods_list if m["name"] != mod_name]
        self._save_db()

        message = f"Removed mod '{mod_name}'. Deleted {deleted_count} files."
        if failed_deletes:
            message += f" Note: Could not delete {len(failed_deletes)} items: {', '.join(failed_deletes)}"

        log.info("mod_uninstalled", game=game_id, name=mod_name)
        return {"success": True, "message": message}


# Singleton
mod_manager_service = ModManagerService()
