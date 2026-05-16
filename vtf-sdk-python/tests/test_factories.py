"""Step 8: Factory tests."""
import os


class TestFactories:

    def test_build_task_factory(self):
        """DoD #4"""
        from vtf_sdk.testing import build_task
        from vtf_sdk.entities import Task
        task = build_task()
        assert isinstance(task, Task)
        assert task.title == "Test Task"

    def test_build_project_factory(self):
        """DoD #5"""
        from vtf_sdk.testing import build_project
        from vtf_sdk.entities import Project
        proj = build_project()
        assert isinstance(proj, Project)
        assert proj.name == "Test Project"

    def test_build_task_overrides(self):
        """DoD #6"""
        from vtf_sdk.testing import build_task
        task = build_task(status="doing", title="Custom Task")
        assert task.status == "doing"
        assert task.title == "Custom Task"

    def test_version_attribute(self):
        """DoD #7"""
        import vtf_sdk
        assert isinstance(vtf_sdk.__version__, str)
        assert vtf_sdk.__version__ == "0.1.0"

    def test_py_typed_exists(self):
        """DoD #8"""
        import vtf_sdk
        pkg_dir = os.path.dirname(vtf_sdk.__file__)
        assert os.path.exists(os.path.join(pkg_dir, "py.typed"))
