from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from src.endpoints import hello, health
from src.dependency import has_access

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200", "https://regmibishal1.github.io"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
