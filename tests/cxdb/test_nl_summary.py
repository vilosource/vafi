"""TDD tests for NL summary generation via Haiku."""

import pytest

from cxdb.models import StructuredSummary, TestResult
from cxdb.nl_summary import HaikuNLGenerator


MOCK_STRUCTURED = StructuredSummary(
    duration_seconds=230,
    turn_count=47,
    model="claude-sonnet-4-6",
    tools_used=["Read", "Edit", "Bash"],
    files_modified=["src/auth.py", "tests/test_auth.py"],
    files_read=["pyproject.toml"],
    tests=TestResult(passed=12, failed=0, command="pytest"),
    commits=["a1b2c3d Add OAuth2 login"],
)


class FakeAnthropicClient:
    """Returns a canned JSON response."""

    def __init__(self, response_text: str):
        self.response_text = response_text
        self.last_messages = None

    async def post(self, url, **kwargs):
        self.last_messages = kwargs.get("json", {}).get("messages", [])

        class Resp:
            status_code = 200

            def json(inner_self):
                return {
                    "content": [{"type": "text", "text": self.response_text}],
                }

        return Resp()


class ErrorAnthropicClient:
    async def post(self, url, **kwargs):
        raise ConnectionError("API unreachable")


VALID_NL_JSON = """{
  "one_liner": "Implemented OAuth2 login with 12 passing tests",
  "what_happened": "Added OAuth2 login endpoint using python-jose for JWT validation. Created 12 tests covering happy path and edge cases.",
  "key_decisions": ["Chose python-jose over authlib for JWT validation"],
  "if_failed": null
}"""

FAILED_NL_JSON = """{
  "one_liner": "Failed: insufficient test coverage",
  "what_happened": "Implemented the endpoint but only added happy-path tests.",
  "key_decisions": ["Used python-jose"],
  "if_failed": "Judge rejected: missing edge case tests for token expiry and invalid grants."
}"""


class TestHaikuNLGenerator:
    @pytest.mark.asyncio
    async def test_generates_valid_summary(self):
        http = FakeAnthropicClient(VALID_NL_JSON)
        gen = HaikuNLGenerator(http_client=http, base_url="http://fake", api_key="key")

        result = await gen.generate(MOCK_STRUCTURED, [], "completed", None)

        assert result is not None
        assert result["one_liner"] == "Implemented OAuth2 login with 12 passing tests"
        assert result["what_happened"].startswith("Added OAuth2")
        assert len(result["key_decisions"]) == 1
        assert result["if_failed"] is None

    @pytest.mark.asyncio
    async def test_includes_failure_info(self):
        http = FakeAnthropicClient(FAILED_NL_JSON)
        gen = HaikuNLGenerator(http_client=http, base_url="http://fake", api_key="key")

        result = await gen.generate(MOCK_STRUCTURED, [], "failed", "missing tests")

        assert result is not None
        assert result["if_failed"] is not None
        assert "edge case" in result["if_failed"]

    @pytest.mark.asyncio
    async def test_prompt_includes_structured_data(self):
        http = FakeAnthropicClient(VALID_NL_JSON)
        gen = HaikuNLGenerator(http_client=http, base_url="http://fake", api_key="key")

        await gen.generate(MOCK_STRUCTURED, [], "completed", None)

        prompt = http.last_messages[0]["content"]
        assert "files_modified" in prompt
        assert "src/auth.py" in prompt
        assert "12" in prompt  # test count

    @pytest.mark.asyncio
    async def test_prompt_includes_judge_feedback(self):
        http = FakeAnthropicClient(FAILED_NL_JSON)
        gen = HaikuNLGenerator(http_client=http, base_url="http://fake", api_key="key")

        await gen.generate(MOCK_STRUCTURED, [], "failed", "Missing edge case tests")

        prompt = http.last_messages[0]["content"]
        assert "Missing edge case tests" in prompt

    @pytest.mark.asyncio
    async def test_returns_none_on_api_error(self):
        http = ErrorAnthropicClient()
        gen = HaikuNLGenerator(http_client=http, base_url="http://fake", api_key="key")

        result = await gen.generate(MOCK_STRUCTURED, [], "completed", None)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_invalid_json_response(self):
        http = FakeAnthropicClient("This is not JSON at all")
        gen = HaikuNLGenerator(http_client=http, base_url="http://fake", api_key="key")

        result = await gen.generate(MOCK_STRUCTURED, [], "completed", None)
        assert result is None

    @pytest.mark.asyncio
    async def test_handles_markdown_fenced_json(self):
        """Haiku sometimes wraps JSON in ```json ... ``` fences."""
        fenced = '```json\n{"one_liner": "Did it", "what_happened": "Built stuff", "key_decisions": [], "if_failed": null}\n```'
        http = FakeAnthropicClient(fenced)
        gen = HaikuNLGenerator(http_client=http, base_url="http://fake", api_key="key")
        result = await gen.generate(MOCK_STRUCTURED, [], "completed", None)
        assert result is not None
        assert result["one_liner"] == "Did it"

    @pytest.mark.asyncio
    async def test_one_liner_under_100_chars(self):
        http = FakeAnthropicClient(VALID_NL_JSON)
        gen = HaikuNLGenerator(http_client=http, base_url="http://fake", api_key="key")

        result = await gen.generate(MOCK_STRUCTURED, [], "completed", None)
        assert len(result["one_liner"]) <= 100
