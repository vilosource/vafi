"""HTTP transport layer for the vtf SDK.

Handles authentication, headers, error mapping, retry, and timeout.
"""
import time

import httpx

from . import __version__
from .exceptions import (
    AuthenticationRequired,
    ClaimConflict,
    Conflict,
    GuardViolation,
    InvalidTransition,
    NotFound,
    PermissionDenied,
    RateLimited,
    ServiceUnavailable,
    ValidationError,
    VtfError,
)

# Map v2 error codes to exception classes
_ERROR_CODE_MAP = {
    "VALIDATION_ERROR": ValidationError,
    "AUTHENTICATION_REQUIRED": AuthenticationRequired,
    "PERMISSION_DENIED": PermissionDenied,
    "NOT_FOUND": NotFound,
    "ALREADY_CLAIMED": ClaimConflict,
    "GUARD_VIOLATION": GuardViolation,
    "INVALID_TRANSITION": InvalidTransition,
    "CONFLICT": Conflict,
    "DUPLICATE": Conflict,
    "RATE_LIMITED": RateLimited,
    "SERVICE_UNAVAILABLE": ServiceUnavailable,
}

# HTTP status codes that trigger retry
_RETRYABLE_STATUSES = {429, 503}


class SyncTransport:
    """Synchronous HTTP transport using httpx."""

    def __init__(
        self,
        base_url: str,
        token: str,
        timeout: float = 30.0,
        max_retries: int = 0,
        backoff_factor: float = 0.5,
    ):
        self._client = httpx.Client(
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

    def get(self, path: str, params: dict | None = None) -> dict:
        return self._request("GET", path, params=params)

    def post(self, path: str, json: dict | None = None) -> dict:
        return self._request("POST", path, json=json)

    def patch(self, path: str, json: dict | None = None) -> dict:
        return self._request("PATCH", path, json=json)

    def delete(self, path: str) -> None:
        self._request("DELETE", path)

    def _request(self, method: str, path: str, **kwargs) -> dict | None:
        last_exc = None
        for attempt in range(1 + self._max_retries):
            if attempt > 0:
                time.sleep(self._backoff_factor * (2 ** (attempt - 1)))

            response = self._client.request(method, path, **kwargs)

            if response.status_code in _RETRYABLE_STATUSES and attempt < self._max_retries:
                continue

            if response.status_code >= 400:
                self._raise_for_error(response)

            if response.status_code == 204 or not response.content:
                return None

            return response.json()

        # Should not reach here, but just in case
        return None

    def _raise_for_error(self, response: httpx.Response) -> None:
        """Map v2 error response to SDK exception."""
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
            held_by = (details or {}).get("held_by", "")
            raise ClaimConflict(code, message, details, held_by=held_by)
        elif exc_class is GuardViolation:
            guard_name = (details or {}).get("guard", "")
            raise GuardViolation(code, message, details, guard_name=guard_name)
        elif exc_class is InvalidTransition:
            current = (details or {}).get("current_status", "")
            requested = (details or {}).get("requested_status", "")
            raise InvalidTransition(code, message, details,
                                    current_status=current, attempted_action=requested)
        else:
            raise exc_class(code, message, details)

    def close(self):
        self._client.close()
