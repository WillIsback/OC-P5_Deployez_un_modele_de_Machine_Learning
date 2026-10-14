"""OAuth2 with Password (and hashing), Bearer with JWT tokens and scopes.

Implementation follows the FastAPI reference example:
https://fastapi.tiangolo.com/advanced/security/oauth2-scopes/
"""

import os
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from dotenv import load_dotenv
from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBearer,
)
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import User
from ..db.session import SessionDep

# Load the environment variables from the root .env file.
# Generate a secret with:  openssl rand -hex 32
load_dotenv()

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30


password_hash = PasswordHash.recommended()

DUMMY_HASH = password_hash.hash("dummypassword")

# Security scheme for protected routes: client must send a "Bearer <token>"
# header. In the docs, the "Authorize" dialog then only asks for the JWT.
security = HTTPBearer(auto_error=False)


def _secret_key() -> str:
    """Clé de signature des JWT, lue à chaque usage (aucune clé de repli).

    L'import reste possible sans clé (CI, outillage) ; créer ou vérifier un jeton
    sans ``SECRET_KEY`` échoue explicitement.
    """
    key = os.getenv("SECRET_KEY")
    if not key:
        raise RuntimeError(
            "SECRET_KEY non défini : renseignez-le dans .env ou l'environnement "
            "(génération : `openssl rand -hex 32`)."
        )
    return key


def decode_token(token: str) -> dict:
    """Vérifie la signature et l'expiration du jeton, puis retourne ses claims."""
    return jwt.decode(token, _secret_key(), algorithms=[ALGORITHM])


def verify_password(plain_password, hashed_password):
    return password_hash.verify(plain_password, hashed_password)


def get_password_hash(password):
    return password_hash.hash(password)


def get_user_by_username(session: Session, username: str) -> User | None:
    return session.scalar(select(User).where(User.username == username))


def authenticate_user(session: Session, username: str, password: str) -> User | None:
    """Retourne l'utilisateur si identifiants valides et compte actif, sinon None."""
    user = get_user_by_username(session, username)
    if user is None:
        verify_password(password, DUMMY_HASH)  # temps constant
        return None
    if not verify_password(password, user.hashed_password) or not user.is_active:
        return None
    return user


def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, _secret_key(), algorithm=ALGORITHM)
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


def get_current_user(
    request: Request,
    session: SessionDep,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(security)
    ] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Identifiants invalides",
        headers={"WWW-Authenticate": "Bearer"},
    )
    token = _extract_token(credentials, authorization)
    if token is None:
        raise credentials_exception
    try:
        payload = decode_token(token)
        user_id = int(payload.get("sub"))
    except (InvalidTokenError, TypeError, ValueError):
        raise credentials_exception
    # Relecture en base à chaque requête : un token d'un utilisateur supprimé
    # ou désactivé après émission est refusé.
    user = session.get(User, user_id)
    if user is None or not user.is_active:
        raise credentials_exception
    # Lu par le middleware de trace pour renseigner api_requests.user_id.
    request.state.user_id = user.id
    return user
