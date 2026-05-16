"""Optional vfobs observability emission (WG5-min T1).

DEGRADABLE BY DESIGN (D-T1-impl-2, symmetric to vfobs read-side
D-T0-1): if `vfobs_sdk` is not installed OR emission is
disabled/unconfigured OR anything goes wrong, this degrades to a
no-op and the controller is **completely unaffected**. Emission is
never on the critical path. `vfobs_sdk` is an OPTIONAL dependency
(extra `observability`) — vafi installs and runs without it.
"""

import hashlib
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    from vfobs_sdk import (  # type: ignore
        ExecutionSummary,
        make_emitter,
        task_claimed,
        task_heartbeat,
        task_state_changed,
        task_workdir_changed,
        harness_turn_started,
        harness_turn_completed,
    )

    _SDK_AVAILABLE = True
except Exception:  # pragma: no cover - import-environment dependent
    _SDK_AVAILABLE = False


class _NoopEmitter:
    """Used whenever real emission is unavailable/disabled. Every
    method is a guaranteed no-op that never raises."""

    def emit(self, *a, **k) -> None:
        return None

    async def aclose(self) -> None:
        return None


def build_emitter(config):
    """Return a real Emitter only if the SDK is importable AND
    emission is explicitly enabled AND configured; otherwise a
    no-op. Never raises."""
    if not _SDK_AVAILABLE or not getattr(config, "vfobs_emit_enabled", False):
        return _NoopEmitter()
    try:
        return make_emitter(
            enabled=True,
            url=config.vfobs_emit_url or None,
            token=config.vfobs_emit_token or None,
        )
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("vfobs emitter init failed; emission disabled: %r", e)
        return _NoopEmitter()


def workdir_signature(workdir: Path) -> str | None:
    """Cheap workdir-change signature for the stall/progress signal
    (plan §D7). `git status --porcelain` hashed; max-mtime fallback
    for non-git trees. Returns None on ANY error (caller then skips
    the workdir emit — never breaks the heartbeat)."""
    try:
        if not workdir.exists():
            return None
        if (workdir / ".git").exists():
            out = subprocess.run(
                ["git", "-C", str(workdir), "status", "--porcelain"],
                capture_output=True, text=True, timeout=5, check=False,
            ).stdout
            return hashlib.sha256(out.encode()).hexdigest()[:16]
        # Non-git fallback: (relpath, size, mtime) so a same-mtime
        # content change of different length is still detected.
        stamp = sorted(
            (str(p.relative_to(workdir)), s.st_size, s.st_mtime)
            for p in workdir.rglob("*")
            if (s := p.stat())
        )[:5000]
        return hashlib.sha256(repr(stamp).encode()).hexdigest()[:16]
    except Exception:
        return None


# Re-export the safe constructors (or None sentinels) so the
# controller imports from one place.
if _SDK_AVAILABLE:
    EVENTS = dict(
        task_claimed=task_claimed,
        task_heartbeat=task_heartbeat,
        task_state_changed=task_state_changed,
        task_workdir_changed=task_workdir_changed,
        harness_turn_started=harness_turn_started,
        harness_turn_completed=harness_turn_completed,
        ExecutionSummary=ExecutionSummary,
    )
else:  # pragma: no cover
    EVENTS = {}


def make_execution_summary(num_turns: int, cost_usd: float):
    """SDK ExecutionSummary (or None if SDK absent). total_tokens
    is intentionally omitted — vafi ExecutionResult doesn't carry
    it (D8); the field is Optional on the vfobs side."""
    if not _SDK_AVAILABLE:
        return None
    try:
        return EVENTS["ExecutionSummary"](
            num_turns=num_turns, cost_usd=cost_usd
        )
    except Exception:  # pragma: no cover
        return None


def safe_emit(emitter, factory_name: str, **kwargs) -> None:
    """Construct + emit one event, swallowing EVERYTHING. A missing
    workgraph_id (vtaskforge task with no milestone) skips the emit
    with a single debug line. This wrapper guarantees no hook can
    perturb the controller."""
    try:
        if not _SDK_AVAILABLE or factory_name not in EVENTS:
            return
        if not kwargs.get("workgraph_id"):
            logger.debug(
                "vfobs: skipping %s — task has no workgraph_id "
                "(no vtaskforge milestone)", factory_name,
            )
            return
        emitter.emit(EVENTS[factory_name](**kwargs))
    except Exception as e:  # pragma: no cover - defensive
        logger.debug("vfobs: %s emit suppressed: %r", factory_name, e)
