FROM python:3.11-slim

WORKDIR /app

# Install build dependencies (gcc needed for compiled Python packages)
# Clean up in same layer to keep image small
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc && \
    rm -rf /var/lib/apt/lists/*

# Copy requirements first for better Docker layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create upload directory (needed for /upload endpoint)
RUN mkdir -p data/uploads

# HF Spaces exposes this port by default
EXPOSE 7860

# Use entrypoint.py (handles both FastAPI + Streamlit or just FastAPI)
CMD ["python", "entrypoint.py"]
