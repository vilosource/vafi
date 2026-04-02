"""E2E test configuration for bridge service.

These tests run against the deployed bridge in vafi-dev.
Set BRIDGE_URL env var to override the default URL.
"""

import os

import pytest
import httpx


BRIDGE_URL = os.environ.get("BRIDGE_URL", "https://bridge.dev.viloforge.com")


@pytest.fixture
def bridge_url():
    return BRIDGE_URL


@pytest.fixture
async def e2e_client():
    async with httpx.AsyncClient(base_url=BRIDGE_URL, verify=True, timeout=30) as c:
        yield c
