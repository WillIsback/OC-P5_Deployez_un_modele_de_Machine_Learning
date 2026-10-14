from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

from .middleware.trace import TraceMiddleware
from .routers import auth, model

app = FastAPI()
app.add_middleware(TraceMiddleware)


@app.exception_handler(OperationalError)
async def database_unavailable(request: Request, exc: OperationalError) -> JSONResponse:
    return JSONResponse(
        status_code=503, content={"detail": "Base de données indisponible"}
    )


app.include_router(auth.router)
app.include_router(model.router)
