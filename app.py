"""HF Spaces entry point — launches FastAPI + Streamlit."""

import subprocess
import sys
import time
import os
import signal

# Start FastAPI backend on internal port
print("🚀 Starting FastAPI backend on port 8000...")
fastapi = subprocess.Popen(
    [
        sys.executable,
        "-m",
        "uvicorn",
        "src.api.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
        "--log-level",
        "warning",
    ]
)

# Wait for FastAPI to be ready
time.sleep(5)

# Start Streamlit on HF Spaces port 7860
print("🚀 Starting Streamlit on port 7860...")
streamlit = subprocess.Popen(
    [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        "streamlit_app.py",
        "--server.port",
        "7860",
        "--server.address",
        "0.0.0.0",
        "--server.headless",
        "true",
        "--browser.gatherUsageStats",
        "false",
    ]
)


def shutdown(signum, frame):
    print("\n🛑 Shutting down...")
    fastapi.terminate()
    streamlit.terminate()
    sys.exit(0)


signal.signal(signal.SIGTERM, shutdown)
signal.signal(signal.SIGINT, shutdown)

# Keep both alive — Streamlit is the foreground process
try:
    streamlit.wait()
except KeyboardInterrupt:
    pass
finally:
    fastapi.terminate()
    streamlit.terminate()
    print("Shutdown complete.")
