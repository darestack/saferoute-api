# ──────────────────────────────────────────────
# Stage 1 – Build dependencies
# ──────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ──────────────────────────────────────────────
# Stage 2 – Production image
# ──────────────────────────────────────────────
FROM python:3.12-slim AS production

# OCI / opencontainers image metadata
LABEL org.opencontainers.image.title="SafeRoute API" \
      org.opencontainers.image.description="Webhook proxy API — routes, validates, and forwards webhooks securely" \
      org.opencontainers.image.source="https://github.com/darestack/saferoute-api" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.authors="DareTechie"

# Install curl for the healthcheck (tiny addition to slim image)
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd --gid 1000 appuser \
    && useradd --uid 1000 --gid appuser --shell /bin/sh --create-home appuser

WORKDIR /home/appuser/src

# Copy pre-built Python packages from builder stage
COPY --from=builder /install /usr/local

# Copy application code (only what is needed at runtime)
COPY app/ ./app/
COPY api/ ./api/

# Ensure the non-root user owns the application files
RUN chown -R appuser:appuser /home/appuser/src

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["curl", "--fail", "--silent", "http://localhost:8000/", "-o", "/dev/null"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
