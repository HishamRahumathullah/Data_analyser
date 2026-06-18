#!/bin/bash
# Startup script for AI Data Analyst Agent

echo "🚀 Starting AI Data Analyst Agent v2.0"
echo "========================================"

# Check Python version
python_version=$(python3 --version 2>&1 | awk '{print $2}')
echo "Python version: $python_version"

# Set PYTHONPATH
export PYTHONPATH="${PYTHONPATH}:$(pwd)"

# Create data directory
mkdir -p data

# Start API server in background
echo "📡 Starting FastAPI server on http://localhost:8000"
uvicorn src.api.main:app --host 0.0.0.0 --port 8000 &
API_PID=$!

# Wait for API to be ready
echo "⏳ Waiting for API to start..."
sleep 3

# Check if API is healthy
if curl -s http://localhost:8000/health > /dev/null; then
    echo "✅ API is healthy"
else
    echo "⚠️  API health check failed, but continuing..."
fi

# Start Streamlit
echo "🎨 Starting Streamlit UI on http://localhost:8501"
streamlit run src/ui/app.py

# Cleanup on exit
trap "kill $API_PID 2>/dev/null; echo 'Shutdown complete'" EXIT
