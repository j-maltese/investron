from fastapi import APIRouter, Depends
from app.auth.dependencies import get_current_user

router = APIRouter()


@router.get("/me")
async def get_me(user: dict = Depends(get_current_user)):
    """Return current authenticated user info."""
    return user
