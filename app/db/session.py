"""Sessions SQLAlchemy : rôle API (requêtes HTTP) et rôle propriétaire (CLIs)."""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Annotated, Any

from dotenv import load_dotenv
from fastapi import Depends
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

load_dotenv()

_engine: Engine | None = None


def get_engine() -> Engine:
    """Engine du rôle restreint `p5_api` (spec §5.2), créé au premier usage.

    L'URL (mot de passe compris) vient uniquement de ``DATABASE_URL`` : aucune
    valeur de repli dans le code. L'import reste possible sans la variable (CI,
    outillage) ; ouvrir une session sans elle échoue explicitement. La création
    de l'engine n'ouvre aucune connexion.
    """
    global _engine
    if _engine is None:
        url = os.getenv("DATABASE_URL")
        if not url:
            raise RuntimeError(
                "DATABASE_URL non défini : renseignez-le dans .env ou "
                "l'environnement (voir .example.env)."
            )
        _engine = create_engine(url, pool_pre_ping=True)
    return _engine


class ApiSession(Session):
    """Session liée à l'engine de l'API, résolu à la première ouverture."""

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("bind", get_engine())
        super().__init__(**kwargs)


SessionLocal = sessionmaker(class_=ApiSession, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    # `SessionLocal` est relu à chaque appel : les tests le remplacent.
    with SessionLocal() as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


def owner_session_factory() -> sessionmaker[Session]:
    """Fabrique de sessions du rôle propriétaire (ingestion, préparation, entraînement)."""
    url = os.getenv("DATABASE_OWNER_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_OWNER_URL non défini : renseignez-le dans .env "
            "(voir .example.env)."
        )
    return sessionmaker(bind=create_engine(url), expire_on_commit=False)
