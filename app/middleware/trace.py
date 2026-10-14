"""Middleware ASGI : une ligne `api_requests` par appel (spec §4.3).

La ligne est insérée dès l'entrée (les prédictions peuvent la référencer et une
requête qui plante laisse une trace), puis complétée à la sortie.
"""

from __future__ import annotations

import ipaddress
import time
import uuid
from typing import Any

from sqlalchemy import update
from sqlalchemy.exc import InterfaceError, OperationalError, SQLAlchemyError
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.db import session as db_session
from app.db.models import ApiRequest
from app.db.redaction import to_trace
from app.lib.tools import get_logger

log = get_logger(__name__)

UNTRACED_PATHS = frozenset(
    {"/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"}
)
MAX_PATH_LENGTH = 255
MAX_METHOD_LENGTH = 10


def _client_ip(scope: Scope) -> str | None:
    client = scope.get("client")
    if not client:
        return None
    try:
        return str(ipaddress.ip_address(client[0]))
    except ValueError:
        return None


def _insert_request(
    request_id: uuid.UUID,
    method: str,
    path: str,
    client_ip: str | None,
    request_body: Any,
) -> int:
    # SessionLocal est relu à chaque appel pour pouvoir être patché en test.
    with db_session.SessionLocal() as session:
        row = ApiRequest(
            request_id=request_id,
            method=method[:MAX_METHOD_LENGTH],
            # Postgres refuse le caractère nul dans un varchar.
            path=path.replace("\x00", "\ufffd")[:MAX_PATH_LENGTH],
            client_ip=client_ip,
            request_body=request_body,
        )
        session.add(row)
        session.commit()
        return row.id


def _finalize_request(api_request_id: int, **values: Any) -> None:
    with db_session.SessionLocal() as session:
        session.execute(
            update(ApiRequest).where(ApiRequest.id == api_request_id).values(**values)
        )
        session.commit()


async def _buffer_body(receive: Receive) -> tuple[bytes, Receive]:
    """Lit tout le corps puis renvoie un ``receive`` qui le rejoue à l'app."""
    messages: list[Message] = []
    body = b""
    while True:
        message = await receive()
        messages.append(message)
        if message["type"] != "http.request":
            break
        body += message.get("body", b"")
        if not message.get("more_body", False):
            break
    pending = iter(messages)

    async def replay() -> Message:
        try:
            return next(pending)
        except StopIteration:
            return await receive()

    return body, replay


class TraceMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in UNTRACED_PATHS:
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        request_id = uuid.uuid4()
        body, replay = await _buffer_body(receive)
        try:
            api_request_id = await run_in_threadpool(
                _insert_request,
                request_id,
                scope["method"],
                scope["path"],
                _client_ip(scope),
                to_trace(body, Headers(scope=scope).get("content-type")),
            )
        except SQLAlchemyError as exc:
            if not isinstance(exc, (OperationalError, InterfaceError)):
                # Erreur de données : la base est joignable, la requête passe sans trace.
                log.exception("Trace impossible, requête traitée sans trace")
                await self.app(scope, replay, send)
                return
            log.exception("Trace impossible : base de données indisponible")
            response = JSONResponse(
                {"detail": "Base de données indisponible"}, status_code=503
            )
            await response(scope, replay, send)
            return

        state = scope.setdefault("state", {})
        state["api_request_id"] = api_request_id
        state["request_id"] = str(request_id)

        status_code: int | None = None
        content_type: str | None = None
        chunks: list[bytes] = []

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code, content_type
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = str(request_id)
                content_type = headers.get("content-type")
            elif message["type"] == "http.response.body":
                chunks.append(message.get("body", b""))
            await send(message)

        try:
            await self.app(scope, replay, send_wrapper)
        except Exception:
            status_code = status_code or 500
            raise
        finally:
            try:
                await run_in_threadpool(
                    _finalize_request,
                    api_request_id,
                    status_code=status_code,
                    duration_ms=int((time.perf_counter() - start) * 1000),
                    user_id=state.get("user_id"),
                    response_body=to_trace(b"".join(chunks), content_type),
                )
            except SQLAlchemyError:
                log.exception("Échec de la finalisation de la trace %s", request_id)
