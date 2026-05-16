"""4a-2: Admin/agent/health/events/bulk manager gap tests."""
import pytest
import respx

from tests.test_entities import V2_TASK, V2_AGENT, V2_EVENT


@pytest.fixture
def client():
    from vtf_sdk.client import VtfClient
    router = respx.mock(base_url="http://vtf-test:8000")
    router.start()
    vtf = VtfClient(url="http://vtf-test:8000", token="test-token")
    yield vtf, router
    vtf.close()
    router.stop()


# --- Agent gaps ---

class TestAgentGaps:

    def test_agent_register(self, client):
        """Register a new agent (unauthenticated)."""
        vtf, router = client
        reg_response = {"id": "new-agent", "name": "my-agent", "tags": ["executor"],
                        "status": "online", "effective_status": "online",
                        "last_heartbeat": None, "pod_name": None,
                        "registered_at": "2026-04-04T00:00:00Z",
                        "created_at": "2026-04-04T00:00:00Z", "updated_at": "2026-04-04T00:00:00Z",
                        "current_task": None, "tasks_completed": 0, "tasks_failed": 0}
        router.post("/v2/agents/").respond(201, json=reg_response)
        agent, raw = vtf.agents.register(name="my-agent", tags=["executor"])
        assert agent.id == "new-agent"
        assert agent.name == "my-agent"

    def test_agent_update_status(self, client):
        """Update agent status."""
        vtf, router = client
        updated = {**V2_AGENT, "status": "offline"}
        router.patch("/v2/agents/agt-001/").respond(200, json=updated)
        agent = vtf.agents.update_status("agt-001", status="offline")
        assert agent.status == "offline"


# --- Health ---

class TestHealth:

    def test_health(self, client):
        """Client.health() returns health dict."""
        vtf, router = client
        router.get("/v2/health").respond(200, json={"status": "healthy", "checks": {"db": "ok"}})
        result = vtf.health()
        assert result["status"] == "healthy"


# --- Task extras ---

class TestTaskExtras:

    def test_task_events(self, client):
        """List task events."""
        vtf, router = client
        from vtf_sdk.entities import TaskEvent
        router.get("/v2/tasks/t1/events/").respond(200, json={
            "results": [V2_EVENT], "next": None, "previous": None
        })
        result = vtf.tasks.list_events("t1")
        assert len(result.items) == 1
        assert isinstance(result.items[0], TaskEvent)

    def test_task_reset(self, client):
        """Force-reset a task status."""
        vtf, router = client
        reset = {**V2_TASK, "status": "todo"}
        router.post("/v2/tasks/t1/reset/").respond(200, json=reset)
        task = vtf.tasks.reset("t1", status="todo", reason="test reset")
        assert task.status == "todo"


# --- User/Member/Lock/Channel/ServiceAccount managers ---

class TestUserManager:

    def test_user_list(self, client):
        """List users."""
        vtf, router = client
        users = [{"id": 1, "username": "admin", "is_staff": True, "is_active": True,
                  "user_type": "human", "date_joined": "2026-01-01T00:00:00Z", "last_login": None}]
        router.get("/v2/users/").respond(200, json={"results": users})
        result = vtf.users.list()
        assert len(result.items) == 1
        assert result.items[0]["username"] == "admin"

    def test_user_get(self, client):
        """Get user detail."""
        vtf, router = client
        user = {"id": 1, "username": "admin", "is_staff": True, "is_active": True,
                "user_type": "human", "date_joined": "2026-01-01T00:00:00Z",
                "last_login": None, "memberships": []}
        router.get("/v2/users/1/").respond(200, json=user)
        result = vtf.users.get(1)
        assert result["username"] == "admin"


class TestMemberManager:

    def test_member_list(self, client):
        """List project members."""
        vtf, router = client
        members = [{"id": 1, "user": {"type": "user", "id": "1", "username": "admin"},
                    "project": {"id": "p1", "name": "Proj"}, "role": "owner", "created_at": "2026-01-01T00:00:00Z"}]
        router.get("/v2/projects/p1/members/").respond(200, json={"results": members})
        result = vtf.members.list("p1")
        assert len(result.items) == 1

    def test_member_add(self, client):
        """Add a member."""
        vtf, router = client
        member = {"id": 2, "user": {"type": "user", "id": "2", "username": "newuser"},
                  "project": {"id": "p1", "name": "Proj"}, "role": "member", "created_at": "2026-01-01T00:00:00Z"}
        router.post("/v2/projects/p1/members/").respond(201, json=member)
        result = vtf.members.add("p1", username="newuser", role="member")
        assert result["role"] == "member"


class TestLockManager:

    def test_lock_list(self, client):
        """List locks."""
        vtf, router = client
        locks = [{"id": 1, "project": {"id": "p1", "name": "Proj"}, "role": "architect",
                  "user": {"type": "user", "id": "1", "username": "admin"},
                  "session_id": "", "created_at": "2026-04-04T00:00:00Z", "last_activity": None}]
        router.get("/v2/locks/").respond(200, json={"results": locks})
        result = vtf.locks.list()
        assert len(result.items) == 1

    def test_lock_release(self, client):
        """Release a lock."""
        vtf, router = client
        router.delete("/v2/locks/1/").respond(200)
        vtf.locks.release(1)


class TestBulkManager:

    def test_bulk_import(self, client):
        """Bulk import."""
        vtf, router = client
        ref_map = {"workplan": "wp-new", "task-t1": "tsk-new"}
        router.post("/v2/bulk/import").respond(200, json={"ref_map": ref_map})
        result = vtf.bulk.do_import(payload={"milestones": [], "project_id": "p1", "workplan_id": "wp1"})
        assert result["ref_map"]["workplan"] == "wp-new"
