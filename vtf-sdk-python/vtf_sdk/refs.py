"""Entity reference types for the vtf SDK.

Every FK or string-ID reference in a v2 response is one of these shapes.
Never a bare ID.
"""
from typing import Annotated, Literal

from pydantic import Discriminator

from .base import VtfModel


# --- Simple refs ---

class ProjectRef(VtfModel):
    id: str
    name: str

    def __str__(self) -> str:
        return self.name


class WorkplanRef(VtfModel):
    id: str
    name: str

    def __str__(self) -> str:
        return self.name


class MilestoneRef(VtfModel):
    id: str
    name: str
    status: Literal["pending", "active", "completed"]

    def __str__(self) -> str:
        return self.name


class TaskRef(VtfModel):
    id: str
    title: str
    status: str

    def __str__(self) -> str:
        return self.title


# --- ActorRef (discriminated union) ---

class AgentActor(VtfModel):
    type: Literal["agent"]
    id: str
    name: str
    pod_name: str | None = None

    def __str__(self) -> str:
        return self.name


class UserActor(VtfModel):
    type: Literal["user"]
    id: str
    username: str

    def __str__(self) -> str:
        return self.username


ActorRef = Annotated[AgentActor | UserActor, Discriminator("type")]


# --- LinkRef (polymorphic) ---

class TaskLinkRef(VtfModel):
    type: Literal["task"]
    id: str
    title: str
    status: str

    def __str__(self) -> str:
        return self.title


class MilestoneLinkRef(VtfModel):
    type: Literal["milestone"]
    id: str
    name: str
    status: str

    def __str__(self) -> str:
        return self.name


class WorkplanLinkRef(VtfModel):
    type: Literal["workplan"]
    id: str
    name: str

    def __str__(self) -> str:
        return self.name


class ExternalLinkRef(VtfModel):
    type: Literal["commit", "jira", "doc", "file", "area", "mr"]
    id: str
    label: str

    def __str__(self) -> str:
        return self.label


InternalLinkRef = Annotated[
    TaskLinkRef | MilestoneLinkRef | WorkplanLinkRef,
    Discriminator("type"),
]

LinkRef = Annotated[
    TaskLinkRef | MilestoneLinkRef | WorkplanLinkRef | ExternalLinkRef,
    Discriminator("type"),
]
