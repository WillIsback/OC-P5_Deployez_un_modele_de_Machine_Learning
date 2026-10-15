"""Provisionnement idempotent de PostgreSQL (spec §5.3).

Usage : ``uv run python -m app.db.create_db [--demo-users]`` (ou via le service
Compose ``tools``). Les comptes de démonstration (johndoe/secret) ne sont créés
que sur demande : ``--demo-users`` ou ``P5_SEED_DEMO_USERS=1``. À désactiver en
production.
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path

import psycopg
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.security import get_password_hash
from app.db.models import MlModel, User
from app.db.registry import CATBOOST_NAME, KUMO_NAME
from app.lib.tools import get_logger

log = get_logger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

# Droits du rôle API (spec §5.2) ; {api} est remplacé par l'identifiant du rôle.
API_GRANTS = (
    "GRANT USAGE ON SCHEMA public TO {api}",
    "GRANT SELECT ON users, buildings, building_features, ml_models TO {api}",
    "GRANT SELECT (id, building_id, data_year) ON building_records_raw TO {api}",
    "GRANT SELECT, INSERT, UPDATE ON api_requests TO {api}",
    "GRANT SELECT, INSERT ON prediction_inputs, predictions TO {api}",
    "GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO {api}",
)

DEMO_USERS = (
    {
        "username": "johndoe",
        "full_name": "John Doe",
        "email": "johndoe@example.com",
        "is_active": True,
    },
    {
        "username": "alice",
        "full_name": "Alice Chains",
        "email": "alicechains@example.com",
        "is_active": False,
    },
)

# (nom, version, artifact_path) des modèles disponibles dès l'installation.
SEED_MODELS = (
    (CATBOOST_NAME, "baseline", "models"),
    (KUMO_NAME, "zero-shot", None),
)


@dataclass(frozen=True)
class Roles:
    owner: str
    api: str
    mlflow: str

    @classmethod
    def with_prefix(cls, prefix: str) -> Roles:
        return cls(f"{prefix}_owner", f"{prefix}_api", f"{prefix}_mlflow")


def dsn(url: str, **overrides: object) -> str:
    """URL SQLAlchemy → DSN libpq utilisable par psycopg."""
    return (
        make_url(url)
        .set(drivername="postgresql", **overrides)
        .render_as_string(hide_password=False)
    )


def _ensure_role(conn: psycopg.Connection, name: str, password: str) -> None:
    exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (name,))
    verb = "ALTER" if exists.fetchone() else "CREATE"
    conn.execute(
        sql.SQL(verb + " ROLE {} LOGIN PASSWORD {}").format(
            sql.Identifier(name), sql.Literal(password)
        )
    )


def _ensure_database(conn: psycopg.Connection, name: str, owner: str) -> None:
    exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,))
    if exists.fetchone() is None:
        conn.execute(
            sql.SQL("CREATE DATABASE {} OWNER {}").format(
                sql.Identifier(name), sql.Identifier(owner)
            )
        )
    conn.execute(
        sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(name))
    )


def run_migrations(owner_url: str) -> None:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", owner_url.replace("%", "%%"))
    command.upgrade(cfg, "head")


def _apply_grants(admin_url: str, db_name: str, roles: Roles) -> None:
    with psycopg.connect(dsn(admin_url, database=db_name), autocommit=True) as conn:
        conn.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(db_name), sql.Identifier(roles.api)
            )
        )
        for stmt in API_GRANTS:
            conn.execute(sql.SQL(stmt).format(api=sql.Identifier(roles.api)))


def seed(session: Session, *, demo_users: bool = False) -> None:
    """Modèles initiaux et, sur demande, utilisateurs de démo (hash à l'exécution)."""
    for user in DEMO_USERS if demo_users else ():
        if session.scalar(select(User).where(User.username == user["username"])):
            continue
        session.add(User(**user, hashed_password=get_password_hash("secret")))
    for name, version, artifact_path in SEED_MODELS:
        if session.scalar(select(MlModel).where(MlModel.name == name)):
            continue
        session.add(
            MlModel(
                name=name, version=version, artifact_path=artifact_path, is_active=True
            )
        )
    session.commit()


def provision(
    admin_url: str,
    *,
    passwords: dict[str, str],
    db_name: str = "p5",
    mlflow_db: str = "mlflow",
    role_prefix: str = "p5",
    demo_users: bool = False,
) -> str:
    """Crée rôles et bases, migre, applique les droits, seed. Retourne l'URL owner.

    ``demo_users`` crée les comptes de démonstration (mot de passe connu) : jamais
    en production.
    """
    roles = Roles.with_prefix(role_prefix)
    with psycopg.connect(dsn(admin_url), autocommit=True) as conn:
        _ensure_role(conn, roles.owner, passwords["owner"])
        _ensure_role(conn, roles.api, passwords["api"])
        _ensure_role(conn, roles.mlflow, passwords["mlflow"])
        _ensure_database(conn, db_name, roles.owner)
        _ensure_database(conn, mlflow_db, roles.mlflow)
    owner_url = (
        make_url(admin_url)
        .set(username=roles.owner, password=passwords["owner"], database=db_name)
        .render_as_string(hide_password=False)
    )
    run_migrations(owner_url)
    _apply_grants(admin_url, db_name, roles)
    engine = create_engine(owner_url)
    try:
        with Session(engine) as session:
            seed(session, demo_users=demo_users)
    finally:
        engine.dispose()
    log.info("Base %s provisionnée (rôles %s_*)", db_name, role_prefix)
    return owner_url


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Provisionnement PostgreSQL (P5)")
    parser.add_argument(
        "--demo-users",
        action="store_true",
        help="Crée les comptes de démo johndoe/alice (mot de passe « secret ») ; "
        "équivaut à P5_SEED_DEMO_USERS=1. À ne jamais utiliser en production.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    demo_users = args.demo_users or os.getenv("P5_SEED_DEMO_USERS") == "1"
    passwords = {
        "owner": os.environ["P5_OWNER_PASSWORD"],
        "api": os.environ["P5_API_PASSWORD"],
        "mlflow": os.environ["P5_MLFLOW_PASSWORD"],
    }
    provision(
        os.environ["DATABASE_ADMIN_URL"], passwords=passwords, demo_users=demo_users
    )
    if demo_users:
        print("[create_db] comptes de démo créés (johndoe/secret) : pas en production")
    print("[create_db] base p5 et base mlflow prêtes")


if __name__ == "__main__":
    main()
