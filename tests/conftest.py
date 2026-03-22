"""Shared test fixtures for vafi controller tests."""

import pytest

from controller.config import AgentConfig


@pytest.fixture
def agent_config():
    """Default agent config for tests."""
    return AgentConfig(
        agent_id="test-executor-1",
        agent_role="executor",
        agent_tags=["executor", "claude"],
        vtf_api_url="http://localhost:8002",
        poll_interval=5,
        task_timeout=60,
        max_rework=3,
        sessions_dir="/tmp/vafi-test-sessions",
    )
