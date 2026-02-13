# Multi-stage build for Network & Sensor Stability Monitor
# Optimized for ARM64 (Raspberry Pi 5)

FROM python:3.11-slim AS base

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    wireless-tools \
    iw \
    iputils-ping \
    iproute2 \
    net-tools \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first (for better caching)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ ./src/
COPY monitor.py generate_report.py ./

# Create directories for data, reports, and logs
RUN mkdir -p /app/data /app/reports /app/logs

# Make scripts executable
RUN chmod +x monitor.py generate_report.py

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD test -f /app/data/monitor.db || exit 1

# Default command
CMD ["python", "monitor.py", "--config", "/app/config.yml"]
