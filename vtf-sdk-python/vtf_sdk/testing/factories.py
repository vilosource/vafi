"""Test factories for building SDK entities with sensible defaults."""
from datetime import datetime, timezone

from vtf_sdk.entities import (
    Task, Project, Workplan, Milestone, Agent, Review, Note, TaskPermissions,
    ProjectPermissions,
)
from vtf_sdk.refs import ProjectRef, WorkplanRef, UserActor

_counter = 0


def _next_id(prefix: str = "test") -> str:
    global _counter
    _counter += 1
    return f"{prefix}-{_counter:04d}"


def build_task(**overrides) -> Task:
    defaults = {
        "id": _next_id("tsk"),
        "title": "Test Task",
        "description": "A test task",
        "status": "draft",
        "project": ProjectRef(id=_next_id("prj"), name="Test Project"),
        "labels": [],
        "acceptance_criteria": [],
        "requires": [],
        "spec": "",
        "agent_model": "sonnet",
        "test_command": {},
        "judge": False,
        "isolation": "worktree",
        "retry_count": 0,
        "permissions": TaskPermissions(can_edit=True, can_delete=False, available_actions=["todo"]),
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    defaults.update(overrides)
    return Task.model_validate(defaults)


def build_project(**overrides) -> Project:
    defaults = {
        "id": _next_id("prj"),
        "name": "Test Project",
        "description": "A test project",
        "status": "active",
        "repo_url": "",
        "default_branch": "main",
        "tags": [],
        "owner": UserActor(type="user", id="1", username="testuser"),
        "created_by": UserActor(type="user", id="1", username="testuser"),
        "permissions": ProjectPermissions(can_edit=True, can_delete=True, can_archive=True, can_manage_members=True),
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    defaults.update(overrides)
    return Project.model_validate(defaults)
