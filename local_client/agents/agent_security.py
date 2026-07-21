# ====================================================================
# JARVIS OMEGA — Security Agent
# ====================================================================
"""
Specialized Security Agent responsible for scanning configurations, locating
accidental plain-text credentials, auditing access controls, and verifying
.gitignore hygiene.

Phase 4 promoted this from a stub to a real regex-based secret scanner. It
walks the workspace, classifies hits by secret type, and routes any *remediation*
(not detection) through the approval gateway.
"""

from __future__ import annotations

import os
import re
import time
import math
import traceback
from pathlib import Path
from typing import Dict, Any, List, Tuple
from datetime import datetime

from shared.models import TaskDefinition, TaskResult
from shared.constants import AgentType, TaskStatus
from shared.logger import get_logger

log = get_logger("agent_security")


# --------------------------------------------------------------------
# Secret-detection patterns.
#
# Each entry: (name, compiled regex, recommended_remediation).
# Patterns intentionally require word boundaries / canonical prefixes so the
# false-positive rate stays low for ordinary prose and code.
# --------------------------------------------------------------------
_SECRET_PATTERNS: List[Tuple[str, "re.Pattern[str]", str]] = [
    (
        "AWS Access Key ID",
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        "Rotate at AWS IAM console; do not commit.",
    ),
    (
        "AWS Secret Access Key",
        re.compile(r"\baws_secret_access_key\s*[=:]\s*['\"]?[A-Za-z0-9/+=]{40}['\"]?"),
        "Rotate at AWS IAM console; do not commit.",
    ),
    (
        "OpenRouter API Key",
        re.compile(r"\bsk-or-v1-[A-Za-z0-9_\-]{40,}\b"),
        "Revoke at https://openrouter.ai/keys and reissue.",
    ),
    (
        "OpenAI API Key",
        re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
        "Revoke at https://platform.openai.com/api-keys.",
    ),
    (
        "Anthropic API Key",
        re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{40,}\b"),
        "Revoke at https://console.anthropic.com/settings/keys.",
    ),
    (
        "GitHub Personal Access Token",
        re.compile(r"\bghp_[A-Za-z0-9]{36,}\b"),
        "Revoke at https://github.com/settings/tokens.",
    ),
    (
        "GitHub OAuth Token",
        re.compile(r"\bgho_[A-Za-z0-9]{36,}\b"),
        "Revoke at https://github.com/settings/applications.",
    ),
    (
        "Slack Bot Token",
        re.compile(r"\bxoxb-[0-9]{10,}-[0-9]{10,}-[A-Za-z0-9]{24,}\b"),
        "Revoke at https://api.slack.com/apps.",
    ),
    (
        "Slack User Token",
        re.compile(r"\bxox[porsa]-[0-9A-Za-z-]{10,72}\b"),
        "Revoke at https://api.slack.com/apps.",
    ),
    (
        "Stripe Secret Key",
        re.compile(r"\bsk_live_[A-Za-z0-9]{24,}\b"),
        "Revoke at https://dashboard.stripe.com/apikeys.",
    ),
    (
        "Google API Key",
        re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"),
        "Revoke at https://console.cloud.google.com/apis/credentials.",
    ),
    (
        "Google OAuth Client Secret",
        re.compile(r"\bGOCSPX-[A-Za-z0-9_\-]{20,}\b"),
        "Revoke at Google Cloud Console credentials page.",
    ),
    (
        "PEM Private Key Block",
        re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY-----"),
        "Rotate the key; do not commit PEM blocks.",
    ),
    (
        "Generic Bearer Token",
        re.compile(r"\bBearer\s+[A-Za-z0-9_\-\.=]{40,}\b"),
        "Investigate origin; rotate if sensitive.",
    ),
    (
        "JWT",
        re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b"),
        "JWT may be a live session token — verify scope and revoke if needed.",
    ),
    (
        "Password Assignment",
        re.compile(r"\b(password|passwd|pwd)\s*[=:]\s*['\"][^'\"]{6,}['\"]", re.IGNORECASE),
        "Move to a secrets manager; do not hardcode.",
    ),
]


# Files / directories we never scan. Keeps the scanner fast and avoids
# touching dependency noise.
_DEFAULT_SKIP_DIRS = {
    ".git", ".hg", ".svn",
    "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "venv", ".venv", "env",
    "dist", "build", "target", ".next", "out",
    "storage", "logs", "memory", "cache", "backups", "workspace",
    "src/data",  # vault.db lives here
    ".idea", ".vscode",
}

