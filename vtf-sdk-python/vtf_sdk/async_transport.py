"""Async HTTP transport for the vtf SDK."""
from __future__ import annotations

import asyncio

import httpx

from . import __version__
from .transport import _ERROR_CODE_MAP, _RETRYABLE_STATUSES
from .exceptions import (
    ClaimConflict,
    GuardViolation,
    InvalidTransition,
    ValidationError,
    VtfError,
)


class AsyncTransport:
    """Asynchronous HTTP transport using httpx.AsyncClient."""

    def __init__(
        self,
        base_url: str,
        token: str,
        timeout: float = 30.0,
        max_retries: int = 0,
        backoff_factor: float = 0.5,
    ):
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout,
            headers={
                "Authorization": f"Token {token}",
                "User-Agent": f"vtf-sdk-python/{__version__}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        self._max_retries = max_retries
        self._backoff_factor = backoff_factor

    async def get(self, path: str, params: dict | None = None) -> dict:
        return await self._request("GET", path, params=params)

    async def post(self, path: str, json: dict | None = None) -> dict:
        return await self._request("POST", path, json=json)

    async def patch(self, path: str, json: dict | None = None) -> dict:
        return await self._request("PATCH", path, json=json)

    async def delete(self, path: str) -> None:
        await self._request("DELETE", path)

    async def _request(self, method: str, path: str, **kwargs) -> dict | None:
        for attempt in range(1 + self._max_retries):
            if attempt > 0:
                await asyncio.sleep(self._backoff_factor * (2 ** (attempt - 1)))

            response = await self._client.request(method, path, **kwargs)

            if response.status_code in _RETRYABLE_STATUSES and attempt < self._max_retries:
                continue

            if response.status_code >= 400:
                self._raise_for_error(response)

            if response.status_code == 204 or not response.content:
                return None

            return response.json()

        return None

    def _raise_for_error(self, response: httpx.Response) -> None:
        """Same error mapping as sync transport."""
        try:
            body = response.json()
        except Exception:
            raise VtfError("UNKNOWN", f"HTTP {response.status_code}", None)

        error = body.get("error", {})
        code = error.get("code", "UNKNOWN")
        message = error.get("message", f"HTTP {response.status_code}")
        details = error.get("details")
        field_errors = error.get("field_errors")

        exc_class = _ERROR_CODE_MAP.get(code, VtfError)

        if exc_class is ValidationError:
            raise ValidationError(code, message, details, field_errors=field_errors)
        elif exc_class is ClaimConflict:
            raise ClaimConflict(code, message, details, held_by=(details or {}).get("held_by", ""))
        elif exc_class is GuardViolation:
            raise GuardViolation(code, message, details, guard_name=(details or {}).get("guard", ""))
        elif exc_class is InvalidTransition:
            raise InvalidTransition(code, message, details,
                                    current_status=(details or {}).get("current_status", ""),
                                    attempted_action=(details or {}).get("requested_status", ""))
        else:
            raise exc_class(code, message, details)

    async def close(self):
        await self._client.aclose()
