# ====================================================================
# JARVIS OMEGA - Mobile App Factory (Phase 14)
# ====================================================================
"""
Generate Flutter mobile apps from natural language specs.

  app.spec_design        - LLM writes spec + UI mockups
  app.generate_flutter   - Full Flutter/Dart codebase generator
  app.add_features       - Inject: auth, payments, push
  app.build_apk          - Local flutter build (or Codemagic free CI)
  app.publish_play_store - Google Play Developer API
  app.list_projects      - list all app projects
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.tools import tool, RiskTier
from backend import business_db


_APP_DIR = Path("./storage/app_projects")
_APP_DIR.mkdir(parents=True, exist_ok=True)


def _cred(key: str) -> Optional[str]:
    try:
        from backend.services.credentials_vault import credentials_vault
        return credentials_vault.get(key) or None
    except Exception:
        return None


@tool(
    name="app.spec_design",
    description="Generate a mobile app spec from a description. Returns structured JSON spec + UI mockups.",
    parameters={
        "type": "object",
        "properties": {
            "description": {"type": "string", "description": "What the app does + target audience."},
            "platform": {"type": "string", "default": "both", "enum": ["android", "ios", "both"]},
            "language": {"type": "string", "default": "ar", "enum": ["ar", "en"]},
        },
        "required": ["description"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="app_factory",
)
async def app_spec_design(description: str, platform: str = "both", language: str = "ar") -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    sys_prompt = (
        f"You are a senior mobile product designer. Output STRICT JSON in {'Arabic' if language == 'ar' else 'English'}: "
        "{\"app_name\": string, \"tagline\": string, \"target_user\": string, "
        "\"screens\": [{\"name\": string, \"purpose\": string, \"elements\": [string]}], "
        "\"features\": [string], \"data_models\": [{\"name\": string, \"fields\": [string]}], "
        "\"api_endpoints\": [{\"method\": string, \"path\": string, \"purpose\": string}]}"
    )
    try:
        reply = await llm_service.get_response(
            user_message=f"App description: {description}\nPlatform: {platform}",
            system_instructions=sys_prompt, inject_memory=False,
        )
        text = reply.strip().lstrip("`").rstrip("`")
        if text.startswith("json"): text = text[4:]
        spec = json.loads(text)
        # Persist project
        pid = business_db.execute(
            "INSERT INTO app_projects (name, niche, platform, status, created_at) VALUES (?, ?, ?, 'spec', ?)",
            (spec.get("app_name", "Untitled"), description[:100], platform, datetime.utcnow().isoformat()),
        )
        return {"ok": True, "project_id": pid, "spec": spec}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="app.generate_flutter",
    description="Generate a complete Flutter project from a spec. Writes main.dart, pubspec.yaml, screens.",
    parameters={
        "type": "object",
        "properties": {
            "spec": {"type": "object", "description": "Spec from app.spec_design."},
            "project_id": {"type": "integer", "default": 0},
            "output_dir": {"type": "string", "default": ""},
        },
        "required": ["spec"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="app_factory",
)
async def app_generate_flutter(spec: Dict[str, Any], project_id: int = 0, output_dir: str = "") -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    app_name = spec.get("app_name", "JarvisApp")
    out_dir = Path(output_dir) if output_dir else _APP_DIR / app_name.lower().replace(" ", "_")
    out_dir.mkdir(parents=True, exist_ok=True)

    # Generate main.dart
    try:
        main_dart = await llm_service.get_response(
            user_message=f"App spec:\n{json.dumps(spec, indent=2)}",
            system_instructions=(
                "Generate a complete Flutter main.dart for this app. Use Material Design. "
                "Include all screens mentioned in the spec as separate widgets in the same file. "
                "Output Dart code only — no markdown fences."
            ),
            inject_memory=False,
        )
    except Exception as e:
        return {"ok": False, "error": f"main.dart generation failed: {e}"}

    # Generate pubspec.yaml
    pubspec = f"""name: {app_name.lower().replace(' ', '_')}
description: {spec.get('tagline', '')}
publish_to: 'none'
version: 1.0.0+1

environment:
  sdk: '>=3.0.0 <4.0.0'

dependencies:
  flutter:
    sdk: flutter
  http: ^1.1.0
  shared_preferences: ^2.2.0
  provider: ^6.0.5

