# ====================================================================
# JARVIS OMEGA — Backend Docker Deployment
# ====================================================================
# Multi-stage build:
#   1) builder  — installs build-essential + wheels for all deps
#   2) runtime  — slim image with only runtime wheels + curl for HEALTHCHECK
#
# Result: smaller image, no compiler toolchain shipped to production.

# --------------------------------------------------------------------
# Stage 1: builder
# --------------------------------------------------------------------
FROM python:3.12-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        libportaudio2 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# --------------------------------------------------------------------
# Stage 2: runtime
# --------------------------------------------------------------------
FROM python:3.12-slim

WORKDIR /app

# Copy the user-site from the builder stage.
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1
ENV HOST=0.0.0.0
ENV PORT=8000

# Minimal runtime system deps (curl for HEALTHCHECK; portaudio for sounddevice
# if you ever run audio inside the container — usually you do not).
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        libportaudio2 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /bin/bash jarvis

# Copy application code (backend + shared only — local_client, frontend, src,
# roles are intentionally excluded; the backend does not need them).
COPY --chown=jarvis:jarvis backend/ ./backend/
COPY --chown=jarvis:jarvis shared/ ./shared/
COPY --chown=jarvis:jarvis conftest.py ./conftest.py
COPY --chown=jarvis:jarvis pytest.ini ./pytest.ini

USER jarvis

EXPOSE 8000

# Container self-check — uvicorn answers /health with 200 once the lifespan
# has finished wiring event bus, registries, etc.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
