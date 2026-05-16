"""Step 5: VtfClient + managers (read operations) tests.

Uses respx to mock the v2 API.
"""
import pytest
import respx
import httpx

from tests.test_entities import V2_TASK, V2_PROJECT, V2_WORKPLAN, V2_MILESTONE, V2_AGENT


@pytest.fixture
def client():
    from vtf_sdk.client import VtfClient
    router = respx.mock(base_url="http://vtf-test:8000")
    router.start()
    vtf = VtfClient(url="http://vtf-test:8000", token="test-token")
    yield vtf, router
    vtf.close()
    router.stop()


class TestClientStructure:

    def test_client_has_managers(self, client):
        """DoD #1"""
        vtf, _ = client
        assert hasattr(vtf, "tasks")
        assert hasattr(vtf, "projects")
        assert hasattr(vtf, "workplans")
        assert hasattr(vtf, "milestones")
        assert hasattr(vtf, "agents")


class TestTaskManagerRead:

    def test_task_get(self, client):
        """DoD #2"""
        vtf, router = client
        from vtf_sdk.entities import Task
        router.get("/v2/tasks/tsk-abc/").respond(200, json=V2_TASK)
        task = vtf.tasks.get("tsk-abc")
        assert isinstance(task, Task)
        assert task.id == "tsk-abc-123"

    def test_task_get_expand(self, client):
        """DoD #3"""
        vtf, router = client
        expanded = {**V2_TASK, "links": [], "reviews": []}
        router.get("/v2/tasks/tsk-abc/").respond(200, json=expanded)
        task = vtf.tasks.get("tsk-abc", expand=["links", "reviews"])
        assert task.links == []
        assert task.reviews == []
        # Verify expand param was sent
        assert "expand=links%2Creviews" in str(router.calls[0].request.url)

    def test_task_list(self, client):
        """DoD #4"""
        vtf, router = client
        from vtf_sdk.pagination import PagedResult
        router.get("/v2/tasks/").respond(200, json={"results": [V2_TASK], "next": None, "previous": None})
        result = vtf.tasks.list()
        assert isinstance(result, PagedResult)
        assert len(result.items) == 1

    def test_task_list_filter(self, client):
        """DoD #5"""
        vtf, router = client
        router.get("/v2/tasks/").respond(200, json={"results": [], "next": None, "previous": None})
        vtf.tasks.list(status="doing")
        assert "status=doing" in str(router.calls[0].request.url)

    def test_task_list_all(self, client):
        """DoD #6"""
        vtf, router = client
        router.get("/v2/tasks/").respond(200, json={"results": [V2_TASK], "next": None})
        tasks = list(vtf.tasks.list_all())
        assert len(tasks) == 1

    def test_task_claimable(self, client):
        """DoD #7"""
        vtf, router = client
        router.get("/v2/tasks/claimable/").respond(200, json={"results": [V2_TASK], "next": None, "previous": None})
        result = vtf.tasks.claimable()
        assert len(result.items) == 1


class TestOtherManagersRead:

    def test_project_get(self, client):
        """DoD #8"""
        vtf, router = client
        from vtf_sdk.entities import Project
        from vtf_sdk.refs import UserActor
        router.get("/v2/projects/p1/").respond(200, json=V2_PROJECT)
        proj = vtf.projects.get("p1")
        assert isinstance(proj, Project)
        assert isinstance(proj.owner, UserActor)

    def test_project_list(self, client):
        """DoD #9"""
        vtf, router = client
        router.get("/v2/projects/").respond(200, json={"results": [V2_PROJECT], "next": None, "previous": None})
        result = vtf.projects.list()
        assert len(result.items) == 1

    def test_workplan_get(self, client):
        """DoD #10"""
        vtf, router = client
        from vtf_sdk.refs import ProjectRef
        router.get("/v2/workplans/wp1/").respond(200, json=V2_WORKPLAN)
        wp = vtf.workplans.get("wp1")
        assert isinstance(wp.project, ProjectRef)

    def test_milestone_get(self, client):
        """DoD #11"""
        vtf, router = client
        router.get("/v2/milestones/ms1/").respond(200, json=V2_MILESTONE)
        ms = vtf.milestones.get("ms1")
        assert ms.name == "Phase 1 Core"

    def test_agent_list(self, client):
        """DoD #12"""
        vtf, router = client
        router.get("/v2/agents/").respond(200, json={"results": [V2_AGENT], "next": None, "previous": None})
        result = vtf.agents.list()
        assert len(result.items) == 1
        assert result.items[0].name == "executor-1"
