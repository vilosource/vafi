"""4a-1: Workplan/Milestone manager gap tests."""
import pytest
import respx

from tests.test_entities import V2_WORKPLAN, V2_MILESTONE


@pytest.fixture
def client():
    from vtf_sdk.client import VtfClient
    router = respx.mock(base_url="http://vtf-test:8000")
    router.start()
    vtf = VtfClient(url="http://vtf-test:8000", token="test-token")
    yield vtf, router
    vtf.close()
    router.stop()


class TestWorkplanManagerGaps:

    def test_workplan_archive(self, client):
        """Archive a workplan."""
        vtf, router = client
        from vtf_sdk.entities import Workplan
        archived = {**V2_WORKPLAN, "status": "archived"}
        router.post("/v2/workplans/wp1/archive/").respond(200, json=archived)
        wp = vtf.workplans.archive("wp1")
        assert isinstance(wp, Workplan)
        assert wp.status == "archived"

    def test_workplan_complete(self, client):
        """Complete a workplan."""
        vtf, router = client
        completed = {**V2_WORKPLAN, "status": "completed"}
        router.post("/v2/workplans/wp1/complete/").respond(200, json=completed)
        wp = vtf.workplans.complete("wp1")
        assert wp.status == "completed"

    def test_workplan_stats(self, client):
        """Get workplan stats."""
        vtf, router = client
        stats = {"total_tasks": 10, "completed_percentage": 50.0, "by_status": {"done": 5, "todo": 5}}
        router.get("/v2/workplans/wp1/stats/").respond(200, json=stats)
        result = vtf.workplans.stats("wp1")
        assert result["total_tasks"] == 10
        assert result["completed_percentage"] == 50.0


class TestMilestoneManagerGaps:

    def test_milestone_create(self, client):
        """Create a milestone."""
        vtf, router = client
        from vtf_sdk.entities import Milestone
        router.post("/v2/milestones/").respond(201, json=V2_MILESTONE)
        ms = vtf.milestones.create(name="New MS", workplan="wp1")
        assert isinstance(ms, Milestone)

    def test_milestone_update(self, client):
        """Update a milestone."""
        vtf, router = client
        updated = {**V2_MILESTONE, "name": "Updated MS"}
        router.patch("/v2/milestones/ms1/").respond(200, json=updated)
        ms = vtf.milestones.update("ms1", name="Updated MS")
        assert ms.name == "Updated MS"

    def test_milestone_stats(self, client):
        """Get milestone stats."""
        vtf, router = client
        stats = {"total_tasks": 5, "completed_percentage": 80.0, "by_status": {"done": 4, "todo": 1}}
        router.get("/v2/milestones/ms1/stats/").respond(200, json=stats)
        result = vtf.milestones.stats("ms1")
        assert result["total_tasks"] == 5
