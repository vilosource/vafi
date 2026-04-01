"""TDD tests for dispatch prompt injection (prior summaries + workplan context)."""

from cxdb.dispatch import build_dispatch_prompt


class TestBuildDispatchPrompt:
    def test_no_prior_summaries_no_context(self):
        prompt = build_dispatch_prompt(spec="Do the thing", prior_summaries=[], workplan_context="")
        assert "Do the thing" in prompt
        assert "Prior Attempt" not in prompt
        assert "Workplan Context" not in prompt

    def test_includes_single_prior_summary(self):
        prior = [{
            "attempt": 1,
            "structured": {
                "duration_seconds": 120,
                "tools_used": ["Read", "Edit"],
                "files_modified": ["auth.py"],
                "tests": {"passed": 5, "failed": 0, "command": "pytest"},
            },
            "nl_summary": {
                "one_liner": "Failed: insufficient tests",
                "what_happened": "Added auth endpoint with 5 tests.",
                "key_decisions": ["Used python-jose"],
                "if_failed": "Judge: missing edge case tests",
            },
        }]
        prompt = build_dispatch_prompt(spec="Fix the tests", prior_summaries=prior, workplan_context="")
        assert "Attempt 1" in prompt
        assert "Failed: insufficient tests" in prompt
        assert "missing edge case" in prompt

    def test_includes_multiple_prior_summaries(self):
        prior = [
            {"attempt": 1, "structured": {"duration_seconds": 60}, "nl_summary": {"one_liner": "Failed: A", "what_happened": "Did A", "key_decisions": [], "if_failed": "Problem A"}},
            {"attempt": 2, "structured": {"duration_seconds": 90}, "nl_summary": {"one_liner": "Failed: B", "what_happened": "Did B", "key_decisions": [], "if_failed": "Problem B"}},
        ]
        prompt = build_dispatch_prompt(spec="Try again", prior_summaries=prior, workplan_context="")
        assert "Attempt 1" in prompt
        assert "Attempt 2" in prompt
        assert "Failed: A" in prompt
        assert "Failed: B" in prompt

    def test_includes_workplan_context(self):
        context = "## Workplan Context\n- Task 3: Chose python-jose for JWT"
        prompt = build_dispatch_prompt(spec="Extend auth", prior_summaries=[], workplan_context=context)
        assert "python-jose" in prompt

    def test_includes_both_summaries_and_context(self):
        prior = [{"attempt": 1, "structured": {}, "nl_summary": {"one_liner": "Failed", "what_happened": "Tried", "key_decisions": [], "if_failed": "Bad"}}]
        context = "## Workplan Context\n- Prior: Used Django ORM"
        prompt = build_dispatch_prompt(spec="Build it", prior_summaries=prior, workplan_context=context)
        assert "Attempt 1" in prompt
        assert "Django ORM" in prompt
        assert "Build it" in prompt

    def test_handles_prior_summary_without_nl(self):
        """Phase A summaries have nl_summary=None."""
        prior = [{"attempt": 1, "structured": {"duration_seconds": 60, "tools_used": ["Read"], "files_modified": ["a.py"]}, "nl_summary": None}]
        prompt = build_dispatch_prompt(spec="Do it", prior_summaries=prior, workplan_context="")
        assert "Attempt 1" in prompt
        assert "a.py" in prompt  # Falls back to structured data
