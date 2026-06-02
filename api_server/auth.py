import jwt
import time
import os
from functools import wraps
from fastapi import HTTPException, Request

# JWT Configuration
JWT_SECRET = os.environ.get("JWT_SECRET", "fallguard-secret-key-change-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_DAYS = 7


def create_jwt_token(user_id: int, email: str) -> str:
    """Create a JWT token for the authenticated user."""
    payload = {
        "user_id": user_id,
        "email": email,
        "iat": time.time(),
        "exp": time.time() + (JWT_EXPIRY_DAYS * 86400),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_jwt_token(token: str) -> dict | None:
    """Decode and validate a JWT token. Returns payload or None if invalid."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except (jwt.InvalidTokenError, jwt.ExpiredSignatureError):
        return None


def verify_google_token(credential: str, client_id: str) -> dict | None:
    """
    Verify a Google ID token using google-auth library.
    Returns user info dict or None if invalid.
    """
    try:
        from google.oauth2 import id_token
        from google.auth.transport import requests as google_requests

        idinfo = id_token.verify_oauth2_token(
            credential,
            google_requests.Request(),
            client_id
        )

        # Verify issuer
        if idinfo["iss"] not in ["accounts.google.com", "https://accounts.google.com"]:
            return None

        return {
            "google_id": idinfo["sub"],
            "email": idinfo.get("email", ""),
            "name": idinfo.get("name", ""),
            "picture": idinfo.get("picture", ""),
        }
    except Exception as e:
        print(f"❌ Google token verification failed: {e}")
        return None


def get_current_user(request: Request) -> dict:
    """
    Extract and validate JWT from Authorization header.
    Returns decoded payload or raises HTTPException.
    """
    auth_header = request.headers.get("Authorization", "")

    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    token = auth_header[7:]  # Remove "Bearer "
    payload = decode_jwt_token(token)

    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return payload
