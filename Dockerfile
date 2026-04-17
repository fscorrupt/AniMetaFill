# ---- Final runtime image ----
FROM python:3.13-alpine

LABEL org.opencontainers.image.title="AniMetaFill"
LABEL org.opencontainers.image.description="Automated Anime Filler Classification for Kometa"
LABEL org.opencontainers.image.authors="fscorrupt"
LABEL org.opencontainers.image.licenses="MIT"

ENV TZ="Europe/Berlin" \
    APP_ROOT="/app" \
    APP_DATA="/config" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Install runtime dependencies
RUN apk add --no-cache \
        curl \
        tzdata \
        bash \
        shadow \
    && mkdir -p /app /config /data /app/logs

# Set working directory
WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN apk add --no-cache --virtual .build-deps build-base \
    && pip install --no-cache-dir -r requirements.txt \
    && apk del .build-deps

# Copy application files
COPY . .

# Set permissions for non-root execution
RUN chmod -R 755 /app \
    && chmod -R 777 /config /data /app/logs

# Setup Entrypoint
COPY <<'EOF' /app/start.sh
#!/bin/bash
set -e
echo "Starting AniMetaFill Daemon..."
exec python -m app.main
EOF

RUN chmod +x /app/start.sh

# Volumes for persistence
VOLUME ["/config", "/data"]

# Switch to non-root user
USER nobody:nogroup

ENTRYPOINT ["/app/start.sh"]
