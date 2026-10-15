"""Authentification JWT sur la table users (sub = id)."""

import os
from datetime import timedelta

import jwt
import pytest
from conftest import login
from sqlalchemy import select

from app.core import security
from app.core.security import ALGORITHM, create_access_token
from app.db.models import User

pytestmark = pytest.mark.db


def _johndoe_id(db) -> int:
    with db() as s:
        return s.scalar(select(User.id).where(User.username == "johndoe"))


def test_token_sub_is_user_id(client, db):
    r = login(client, "johndoe", "secret")
    assert r.status_code == 200, r.text
    payload = jwt.decode(
        r.json()["access_token"], os.environ["SECRET_KEY"], algorithms=[ALGORITHM]
    )
    assert payload["sub"] == str(_johndoe_id(db))


def test_wrong_password(client):
    assert login(client, "johndoe", "wrong").status_code == 400


def test_unknown_user(client):
    assert login(client, "nobody", "secret").status_code == 400


def test_inactive_user_cannot_login(client):
    assert login(client, "alice", "secret").status_code == 400


def test_list_requires_token(client):
    assert client.get("/model/list").status_code == 401


def test_list_with_token(client, auth_headers):
    r = client.get("/model/list", headers=auth_headers)
    assert r.status_code == 200, r.text


def test_bare_token_accepted(client, auth_headers):
    bare = auth_headers["Authorization"].removeprefix("Bearer ")
    assert client.get("/model/list", headers={"Authorization": bare}).status_code == 200


def test_token_with_non_numeric_sub_rejected(client):
    token = create_access_token({"sub": "johndoe"})
    r = client.get("/model/list", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


def test_token_of_deleted_user_rejected(client, db):
    with db() as s:
        user = User(username="ephemere", hashed_password="x", is_active=True)
        s.add(user)
        s.commit()
        token = create_access_token(
            {"sub": str(user.id)}, expires_delta=timedelta(minutes=5)
        )
        s.delete(user)
        s.commit()
    r = client.get("/model/list", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


def test_token_of_deactivated_user_rejected(client, db, auth_headers):
    with db() as s:
        s.get(User, _johndoe_id(db)).is_active = False
        s.commit()
    assert client.get("/model/list", headers=auth_headers).status_code == 401


def test_missing_secret_key_raises_explicit_error(monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_access_token({"sub": "1"})
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        security.decode_token("x.y.z")
