# Aegis Sovereign Knowledge Appliance — Production Multi-Task Container Image
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app:/home/tlima/Enterprise_Hub

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    sqlite3 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml requirements.txt /app/
# Quoted: unquoted, the shell reads ">=42.0.0" as a redirect and the version floors are silently dropped.
RUN pip install --no-cache-dir \
    "cryptography>=42.0.0" \
    "zstandard>=0.22.0" \
    "pydantic>=2.0.0" \
    "qdrant-client>=1.12.0" \
    "requests>=2.31.0" \
    "pyyaml>=6.0" \
    "watchdog>=4.0.0" \
    "fastembed>=0.3.0" \
    "python-docx>=1.1.0" \
    "openpyxl>=3.1.0" \
    "xlrd>=2.0.0"

LABEL org.opencontainers.image.source="https://github.com/TravT/aegis-sovereign"
LABEL org.opencontainers.image.description="Aegis Sovereign Knowledge Appliance (AS)"
LABEL org.opencontainers.image.licenses="Apache-2.0"

COPY core /app/core
COPY desktop /app/desktop
COPY web /app/web
COPY tools /app/tools
COPY docs /app/docs

EXPOSE 8765 8766 8767

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8765/health || exit 1

CMD ["python3", "-m", "core.server", "--host", "0.0.0.0", "--port", "8765"]
