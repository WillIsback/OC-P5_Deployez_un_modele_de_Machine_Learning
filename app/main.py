import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .middleware.trace import DB_UNAVAILABLE_ERRORS, TraceMiddleware
from .routers import auth, buildings, model

DESCRIPTION = """
Prédit la consommation d'énergie (kBtu/an) et les émissions de gaz à effet de
serre (t CO2e/an) des bâtiments non résidentiels de Seattle, avec deux
CatBoost entraînés sur le relevé 2016.

**Authentification** : obtenir un jeton par `POST /token` (bouton *Authorize*),
puis l'envoyer en en-tête `Authorization: Bearer <jeton>`.

Chaque appel est tracé dans PostgreSQL (`api_requests`) et l'identifiant de la
trace est renvoyé dans l'en-tête `X-Request-ID`.
"""

OPENAPI_TAGS = [
    {"name": "auth", "description": "Obtention du jeton JWT (OAuth2 password)."},
    {
        "name": "buildings",
        "description": "Recherche parmi les bâtiments jamais vus par l'entraînement.",
    },
    {
        "name": "model",
        "description": "Prédictions (par identifiant, saisie libre, comparaison "
        "CatBoost / Kumo), modèles enregistrés et scores.",
    },
]

app = FastAPI(
    title="API de prédiction énergétique — Seattle",
    description=DESCRIPTION,
    # Tag de release injecté au build de l'image (release.yml) ; « dev » sinon.
    version=os.getenv("APP_VERSION", "dev"),
    openapi_tags=OPENAPI_TAGS,
    license_info={"name": "MIT", "identifier": "MIT"},
)
app.add_middleware(TraceMiddleware)


async def database_unavailable(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=503, content={"detail": "Base de données indisponible"}
    )


for _error in DB_UNAVAILABLE_ERRORS:
    app.add_exception_handler(_error, database_unavailable)


app.include_router(auth.router)
app.include_router(buildings.router)
app.include_router(model.router)
