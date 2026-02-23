from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from app.config import get_settings

security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """Validate Supabase JWT token and return user info."""
    settings = get_settings()
    token = credentials.credentials

    try:
        # Supabase JWTs use the JWT secret derived from the project
        # For now, we decode without full verification for development
        # In production, verify with Supabase's JWKS endpoint
        payload = jwt.decode(
            token,
            settings.supabase_publishable_key,
            algorithms=["HS256"],
            options={"verify_aud": False},
        )
        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: missing user ID",
            )
        return {
            "id": user_id,
            "email": payload.get("email"),
            "role": payload.get("role"),
        }
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
