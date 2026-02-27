import logging
import time

import httpx
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

# ---------------------------------------------------------------------------
# JWKS cache — Supabase publishes signing keys at a well-known endpoint.
# We cache for 5 minutes to avoid fetching on every request.
# ---------------------------------------------------------------------------
_jwks_cache: dict | None = None
_jwks_fetched_at: float = 0
_JWKS_TTL = 300  # seconds


async def _get_supabase_jwks(supabase_url: str) -> dict:
    """Fetch and cache Supabase's public JWKS (signing keys)."""
    global _jwks_cache, _jwks_fetched_at
    now = time.time()
    if _jwks_cache and (now - _jwks_fetched_at) < _JWKS_TTL:
        return _jwks_cache

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{supabase_url}/auth/v1/.well-known/jwks.json",
            timeout=10,
        )
        resp.raise_for_status()
        _jwks_cache = resp.json()
        _jwks_fetched_at = now
        logger.info(f"Fetched JWKS from Supabase ({len(_jwks_cache.get('keys', []))} keys)")
        return _jwks_cache


def _extract_user(payload: dict) -> dict:
    """Extract user info from a verified JWT payload."""
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


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict:
    """Validate Supabase JWT token and return user info.

    When DEBUG=true, skips JWT verification and returns a hardcoded test user
    so the full app works locally without a Supabase account.

    Supports both modern JWKS verification (ES256/RS256) and legacy HS256.
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
    header = jwt.get_unverified_header(token)
    kid = header.get("kid")
    alg = header.get("alg", "HS256")

    # Strategy 1: JWKS-based verification (ES256, RS256, etc.)
    # Supabase publishes signing keys at {url}/auth/v1/.well-known/jwks.json
    if kid and settings.supabase_url:
        try:
            jwks = await _get_supabase_jwks(settings.supabase_url)
            for key in jwks.get("keys", []):
                if key.get("kid") == kid:
                    payload = jwt.decode(
                        token,
                        key,
                        algorithms=[alg, "ES256", "RS256", "HS256"],
                        options={"verify_aud": False},
                    )
                    return _extract_user(payload)
            logger.warning(f"No JWKS key matched kid={kid}")
        except JWTError as e:
            logger.error(f"JWKS verification failed: {e}")
        except Exception as e:
            logger.error(f"JWKS fetch/parse error: {e}")

    # Strategy 2: Legacy HS256 with JWT secret
    jwt_secret = settings.supabase_jwt_secret or settings.supabase_publishable_key
    if jwt_secret:
        try:
            payload = jwt.decode(
                token,
                jwt_secret,
                algorithms=["HS256"],
                options={"verify_aud": False},
            )
            return _extract_user(payload)
        except JWTError as e:
            logger.error(f"HS256 fallback failed: {e} | secret_source={'jwt_secret' if settings.supabase_jwt_secret else 'publishable_key'}")

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
    )
