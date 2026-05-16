"""Step 7: AsyncVtfClient tests."""
import pytest
import respx

from tests.test_entities import V2_TASK, V2_PROJECT


@pytest.fixture
def async_client():
    from vtf_sdk.async_client import AsyncVtfClient
    router = respx.mock(base_url="http://vtf-test:8000")
    router.start()
    vtf = AsyncVtfClient(url="http://vtf-test:8000", token="test-token")
    yield vtf, router
    router.stop()


class TestAsyncClient:

    @pytest.mark.asyncio
    async def test_async_task_get(self, async_client):
        """DoD #1"""
        vtf, router = async_client
        from vtf_sdk.entities import Task
        router.get("/v2/tasks/tsk-abc/").respond(200, json=V2_TASK)
        task = await vtf.tasks.get("tsk-abc")
        assert isinstance(task, Task)

    @pytest.mark.asyncio
    async def test_async_task_list(self, async_client):
        """DoD #2"""
        vtf, router = async_client
        router.get("/v2/tasks/").respond(200, json={"results": [V2_TASK], "next": None, "previous": None})
        result = await vtf.tasks.list()
        assert len(result.items) == 1

    @pytest.mark.asyncio
    async def test_async_task_create(self, async_client):
        """DoD #3"""
        vtf, router = async_client
        created = {**V2_TASK, "id": "async-t1"}
        router.post("/v2/tasks/").respond(201, json=created)
        task = await vtf.tasks.create(title="Async Task", project="p1")
        assert task.id == "async-t1"

    @pytest.mark.asyncio
    async def test_async_task_claim(self, async_client):
        """DoD #4"""
        vtf, router = async_client
        claimed = {**V2_TASK, "claimed_by": {"type": "agent", "id": "a1", "name": "exec", "pod_name": None}}
        router.post("/v2/tasks/tsk-abc/claim/").respond(200, json=claimed)
        task = await vtf.tasks.claim("tsk-abc", agent_id="a1")
        assert task.claimed_by is not None

    @pytest.mark.asyncio
    async def test_async_list_all(self, async_client):
        """DoD #5"""
        vtf, router = async_client
        router.get("/v2/tasks/").respond(200, json={"results": [V2_TASK], "next": None})
        tasks = [t async for t in vtf.tasks.list_all()]
        assert len(tasks) == 1

    @pytest.mark.asyncio
    async def test_async_error_mapping(self, async_client):
        """DoD #6"""
        vtf, router = async_client
        from vtf_sdk.exceptions import NotFound
        router.get("/v2/tasks/nope/").respond(404, json={
            "error": {"code": "NOT_FOUND", "message": "Not found", "details": None, "field_errors": None}
        })
        with pytest.raises(NotFound):
            await vtf.tasks.get("nope")
