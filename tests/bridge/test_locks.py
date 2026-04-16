"""Tests for bridge lock management with vtf persistence."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import ASGITransport, AsyncClient

from bridge.app import create_app
from bridge.lock_manager import LockManager, LockConflictError
from bridge.pi_session import PiSession
from bridge.pod_process import PodProcessManager, PodSession


ROLES_YAML = """
roles:
  architect:
    session_type: locked
    harness: pi-rpc
    model: claude-sonnet-4-20250514
    thinking_level: medium
    methodology: /opt/vf-agent/methodologies/architect.md
    mcp_tools: [vtf, cxdb]
    description: Planning
  assistant:
    session_type: ephemeral
    harness: pi-rpc
    model: claude-sonnet-4-20250514
    thinking_level: low
    methodology: ""
    mcp_tools: [vtf]
    description: Quick ops
"""


def _mock_user(user_id=1, username="testuser", projects=None):
    return {
        "user_id": user_id, "username": username, "user_type": "human",
        "is_staff": False,
        "projects": projects or [{"project_id": "proj-1", "role": "member"}],
    }


@pytest.fixture
def roles_file(tmp_path):
    f = tmp_path / "roles.yaml"
    f.write_text(ROLES_YAML)
    return str(f)


@pytest.fixture
def app(roles_file):
    return create_app(roles_config=roles_file)


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _mock_pod_session():
    """Create a mocked PodSession."""
    session = MagicMock(spec=PodSession)
    session.session_id = "mock-locked-sess"
    session.initialize = AsyncMock()
    session.send_prompt = AsyncMock(return_value={
        "session_id": "mock-locked-sess", "text": "ok",
        "input_tokens": 10, "output_tokens": 5, "total_tokens": 15,
        "cost_usd": 0, "num_turns": 1, "tool_uses": [],
    })
    session.stream_prompt = AsyncMock()
    session.shutdown = AsyncMock()
    return session


@pytest.fixture(autouse=True)
def mock_pod_creation():
    """Mock pod creation for all lock tests — unit tests don't create real k8s pods."""
    mock_session = _mock_pod_session()
    with patch.object(PodProcessManager, "create_or_get_pod", new_callable=AsyncMock, return_value="mock-pod"), \
         patch.object(PodProcessManager, "exec_pi", new_callable=AsyncMock, return_value=MagicMock()), \
         patch("bridge.app.PodSession", return_value=mock_session):
        yield mock_session