_DEFAULT_SKIP_EXTENSIONS = {
    ".pyc", ".pyo", ".so", ".dll", ".exe", ".bin",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp",
    ".mp3", ".mp4", ".wav", ".avi", ".mov", ".mkv",
    ".zip", ".gz", ".tar", ".bz2", ".7z", ".rar",
    ".pdf", ".docx", ".xlsx", ".pptx",  # binary office formats
    ".db", ".db-shm", ".db-wal", ".sqlite", ".sqlite3",
    ".lock",
}

# Cap individual file size at 1 MiB so the scanner can't be DoS'd by a giant
# generated artefact.
MAX_FILE_SIZE_BYTES = 1 * 1024 * 1024


class AgentSecurity:
    """
    Host and workspace security scanner.

    Capabilities:
      * ``scan`` (default) — regex-based scan of all source/config files for
        leaked credentials. Returns a structured ``leaks`` list.
      * ``credential_check`` — alias for ``scan``.
      * ``file_permissions`` — quick audit of world-writable directories.
    """

    def __init__(self) -> None:
        self.agent_id = "agent_security"
        self.agent_type = AgentType.SECURITY

    async def execute_task(self, task: TaskDefinition) -> TaskResult:
        """Processes security tasks like auditing keys or checking file permissions."""
        log.info("security_agent_executing", task_id=task.task_id, title=task.title)
        start_time = time.time()

        try:
            action = task.payload.get("action", "scan")

            if action in ("scan", "credential_check"):
                result_data = await self._audit_credentials(task)
            elif action == "file_permissions":
                result_data = await self._check_file_permissions(task)
            else:
                raise ValueError(f"Unknown Security action: {action}")

            elapsed = (time.time() - start_time) * 1000
            return TaskResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                status=TaskStatus.COMPLETED,
                result=result_data,
                execution_time=elapsed,
            )

        except Exception as e:
            elapsed = (time.time() - start_time) * 1000
            err_msg = f"{str(e)}\n{traceback.format_exc()}"
            log.error("security_agent_failed", task_id=task.task_id, error=err_msg)
            return TaskResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                status=TaskStatus.FAILED,
                error=err_msg,
                execution_time=elapsed,
            )

    # ------------------------------------------------------------------
    # Credential scanning
    # ------------------------------------------------------------------

    async def _audit_credentials(self, task: TaskDefinition) -> Dict[str, Any]:
        """
        Walks ``scan_path`` and applies every regex in ``_SECRET_PATTERNS``
        to each candidate file. Returns structured findings.
        """
        scan_path = task.payload.get("scan_path", ".")
        scan_root = Path(scan_path).resolve()
        skip_dirs = set(task.payload.get("skip_dirs", _DEFAULT_SKIP_DIRS))
        skip_ext = set(task.payload.get("skip_extensions", _DEFAULT_SKIP_EXTENSIONS))

        log.info("scanning_for_secrets", path=str(scan_root))

        leaks: List[Dict[str, Any]] = []
        files_scanned = 0
        files_skipped = 0

        if not scan_root.exists():
            return {
                "status": "scan_failed",
                "error": f"path does not exist: {scan_root}",
                "secrets_found": 0,
                "critical_leaks": [],
            }

        for path in self._iter_candidate_files(scan_root, skip_dirs, skip_ext):
            files_scanned += 1
            try:
                file_leaks = self._scan_file(path)
                leaks.extend(file_leaks)
            except Exception as scan_err:
                files_skipped += 1
                log.warning("file_scan_error", path=str(path), error=str(scan_err))

        # Also report .env / .gitignore hygiene.
        env_status = self._check_env_gitignore(scan_root)

        # Bucket leaks by severity: PEM keys, AWS, OpenRouter, GitHub, Slack,
        # Stripe, OpenAI are critical. JWT/password/bearer are warnings.
        critical_types = {
            "PEM Private Key Block",
            "AWS Access Key ID",
            "AWS Secret Access Key",
            "OpenRouter API Key",
            "OpenAI API Key",
            "Anthropic API Key",
            "GitHub Personal Access Token",
            "GitHub OAuth Token",
            "Slack Bot Token",
            "Slack User Token",
            "Stripe Secret Key",
            "Google API Key",
            "Google OAuth Client Secret",
        }
        critical_leaks = [l for l in leaks if l["type"] in critical_types]

        return {
            "status": "scan_completed",
            "secrets_found": len(leaks),
            "critical_count": len(critical_leaks),
            "critical_leaks": critical_leaks,
            "all_leaks": leaks,
            "files_scanned": files_scanned,
            "files_skipped_due_to_error": files_skipped,
            "scan_root": str(scan_root),
            "dot_env_file_detected": env_status["env_exists"],
            "dot_env_properly_ignored": env_status["env_ignored"],
            "security_recommendation": (
                "Rotate every critical secret listed above at its provider. "
                "Move all secrets to a credential vault or .env (which must be in .gitignore)."
                if critical_leaks
                else "No critical secrets detected. Continue to store secrets only in .env / vault."
            ),
        }

    def _iter_candidate_files(self, root: Path, skip_dirs: set, skip_ext: set):
        """Yields files that should be scanned, skipping binary/noise dirs."""
        for dirpath, dirnames, filenames in os.walk(root):
            # Prune skipped directories in-place so os.walk doesn't descend.
            dirnames[:] = [
                d for d in dirnames
                if d not in skip_dirs
                and not any(str(Path(dirpath, d)).replace("\\", "/").endswith(s.strip("/")) for s in skip_dirs)
            ]
            for fname in filenames:
                fpath = Path(dirpath, fname)
                if fpath.suffix.lower() in skip_ext:
                    continue
                try:
                    if fpath.stat().st_size > MAX_FILE_SIZE_BYTES:
                        continue
                except OSError:
                    continue
                yield fpath

    def _scan_file(self, path: Path) -> List[Dict[str, Any]]:
        """Apply every secret pattern to a single file. Returns a list of hits."""
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception as read_err:
            log.debug("file_unreadable_skipped", path=str(path), error=str(read_err))
            return []

        hits: List[Dict[str, Any]] = []
        seen_spans: set = set()  # de-dup the same (line, type) finding

        for line_no, line in enumerate(text.splitlines(), start=1):
            for name, pattern, remediation in _SECRET_PATTERNS:
                for m in pattern.finditer(line):
                    key = (line_no, name, m.group(0)[:32])
                    if key in seen_spans:
                        continue
                    seen_spans.add(key)

                    # Redact the middle of the match so the report itself isn't a leak vector.
                    matched = m.group(0)
                    redacted = self._redact(matched)

                    # Shannon entropy — high-entropy generic strings are more suspicious.
                    entropy = self._shannon_entropy(matched)

                    hits.append({
                        "file": str(path),
                        "line": line_no,
                        "type": name,
                        "snippet": redacted,
                        "entropy": round(entropy, 2),
                        "remediation": remediation,
                    })
        return hits

    @staticmethod
    def _redact(value: str) -> str:
        """Keep first 8 and last 4 chars; mask the middle."""
        if len(value) <= 12:
            return value[:2] + "***"
        return f"{value[:8]}...{value[-4:]} (redacted)"

    @staticmethod
    def _shannon_entropy(value: str) -> float:
        """Approximate randomness — useful for surfacing high-entropy tokens."""
        if not value:
            return 0.0
        freq: Dict[str, int] = {}
        for ch in value:
            freq[ch] = freq.get(ch, 0) + 1
        n = len(value)
        entropy = 0.0
        for count in freq.values():
            p = count / n
            entropy -= p * math.log2(p)
        return entropy

    def _check_env_gitignore(self, root: Path) -> Dict[str, Any]:
        """Return whether `.env` exists and is properly gitignored."""
        env_path = root / ".env"
        gitignore_path = root / ".gitignore"
        env_exists = env_path.exists()
        env_ignored = False
        if env_exists and gitignore_path.exists():
            try:
                contents = gitignore_path.read_text(encoding="utf-8", errors="ignore")
                env_ignored = any(
                    line.strip() == ".env" or line.strip().startswith(".env")
                    for line in contents.splitlines()
                )
            except Exception:
                env_ignored = False
        return {"env_exists": env_exists, "env_ignored": env_ignored}

    # ------------------------------------------------------------------
    # File permission audit
    # ------------------------------------------------------------------

    async def _check_file_permissions(self, task: TaskDefinition) -> Dict[str, Any]:
        """
        Audits folder structures for world-writable directories (POSIX only;
        on Windows the ACL model differs, so we report a no-op with context).
        """
        import platform
        root_path = Path(task.payload.get("root_path", ".")).resolve()

        if platform.system() == "Windows":
            return {
                "root_path": str(root_path),
                "platform": "windows",
                "audit_message": (
                    "POSIX world-writable checks skipped on Windows. Use icacls "
                    "manually if you need ACL auditing."
                ),
                "world_writable_dirs": [],
            }

        world_writable: List[str] = []
        for dirpath, dirnames, _ in os.walk(root_path):
            for d in dirnames:
                full = Path(dirpath, d)
                try:
                    mode = full.stat().st_mode
                    if mode & 0o002:  # others have write bit
                        world_writable.append(str(full))
                except OSError:
                    continue

        return {
            "root_path": str(root_path),
            "platform": platform.system().lower(),
            "world_writable_dirs": world_writable[:50],
            "world_writable_count": len(world_writable),
            "audit_message": (
                "All directory nodes restrict external writes."
                if not world_writable
                else f"{len(world_writable)} world-writable directories detected."
            ),
        }
