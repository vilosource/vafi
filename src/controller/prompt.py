"""Prompt template loading and rendering for vafi harness invocation.

Provides functionality to load prompt templates from the filesystem and
render them with task-specific data using simple string substitution.
"""

import logging
from pathlib import Path
from typing import Dict, Any

from .types import TaskInfo

logger = logging.getLogger(__name__)


def load_template(path: Path | str) -> str:
    """Load a prompt template from the filesystem.

    Args:
        path: Path to the template file

    Returns:
        Template content as a string

    Raises:
        FileNotFoundError: If the template file doesn't exist
        IOError: If the template file cannot be read
    """
    template_path = Path(path)
    logger.debug(f"Loading template from {template_path}")

    try:
        content = template_path.read_text(encoding='utf-8')
        logger.debug(f"Loaded template with {len(content)} characters")
        return content
    except FileNotFoundError:
        logger.error(f"Template not found: {template_path}")
        raise
    except Exception as e:
        logger.error(f"Failed to load template {template_path}: {e}")
        raise IOError(f"Cannot read template {template_path}: {e}") from e


def render_prompt(template: str, task: TaskInfo) -> str:
    """Render a prompt template with task data using simple string substitution.

    Available template variables:
    - {id}: Task ID
    - {title}: Task title
    - {spec}: Task specification (YAML content)
    - {test_command}: Test command data as string

    Args:
        template: Template string with {variable} placeholders
        task: Task information to substitute into the template

    Returns:
        Rendered prompt string

    Raises:
        ValueError: If template substitution fails due to missing variables
    """
    try:
        # Convert test_command dict to string representation
        if task.test_command is None:
            test_command_str = "No test command"
        else:
            test_command_str = str(task.test_command)

        # Prepare substitution variables
        variables = {
            'id': task.id,
            'title': task.title,
            'spec': task.spec,
            'test_command': test_command_str,
        }

        logger.debug(f"Rendering template for task {task.id}")
        rendered = template.format(**variables)

        logger.debug(f"Rendered prompt with {len(rendered)} characters")
        return rendered

    except KeyError as e:
        missing_var = str(e).strip("'")
        logger.error(f"Template variable {missing_var} not available for task {task.id}")
        raise ValueError(f"Missing template variable: {missing_var}") from e
    except Exception as e:
        logger.error(f"Failed to render template for task {task.id}: {e}")
        raise ValueError(f"Template rendering failed: {e}") from e