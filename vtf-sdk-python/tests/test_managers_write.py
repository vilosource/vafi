"""Step 6: Manager write + state transition tests."""
import pytest
import respx
import httpx

from tests.test_entities import V2_TASK, V2_PROJECT, V2_NOTE, V2_REVIEW


@pytest.fixture
def client():
    from vtf_sdk.client import VtfClient
    router = respx.mock(base_url="http://vtf-test:8000")
    router.start()
    vtf = VtfClient(url="http://vtf-test:8000", token="test-token")
    yield vtf, router
    vtf.close()
    router.stop()


class TestTaskWrite:

    def test_task_create(self, client):
        """DoD #1"""
        vtf, router = client
        from vtf_sdk.entities import Task
        created = {**V2_TASK, "id": "new-task-1", "status": "draft"}
        router.post("/v2/tasks/").respond(201, json=created)
        task = vtf.tasks.create(title="New Task", project="p1")
        assert isinstance(task, Task)
        assert task.id == "new-task-1"

    def test_task_update(self, client):
        """DoD #2"""
        vtf, router = client
        updated = {**V2_TASK, "title": "Updated Title"}
        router.patch("/v2/tasks/tsk-abc-123/").respond(200, json=updated)
        task = vtf.tasks.update("tsk-abc-123", title="Updated Title")
        assert task.title == "Updated Title"

    def test_task_delete(self, client):
        """DoD #3"""
        vtf, router = client
        router.delete("/v2/tasks/tsk-abc-123/").respond(204)
        result = vtf.tasks.delete("tsk-abc-123")
        assert result is None


class TestTaskTransitions:

    def test_task_submit(self, client):
        """DoD #4"""
        vtf, router = client
        submitted = {**V2_TASK, "status": "todo"}
        router.post("/v2/tasks/tsk-abc-123/submit/").respond(200, json=submitted)
        task = vtf.tasks.submit("tsk-abc-123")
        assert task.status == "todo"

    def test_task_claim(self, client):
        """DoD #5"""
        vtf, router = client
        claimed = {**V2_TASK, "status": "doing", "claimed_by": {"type": "agent", "id": "a1", "name": "exec", "pod_name": "p1"}}
        router.post("/v2/tasks/tsk-abc-123/claim/").respond(200, json=claimed)
        task = vtf.tasks.claim("tsk-abc-123", agent_id="a1")
        assert task.claimed_by is not None
        assert task.claimed_by.name == "exec"

    def test_task_complete(self, client):
        """DoD #6"""
        vtf, router = client
        done = {**V2_TASK, "status": "done"}
        router.post("/v2/tasks/tsk-abc-123/complete/").respond(200, json=done)
        task = vtf.tasks.complete("tsk-abc-123")
        assert task.status == "done"

    def test_task_fail(self, client):
        """DoD #7"""
        vtf, router = client
        failed = {**V2_TASK, "status": "needs_attention"}
        router.post("/v2/tasks/tsk-abc-123/fail/").respond(200, json=failed)
        task = vtf.tasks.fail("tsk-abc-123")
        assert task.status == "needs_attention"

    def test_task_block(self, client):
        """DoD #8"""
        vtf, router = client
        blocked = {**V2_TASK, "status": "blocked"}
        router.post("/v2/tasks/tsk-abc-123/block/").respond(200, json=blocked)
        task = vtf.tasks.block("tsk-abc-123")
        assert task.status == "blocked"

    def test_task_unblock(self, client):
        """DoD #9"""
        vtf, router = client
        unblocked = {**V2_TASK, "status": "todo"}
        router.post("/v2/tasks/tsk-abc-123/unblock/").respond(200, json=unblocked)
        task = vtf.tasks.unblock("tsk-abc-123")
        assert task.status == "todo"


class TestTaskNotes:

    def test_task_add_note(self, client):
        """DoD #10"""
        vtf, router = client
        from vtf_sdk.entities import Note
        router.post("/v2/tasks/tsk-abc-123/notes/").respond(201, json=V2_NOTE)
        note = vtf.tasks.add_note("tsk-abc-123", text="Test note")
        assert isinstance(note, Note)

    def test_task_list_notes(self, client):
        """DoD #11"""
        vtf, router = client
        router.get("/v2/tasks/tsk-abc-123/notes/").respond(200, json={"results": [V2_NOTE], "next": None, "previous": None})
        result = vtf.tasks.list_notes("tsk-abc-123")
        assert len(result.items) == 1


class TestTaskReviews:

    def test_task_submit_review(self, client):
        """DoD #12"""
        vtf, router = client
        from vtf_sdk.entities import Review
        router.post("/v2/tasks/tsk-abc-123/reviews/").respond(201, json=V2_REVIEW)
        review = vtf.tasks.submit_review("tsk-abc-123", decision="approved", reason="LGTM")
        assert isinstance(review, Review)


class TestProjectWrite:

    def test_project_create(self, client):
        """DoD #13"""
        vtf, router = client
        from vtf_sdk.entities import Project
        router.post("/v2/projects/").respond(201, json=V2_PROJECT)
        proj = vtf.projects.create(name="New Project")
        assert isinstance(proj, Project)


class TestErrorHandling:

    def test_claim_conflict_exception(self, client):
        """DoD #14"""
        vtf, router = client
        from vtf_sdk.exceptions import ClaimConflict
        router.post("/v2/tasks/tsk-abc-123/claim/").respond(409, json={
            "error": {"code": "ALREADY_CLAIMED", "message": "Claimed by another",
                      "details": {"held_by": "agent-2"}, "field_errors": None}
        })
        with pytest.raises(ClaimConflict) as exc_info:
            vtf.tasks.claim("tsk-abc-123", agent_id="a1")
        assert exc_info.value.held_by == "agent-2"
