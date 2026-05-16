"""Step 1: VtfModel base and ref type tests."""
import pytest
from pydantic import ValidationError as PydanticValidationError


class TestVtfModel:

    def test_vtf_model_frozen(self):
        """DoD #1: VtfModel instances are immutable."""
        from vtf_sdk.base import VtfModel

        class Sample(VtfModel):
            name: str

        obj = Sample(name="test")
        with pytest.raises(PydanticValidationError):
            obj.name = "changed"

    def test_vtf_model_extra_ignore(self):
        """DoD #2: Unknown fields are silently ignored."""
        from vtf_sdk.base import VtfModel

        class Sample(VtfModel):
            name: str

        obj = Sample.model_validate({"name": "test", "unknown_field": 42})
        assert obj.name == "test"
        assert not hasattr(obj, "unknown_field")


class TestProjectRef:

    def test_project_ref_parse(self):
        """DoD #3"""
        from vtf_sdk.refs import ProjectRef
        ref = ProjectRef.model_validate({"id": "abc", "name": "My Project"})
        assert ref.id == "abc"
        assert ref.name == "My Project"


class TestWorkplanRef:

    def test_workplan_ref_parse(self):
        """DoD #4"""
        from vtf_sdk.refs import WorkplanRef
        ref = WorkplanRef.model_validate({"id": "wp1", "name": "Sprint 1"})
        assert ref.id == "wp1"
        assert ref.name == "Sprint 1"


class TestMilestoneRef:

    def test_milestone_ref_parse(self):
        """DoD #5"""
        from vtf_sdk.refs import MilestoneRef
        ref = MilestoneRef.model_validate({"id": "ms1", "name": "Phase 1", "status": "active"})
        assert ref.status == "active"


class TestTaskRef:

    def test_task_ref_parse(self):
        """DoD #6"""
        from vtf_sdk.refs import TaskRef
        ref = TaskRef.model_validate({"id": "t1", "title": "Do thing", "status": "todo"})
        assert ref.title == "Do thing"
        assert ref.status == "todo"


class TestActorRef:

    def test_actor_ref_agent(self):
        """DoD #7"""
        from vtf_sdk.refs import ActorRef, AgentActor
        data = {"type": "agent", "id": "a1", "name": "executor-1", "pod_name": None}
        from pydantic import TypeAdapter
        actor = TypeAdapter(ActorRef).validate_python(data)
        assert isinstance(actor, AgentActor)
        assert actor.pod_name is None

    def test_actor_ref_user(self):
        """DoD #8"""
        from vtf_sdk.refs import ActorRef, UserActor
        data = {"type": "user", "id": "42", "username": "jdoe"}
        from pydantic import TypeAdapter
        actor = TypeAdapter(ActorRef).validate_python(data)
        assert isinstance(actor, UserActor)
        assert actor.username == "jdoe"

    def test_actor_ref_discriminated(self):
        """DoD #9: Discriminated union dispatches on type field."""
        from vtf_sdk.refs import ActorRef, AgentActor, UserActor
        from pydantic import TypeAdapter
        ta = TypeAdapter(ActorRef)
        agent = ta.validate_python({"type": "agent", "id": "a", "name": "n", "pod_name": None})
        user = ta.validate_python({"type": "user", "id": "1", "username": "u"})
        assert type(agent) is AgentActor
        assert type(user) is UserActor

    def test_actor_ref_str(self):
        """DoD #10: str() returns display name."""
        from vtf_sdk.refs import ActorRef
        from pydantic import TypeAdapter
        ta = TypeAdapter(ActorRef)
        agent = ta.validate_python({"type": "agent", "id": "a", "name": "exec-1", "pod_name": None})
        user = ta.validate_python({"type": "user", "id": "1", "username": "jdoe"})
        assert str(agent) == "exec-1"
        assert str(user) == "jdoe"


class TestLinkRef:

    def test_link_ref_internal_task(self):
        """DoD #11"""
        from vtf_sdk.refs import TaskLinkRef
        ref = TaskLinkRef.model_validate({"type": "task", "id": "t1", "title": "Fix bug", "status": "doing"})
        assert ref.title == "Fix bug"
        assert ref.status == "doing"

    def test_link_ref_external(self):
        """DoD #12"""
        from vtf_sdk.refs import ExternalLinkRef
        ref = ExternalLinkRef.model_validate({"type": "jira", "id": "PROJ-123", "label": "PROJ-123"})
        assert ref.type == "jira"
        assert str(ref) == "PROJ-123"
