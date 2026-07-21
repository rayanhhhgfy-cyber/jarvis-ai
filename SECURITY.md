# Security Policy

## Reporting a Vulnerability

If you discover a security issue in JARVIS OMEGA, please **do not** open a
public GitHub issue. Instead, email the maintainer directly with a proof of
concept and repro steps. We will acknowledge receipt within 72 hours and aim
to ship a fix within 30 days for high-severity issues.

## Threat Model

JARVIS OMEGA is an autonomous AI assistant with the ability to execute shell
commands, modify files, and (in Phase 8) call external APIs on Sir's behalf.
Treat the JARVIS process as **equivalent to a logged-in user** of the
workstation: any compromise of JARVIS is a compromise of the host.

The primary attack surfaces are:

1. **Prompt injection** — malicious content in web pages, emails, or
   documents that JARVIS reads could trick it into running commands.
2. **LLM hallucination** — the model emits a destructive command even
   without adversarial input.
3. **Credential leakage** — API keys or device tokens committed to the repo.
4. **WS hijack** — untrusted devices connecting via the WebSocket hub.

## Defense in Depth

### Layer 1 — Command Safety Validator

Every shell command emitted by the LLM or the natural-language command
interpreter passes through `backend/services/command_safety.py` BEFORE
execution. The validator returns one of three verdicts:

| Verdict | Meaning | Examples |
|---------|---------|---------|
| `ALLOWED` | Safe to run immediately | `echo`, `dir`, `git status`, `ls` |
| `NEEDS_APPROVAL` | Destructive — routes to approval gateway | `format D:`, `rm -rf C:\\`, `reg delete`, `curl … \| bash`, `taskkill /f /im`, `net user /add`, `shutdown`, `reboot` |
| `BLOCKED` | Unconditionally refused — cannot be approved | `rm -rf /`, fork bombs, `dd … of=/dev/sda`, `mkfs /dev/sd*`, oversize commands, control characters |

The full pattern table lives in `shared/constants.py:DANGEROUS_COMMAND_PATTERNS`
and `BLOCKED_COMMAND_PATTERNS`.

### Layer 2 — Human Approval Gateway

Anything classified as `NEEDS_APPROVAL` blocks on
`backend/approval_gateway.py:wait_for_approval` until Sir clicks Approve in the
dashboard. If no response arrives within 300 seconds the request is rejected.

Approval requests are mirrored to every UI client via the
`/ws/ui` socket so they can be acted on from any connected device.

### Layer 3 — Bootstrap Secret Fail-Fast

`backend/config.py:validate_security_settings` is invoked during the FastAPI
lifespan. It refuses to boot if either:

- `BACKEND_SECRET_KEY` is missing or a known placeholder. (Without a stable
  secret, JWT signatures change on every restart and trusted devices become
  untrusted — this was the WebSocket 403 storm root cause.)
- `ENCRYPTION_KEY` is missing. (Without it, `shared/security.py` would
  silently generate a new Fernet key on each boot, making previously
  encrypted data undecryptable.)

Generate both with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"      # BACKEND_SECRET_KEY
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # ENCRYPTION_KEY
```

### Layer 4 — Device Pairing

Every local client must be paired through `device_registry.initiate_pairing`
before it can open a WebSocket session. Pairing is a two-step flow:

1. Client calls `POST /api/devices/pair/initiate` → receives a 6-digit code.
2. Sir calls `POST /api/devices/pair/approve?pairing_code=…` from the
   dashboard → device is marked `trusted=True`, persisted to
   `storage/devices.json`, and issued access/refresh JWTs.

Trusted state survives backend restarts (regression-tested in
`backend/tests/test_device_registry.py`).

## Secret Handling Policy

- `.env` is the **only** place bootstrap secrets live. It is gitignored.
- `config/client_config.json` and `config/daemon.json` are gitignored.
- The `config/*.json` files committed to the repo contain only placeholder
  strings (`REPLACE_ME`, `REPLACE_WITH_*`).
- `.gitignore` also excludes `*.db`, `*.db-shm`, `*.db-wal`, `*.pem`,
  `*.key`, `*.cert`, `credentials/`, `storage/`, `audit.log`, and all
  `*.log` files.

## Rotation Checklist (if a leak occurs)

1. **OpenRouter**: revoke at https://openrouter.ai/keys and reissue.
2. **OpenAI**: revoke at https://platform.openai.com/api-keys.
3. **Anthropic**: revoke at https://console.anthropic.com/settings/keys.
4. **AWS**: rotate at the IAM console; revoke the old access key.
5. **GitHub**: revoke at https://github.com/settings/tokens.
6. **Slack**: revoke at https://api.slack.com/apps.
7. **Backend**: regenerate `BACKEND_SECRET_KEY` and `ENCRYPTION_KEY` (note:
   this invalidates all existing device tokens — clients must re-pair).
8. **Audit**: review `storage/audit.log` for any commands executed with the
   leaked credentials.

## What's intentionally not sandboxed

Per the system owner's explicit decision, code-execution commands are
**approval-gated but not sandboxed** (no Docker/firejail isolation). A
misclicked approval is therefore equivalent to running the command in your
own shell. Treat every approval dialog with the seriousness of a `sudo`
prompt.

## Disallowed Patterns in this Codebase

- `subprocess.Popen(cmd, shell=True)` — replaced with explicit argv
  (`["cmd", "/c", cmd]` on Windows, `["/bin/sh", "-c", cmd]` on POSIX).
- Hardcoded fallbacks for `BACKEND_SECRET_KEY` / `ENCRYPTION_KEY` —
  removed in Phase 1.
- `except Exception: pass` without logging — replaced with specific
  exception types and at minimum `log.warning` calls (Phase 3).
