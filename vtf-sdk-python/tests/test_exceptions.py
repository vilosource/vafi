"""Step 3: Exception hierarchy tests."""
import pytest


class TestExceptions:

    def test_vtf_error_base(self):
        """DoD #1"""
        from vtf_sdk.exceptions import VtfError
        err = VtfError("TEST_CODE", "test message", {"key": "val"})
        assert err.code == "TEST_CODE"
        assert err.message == "test message"
        assert err.details == {"key": "val"}
        assert str(err) == "test message"

    def test_validation_error_field_errors(self):
        """DoD #2"""
        from vtf_sdk.exceptions import ValidationError
        err = ValidationError("VALIDATION_ERROR", "Invalid", field_errors={"title": ["Required"]})
        assert err.field_errors == {"title": ["Required"]}

    def test_claim_conflict_held_by(self):
        """DoD #3"""
        from vtf_sdk.exceptions import ClaimConflict
        err = ClaimConflict("ALREADY_CLAIMED", "Task claimed", held_by="agent-1")
        assert err.held_by == "agent-1"

    def test_guard_violation_guard_name(self):
        """DoD #4"""
        from vtf_sdk.exceptions import GuardViolation
        err = GuardViolation("GUARD_VIOLATION", "Guard failed", guard_name="guard_has_workplan")
        assert err.guard_name == "guard_has_workplan"

    def test_invalid_transition(self):
        """DoD #5"""
        from vtf_sdk.exceptions import InvalidTransition
        err = InvalidTransition("INVALID_TRANSITION", "Cannot transition",
                                current_status="draft", attempted_action="complete")
        assert err.current_status == "draft"
        assert err.attempted_action == "complete"

    def test_not_found_subclasses(self):
        """DoD #6"""
        from vtf_sdk.exceptions import NotFound, TaskNotFound, ProjectNotFound
        assert issubclass(TaskNotFound, NotFound)
        assert issubclass(ProjectNotFound, NotFound)

    def test_error_hierarchy(self):
        """DoD #7"""
        from vtf_sdk.exceptions import (
            VtfError, AuthenticationRequired, PermissionDenied,
            NotFound, ValidationError, Conflict, ClaimConflict,
            GuardViolation, InvalidTransition, RateLimited,
        )
        for cls in [AuthenticationRequired, PermissionDenied, NotFound,
                    ValidationError, Conflict, ClaimConflict, GuardViolation,
                    InvalidTransition, RateLimited]:
            assert issubclass(cls, VtfError)
