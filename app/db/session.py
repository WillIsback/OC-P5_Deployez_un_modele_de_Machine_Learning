"""Sessions SQLAlchemy : rôle API (requêtes HTTP) et rôle propriétaire (CLIs)."""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Annotated

from dotenv import load_dotenv
from fastapi import Depends
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

load_dotenv()

# Rôle restreint `p5_api` : aucune PII, aucune cible réelle (spec §5.2).
# Pas de mot de passe par défaut dans le code : il vient de DATABASE_URL (.env).
DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql+psycopg://p5_api@localhost:5432/p5"
)

# create_engine est paresseux : aucune connexion n'est ouverte à l'import.
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


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
