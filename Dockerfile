# ====================================================================
# JARVIS OMEGA — Backend Docker Deployment
# ====================================================================

FROM python:3.10-slim

WORKDIR /app

# Install system utilities needed for building packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend, shared modules, and configs
COPY backend/ ./backend/
COPY shared/ ./shared/

# Expose backend REST & websocket ports
EXPOSE 8000

ENV PYTHONUNBUFFERED=1
ENV HOST=0.0.0.0
ENV PORT=8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
