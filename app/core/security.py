"""OAuth2 with Password (and hashing), Bearer with JWT tokens and scopes.

Implementation follows the FastAPI reference example:
https://fastapi.tiangolo.com/advanced/security/oauth2-scopes/
"""

import os
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from dotenv import load_dotenv
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBearer,
)
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash
from pydantic import ValidationError

from ..schemas.security import TokenData, UserInDB

# Load the environment variables from the root .env file.
# Generate a secret with:  openssl rand -hex 32
load_dotenv()

# En production, définir impérativement SECRET_KEY (via .env / variable d'env).
# Fallback de développement et de CI : clé de démo NON sûre pour la production.
# Elle évite qu'un import échoue quand le fichier .env est absent (ex: pipeline CI).
SECRET_KEY = os.getenv("SECRET_KEY") or "09d25e094faa6ca2556c818166b7a9563b93f7099f6f0f4caa6cf63b88e8d3e7"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30


fake_users_db = {
    "johndoe": {
        "username": "johndoe",
        "full_name": "John Doe",
        "email": "johndoe@example.com",
        "hashed_password": "$argon2id$v=19$m=65536,t=3,p=4$YXk8xolITq4hrP3iy9mYhQ$uGLyNyh5LSUOSEtDJgzgcTFNGn9QBA9iNirZ32K9lns",
        "disabled": False,
    },
    "alice": {
        "username": "alice",
        "full_name": "Alice Chains",
        "email": "alicechains@example.com",
        "hashed_password": "$argon2id$v=19$m=65536,t=3,p=4$YXk8xolITq4hrP3iy9mYhQ$uGLyNyh5LSUOSEtDJgzgcTFNGn9QBA9iNirZ32K9lns",
        "disabled": True,
    },
}


password_hash = PasswordHash.recommended()

DUMMY_HASH = password_hash.hash("dummypassword")

# Security scheme for protected routes: client must send a "Bearer <token>"
# header. In the docs, the "Authorize" dialog then only asks for the JWT.
security = HTTPBearer(auto_error=False)


def verify_password(plain_password, hashed_password):
    return password_hash.verify(plain_password, hashed_password)


def get_password_hash(password):
    return password_hash.hash(password)


def get_user(db, username: str) -> UserInDB | None:
    if username in db:
        user_dict = db[username]
        return UserInDB(**user_dict)
    return None


def authenticate_user(fake_db, username: str, password: str) -> UserInDB | bool:
    user = get_user(fake_db, username)
    if not user:
        verify_password(password, DUMMY_HASH)
        return False
    if not verify_password(password, user.hashed_password):
        return False
    return user


def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def _extract_token(
    credentials: HTTPAuthorizationCredentials | None,
    authorization: str | None,
) -> str | None:
    """Return the raw JWT from the Authorization header.

    Tolerant parser: accepts ``Bearer <token>`` (standard, what the HTTPBearer
    scheme recognizes), ``Token <token>``, or the token pasted bare — some
    Swagger UI versions do not add the ``Bearer `` prefix automatically.
    """
    if credentials is not None:
        return credentials.credentials
    if authorization is None:
        return None
    raw = authorization.strip()
    if not raw:
        return None
    for scheme in ("Bearer ", "Token "):
        if raw.lower().startswith(scheme.lower()):
            token = raw[len(scheme) :].strip()
            return token or None
    return raw


async def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(security)
    ] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> UserInDB:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    token = _extract_token(credentials, authorization)
    if token is None:
        raise credentials_exception
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if username is None:
            raise credentials_exception
        token_data = TokenData(username=username)
    except (InvalidTokenError, ValidationError):
        raise credentials_exception
    user = get_user(fake_users_db, username=token_data.username)
    if user is None:
        raise credentials_exception
    return user
