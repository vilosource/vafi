"""Domain exception hierarchy for the vtf SDK.

Maps v2 API error codes to typed Python exceptions.
"""


class VtfError(Exception):
    """Base for all SDK exceptions."""

    def __init__(self, code: str, message: str, details: dict | None = None):
        self.code = code
        self.message = message
        self.details = details
        super().__init__(message)


class AuthenticationRequired(VtfError):
    ...


class PermissionDenied(VtfError):
    ...


class NotFound(VtfError):
    ...


class TaskNotFound(NotFound):
    ...


class ProjectNotFound(NotFound):
    ...


class ValidationError(VtfError):
    def __init__(self, code: str, message: str, details: dict | None = None,
                 field_errors: dict[str, list[str]] | None = None):
        super().__init__(code, message, details)
        self.field_errors = field_errors


class Conflict(VtfError):
    ...


class ClaimConflict(Conflict):
    def __init__(self, code: str, message: str, details: dict | None = None,
                 held_by: str = ""):
        super().__init__(code, message, details)
        self.held_by = held_by


class GuardViolation(Conflict):
    def __init__(self, code: str, message: str, details: dict | None = None,
                 guard_name: str = ""):
        super().__init__(code, message, details)
        self.guard_name = guard_name


class DuplicateError(Conflict):
    ...


class InvalidTransition(VtfError):
    def __init__(self, code: str, message: str, details: dict | None = None,
                 current_status: str = "", attempted_action: str = ""):
        super().__init__(code, message, details)
        self.current_status = current_status
        self.attempted_action = attempted_action


class RateLimited(VtfError):
    ...


class ServiceUnavailable(VtfError):
    ...
