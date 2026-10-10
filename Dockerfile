FROM python:3.12-slim

# Install uv.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Create a non-root user
RUN groupadd --system --gid 1001 appuser \
    && useradd --system --uid 1001 --gid 1001 --no-create-home --home-dir /app appuser

# Create app directory with proper ownership
WORKDIR /app

# Copy only the application files (not .venv, .git, etc.)
COPY pyproject.toml uv.lock ./
COPY app/ ./app/

# Installer git (requis par uv pour la dépendance git structured-data-models),
# puis les dépendances applicatives.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && uv sync --frozen --no-cache --no-install-project \
    && apt-get purge -y git \
    && rm -rf /var/lib/apt/lists/* \
    && chown -R appuser:appuser /app

# Healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD /app/.venv/bin/python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/')" || exit 1

# Switch to non-root user
USER appuser

# Run the application.
EXPOSE 8080
CMD ["/app/.venv/bin/fastapi", "run", "app/main.py", "--port", "8080", "--host", "0.0.0.0"]