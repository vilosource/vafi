"""Tests for controller.context — task context file generation."""

import pytest
from pathlib import Path
from src.controller.context import build_context, write_context


class TestBuildContext:
    def test_basic_context_has_title_and_spec(self):
        task_data = {"id": "t1", "title": "Add feature", "spec": "do stuff", "test_command": {}}
        result = build_context(task_data, notes=[], reviews=[])
        assert "# Task: Add feature (t1)" in result
        assert "do stuff" in result

    def test_includes_test_commands(self):
        task_data = {"id": "t1", "title": "T", "spec": "", "test_command": {"unit": "pytest -v"}}
        result = build_context(task_data, notes=[], reviews=[])
        assert "pytest -v" in result

    def test_no_history_when_empty(self):
        task_data = {"id": "t1", "title": "T", "spec": "", "test_command": {}}
        result = build_context(task_data, notes=[], reviews=[])
        assert "## History" not in result

    def test_includes_review_in_history(self):
        task_data = {"id": "t1", "title": "T", "spec": "", "test_command": {}}
        reviews = [{"decision": "changes_requested", "reason": "Fix the bug", "reviewer_id": "judge-1", "created_at": "2026-03-28T10:00:00Z"}]
        result = build_context(task_data, notes=[], reviews=reviews)
        assert "## History" in result
        assert "changes_requested" in result
        assert "Fix the bug" in result

    def test_includes_notes_in_history(self):
        task_data = {"id": "t1", "title": "T", "spec": "", "test_command": {}}
        notes = [{"text": "Completed task", "actor_id": "executor-1", "created_at": "2026-03-28T09:00:00Z"}]
        result = build_context(task_data, notes=notes, reviews=[])
        assert "Completed task" in result

    def test_filters_vafi_metadata_notes(self):
        task_data = {"id": "t1", "title": "T", "spec": "", "test_command": {}}
        notes = [
            {"text": "vafi:session_id=abc123", "actor_id": "controller", "created_at": "2026-03-28T09:00:00Z"},
            {"text": "Real note", "actor_id": "executor", "created_at": "2026-03-28T09:01:00Z"},
        ]
        result = build_context(task_data, notes=notes, reviews=[])
        assert "vafi:session_id" not in result
        assert "Real note" in result

    def test_executor_rework_instruction_when_rejection_exists(self):
        task_data = {"id": "t1", "title": "T", "spec": "", "test_command": {}}
        reviews = [{"decision": "changes_requested", "reason": "Fix it", "reviewer_id": "j1", "created_at": "2026-03-28T10:00:00Z"}]
        result = build_context(task_data, notes=[], reviews=reviews, role="executor")
        assert "rework" in result.lower()
        assert "fix the issues" in result.lower() or "previous review" in result.lower()

    def test_executor_new_work_instruction_when_no_rejection(self):
        task_data = {"id": "t1", "title": "T", "spec": "", "test_command": {}}
        result = build_context(task_data, notes=[], reviews=[], role="executor")
        assert "Implement" in result

    def test_judge_instruction(self):
        task_data = {"id": "t1", "title": "T", "spec": "", "test_command": {}}
        result = build_context(task_data, notes=[], reviews=[], role="judge")
        assert "judge" in result.lower()
        assert "verify" in result.lower() or "verdict" in result.lower()

    def test_judge_re_review_instruction(self):
        task_data = {"id": "t1", "title": "T", "spec": "", "test_command": {}}
        reviews = [{"decision": "changes_requested", "reason": "Fix it", "reviewer_id": "j1", "created_at": "2026-03-28T10:00:00Z"}]
        result = build_context(task_data, notes=[], reviews=reviews, role="judge")
        assert "re-review" in result.lower() or "previous rejection" in result.lower()


class TestWriteContext:
    def test_creates_vafi_directory(self, tmp_path):
        workdir = tmp_path / "task-123"
        workdir.mkdir()
        write_context(workdir, "test content")
        assert (workdir / ".vafi" / "context.md").exists()

    def test_writes_content(self, tmp_path):
        workdir = tmp_path / "task-123"
        workdir.mkdir()
        write_context(workdir, "hello world")
        content = (workdir / ".vafi" / "context.md").read_text()
        assert content == "hello world"

    def test_overwrites_existing(self, tmp_path):
        workdir = tmp_path / "task-123"
        workdir.mkdir()
        write_context(workdir, "first")
        write_context(workdir, "second")
        content = (workdir / ".vafi" / "context.md").read_text()
        assert content == "second"