dev_dependencies:
  flutter_test:
    sdk: flutter
  flutter_lints: ^3.0.0

flutter:
  uses-material-design: true
"""

    # Write files
    lib_dir = out_dir / "lib"
    lib_dir.mkdir(parents=True, exist_ok=True)
    (lib_dir / "main.dart").write_text(main_dart, encoding="utf-8")
    (out_dir / "pubspec.yaml").write_text(pubspec, encoding="utf-8")

    # README
    (out_dir / "README.md").write_text(
        f"# {app_name}\n\nGenerated by JARVIS OMEGA.\n\n## Setup\n```bash\nflutter pub get\nflutter run\n```\n",
        encoding="utf-8",
    )

    if project_id:
        business_db.execute(
            "UPDATE app_projects SET repo_url = ?, status = 'generated' WHERE id = ?",
            (str(out_dir), project_id),
        )

    return {
        "ok": True, "project_dir": str(out_dir),
        "main_dart_chars": len(main_dart),
        "screens_count": len(spec.get("screens", [])),
        "next_steps": [
            f"cd {out_dir}",
            "flutter pub get",
            "flutter run  # for development",
            "flutter build apk  # for Android APK",
        ],
    }


@tool(
    name="app.build_apk",
    description="Build an Android APK from a Flutter project. Requires Flutter SDK on PATH.",
    parameters={
        "type": "object",
        "properties": {
            "project_dir": {"type": "string"},
            "release_mode": {"type": "boolean", "default": True},
        },
        "required": ["project_dir"],
    },
    risk_tier=RiskTier.TIER_2_SYSTEM,
    category="app_factory",
)
async def app_build_apk(project_dir: str, release_mode: bool = True) -> Dict[str, Any]:
    if not Path(project_dir).is_dir():
        return {"ok": False, "error": f"project dir not found: {project_dir}"}
    try:
        cmd = ["flutter", "build", "apk"]
        if release_mode:
            cmd.append("--release")
        proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=project_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=600)
        if proc.returncode != 0:
            return {"ok": False, "exit_code": proc.returncode, "stderr": stderr.decode("utf-8", errors="replace")[-1000:]}
        apk_path = Path(project_dir) / "build" / "app" / "outputs" / "flutter-apk" / "app-release.apk"
        if apk_path.exists():
            return {"ok": True, "apk_path": str(apk_path), "size_mb": round(apk_path.stat().st_size / (1024*1024), 2)}
        return {"ok": False, "error": "build succeeded but APK not found at expected path"}
    except FileNotFoundError:
        return {"ok": False, "error": "flutter SDK not on PATH. Install from https://flutter.dev"}
    except asyncio.TimeoutError:
        return {"ok": False, "error": "build timed out (>10 min)"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="app.publish_play_store",
    description="Publish APK to Google Play Store. Requires Google Play Developer API setup ($25 one-time).",
    parameters={
        "type": "object",
        "properties": {
            "apk_path": {"type": "string"},
            "app_name": {"type": "string"},
            "description": {"type": "string", "default": ""},
        },
        "required": ["apk_path", "app_name"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="app_factory",
)
async def app_publish_play_store(apk_path: str, app_name: str, description: str = "") -> Dict[str, Any]:
    service_account = _cred("google_play_service_account_json")
    if not service_account:
        return {
            "ok": False,
            "error": "google_play_service_account_json not in vault. Create a Google Play Console account ($25 one-time) + service account.",
            "manual_url": "https://play.google.com/console",
        }
    return {
        "ok": False,
        "error": "Play Publishing API requires Google API client + OAuth flow. Use the manual upload as a first step.",
        "manual_url": "https://play.google.com/console/u/0/developers",
        "apk_path": apk_path, "app_name": app_name,
    }


@tool(
    name="app.list_projects",
    description="List all generated app projects.",
    parameters={"type": "object"},
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="app_factory",
)
async def app_list_projects() -> Dict[str, Any]:
    rows = business_db.rows_to_dicts(business_db.query(
        "SELECT * FROM app_projects ORDER BY id DESC LIMIT 50",
    ))
    return {"ok": True, "count": len(rows), "projects": rows}


PLUGIN_NAME = "app_factory"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Mobile app factory: spec → Flutter code → APK → Play Store."
