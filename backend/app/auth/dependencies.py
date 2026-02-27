import logging

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from app.config import get_settings

logger = logging.getLogger(__name__)

# auto_error=False so missing tokens don't 403 before we can check DEBUG mode
security = HTTPBearer(auto_error=False)

# Hardcoded dev user returned when DEBUG=true — safe because DEBUG is never
# true in production (Railway doesn't set it).
_DEV_USER = {
    "id": "dev-user-001",
    "email": "dev@investron.local",
    "role": "authenticated",
}


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict:
    """Validate Supabase JWT token and return user info.

    When DEBUG=true, skips JWT verification and returns a hardcoded test user
    so the full app works locally without a Supabase account.
    """
    settings = get_settings()

    # Dev bypass: return fake user without any token validation
    if settings.debug:
        logger.debug("DEBUG mode: returning dev user (JWT verification skipped)")
        return _DEV_USER

    # Production: require and validate JWT
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    # Supabase signs JWTs with the JWT Secret, not the anon/service keys
    jwt_secret = settings.supabase_jwt_secret or settings.supabase_publishable_key
    try:
        payload = jwt.decode(
            token,
            jwt_secret,
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
