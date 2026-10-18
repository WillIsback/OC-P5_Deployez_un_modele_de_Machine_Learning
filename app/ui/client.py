"""Client HTTP de l'API : seul point de contact de l'interface avec le service.

Les erreurs sont converties en messages français affichables tels quels ; le
jeton n'est jamais journalisé.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

UNAVAILABLE = "API indisponible"
BAD_CREDENTIALS = "Identifiants incorrects ou compte inactif"
INVALID_REQUEST = "Requête invalide"


class ApiError(Exception):
    """Erreur de l'API (``status`` None si elle est injoignable)."""

    def __init__(self, status: int | None, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class SessionExpired(ApiError):
    def __init__(self) -> None:
        super().__init__(401, "Session expirée, reconnectez-vous")


class ApiClient:
    def __init__(self, http: httpx.Client) -> None:
        self.http = http

    def _request(self, method: str, path: str, token: str | None = None, **kwargs):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        try:
            response = self.http.request(method, path, headers=headers, **kwargs)
        except httpx.TransportError as exc:
            raise ApiError(None, UNAVAILABLE) from exc
        if response.status_code == 401:
            raise SessionExpired()
        if response.status_code >= 400:
            raise ApiError(response.status_code, _detail(response))
        return response.json()

    def login(self, username: str, password: str) -> str:
        try:
            body = self._request(
                "POST", "/token", data={"username": username, "password": password}
            )
        except ApiError as err:
            if err.status == 400:
                raise ApiError(400, BAD_CREDENTIALS) from err
            raise
        return body["access_token"]

    def search_buildings(
        self,
        token: str,
        *,
        q: str | None = None,
        neighborhood: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict:
        params = {
            "q": q,
            "neighborhood": neighborhood,
            "limit": limit,
            "offset": offset,
        }
        return self._request(
            "GET",
            "/buildings",
            token,
            params={k: v for k, v in params.items() if v is not None},
        )

    def get_building(self, token: str, building_id: int) -> dict:
        return self._request("GET", f"/buildings/{building_id}", token)

    def predict(
        self, token: str, building_id: int, data_year: int | None = None
    ) -> dict:
        return self._request(
            "POST", "/model/predict", token, json=_payload(building_id, data_year)
        )

    def compare(
        self, token: str, building_id: int, data_year: int | None = None
    ) -> dict:
        return self._request(
            "POST",
            "/model/predict/compare",
            token,
            json=_payload(building_id, data_year),
        )


def _payload(building_id: int, data_year: int | None) -> dict[str, Any]:
    payload: dict[str, Any] = {"building_id": building_id}
    if data_year is not None:
        payload["data_year"] = data_year
    return payload


def _detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        body = None
    detail = body.get("detail") if isinstance(body, dict) else None
    return detail if isinstance(detail, str) else INVALID_REQUEST


def default_client() -> ApiClient:
    return ApiClient(
        httpx.Client(
            base_url=os.getenv("P5_API_URL", "http://localhost:8080"), timeout=60
        )
    )
