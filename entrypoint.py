import subprocess, time, sys

print("🚀 Starting AI Data Analyst on Hugging Face Spaces...")

# FastAPI on port 7860 (HF Spaces requirement)
backend = subprocess.Popen(
    [
        sys.executable,
        "-m",
        "uvicorn",
        "src.api.main:app",
        "--host",
        "0.0.0.0",
        "--port",
        "7860",
    ]
)

time.sleep(5)

# Streamlit on secondary port
frontend = subprocess.Popen(
    [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        "src/ui/app.py",
        "--server.port",
        "7861",
        "--server.address",
        "0.0.0.0",
        "--server.headless",
        "true",
    ]
)

try:
    backend.wait()
except KeyboardInterrupt:
    backend.terminate()
    frontend.terminate()
