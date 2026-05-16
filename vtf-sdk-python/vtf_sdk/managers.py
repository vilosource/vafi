"""Resource managers for the vtf SDK.

Each manager provides typed CRUD and action methods for a v2 API resource.
"""
from __future__ import annotations

from typing import Iterator

from .entities import (
    Agent,
    Link,
    Milestone,
    Note,
    Project,
    Review,
    Task,
    TaskEvent,
    Workplan,
)
from .pagination import PagedResult
from .transport import SyncTransport


class _BaseManager:
    """Base for all resource managers."""

    def __init__(self, transport: SyncTransport):
        self._transport = transport


class TaskManager(_BaseManager):
    """Manage tasks via the v2 API."""

    def get(self, id: str, expand: list[str] | None = None) -> Task:
        params = {}
        if expand:
            params["expand"] = ",".join(expand)
        data = self._transport.get(f"/v2/tasks/{id}/", params=params or None)
        return Task.model_validate(data)

    def list(self, *, status: str | None = None, project_id: str | None = None,
             workplan_id: str | None = None, milestone_id: str | None = None,
             page_size: int = 50) -> PagedResult[Task]:
        params: dict = {"page_size": page_size}
        if status:
            params["status"] = status
        if project_id:
            params["project"] = project_id
        if workplan_id:
            params["workplan"] = workplan_id
        if milestone_id:
            params["milestone"] = milestone_id
        data = self._transport.get("/v2/tasks/", params=params)
        return _parse_paged(data, Task)

    def list_all(self, **filters) -> Iterator[Task]:
        """Iterate through all pages."""
        params: dict = {k: v for k, v in filters.items() if v is not None}
        url = "/v2/tasks/"
        while url:
            data = self._transport.get(url, params=params if url == "/v2/tasks/" else None)
            for item in data.get("results", []):
                yield Task.model_validate(item)
            url = data.get("next")

    def claimable(self, *, tags: list[str] | None = None,
                  project_id: str | None = None) -> PagedResult[Task]:
        params: dict = {}
        if tags:
            params["tags"] = ",".join(tags)
        if project_id:
            params["project"] = project_id
        data = self._transport.get("/v2/tasks/claimable/", params=params or None)
        return _parse_paged(data, Task)

    # --- State transitions ---

    def submit(self, id: str) -> Task:
        data = self._transport.post(f"/v2/tasks/{id}/submit/")
        return Task.model_validate(data)

    def claim(self, id: str, *, agent_id: str) -> Task:
        data = self._transport.post(f"/v2/tasks/{id}/claim/", json={"agent_id": agent_id})
        return Task.model_validate(data)

    def unclaim(self, id: str) -> Task:
        data = self._transport.post(f"/v2/tasks/{id}/unclaim/")
        return Task.model_validate(data)

    def complete(self, id: str) -> Task:
        data = self._transport.post(f"/v2/tasks/{id}/complete/")
        return Task.model_validate(data)

    def fail(self, id: str) -> Task:
        data = self._transport.post(f"/v2/tasks/{id}/fail/")
        return Task.model_validate(data)

    def recover(self, id: str, *, target: str, reason: str = "") -> Task:
        data = self._transport.post(f"/v2/tasks/{id}/recover/", json={"target": target, "reason": reason})
        return Task.model_validate(data)

    def block(self, id: str, *, reason: str = "") -> Task:
        data = self._transport.post(f"/v2/tasks/{id}/block/", json={"reason": reason} if reason else None)
        return Task.model_validate(data)

    def unblock(self, id: str) -> Task:
        data = self._transport.post(f"/v2/tasks/{id}/unblock/")
        return Task.model_validate(data)

    def defer(self, id: str) -> Task:
        data = self._transport.post(f"/v2/tasks/{id}/defer/")
        return Task.model_validate(data)

    def cancel(self, id: str) -> Task:
        data = self._transport.post(f"/v2/tasks/{id}/cancel/")
        return Task.model_validate(data)

    def heartbeat(self, id: str) -> None:
        self._transport.post(f"/v2/tasks/{id}/heartbeat/")

    def assign(self, id: str, *, agent_id: str) -> Task:
        data = self._transport.post(f"/v2/tasks/{id}/assign/", json={"assigned_to": agent_id})
        return Task.model_validate(data)

    def unassign(self, id: str) -> Task:
        data = self._transport.post(f"/v2/tasks/{id}/unassign/")
        return Task.model_validate(data)

    # --- Write ---

    def create(self, *, title: str, project: str, **kwargs) -> Task:
        payload = {"title": title, "project": project, **kwargs}
        data = self._transport.post("/v2/tasks/", json=payload)
        return Task.model_validate(data)

    def update(self, id: str, **kwargs) -> Task:
        data = self._transport.patch(f"/v2/tasks/{id}/", json=kwargs)
        return Task.model_validate(data)

    def delete(self, id: str) -> None:
        self._transport.delete(f"/v2/tasks/{id}/")

    # --- Notes ---

    def list_notes(self, task_id: str) -> PagedResult[Note]:
        data = self._transport.get(f"/v2/tasks/{task_id}/notes/")
        return _parse_paged(data, Note)

    def add_note(self, task_id: str, *, text: str) -> Note:
        data = self._transport.post(f"/v2/tasks/{task_id}/notes/", json={"text": text})
        return Note.model_validate(data)

    # --- Reviews ---

    def list_reviews(self, task_id: str) -> PagedResult[Review]:
        data = self._transport.get(f"/v2/tasks/{task_id}/reviews/")
        return _parse_paged(data, Review)

    def submit_review(self, task_id: str, *, decision: str, reason: str,
                      reviewer_id: str = "", reviewer_type: str = "agent") -> Review:
        payload = {"decision": decision, "reason": reason, "reviewer_type": reviewer_type}
        data = self._transport.post(f"/v2/tasks/{task_id}/reviews/", json=payload)
        return Review.model_validate(data)

    # --- Events ---

    def list_events(self, task_id: str) -> PagedResult[TaskEvent]:
        data = self._transport.get(f"/v2/tasks/{task_id}/events/")
        return _parse_paged(data, TaskEvent)

    # --- Reset ---

    def reset(self, id: str, *, status: str, reason: str) -> Task:
        data = self._transport.post(f"/v2/tasks/{id}/reset/", json={"status": status, "reason": reason})
        return Task.model_validate(data)


