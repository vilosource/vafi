"""TDD tests for cxdb async HTTP client."""

import pytest

from cxdb.client import CxdbClient


class FakeResponse:
    def __init__(self, json_data, status_code=200):
        self._json = json_data
        self.status_code = status_code

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")


class FakeHttpClient:
    """Fake httpx.AsyncClient for testing."""

    def __init__(self, responses=None):
        self.responses = responses or {}
        self.requests: list[tuple[str, dict]] = []

    async def get(self, url, **kwargs):
        self.requests.append((url, kwargs))
        for pattern, response in self.responses.items():
            if pattern in url:
                return FakeResponse(response)
        return FakeResponse({})

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


@pytest.fixture
def contexts_response():
    return {
        "contexts": [
            {"context_id": 59, "labels": ["cxtx", "task:abc123"], "created_at_unix_ms": 1000},
            {"context_id": 60, "labels": ["cxtx", "task:other"], "created_at_unix_ms": 2000},
        ]
    }


@pytest.fixture
def turns_response():
    return {
        "turns": [
            {
                "turn_id": 100,
                "depth": 0,
                "data": {
                    "item_type": "system",
                    "timestamp": "2026-01-01T00:00:00Z",
                    "system": {"kind": "info", "title": "session_start", "content": "{}"},
                },
            }
        ],
        "meta": {"head_depth": 1},
    }


class TestFindContextByTask:
    @pytest.mark.asyncio
    async def test_returns_matching_context_id(self, contexts_response):
        http = FakeHttpClient(responses={"/v1/contexts": contexts_response})
        client = CxdbClient("http://cxdb:9010", http_client=http)
        result = await client.find_context_by_task("abc123")
        assert result == 59

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        http = FakeHttpClient(responses={"/v1/contexts": {"contexts": []}})
        client = CxdbClient("http://cxdb:9010", http_client=http)
        result = await client.find_context_by_task("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_latest_when_multiple(self):
        http = FakeHttpClient(responses={"/v1/contexts": {"contexts": [
            {"context_id": 59, "labels": ["task:abc"], "created_at_unix_ms": 1000},
            {"context_id": 60, "labels": ["task:abc"], "created_at_unix_ms": 2000},
        ]}})
        client = CxdbClient("http://cxdb:9010", http_client=http)
        result = await client.find_context_by_task("abc")
        assert result == 60


class TestGetTurns:
    @pytest.mark.asyncio
    async def test_returns_turns_list(self, turns_response):
        http = FakeHttpClient(responses={"/turns": turns_response})
        client = CxdbClient("http://cxdb:9010", http_client=http)
        turns = await client.get_turns(59)
        assert len(turns) == 1
        assert turns[0]["turn_id"] == 100
