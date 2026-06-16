# JARVIS OMEGA — Localhost Run Guide

To run JARVIS OMEGA on your local machine with full GOD MODE capabilities, follow these steps:

### 1. Prerequisites
- **Python 3.10+**
- **Node.js 18+** (for frontend)
- **ADB (Android Debug Bridge)** installed and in your PATH.
- **Docker** (optional, for sandboxed code execution).

### 2. Installation
```bash
# Clone the repository
git clone https://github.com/your-repo/jarvis-omega.git
cd jarvis-omega

# Install Python dependencies
pip install -r requirements.txt

# Install specific OMEGA requirements
pip install structlog pydantic psutil playwright Pillow pywebpush orjson aiohttp async-timeout pydantic-settings chromadb
```

### 3. Environment Setup
Create a `.env` file in the root directory:
```env
OPENAI_API_KEY=your_key_here
ANTHROPIC_API_KEY=your_key_here
OPENROUTER_API_KEY=your_key_here
BACKEND_SECRET_KEY=generate_a_random_string
ENCRYPTION_KEY=generate_a_random_32_char_string
```

### 4. Running the Backend
```bash
# Start the FastAPI server
PYTHONPATH=. uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

### 5. Running the Local Client (Daemon)
```bash
# In a new terminal
PYTHONPATH=. python local_client/daemon.py
```

### 6. Running the Frontend
```bash
# Open frontend/index.html in your browser or serve it:
# cd frontend && npx serve .
```

---

## ◈ OMEGA LOCAL MODEL AUTO-SCAN
When you initialize JARVIS on localhost, he will execute the following logic:

1. **Hardware Scan**: JARVIS checks your CPU cores, RAM, and GPU VRAM.
2. **Recommendation**:
   - < 8GB RAM: Recommended **Gemma-2b-it**
   - 8-16GB RAM: Recommended **Mistral-7b-v0.1**
   - 16-32GB RAM / 8GB VRAM: Recommended **Llama-3-8b-Instruct**
   - > 32GB RAM / 24GB VRAM: Recommended **Llama-3-70b-Instruct (Quantized)**
3. **Download & Setup**: If you approve, JARVIS will use `ollama` or `huggingface-hub` to download the model and configure his local reasoning engine to use it.

### Commands to trigger scan:
- "Jarvis, scan my specs and recommend a local model."
- "Go local mode."
