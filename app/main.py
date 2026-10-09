from fastapi import FastAPI

from .routers import auth, model

app = FastAPI()


app.include_router(auth.router)
app.include_router(model.router)
