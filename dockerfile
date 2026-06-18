FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all code
COPY . .

# Expose ports
EXPOSE 7860
EXPOSE 8000

# Start both services
CMD bash -c "uvicorn src.api.main:app --host 0.0.0.0 --port 8000 & streamlit run src/ui/app.py --server.port 7860 --server.address 0.0.0.0"
