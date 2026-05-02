# adding script to manage authentication and other dependencies
from jose import jwt
from jose.exceptions import JOSEError
from fastapi import HTTPException, Depends, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import os
import base64
import hmac

# JWT secret for verifying tokens signed by AuthAPI
JWT_SECRET_ENV = "RP_FASTAPI_JWT_SECRET"

# Admin token for internal admin operations (never exposed to the UI)
ADMIN_TOKEN_ENV = "RP_ADMIN_TOKEN"

security = HTTPBearer()


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
