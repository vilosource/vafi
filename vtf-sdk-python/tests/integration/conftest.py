"""Integration test fixtures — requires live vtf-dev on port 8002."""
import os
import pytest

VTF_URL = os.environ.get("VTF_URL", "https://vtf.dev.viloforge.com")
VTF_TOKEN = os.environ.get("VTF_TOKEN", "88dac5ac99f96f3e10c554e0169ec2ff00260652")


@pytest.fixture
def vtf():
    from vtf_sdk.client import VtfClient
    client = VtfClient(url=VTF_URL, token=VTF_TOKEN)
    yield client
    client.close()