class ProjectManager(_BaseManager):

    def get(self, id: str) -> Project:
        data = self._transport.get(f"/v2/projects/{id}/")
        return Project.model_validate(data)

    def list(self, *, page_size: int = 50) -> PagedResult[Project]:
        data = self._transport.get("/v2/projects/", params={"page_size": page_size})
        return _parse_paged(data, Project)

    def create(self, *, name: str, **kwargs) -> Project:
        payload = {"name": name, **kwargs}
        data = self._transport.post("/v2/projects/", json=payload)
        return Project.model_validate(data)

    def update(self, id: str, **kwargs) -> Project:
        data = self._transport.patch(f"/v2/projects/{id}/", json=kwargs)
        return Project.model_validate(data)

    def delete(self, id: str) -> None:
        self._transport.delete(f"/v2/projects/{id}/")


class WorkplanManager(_BaseManager):

    def get(self, id: str) -> Workplan:
        data = self._transport.get(f"/v2/workplans/{id}/")
        return Workplan.model_validate(data)

    def list(self, *, project_id: str | None = None, page_size: int = 50) -> PagedResult[Workplan]:
        params: dict = {"page_size": page_size}
        if project_id:
            params["project"] = project_id
        data = self._transport.get("/v2/workplans/", params=params)
        return _parse_paged(data, Workplan)

    def create(self, *, name: str, project: str, **kwargs) -> Workplan:
        payload = {"name": name, "project": project, **kwargs}
        data = self._transport.post("/v2/workplans/", json=payload)
        return Workplan.model_validate(data)

    def archive(self, id: str) -> Workplan:
        data = self._transport.post(f"/v2/workplans/{id}/archive/")
        return Workplan.model_validate(data)

    def complete(self, id: str) -> Workplan:
        data = self._transport.post(f"/v2/workplans/{id}/complete/")
        return Workplan.model_validate(data)

    def stats(self, id: str) -> dict:
        return self._transport.get(f"/v2/workplans/{id}/stats/")


class MilestoneManager(_BaseManager):

    def get(self, id: str) -> Milestone:
        data = self._transport.get(f"/v2/milestones/{id}/")
        return Milestone.model_validate(data)

    def list(self, *, workplan_id: str | None = None, page_size: int = 50) -> PagedResult[Milestone]:
        params: dict = {"page_size": page_size}
        if workplan_id:
            params["workplan"] = workplan_id
        data = self._transport.get("/v2/milestones/", params=params)
        return _parse_paged(data, Milestone)

    def create(self, *, name: str, workplan: str, **kwargs) -> Milestone:
        payload = {"name": name, "workplan": workplan, **kwargs}
        data = self._transport.post("/v2/milestones/", json=payload)
        return Milestone.model_validate(data)

    def update(self, id: str, **kwargs) -> Milestone:
        data = self._transport.patch(f"/v2/milestones/{id}/", json=kwargs)
        return Milestone.model_validate(data)

    def stats(self, id: str) -> dict:
        return self._transport.get(f"/v2/milestones/{id}/stats/")


