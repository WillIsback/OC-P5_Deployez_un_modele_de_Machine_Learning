from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .middleware.trace import DB_UNAVAILABLE_ERRORS, TraceMiddleware
from .routers import auth, model

app = FastAPI()
app.add_middleware(TraceMiddleware)


async def database_unavailable(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=503, content={"detail": "Base de données indisponible"}
    )


for _error in DB_UNAVAILABLE_ERRORS:
    app.add_exception_handler(_error, database_unavailable)


app.include_router(auth.router)
app.include_router(model.router)
