from fastapi import APIRouter

router = APIRouter()


@router.get("")
async def hello_world(name: str):
    return "Hi " + name
