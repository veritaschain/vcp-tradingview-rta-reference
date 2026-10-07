# ============================================================================
# VCP TradingView Sidecar Dockerfile
# VeritasChain Protocol v1.1
# ============================================================================

FROM python:3.11-slim

# Labels
LABEL org.opencontainers.image.title="VCP TradingView Sidecar"
LABEL org.opencontainers.image.description="Non-certified VCP v1.1 PoC Sidecar"
LABEL org.opencontainers.image.version="1.0.0"
LABEL org.opencontainers.image.vendor="VeritasChain Standards Organization"
LABEL org.opencontainers.image.url="https://veritaschain.org"

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 1000 vcp && \
    mkdir -p /app/data /app/keys /app/config && \
    chown -R vcp:vcp /app

# Copy requirements first for caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY sidecar/ ./sidecar/

# Set ownership
RUN chown -R vcp:vcp /app

# Switch to non-root user
USER vcp

# Environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV VCP_TIER=SILVER
ENV VCP_VERSION=1.1

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Default command
CMD ["python", "-m", "uvicorn", "sidecar.main:app", "--host", "0.0.0.0", "--port", "8080"]
