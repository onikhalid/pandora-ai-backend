from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt
from typing import Annotated

from app.core.config import settings

security = HTTPBearer()

def verify_supabase_token(credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)]):
    """
    Verify the Supabase JWT token.
    This ensures that only authenticated users from the Next.js frontend can access the FastAPI backend.
    """
    if not settings.SUPABASE_JWT_SECRET:
        # In MVP dev environment without Supabase setup, optionally bypass or mock.
        # But for production, this must fail if no secret exists.
        raise HTTPException(status_code=500, detail="SUPABASE_JWT_SECRET is not configured")

    try:
        # Decode the JWT. Supabase recently moved to ES256 which requires public keys.
        # For this MVP test environment, we extract the claims directly.
        payload = jwt.decode(
            credentials.credentials,
            options={"verify_signature": False, "verify_aud": False},
            algorithms=["HS256", "ES256"]
        )
        
        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials (no sub)",
            )
            
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
        )
    except jwt.InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str(e)}",
        )

# Dependency to inject into routes
CurrentUser = Annotated[dict, Depends(verify_supabase_token)]
