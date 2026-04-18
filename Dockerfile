# TruthCert Docker Image
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -s /bin/bash truthcert

# Copy project files
COPY pyproject.toml .
COPY certifier/ certifier/
COPY memory/ memory/
COPY cli/ cli/
COPY gateway/ gateway/
COPY renderer/ renderer/
COPY policies/ policies/
COPY schemas/ schemas/

# Install dependencies
RUN pip install --no-cache-dir -e .

# Create directories
RUN mkdir -p /app/bundles /app/evidence_cache /app/data /app/logs \
    && chown -R truthcert:truthcert /app

# Switch to non-root user
USER truthcert

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Default command
CMD ["python", "-m", "certifier.main"]
