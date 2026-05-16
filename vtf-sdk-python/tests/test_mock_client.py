"""Step 8: Mock client tests."""


class TestMockClient:

    def test_mock_client_get_task(self):
        """DoD #1"""
        from vtf_sdk.testing import MockVtfClient
        from vtf_sdk.entities import Task
        mock = MockVtfClient()
        task = mock.tasks.get("t1")
        assert isinstance(task, Task)

    def test_mock_client_list_tasks(self):
        """DoD #2"""
        from vtf_sdk.testing import MockVtfClient
        from vtf_sdk.pagination import PagedResult
        mock = MockVtfClient()
        result = mock.tasks.list()
        assert isinstance(result, PagedResult)
        assert len(result.items) >= 1

    def test_mock_client_create_task(self):
        """DoD #3"""
        from vtf_sdk.testing import MockVtfClient
        mock = MockVtfClient()
        task = mock.tasks.create(title="New Task", project="p1")
        assert task.title == "New Task"
        assert task.id.startswith("tsk-")
