# Anchorum-prem: Multi-Phase Execution Plan - Phase 1 Dockerfile (FIXED v2)
# Deterministic build for dossier-pipeline-v1-1 (commit: 127615fb53820bd2f6359af59028c41b29b5aa50)
# Plane 1 (kernel/domain/application/governance): deterministic. No wall-clock.

FROM python:3.12-slim

# Prevent Python from writing .pyc files to the filesystem
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Set working directory
WORKDIR /app

# Install system dependencies (minimal set)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    curl \
    openssl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for security FIRST (before copying files)
RUN useradd --create-home --shell /bin/bash app && \
    chown -R app:app /app

# Create virtual environment
RUN python -m venv /venv

# Activate virtual environment and set PATH
ENV PATH="/venv/bin:$PATH" \
    VIRTUAL_ENV="/venv"

# Copy dependency manifests first (leverages Docker layer caching)
COPY pyproject.toml requirements.txt ./

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir cryptography

# Copy application code (excluding .git, __pycache__, etc.)
COPY --chown=app:app dossier_pipeline/ ./dossier_pipeline/
COPY --chown=app:app config/ ./config/
COPY --chown=app:app interface/ ./interface/
COPY --chown=app:app ci/ ./ci/

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import sys; print('OK')" || \
    python -m dossier_pipeline.main demo

# Default command (can be overridden via docker-compose)
CMD ["python", "-m", "dossier_pipeline.main", "--help"]