class TestLockEndpoints:
    @pytest.mark.asyncio
    async def test_acquire_lock_returns_session(self, client):
        with patch("bridge.auth.validate_token", new_callable=AsyncMock, return_value=_mock_user()):
            resp = await client.post(
                "/v1/lock",
                json={"project": "proj-1", "role": "architect"},
                headers={"Authorization": "Token valid"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["session_id"]
            assert data["role"] == "architect"

    @pytest.mark.asyncio
    async def test_acquire_lock_contention_returns_409(self, client):
        # First user acquires
        with patch("bridge.auth.validate_token", new_callable=AsyncMock, return_value=_mock_user(user_id=1, username="user1")):
            resp = await client.post(
                "/v1/lock",
                json={"project": "proj-1", "role": "architect"},
                headers={"Authorization": "Token valid"},
            )
            assert resp.status_code == 200

        # Second user tries — 409
        with patch("bridge.auth.validate_token", new_callable=AsyncMock, return_value=_mock_user(user_id=2, username="user2")):
            resp = await client.post(
                "/v1/lock",
                json={"project": "proj-1", "role": "architect"},
                headers={"Authorization": "Token valid"},
            )
            assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_release_lock(self, client):
        # Acquire first
        with patch("bridge.auth.validate_token", new_callable=AsyncMock, return_value=_mock_user()):
            await client.post(
                "/v1/lock",
                json={"project": "proj-1", "role": "architect"},
                headers={"Authorization": "Token valid"},
            )

        # Release
        with patch("bridge.auth.validate_token", new_callable=AsyncMock, return_value=_mock_user()):
            resp = await client.request(
                "DELETE", "/v1/lock",
                json={"project": "proj-1", "role": "architect"},
                headers={"Authorization": "Token valid"},
            )
            assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_list_locks(self, client):
        with patch("bridge.auth.validate_token", new_callable=AsyncMock, return_value=_mock_user()):
            await client.post(
                "/v1/lock",
                json={"project": "proj-1", "role": "architect"},
                headers={"Authorization": "Token valid"},
            )

        resp = await client.get("/v1/locks")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["role"] == "architect"

    @pytest.mark.asyncio
    async def test_lock_ephemeral_role_returns_400(self, client):
        with patch("bridge.auth.validate_token", new_callable=AsyncMock, return_value=_mock_user()):
            resp = await client.post(
                "/v1/lock",
                json={"project": "proj-1", "role": "assistant"},
                headers={"Authorization": "Token valid"},
            )
            assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_reconnect_existing_lock(self, client):
        """Same user re-acquires lock → gets same session_id."""
        with patch("bridge.auth.validate_token", new_callable=AsyncMock, return_value=_mock_user()):
            resp1 = await client.post(
                "/v1/lock",
                json={"project": "proj-1", "role": "architect"},
                headers={"Authorization": "Token valid"},
            )
            resp2 = await client.post(
                "/v1/lock",
                json={"project": "proj-1", "role": "architect"},
                headers={"Authorization": "Token valid"},
            )
            assert resp1.json()["session_id"] == resp2.json()["session_id"]

    @pytest.mark.asyncio
    async def test_locked_prompt_without_lock_returns_409(self, client):
        """Prompt for locked role without acquiring lock first returns 409."""
        with patch("bridge.auth.validate_token", new_callable=AsyncMock, return_value=_mock_user()):
            resp = await client.post(
                "/v1/prompt",
                json={"message": "hello", "role": "architect", "project": "proj-1"},
                headers={"Authorization": "Token valid"},
            )
            assert resp.status_code == 409


class TestVtfLockSync:
    """Tests for vtf_update_lock session_id sync."""

    @pytest.fixture(autouse=True)
    def mock_pod_creation(self):
        """Override the module-level autouse fixture — these tests don't need pod mocks."""
        yield

    @pytest.mark.asyncio
    async def test_vtf_update_lock_calls_patch(self):
        """vtf_update_lock sends PATCH with session_id."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch("httpx.AsyncClient.patch", new_callable=AsyncMock, return_value=mock_resp) as mock_patch:
            from bridge.vtf_locks import vtf_update_lock
            result = await vtf_update_lock(42, "real-sess-123")

            assert result is True
            mock_patch.assert_called_once()
            call_kwargs = mock_patch.call_args
            assert "session_id" in str(call_kwargs)
            assert "/v1/locks/42/" in str(call_kwargs)

    @pytest.mark.asyncio
    async def test_vtf_update_lock_returns_false_on_failure(self):
        """vtf_update_lock returns False on non-200."""
        mock_resp = MagicMock()
        mock_resp.status_code = 404

        with patch("httpx.AsyncClient.patch", new_callable=AsyncMock, return_value=mock_resp):
            from bridge.vtf_locks import vtf_update_lock
            result = await vtf_update_lock(999, "x")
            assert result is False

    @pytest.mark.asyncio
    async def test_vtf_acquire_lock_passes_user_id(self):
        """R8: vtf_acquire_lock includes user_id in POST body when provided."""
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {"id": 1, "session_id": "", "project_id": "proj-1", "role": "architect"}

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp) as mock_post:
            from bridge.vtf_locks import vtf_acquire_lock
            await vtf_acquire_lock("proj-1", "architect", user_id=42)

            mock_post.assert_called_once()
            call_kwargs = mock_post.call_args
            body = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
            assert body["user_id"] == 42

    @pytest.mark.asyncio
    async def test_vtf_acquire_lock_omits_user_id_when_none(self):
        """vtf_acquire_lock does not include user_id when not provided."""
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {"id": 1, "session_id": "", "project_id": "proj-1", "role": "architect"}

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp) as mock_post:
            from bridge.vtf_locks import vtf_acquire_lock
            await vtf_acquire_lock("proj-1", "architect")

            call_kwargs = mock_post.call_args
            body = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
            assert "user_id" not in body


class TestLockManagerVtfUserIdProxy:
    """R8: _acquire_vtf passes user_id to vtf_acquire_lock."""

    @pytest.fixture(autouse=True)
    def mock_pod_creation(self):
        """Override module-level autouse fixture."""
        yield

    @pytest.mark.asyncio
    async def test_acquire_vtf_passes_user_id(self):
        """LockManager._acquire_vtf forwards user['user_id'] to vtf_acquire_lock."""
        lm = LockManager(use_vtf=True)
        user = _mock_user(user_id=42, username="admin")

        mock_vtf_lock = {"id": 1, "session_id": "", "project_id": "proj-1", "role": "architect", "created_at": ""}

        with patch("bridge.vtf_locks.vtf_acquire_lock", new_callable=AsyncMock, return_value=mock_vtf_lock) as mock_acquire:
            lock = await lm._acquire_vtf(user, "proj-1", "architect", "proj-1:architect")
            mock_acquire.assert_called_once_with("proj-1", "architect", user_id=42)
            assert lock["user_id"] == 42
            assert lock["username"] == "admin"
