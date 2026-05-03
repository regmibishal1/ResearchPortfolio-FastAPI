# adding script to manage authentication and other dependencies
from jose import jwt
from jose.exceptions import JOSEError
from fastapi import HTTPException, Depends, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer, APIKeyHeader
import os
import base64
import hmac

# JWT secret for verifying tokens signed by AuthAPI
JWT_SECRET_ENV = "RP_FASTAPI_JWT_SECRET"

# Admin token for internal admin operations (never exposed to the UI)
ADMIN_TOKEN_ENV = "RP_ADMIN_TOKEN"

# API key for public endpoints (stats, demos) — shared with the Angular UI.
# Not truly secret (embedded in the JS bundle), but prevents trivial bot abuse.
# For real protection rely on CORS + Cloudflare rate limiting.
API_KEY_ENV = "RP_FASTAPI_API_KEY"

security = HTTPBearer()
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)


async def has_access(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    Validates a JWT bearer token signed by the AuthAPI (HS256).
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
                             algorithms=["HS256"])
    except JOSEError as e:  # catches any JOSE exception
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e)
        )


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
    to prevent timing attacks. For internal/admin-only endpoints only —
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
