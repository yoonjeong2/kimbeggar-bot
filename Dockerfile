# ============================================================
# KimBeggar Bot — Docker Image
# ============================================================
# Build:
#   docker build -t kimbeggar .
#
# Run:
#   docker run --env-file .env kimbeggar
#
# Notes:
#   - Linux containers use the system CA bundle, so DEV_MODE=false
#     works out of the box (no SSL workaround needed).
#   - Mount a volume for logs/  if you want logs to persist:
#       docker run --env-file .env -v $(pwd)/logs:/app/logs kimbeggar
# ============================================================

FROM python:3.11-slim

# Install system CA certificates (ensures TLS works without DEV_MODE)
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies before copying source so the layer is cached
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Create runtime directories
RUN mkdir -p logs data

# Ensure stdout/stderr are unbuffered so logs appear in real-time
ENV PYTHONUNBUFFERED=1

CMD ["python", "main.py"]
