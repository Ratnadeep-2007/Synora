# ==============================================================================
# Synesis Backend Production Dockerfile (Multi-stage build)
# ==============================================================================

# Stage 1: Build dependencies
FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Stage 2: Minimal runtime image
FROM python:3.11-slim AS runtime

WORKDIR /app

# Create unprivileged system user
RUN groupadd -g 10001 synesis && \
    useradd -u 10001 -g synesis -s /bin/sh -d /app synesis && \
    mkdir -p /app/.cache/whisper && \
    chown -R synesis:synesis /app/.cache

# Copy Python packages from builder
COPY --from=builder /root/.local /home/synesis/.local
ENV PATH=/home/synesis/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV ENVIRONMENT=production

# Copy application source code
COPY --chown=synesis:synesis ./app /app/app
COPY --chown=synesis:synesis ./run_backend.py /app/run_backend.py

# Switch to non-root user
USER synesis

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health/ready || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4", "--proxy-headers"]
