# Anchorum-prem: Multi-Phase Execution Plan - Phase 1 Dockerfile
# Deterministic build for dossier-pipeline-v1-1
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

# Install the ledger package in editable mode from packages directory
RUN pip install --no-cache-dir -e /app/packages/anchorum_ledger

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash app && \
    chown -R app:app /app
USER app

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import sys; print('OK')" || \
    python -m dossier_pipeline.main demo

# Default command (can be overridden via docker-compose)
CMD ["python", "-m", "dossier_pipeline.main", "--help"]
