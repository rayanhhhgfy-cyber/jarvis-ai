"""
Skill Manager — upload, install, and execute custom Python skills.
Skills are Python scripts stored in storage/skills/ with a standard
execute(params) function interface.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import sys
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from shared.logger import get_logger

log = get_logger("skill_manager")

SKILLS_DIR = Path("./storage/skills")


class Skill:
    """Represents an installed skill."""

    def __init__(self, name: str, filepath: Path, description: str = "", version: str = "1.0.0"):
        self.name = name
        self.filepath = filepath
        self.description = description
        self.version = version
        self._module = None
        self._execute_fn: Optional[Callable] = None

    def load(self) -> bool:
        """Load the skill module and find the execute function."""
        try:
            spec = importlib.util.spec_from_file_location(self.name, str(self.filepath))
            if not spec or not spec.loader:
                return False
            module = importlib.util.module_from_spec(spec)
            sys.modules[self.name] = module
            spec.loader.exec_module(module)

            self._module = module
            self._execute_fn = getattr(module, "execute", None)

            # Extract metadata if available
            self.description = getattr(module, "__description__", self.description)
            self.version = getattr(module, "__version__", self.version)

            log.info("skill_loaded", name=self.name, version=self.version)
            return True
        except Exception as e:
            log.error("skill_load_failed", name=self.name, error=str(e))
            return False

    async def execute(self, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """Execute the skill with given parameters."""
        if not self._execute_fn:
            if not self.load():
                return {"success": False, "error": f"Failed to load skill '{self.name}'"}

        try:
            if inspect.iscoroutinefunction(self._execute_fn):
                result = await self._execute_fn(params or {})
            else:
                import asyncio
                result = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: self._execute_fn(params or {})
                )
            return {"success": True, "result": result}
        except Exception as e:
            log.error("skill_execution_failed", name=self.name, error=str(e))
            return {"success": False, "error": str(e), "traceback": traceback.format_exc()}

    def get_info(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "filepath": str(self.filepath),
            "loaded": self._module is not None,
        }


class SkillManager:
    """
    Manages skill lifecycle: upload, install, list, execute, delete.
    Skills are Python files with:
    - execute(params: dict) -> Any  (required)
    - __description__ = "..."      (optional)
    - __version__ = "1.0.0"        (optional)
    """

    def __init__(self):
        self._skills: Dict[str, Skill] = {}
        self._manifest_file = SKILLS_DIR / "manifest.json"
        SKILLS_DIR.mkdir(parents=True, exist_ok=True)
        self._scan_installed()

    def _scan_installed(self) -> None:
        """Scan the skills directory for installed skills."""
        if not SKILLS_DIR.exists():
            return
        for f in sorted(SKILLS_DIR.iterdir()):
            if f.suffix == ".py" and f.stem != "__init__":
                skill = Skill(name=f.stem, filepath=f)
                self._skills[f.stem] = skill
                # Pre-load for metadata
                skill.load()
        log.info("skills_scanned", count=len(self._skills))

    async def install_skill(self, name: str, code: str) -> Dict[str, Any]:
        """
        Install a new skill from Python source code.
        The code must define an execute(params) function.
        """
        if not name.endswith(".py"):
            name += ".py"

        # Basic validation - check for execute function
        if "def execute" not in code:
            return {"success": False, "error": "Skill must define an execute(params) function"}

        filepath = SKILLS_DIR / name
        try:
            filepath.write_text(code, encoding="utf-8")

            # Load and validate
            skill_name = name.replace(".py", "")
            skill = Skill(name=skill_name, filepath=filepath)
            if not skill.load():
                filepath.unlink(missing_ok=True)
                return {"success": False, "error": f"Skill '{skill_name}' has syntax errors or missing dependencies"}

            self._skills[skill_name] = skill
            self._save_manifest()

            log.info("skill_installed", name=skill_name, version=skill.version)
            return {"success": True, "skill": skill.get_info()}

        except Exception as e:
            filepath.unlink(missing_ok=True)
            log.error("skill_install_failed", name=name, error=str(e))
            return {"success": False, "error": str(e)}

    async def install_from_file(self, filepath: str) -> Dict[str, Any]:
        """Install a skill from an existing file path."""
        path = Path(filepath)
        if not path.exists():
            return {"success": False, "error": f"File not found: {filepath}"}

        code = path.read_text(encoding="utf-8")
        return await self.install_skill(path.stem, code)

    async def execute_skill(self, name: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """Execute a skill by name."""
        skill = self._skills.get(name)
        if not skill:
            return {"success": False, "error": f"Skill '{name}' not found"}
        return await skill.execute(params)

    def get_skill(self, name: str) -> Optional[Dict[str, Any]]:
        """Get skill info by name."""
        skill = self._skills.get(name)
        if skill:
            return skill.get_info()
        return None

    def list_skills(self) -> List[Dict[str, Any]]:
        """List all installed skills."""
        return [s.get_info() for s in self._skills.values()]

    def delete_skill(self, name: str) -> bool:
        """Delete an installed skill."""
        skill = self._skills.pop(name, None)
        if skill:
            try:
                skill.filepath.unlink(missing_ok=True)
                self._save_manifest()
                log.info("skill_deleted", name=name)
                return True
            except Exception as e:
                log.error("skill_delete_failed", name=name, error=str(e))
                self._skills[name] = skill  # restore
        return False

    def get_skill_template(self) -> str:
        """Return a template for creating new skills."""
        return '''"""
{name} — JARVIS Skill
"""

__description__ = "Description of what this skill does"
__version__ = "1.0.0"


def execute(params: dict) -> dict:
    """
    Main entry point for the skill.
    Args:
        params: Dictionary of input parameters
    Returns:
        Dictionary with results
    """
    # Your skill logic here
    return {"status": "completed", "message": "Skill executed successfully"}
'''

    def _save_manifest(self) -> None:
        """Save skill manifest."""
        try:
            manifest = []
            for skill in self._skills.values():
                manifest.append(skill.get_info())
            self._manifest_file.write_text(json.dumps(manifest, indent=2))
        except Exception as e:
            log.error("manifest_save_failed", error=str(e))


skill_manager = SkillManager()
