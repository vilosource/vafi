"""Step 9: Integration tests against live vtf-dev API.

Run with: pytest tests/integration/ -v
Requires: kubectl port-forward deployment/vtf-api -n vtf-dev 8002:8000
"""
import pytest
from vtf_sdk.entities import Task, Project
from vtf_sdk.refs import ProjectRef, UserActor
from vtf_sdk.exceptions import NotFound, GuardViolation


class TestFullLifecycle:

    def test_full_task_lifecycle(self, vtf):
        """DoD #1: create → submit → claim → complete, all return typed entities."""
        # Get existing project + workplan
        projects = vtf.projects.list()
        assert len(projects.items) > 0
        proj = projects.items[0]
        workplans = vtf.workplans.list(project_id=proj.id)
        assert len(workplans.items) > 0
        wp = workplans.items[0]

        # Get an agent for claiming
        agents = vtf.agents.list()
        assert len(agents.items) > 0
        agent = agents.items[0]

        # Create
        task = vtf.tasks.create(title="SDK-Integration-Lifecycle", project=proj.id, workplan=wp.id)
        assert isinstance(task, Task)
        assert isinstance(task.project, ProjectRef)
        assert task.status == "draft"

        # Submit
        task = vtf.tasks.submit(task.id)
        assert task.status == "todo"

        # Claim
        task = vtf.tasks.claim(task.id, agent_id=agent.id)
        assert task.status == "doing"
        assert task.claimed_by is not None

        # Complete (may go to pending_completion_review or done)
        task = vtf.tasks.complete(task.id)
        assert task.status in ("done", "pending_completion_review")

        # Clean up
        vtf.tasks.delete(task.id)

    def test_list_projects_typed(self, vtf):
        """DoD #2"""
        result = vtf.projects.list()
        assert len(result.items) > 0
        for p in result.items:
            assert isinstance(p, Project)
            if p.owner:
                assert hasattr(p.owner, "type")

    def test_error_on_invalid_transition(self, vtf):
        """DoD #3: Completing a draft task raises GuardViolation or error."""
        projects = vtf.projects.list()
        task = vtf.tasks.create(title="SDK-Invalid-Trans", project=projects.items[0].id)
        try:
            with pytest.raises((GuardViolation, Exception)):
                vtf.tasks.complete(task.id)  # draft → done should fail
        finally:
            vtf.tasks.delete(task.id)

    def test_not_found(self, vtf):
        """DoD #5: Getting nonexistent task raises NotFound."""
        with pytest.raises(NotFound):
            vtf.tasks.get("nonexistent-task-id-99999")

    def test_pagination(self, vtf):
        """DoD #6: paginated list returns typed results."""
        result = vtf.tasks.list(page_size=2)
        assert isinstance(result.items, list)
        assert len(result.items) <= 2
        if result.items:
            assert isinstance(result.items[0], Task)