class AgentManager(_BaseManager):

    def get(self, id: str) -> Agent:
        data = self._transport.get(f"/v2/agents/{id}/")
        return Agent.model_validate(data)

    def list(self, *, page_size: int = 50) -> PagedResult[Agent]:
        data = self._transport.get("/v2/agents/", params={"page_size": page_size})
        return _parse_paged(data, Agent)

    def register(self, *, name: str, tags: list[str] | None = None,
                 pod_name: str | None = None) -> tuple[Agent, dict]:
        """Register agent. Returns (Agent, raw_response_dict) — raw dict includes token."""
        payload: dict = {"name": name}
        if tags:
            payload["tags"] = tags
        if pod_name:
            payload["pod_name"] = pod_name
        data = self._transport.post("/v2/agents/", json=payload)
        return Agent.model_validate(data), data

    def update_status(self, id: str, *, status: str) -> Agent:
        data = self._transport.patch(f"/v2/agents/{id}/", json={"status": status})
        return Agent.model_validate(data)

    def update(self, id: str, **kwargs) -> Agent:
        data = self._transport.patch(f"/v2/agents/{id}/", json=kwargs)
        return Agent.model_validate(data)


class LinkManager(_BaseManager):

    def list(self, *, project_id: str | None = None, page_size: int = 50) -> PagedResult[Link]:
        params: dict = {"page_size": page_size}
        if project_id:
            params["project"] = project_id
        data = self._transport.get("/v2/links/", params=params)
        return _parse_paged(data, Link)

    def create(self, *, source_type: str, source_id: str,
               target_type: str, target_id: str, link_type: str,
               **kwargs) -> Link:
        payload = {
            "source_type": source_type, "source_id": source_id,
            "target_type": target_type, "target_id": target_id,
            "link_type": link_type, **kwargs,
        }
        data = self._transport.post("/v2/links/", json=payload)
        return Link.model_validate(data)


class UserManager(_BaseManager):
    """Admin user management (staff only)."""

    def list(self, *, user_type: str | None = None, search: str | None = None) -> PagedResult:
        params: dict = {}
        if user_type:
            params["user_type"] = user_type
        if search:
            params["search"] = search
        data = self._transport.get("/v2/users/", params=params or None)
        return _parse_paged_raw(data)

    def get(self, id: int) -> dict:
        return self._transport.get(f"/v2/users/{id}/")


class MemberManager(_BaseManager):
    """Project membership management."""

    def list(self, project_id: str) -> PagedResult:
        data = self._transport.get(f"/v2/projects/{project_id}/members/")
        return _parse_paged_raw(data)

    def add(self, project_id: str, *, username: str, role: str = "member") -> dict:
        return self._transport.post(
            f"/v2/projects/{project_id}/members/",
            json={"username": username, "role": role},
        )

    def set_role(self, project_id: str, membership_id: int, *, role: str) -> dict:
        return self._transport.patch(
            f"/v2/projects/{project_id}/members/{membership_id}/",
            json={"role": role},
        )

    def remove(self, project_id: str, membership_id: int) -> None:
        self._transport.delete(f"/v2/projects/{project_id}/members/{membership_id}/")


class LockManager(_BaseManager):
    """Lock management."""

    def list(self, *, project_id: str | None = None) -> PagedResult:
        params = {"project_id": project_id} if project_id else None
        data = self._transport.get("/v2/locks/", params=params)
        return _parse_paged_raw(data)

    def release(self, lock_id: int) -> None:
        self._transport.delete(f"/v2/locks/{lock_id}/")


class ChannelMappingManager(_BaseManager):
    """Channel-to-project mapping management."""

    def list(self, *, provider: str | None = None) -> PagedResult:
        params = {"provider": provider} if provider else None
        data = self._transport.get("/v2/channel-mappings/", params=params)
        return _parse_paged_raw(data)

    def create(self, *, provider: str, channel_id: str, project_id: str,
               channel_name: str = "") -> dict:
        return self._transport.post("/v2/channel-mappings/", json={
            "provider": provider, "channel_id": channel_id,
            "project_id": project_id, "channel_name": channel_name,
        })

    def delete(self, id: int) -> None:
        self._transport.delete(f"/v2/channel-mappings/{id}/")


class ServiceAccountManager(_BaseManager):
    """Service account creation."""

    def create(self, *, name: str) -> dict:
        return self._transport.post("/v2/service-accounts/", json={"name": name})


class BulkManager(_BaseManager):
    """Bulk import operations."""

    def do_import(self, *, payload: dict) -> dict:
        return self._transport.post("/v2/bulk/import", json=payload)


def _parse_paged_raw(data: dict) -> PagedResult:
    """Parse paginated response keeping items as raw dicts."""
    items = data.get("results", [])
    return PagedResult(
        items=items,
        has_more=data.get("next") is not None,
        next_cursor=data.get("next"),
        previous_cursor=data.get("previous"),
    )


def _parse_paged(data: dict, model_class) -> PagedResult:
    """Parse a paginated API response into PagedResult."""
    items = [model_class.model_validate(item) for item in data.get("results", [])]
    return PagedResult(
        items=items,
        has_more=data.get("next") is not None,
        next_cursor=data.get("next"),
        previous_cursor=data.get("previous"),
    )
