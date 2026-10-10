# Image applicative : dérive de l'image de base (dépendances précompilées) et
# n'ajoute que le code de l'application. Le build est donc très rapide.
ARG BASE_IMAGE=ghcr.io/willisback/oc-p5_deployez_un_modele_de_machine_learning:base
FROM ${BASE_IMAGE}

WORKDIR /app

# Copier le code applicatif (les deps sont déjà dans /app/.venv via l'image de base).
COPY --chown=appuser:appuser app/ ./app/

# Healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD /app/.venv/bin/python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/')" || exit 1

# Switch to non-root user
USER appuser

# Run the application.
EXPOSE 8080
CMD ["/app/.venv/bin/fastapi", "run", "app/main.py", "--port", "8080", "--host", "0.0.0.0"]
