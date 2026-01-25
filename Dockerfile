# WebOps Voice Service Dockerfile
# Optimized for voice-controlled operations in Docker

# Stage 1: Build stage
FROM python:3.11-slim as builder

WORKDIR /app

# Install system dependencies for building
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY ../requirements.txt .
COPY ../requirements-voice.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Stage 2: Production stage
FROM python:3.11-slim

WORKDIR /app

# Install runtime system dependencies for operations
RUN apt-get update && apt-get install -y \
    curl \
    wget \
    git \
    vim \
    nano \
    htop \
    procps \
    net-tools \
    dnsutils \
    lsof \
    tree \
    unzip \
    zip \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for security
RUN useradd -m -u 1000 webops && \
    mkdir -p /app/logs /app/uploads /app/workspace && \
    chown -R webops:webops /app

# Copy Python packages from builder stage
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code from parent directory
COPY ../src/ ./src/
COPY ../webops/ ./webops/
COPY ../requirements.txt .
COPY ../requirements-voice.txt .
COPY ../pyproject.toml .

# Install the application
RUN pip install -e .

# Set environment variables
ENV PYTHONPATH=/app/src
ENV NLP2CMD_HOST=0.0.0.0
ENV NLP2CMD_PORT=8000
ENV NLP2CMD_DEBUG=false
ENV NLP2CMD_LOG_LEVEL=info
ENV NLP2CMD_AUTO_EXECUTE=true
ENV WORKSPACE_DIR=/app/workspace

# Expose ports
EXPOSE 8000

# Switch to non-root user
USER webops

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Start script
CMD ["python", "-m", "webops.voice_service"]
