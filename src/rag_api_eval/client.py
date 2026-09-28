"""Bounded HTTP client for black-box RAG APIs."""

from __future__ import annotations

import os
from typing import Any

import requests

from .models import APIConfig


class RAGAPIError(RuntimeError):
    pass


def _auth_headers(auth: dict[str, Any]) -> dict[str, str]:
    kind = auth.get("type", "none")
    if kind == "none":
        return {}
    env_name = auth.get("token_env")
    token = os.getenv(env_name) if env_name else auth.get("token")
    if not token:
        raise RAGAPIError("API authentication token is not configured.")
    if kind == "bearer":
        return {"Authorization": f"Bearer {token}"}
    if kind == "api_key":
        return {str(auth.get("header", "X-API-Key")): str(token)}
    raise RAGAPIError(f"Unsupported auth type '{kind}'.")


def call_api(config: APIConfig, body: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    headers = {**config.headers, **_auth_headers(config.auth)}
    try:
        response = requests.request(
            config.method,
            config.url,
            json=body,
            params=params,
            headers=headers,
            timeout=config.timeout_seconds,
        )
    except requests.RequestException as exc:
        raise RAGAPIError(f"API request failed: {exc}") from exc
    if not response.ok:
        raise RAGAPIError(f"API returned HTTP {response.status_code}: {response.text[:500]}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise RAGAPIError("API returned a non-JSON response.") from exc
    if not isinstance(payload, dict):
        raise RAGAPIError("API response must be a JSON object.")
    return payload
