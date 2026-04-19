"""Unit tests for build_prior_context.py.

Covers: no prior dir, empty dir, single session, multi-session ordering,
malformed JSONL handling, byte-cap truncation, methodology-only fallback.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "images" / "agent" / "build_prior_context.py"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "pi_jsonl"

# Load the script as a module for direct testing
sys.path.insert(0, str(SCRIPT_PATH.parent))
import build_prior_context as bpc  # type: ignore  # noqa: E402


@pytest.fixture
def methodology(tmp_path: Path) -> Path:
    m = tmp_path / "methodology.md"
    m.write_text(FIXTURES.joinpath("methodology.md").read_text())
    return m


@pytest.fixture
def empty_dir(tmp_path: Path) -> Path:
    d = tmp_path / "empty-sessions"
    d.mkdir()
    return d


@pytest.fixture
def populated_dir(tmp_path: Path) -> Path:
    d = tmp_path / "populated-sessions"
    d.mkdir()
    # copy fixtures in with distinct mtimes so ordering is deterministic
    for name in ("single-turn.jsonl", "multi-turn.jsonl"):
        src = FIXTURES / name
        dst = d / name
        shutil.copy(src, dst)
    # single-turn fixture is older than multi-turn
    old = time.time() - 3600
    recent = time.time() - 60
    os.utime(d / "single-turn.jsonl", (old, old))
    os.utime(d / "multi-turn.jsonl", (recent, recent))
    return d


# ─── parse_session_jsonl ──────────────────────────────────────────────────

def test_parse_single_turn():
    turns = bpc.parse_session_jsonl(FIXTURES / "single-turn.jsonl")
    assert len(turns) == 1
    ts, user, asst = turns[0]
    assert user == "What is the capital of Japan?"
    assert asst == "The capital of Japan is Tokyo."
    assert ts.startswith("2026-04-10T")


def test_parse_multi_turn_skips_tool_calls():
    turns = bpc.parse_session_jsonl(FIXTURES / "multi-turn.jsonl")
    # 3 user prompts → 3 turns. The 2 assistant messages (one with toolCall,
    # one follow-up text) for the first prompt collapse: first assistant
    # message pairs with the user; the follow-up assistant message has no
    # pending user → discarded. That's intentional behavior.
    assert len(turns) == 3
    users = [t[1] for t in turns]
    assert users == [
        "List the files in the current directory.",
        "What is in the README?",
        "Add a LICENSE file with the MIT license.",
    ]
    # First assistant reply contains text from the tool-calling message (NOT the toolCall dict)
    assert turns[0][2] == "I will use the bash tool to list files."
    assert turns[2][2] == "I have added a LICENSE file with the MIT license text."


def test_parse_malformed_jsonl_skips_bad_lines():
    turns = bpc.parse_session_jsonl(FIXTURES / "malformed.jsonl")
    # one valid user+assistant pair survives
    assert len(turns) == 1
    assert turns[0][1] == "A valid user prompt."
    assert turns[0][2] == "A valid assistant response."


def test_parse_empty_file():
    turns = bpc.parse_session_jsonl(FIXTURES / "empty.jsonl")
    assert turns == []


def test_parse_missing_file(tmp_path):
    turns = bpc.parse_session_jsonl(tmp_path / "does-not-exist.jsonl")
    assert turns == []


# ─── collect_prior_turns ──────────────────────────────────────────────────

def test_collect_nonexistent_dir(tmp_path):
    assert bpc.collect_prior_turns(tmp_path / "nope", max_sessions=5) == []


def test_collect_empty_dir(empty_dir):
    assert bpc.collect_prior_turns(empty_dir, max_sessions=5) == []


def test_collect_orders_by_timestamp(populated_dir):
    turns = bpc.collect_prior_turns(populated_dir, max_sessions=5)
    assert len(turns) == 4  # 1 from single-turn + 3 from multi-turn
    # chronological order across files: single-turn (2026-04-10) before multi-turn (2026-04-11)
    timestamps = [t[0] for t in turns]
    assert timestamps == sorted(timestamps)
    assert turns[0][1] == "What is the capital of Japan?"
    assert turns[-1][1] == "Add a LICENSE file with the MIT license."


def test_collect_respects_max_sessions(populated_dir):
    turns = bpc.collect_prior_turns(populated_dir, max_sessions=1)
    # only the most-recent file (multi-turn) is scanned
    assert len(turns) == 3
    users = [t[1] for t in turns]
    assert "What is the capital of Japan?" not in users


# ─── format_prior_section ─────────────────────────────────────────────────

def test_format_empty_turns():
    assert bpc.format_prior_section([]) == ""


def test_format_renders_markdown():
    out = bpc.format_prior_section([("2026-01-01T00:00:00Z", "Hi", "Hello!")])
    assert "# Continuation from previous sessions" in out
    assert "## User (2026-01-01T00:00:00Z)" in out
    assert "Hi" in out
    assert "## Assistant" in out
    assert "Hello!" in out


# ─── trim_to_byte_cap ─────────────────────────────────────────────────────

def test_trim_under_cap_is_noop():
    turns = [("t1", "a", "b")]
    assert bpc.trim_to_byte_cap(turns, max_bytes=10_000) == turns


def test_trim_drops_oldest_first():
    # build 10 trivial turns; shrink to ~400 bytes
    turns = [(f"t{i}", f"user-{i}", f"asst-{i}" * 20) for i in range(10)]
    trimmed = bpc.trim_to_byte_cap(turns, max_bytes=400)
    assert len(trimmed) < len(turns)
    # the most recent turn is retained
    assert trimmed[-1][1] == "user-9"


def test_trim_truncates_single_huge_turn():
    big_asst = "x" * 20_000
    turns = [("t", "short-user", big_asst)]
    trimmed = bpc.trim_to_byte_cap(turns, max_bytes=500)
    assert len(trimmed) == 1
    assert trimmed[0][1] == "short-user"  # user text preserved
    assert len(trimmed[0][2]) < len(big_asst)


# ─── build (the top-level integration within the script) ─────────────────

def test_build_no_prior_returns_methodology_only(empty_dir, methodology):
    out = bpc.build(session_dir=empty_dir, methodology=methodology)
    assert out == methodology.read_text()
    assert "Continuation from previous sessions" not in out


def test_build_with_prior_appends_section(populated_dir, methodology):
    out = bpc.build(session_dir=populated_dir, methodology=methodology)
    assert out.startswith(methodology.read_text().rstrip())
    assert "Continuation from previous sessions" in out
    assert "What is the capital of Japan?" in out
    assert "Add a LICENSE file with the MIT license." in out


def test_build_respects_max_prompts(populated_dir, methodology):
    # 4 turns available; ask for only 2 most recent
    out = bpc.build(session_dir=populated_dir, methodology=methodology, max_prompts=2)
    assert "Continuation from previous sessions" in out
    assert "What is the capital of Japan?" not in out  # oldest dropped
    assert "Add a LICENSE file with the MIT license." in out  # most recent kept


# ─── main (CLI entry) ─────────────────────────────────────────────────────

def test_main_writes_output_file(populated_dir, methodology, tmp_path):
    out_path = tmp_path / "initial-context.md"
    rc = bpc.main([
        "--session-dir", str(populated_dir),
        "--methodology", str(methodology),
        "--output", str(out_path),
    ])
    assert rc == 0
    assert out_path.is_file()
    content = out_path.read_text()
    assert "Test Methodology" in content
    assert "Continuation from previous sessions" in content


def test_main_no_prior_still_writes_methodology(empty_dir, methodology, tmp_path):
    out_path = tmp_path / "initial-context.md"
    rc = bpc.main([
        "--session-dir", str(empty_dir),
        "--methodology", str(methodology),
        "--output", str(out_path),
    ])
    assert rc == 0
    content = out_path.read_text()
    assert content == methodology.read_text()


def test_main_missing_methodology_errors(empty_dir, tmp_path):
    out_path = tmp_path / "initial-context.md"
    rc = bpc.main([
        "--session-dir", str(empty_dir),
        "--methodology", str(tmp_path / "missing.md"),
        "--output", str(out_path),
    ])
    assert rc == 1
    assert not out_path.exists()
