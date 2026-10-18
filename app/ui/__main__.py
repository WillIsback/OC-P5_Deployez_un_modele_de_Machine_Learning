"""Lance l'interface : ``python -m app.ui`` (API visée : ``P5_API_URL``)."""

from .app import build_app, launch_options

if __name__ == "__main__":
    build_app().launch(**launch_options())
