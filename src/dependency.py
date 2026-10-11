"""Authentication dependencies, see README for the three-tier model."""
import jwt
from fastapi import HTTPException, Depends, Security, status, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer, APIKeyHeader
import os
import base64
import hmac

# Cache policy for the public read-only data (World Cup and stocks). Each
# snapshot changes at most a few times a day, so a short browser cache plus a
# longer serve-stale window keeps repeat visits fast without risking
# staleness. It also lets a Cloudflare cache rule serve these responses from
# the edge.
READ_CACHE_CONTROL = "public, max-age=300, stale-while-revalidate=3600"
WORLDCUP_CACHE_CONTROL = READ_CACHE_CONTROL


async def set_worldcup_cache(response: Response) -> None:
    """Attach the read-only cache policy to every World Cup GET response."""
    response.headers["Cache-Control"] = READ_CACHE_CONTROL


async def set_read_cache(response: Response) -> None:
    """Attach the read-only cache policy to a public GET response."""
    response.headers["Cache-Control"] = READ_CACHE_CONTROL

# JWT secret for verifying tokens signed by AuthAPI
JWT_SECRET_ENV = "RP_FASTAPI_JWT_SECRET"

# Admin token for internal admin operations (never exposed to the UI)
ADMIN_TOKEN_ENV = "RP_ADMIN_TOKEN"

# API key for public endpoints (stats, demos), shared with the Angular UI.
# Not truly secret (embedded in the JS bundle), but prevents trivial bot abuse.
# For real protection rely on CORS + Cloudflare rate limiting.
API_KEY_ENV = "RP_FASTAPI_API_KEY"

security = HTTPBearer()
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)


async def has_access(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    Validates a JWT bearer token signed by the AuthAPI (HS256). Only access
    tokens are accepted; the AuthAPI marks them with typ="access", so a
    refresh token cannot stand in for one.
    """
    token = credentials.credentials

    api_secret = os.getenv(JWT_SECRET_ENV)
    if api_secret is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="JWT secret not configured"
        )

    try:
        # Decode the base64-encoded secret key into bytes
        api_secret_bytes = base64.b64decode(api_secret)

        payload = jwt.decode(token,
                             key=api_secret_bytes,  # need to use bytes
                             algorithms=["HS256"],
                             options={"require": ["exp", "sub"]})
    except jwt.PyJWTError:
        # A fixed message: the library's text says why a token failed,
        # which is nothing a client needs.
        payload = None
    if payload is None or payload.get("typ") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    return payload


async def has_admin_role(payload: dict = Depends(has_access)) -> dict:
    """
    An AuthAPI access token whose user has the ADMIN role, for the site's
    admin dashboard. The role is read from the token, which the AuthAPI signs;
    a role change reaches it on the user's next sign-in or token refresh.
    """
    if payload.get("role") != "ADMIN":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admins only",
        )
    return payload


async def set_no_store(response: Response) -> None:
    """Admin answers are never cached, by the browser or by Cloudflare."""
    response.headers["Cache-Control"] = "no-store"


async def has_api_key(api_key: str = Security(_api_key_header)) -> None:
    """
    Validates the X-API-Key header for public endpoints (e.g. /stats).
    The key is a static secret shared with the Angular UI via Cloudflare Pages
    env vars. Uses constant-time comparison to prevent timing attacks.
    """
    expected = os.getenv(API_KEY_ENV)
    if expected is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="API key not configured on server",
        )
    if not hmac.compare_digest(api_key, expected):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key",
        )


async def has_admin_access(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    Validates a static admin bearer token using constant-time comparison
    to prevent timing attacks. For internal/admin-only endpoints only,
    this token is never issued to the UI.
    """
    admin_token = os.getenv(ADMIN_TOKEN_ENV)
    if admin_token is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Admin token not configured"
        )

    if not hmac.compare_digest(credentials.credentials, admin_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid admin token"
        )
