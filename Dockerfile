# Anchorum-prem: Multi-Phase Execution Plan - Phase 1 Dockerfile
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    curl \
    openssl \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /venv
ENV PATH="/venv/bin:$PATH" \
    VIRTUAL_ENV="/venv"

# Copy dependency manifests first (leverages Docker layer caching)
COPY pyproject.toml requirements.txt ./

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir cryptography

# Create non-root user BEFORE copying files with --chown
RUN useradd --create-home --shell /bin/bash app

# Copy application code (including the new packages directory!)
COPY --chown=app:app dossier_pipeline/ ./dossier_pipeline/
COPY --chown=app:app config/ ./config/
COPY --chown=app:app interface/ ./interface/
COPY --chown=app:app ci/ ./ci/
COPY --chown=app:app packages/ ./packages/

# Install the ledger package in editable mode from packages directory
RUN pip install --no-cache-dir -e /app/packages/anchorum_ledger

USER app

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import sys; print('OK')" || \
    python -m dossier_pipeline.main demo

CMD ["python", "-m", "dossier_pipeline.main", "--help"]
