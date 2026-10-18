"""Lance l'interface : ``python -m app.ui`` (API visée : ``P5_API_URL``)."""

from .app import LAUNCH_OPTIONS, build_app

if __name__ == "__main__":
    build_app().launch(server_name="0.0.0.0", server_port=7860, **LAUNCH_OPTIONS)
