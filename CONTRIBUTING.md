# Contributing to JARVIS OMEGA

Thanks for helping improve JARVIS — your contributions are welcome.

## Development Setup

1. **Clone** the repository.
2. **Create** a Python 3.12+ virtual environment:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate     # Windows
   source .venv/bin/activate  # POSIX
   ```
3. **Install** dependencies:
   ```bash
   pip install -r requirements.txt
   pip install ruff mypy pytest-cov
   ```
4. **Bootstrap secrets** — copy `.env.example` to `.env` and populate:
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(64))"
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```
   Paste the outputs as `BACKEND_SECRET_KEY` and `ENCRYPTION_KEY` in `.env`.
5. **Verify** everything works:
   ```bash
   python -m pytest backend/tests/
   ```

## Code Style

- **Python 3.12+** (use modern typing: `dict[str, Any]` not `Dict[str, Any]`,
  `X | None` not `Optional[X]`).
- **Line length**: 100 characters.
- **Imports**: standard library → third-party → local (`shared`, `backend`,
  `local_client`). Within each group, alphabetical.
- **Docstrings**: every public module, class, and function gets a docstring.
  Google style preferred.
- **No bare `except Exception: pass`**. Always catch specific exceptions or
  at minimum log with `log.warning(..., exc_info=True)`.
- **No `subprocess.Popen(cmd, shell=True)`**. Use explicit argv.
- **No hardcoded `BACKEND_SECRET_KEY` or `ENCRYPTION_KEY`** anywhere — the
  startup validator will refuse to boot.

## Linting & Type Checking

```bash
ruff check backend local_client shared
mypy backend shared --ignore-missing-imports
```

Both are best-effort in CI today; if you can make them clean for the file
you're editing, please do.

## Tests

- Every new feature ships with tests under `backend/tests/`.
- Every bug fix ships with a regression test that fails before the fix and
  passes afterwards.
- Aim for at least 70% coverage on the file you touch.

```bash
python -m pytest backend/tests/ --cov=backend --cov=shared --cov-report=term-missing
```

## Pull Request Checklist

- [ ] Branch is up to date with `main`.
- [ ] `python -m pytest backend/tests/` passes locally.
- [ ] `ruff check` is clean for the files you changed.
- [ ] No new `except Exception: pass` patterns.
- [ ] No secrets, tokens, or `.env` content in the diff.
- [ ] Documentation updated if behavior changed.
- [ ] CHANGELOG-style summary in the PR description.

## Commit Messages

Use the imperative mood ("Add OCR fallback" not "Added OCR fallback").
Reference the issue number if applicable: `Fixes #42`.

## Adding a New Agent

1. Create `local_client/agents/agent_<name>.py` following the pattern of
   `agent_security.py` or `agent_memory.py`.
2. Add the agent type to `shared/constants.AgentType`.
3. Register it in `local_client/agents/agent_orchestrator.py` (it uses
   `importlib` to load by class name).
4. Add at least one parametrized test in `backend/tests/test_agents.py`.

## Adding a New Plugin (Phase 8 and later)

See [`ARCHITECTURE.md`](./ARCHITECTURE.md) § "Tool Registry". Every plugin
must declare a `RiskTier` and pass through the approval gateway if it is
Tier 2 or higher.

## Reporting Security Issues

See [`SECURITY.md`](./SECURITY.md).
