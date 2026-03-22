"""Unit tests for prompt template functionality."""

import pytest
from pathlib import Path
from tempfile import NamedTemporaryFile

from controller.prompt import load_template, render_prompt
from controller.types import TaskInfo


@pytest.fixture
def sample_task():
    """Sample task for template rendering."""
    return TaskInfo(
        id="task-456",
        title="Test Task Implementation",
        spec="description: Implement test feature\nsteps:\n  - write code\n  - write tests",
        project_id="project-789",
        test_command={"command": "pytest tests/", "timeout": 60},
        needs_review=True,
        assigned_to="agent-123"
    )


class TestLoadTemplate:
    """Test cases for load_template function."""

    def test_load_existing_template(self):
        """Test loading an existing template file."""
        content = "Test template with {id} and {title}"

        with NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            f.write(content)
            f.flush()

            template_path = Path(f.name)
            try:
                loaded = load_template(template_path)
                assert loaded == content
            finally:
                template_path.unlink()

    def test_load_nonexistent_template(self):
        """Test loading a non-existent template file."""
        nonexistent_path = Path("/nonexistent/template.txt")

        with pytest.raises(FileNotFoundError):
            load_template(nonexistent_path)

    def test_load_template_with_string_path(self):
        """Test loading template with string path."""
        content = "String path template"

        with NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            f.write(content)
            f.flush()

            template_path = f.name
            try:
                loaded = load_template(template_path)
                assert loaded == content
            finally:
                Path(template_path).unlink()


class TestRenderPrompt:
    """Test cases for render_prompt function."""

    def test_basic_template_rendering(self, sample_task):
        """Test basic template variable substitution."""
        template = "Task: {title} ({id})\n\nSpec:\n{spec}\n\nTest: {test_command}"

        rendered = render_prompt(template, sample_task)

        assert "Task: Test Task Implementation (task-456)" in rendered
        assert "Spec:\ndescription: Implement test feature" in rendered
        assert "Test: {'command': 'pytest tests/', 'timeout': 60}" in rendered

    def test_all_template_variables(self, sample_task):
        """Test that all supported variables are rendered."""
        template = "ID:{id}|Title:{title}|Spec:{spec}|TestCmd:{test_command}"

        rendered = render_prompt(template, sample_task)

        assert "ID:task-456" in rendered
        assert "Title:Test Task Implementation" in rendered
        assert "Spec:description: Implement test feature" in rendered
        assert "TestCmd:{'command': 'pytest tests/', 'timeout': 60}" in rendered

    def test_template_with_no_variables(self, sample_task):
        """Test template without any variables."""
        template = "This is a static template with no variables."

        rendered = render_prompt(template, sample_task)

        assert rendered == template

    def test_missing_template_variable(self, sample_task):
        """Test error handling for missing template variables."""
        template = "Task: {title} - Unknown: {unknown_variable}"

        with pytest.raises(ValueError, match="Missing template variable"):
            render_prompt(template, sample_task)

    def test_empty_test_command(self, sample_task):
        """Test handling of empty test_command."""
        sample_task.test_command = None
        template = "Test command: {test_command}"

        rendered = render_prompt(template, sample_task)

        assert "Test command: No test command" in rendered

    def test_empty_test_command_dict(self, sample_task):
        """Test handling of empty test_command dict."""
        sample_task.test_command = {}
        template = "Test command: {test_command}"

        rendered = render_prompt(template, sample_task)

        assert "Test command: {}" in rendered

    def test_multiline_spec_rendering(self, sample_task):
        """Test rendering of multiline specifications."""
        multiline_spec = """description: Multi-line task
objective: Test multiline handling
steps:
  - step 1
  - step 2
  - step 3"""

        sample_task.spec = multiline_spec
        template = "Specification:\n{spec}\n\nEnd of spec."

        rendered = render_prompt(template, sample_task)

        assert "description: Multi-line task" in rendered
        assert "- step 1" in rendered
        assert "- step 3" in rendered
        assert "End of spec." in rendered

    def test_template_with_special_characters(self, sample_task):
        """Test template rendering with special characters."""
        sample_task.spec = "Special chars: @#$%^&*()_+-={}[]|\\:;\"'<>?,./"
        template = "Content: {spec}"

        rendered = render_prompt(template, sample_task)

        assert "Special chars: @#$%^&*()_+-={}[]|\\:;\"'<>?,./" in rendered