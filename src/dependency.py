# adding script to manage authentication and other dependencies
from jose import jwt
from jose.exceptions import JOSEError
from fastapi import HTTPException, Depends, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import os
import base64

# security token env variable name
SEC_TOKEN = "RP_API_SEC_TOKEN"

security = HTTPBearer()


async def has_access(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
        Used to validate the authentication token
    """
    token = credentials.credentials

    api_secret = os.getenv(SEC_TOKEN)
    if api_secret is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Security token not set"
        )

    try:
        # Decode the base64 encoded secret key into bytes
        api_secret_bytes = base64.b64decode(api_secret)

        payload = jwt.decode(token,
                             key=api_secret_bytes,  # need to use bytes
                             algorithms=["HS256"])
        print("payload => ", payload)
    except JOSEError as e:  # catches any exception
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e)
        )
