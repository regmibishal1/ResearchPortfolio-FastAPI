from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def api_health():
    return "The API is up and running!"
