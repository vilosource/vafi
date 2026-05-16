"""Step 4: HTTP transport, auth, and error mapping tests.

Uses respx to mock httpx requests.
"""
import pytest
import httpx
import respx


@pytest.fixture
def mock_api():
    """respx mock router for the vtf API."""
    with respx.mock(base_url="http://vtf-test:8000") as router:
        yield router


class TestAuth:

    def test_token_auth_header(self, mock_api):
        """DoD #1"""
        from vtf_sdk.transport import SyncTransport
        mock_api.get("/v2/tasks/").respond(200, json={"results": []})
        transport = SyncTransport(base_url="http://vtf-test:8000", token="test-token-123")
        transport.get("/v2/tasks/")
        assert mock_api.calls[0].request.headers["authorization"] == "Token test-token-123"

    def test_user_agent_header(self, mock_api):
        """DoD #2"""
        from vtf_sdk.transport import SyncTransport
        mock_api.get("/v2/tasks/").respond(200, json={"results": []})
        transport = SyncTransport(base_url="http://vtf-test:8000", token="t")
        transport.get("/v2/tasks/")
        assert "vtf-sdk-python" in mock_api.calls[0].request.headers["user-agent"]

    def test_json_content_type(self, mock_api):
        """DoD #3"""
        from vtf_sdk.transport import SyncTransport
        mock_api.post("/v2/tasks/").respond(201, json={"id": "t1"})
        transport = SyncTransport(base_url="http://vtf-test:8000", token="t")
        transport.post("/v2/tasks/", json={"title": "Test"})
        assert "application/json" in mock_api.calls[0].request.headers["content-type"]


class TestErrorMapping:

    def test_error_400_raises_validation(self, mock_api):
        """DoD #4"""
        from vtf_sdk.transport import SyncTransport
        from vtf_sdk.exceptions import ValidationError
        mock_api.post("/v2/tasks/").respond(400, json={
            "error": {"code": "VALIDATION_ERROR", "message": "Invalid", "details": None,
                      "field_errors": {"title": ["Required"]}}
        })
        transport = SyncTransport(base_url="http://vtf-test:8000", token="t")
        with pytest.raises(ValidationError) as exc_info:
            transport.post("/v2/tasks/", json={})
        assert exc_info.value.field_errors == {"title": ["Required"]}

    def test_error_401_raises_auth(self, mock_api):
        """DoD #5"""
        from vtf_sdk.transport import SyncTransport
        from vtf_sdk.exceptions import AuthenticationRequired
        mock_api.get("/v2/tasks/").respond(401, json={
            "error": {"code": "AUTHENTICATION_REQUIRED", "message": "No token", "details": None, "field_errors": None}
        })
        transport = SyncTransport(base_url="http://vtf-test:8000", token="bad")
        with pytest.raises(AuthenticationRequired):
            transport.get("/v2/tasks/")

    def test_error_403_raises_permission(self, mock_api):
        """DoD #6"""
        from vtf_sdk.transport import SyncTransport
        from vtf_sdk.exceptions import PermissionDenied
        mock_api.get("/v2/tasks/t1/").respond(403, json={
            "error": {"code": "PERMISSION_DENIED", "message": "Not allowed", "details": None, "field_errors": None}
        })
        transport = SyncTransport(base_url="http://vtf-test:8000", token="t")
        with pytest.raises(PermissionDenied):
            transport.get("/v2/tasks/t1/")

    def test_error_404_raises_not_found(self, mock_api):
        """DoD #7"""
        from vtf_sdk.transport import SyncTransport
        from vtf_sdk.exceptions import NotFound
        mock_api.get("/v2/tasks/nonexistent/").respond(404, json={
            "error": {"code": "NOT_FOUND", "message": "Not found", "details": None, "field_errors": None}
        })
        transport = SyncTransport(base_url="http://vtf-test:8000", token="t")
        with pytest.raises(NotFound):
            transport.get("/v2/tasks/nonexistent/")

    def test_error_409_claim_conflict(self, mock_api):
        """DoD #8"""
        from vtf_sdk.transport import SyncTransport
        from vtf_sdk.exceptions import ClaimConflict
        mock_api.post("/v2/tasks/t1/claim/").respond(409, json={
            "error": {"code": "ALREADY_CLAIMED", "message": "Claimed", "details": {"held_by": "agent-1"}, "field_errors": None}
        })
        transport = SyncTransport(base_url="http://vtf-test:8000", token="t")
        with pytest.raises(ClaimConflict) as exc_info:
            transport.post("/v2/tasks/t1/claim/", json={})
        assert exc_info.value.held_by == "agent-1"

    def test_error_409_guard_violation(self, mock_api):
        """DoD #9"""
        from vtf_sdk.transport import SyncTransport
        from vtf_sdk.exceptions import GuardViolation
        mock_api.post("/v2/tasks/t1/submit/").respond(409, json={
            "error": {"code": "GUARD_VIOLATION", "message": "Guard failed",
                      "details": {"guard": "guard_has_workplan"}, "field_errors": None}
        })
        transport = SyncTransport(base_url="http://vtf-test:8000", token="t")
        with pytest.raises(GuardViolation) as exc_info:
            transport.post("/v2/tasks/t1/submit/", json={})
        assert exc_info.value.guard_name == "guard_has_workplan"

    def test_error_422_invalid_transition(self, mock_api):
        """DoD #10"""
        from vtf_sdk.transport import SyncTransport
        from vtf_sdk.exceptions import InvalidTransition
        mock_api.post("/v2/tasks/t1/complete/").respond(422, json={
            "error": {"code": "INVALID_TRANSITION", "message": "Cannot transition",
                      "details": {"current_status": "draft", "requested_status": "done"}, "field_errors": None}
        })
        transport = SyncTransport(base_url="http://vtf-test:8000", token="t")
        with pytest.raises(InvalidTransition):
            transport.post("/v2/tasks/t1/complete/", json={})


class TestTransportConfig:

    def test_timeout_config(self, mock_api):
        """DoD #11"""
        from vtf_sdk.transport import SyncTransport
        transport = SyncTransport(base_url="http://vtf-test:8000", token="t", timeout=5.0)
        assert transport._client.timeout.read == 5.0

    def test_retry_on_503(self, mock_api):
        """DoD #12"""
        from vtf_sdk.transport import SyncTransport
        # First call 503, second call 200
        mock_api.get("/v2/tasks/").mock(
            side_effect=[
                httpx.Response(503, json={"error": {"code": "SERVICE_UNAVAILABLE", "message": "Down"}}),
                httpx.Response(200, json={"results": []}),
            ]
        )
        transport = SyncTransport(base_url="http://vtf-test:8000", token="t", max_retries=2)
        result = transport.get("/v2/tasks/")
        assert result == {"results": []}
        assert len(mock_api.calls) == 2
