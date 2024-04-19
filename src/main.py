from fastapi import FastAPI, Depends
from src.endpoints import hello, health
from src.dependency import has_access

app = FastAPI()

# routes
PROTECTED = [Depends(has_access)]

app.include_router(
    hello.router,
    prefix="/hello",
    dependencies=PROTECTED
)

app.include_router(
    health.router
)
