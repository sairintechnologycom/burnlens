FROM python:3.10-slim

WORKDIR /app

# Install curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY burnlens/ ./burnlens/

RUN pip install --no-cache-dir .

EXPOSE 8420

ENV PORT=8420
ENV BURNLENS_DB_PATH=/data/burnlens.db

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:$PORT/health || exit 1

CMD ["sh", "-c", "burnlens start --host 0.0.0.0 --port $PORT"]
