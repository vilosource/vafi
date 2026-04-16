#!/usr/bin/env python3
"""Hydrate project context from VTF API into the architect workdir.

Usage:
  python3 hydrate_context.py /sessions/{project}/
  python3 hydrate_context.py --repo-url-only

Reads env vars:
  VTF_API_URL       — VTF REST API base URL
  VF_VTF_TOKEN      — API auth token
  VTF_PROJECT_SLUG  — project NanoID

Writes:
  {workdir}/PROJECT_CONTEXT.md  — human-readable project summary (default mode)
  /tmp/repo_url                 — repo URL (both modes, if project has one)

With --repo-url-only, skips PROJECT_CONTEXT.md so caller can run
`git clone` into an empty target before filling in context.

All failures are non-fatal — exits 0 with minimal context on error.
Outputs to stderr only (stdout reserved for Pi RPC protocol).
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

TIMEOUT = 5.0  # seconds per request


def log(msg: str) -> None:
    print(f"[hydrate] {msg}", file=sys.stderr)


def fetch(client: httpx.Client, path: str) -> dict | list | None:
    """GET a VTF API endpoint. Returns parsed JSON or None on failure."""
    try:
        r = client.get(path, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log(f"Failed to fetch {path}: {e}")
        return None


def format_status_line(stats: dict) -> str:
    """Format task status counts into a readable line."""
    by_status = stats.get("by_status", {})
    parts = []
    for status, label in [
        ("draft", "Draft"),
        ("todo", "Todo"),
        ("doing", "Doing"),
        ("done", "Done"),
        ("blocked", "Blocked"),
        ("needs_attention", "Needs Attention"),
    ]:
        count = by_status.get(status, 0)
        if count > 0:
            parts.append(f"{label}: {count}")
    return " | ".join(parts) if parts else "No tasks yet"


def build_context_md(
    project: dict | None,
    stats: dict | None,
    workplans: list | None,
) -> str:
    """Build PROJECT_CONTEXT.md content from API responses."""
    lines = []

    # Header
    name = project.get("name", "Unknown") if project else "Unknown"
    lines.append(f"# {name}")
    lines.append("")

    desc = (project.get("description") or "").strip() if project else ""
    if desc:
        lines.append(desc)
        lines.append("")

    # Status
    if stats:
        total = stats.get("total_tasks", 0)
        pct = stats.get("completed_percentage", 0)
        lines.append("## Project Status")
        lines.append(f"- **Total tasks**: {total} ({pct:.0f}% complete)")
        lines.append(f"- {format_status_line(stats)}")
        lines.append("")

    # Workplans
    if workplans:
        active = [w for w in workplans if w.get("status") == "active"]
        if active:
            lines.append("## Active Workplans")
            for wp in active:
                wp_name = wp.get("name", "Untitled")
                wp_desc = (wp.get("description") or "").strip()
                lines.append(f"### {wp_name}")
                if wp_desc:
                    lines.append(wp_desc)
                lines.append("")

    # Repository
    if project:
        repo_url = project.get("repo_url") or ""
        branch = project.get("default_branch") or "main"
        if repo_url:
            lines.append("## Repository")
            lines.append(f"- **URL**: {repo_url}")
            lines.append(f"- **Branch**: {branch}")
            lines.append("")

    # Tags
    if project:
        tags = project.get("tags") or []
        if tags:
            lines.append("## Tags")
            lines.append(", ".join(str(t) for t in tags))
            lines.append("")

    # Footer
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines.append("---")
    lines.append(f"*Last refreshed: {ts}. Use vtf MCP tools for live data.*")
    lines.append("")

    return "\n".join(lines)


def main() -> None:
    repo_url_only = "--repo-url-only" in sys.argv[1:]
    positional = [a for a in sys.argv[1:] if not a.startswith("--")]

    if repo_url_only:
        workdir = None
    else:
        if not positional:
            log("Usage: hydrate_context.py <workdir> | --repo-url-only")
            sys.exit(0)
        workdir = Path(positional[0])

    api_url = os.environ.get("VTF_API_URL", "")
    token = os.environ.get("VF_VTF_TOKEN", "")
    project_slug = os.environ.get("VTF_PROJECT_SLUG", "")

    if not api_url or not token or not project_slug:
        log("Missing VTF_API_URL, VF_VTF_TOKEN, or VTF_PROJECT_SLUG — skipping hydration")
        sys.exit(0)

    # Ensure workdir exists (not needed for repo-url-only mode)
    if workdir is not None:
        workdir.mkdir(parents=True, exist_ok=True)

    base = api_url.rstrip("/")
    headers = {"Authorization": f"Token {token}", "Accept": "application/json"}

    with httpx.Client(base_url=base, headers=headers) as client:
        # Try direct lookup by ID first, fall back to search by name
        project = fetch(client, f"/v1/projects/{project_slug}/")
        if project is None:
            # project_slug might be a name, not an ID — search for it
            results = fetch(client, f"/v1/projects/?search={project_slug}")
            if isinstance(results, dict):
                items = results.get("results", [])
                # Find exact name match to avoid false positives
                for item in items:
                    if item.get("name") == project_slug:
                        project = item
                        project_slug = project.get("id", project_slug)
                        log(f"Resolved project name to ID: {project_slug}")
                        break
                # Fall back to first result if no exact match
                if project is None and items:
                    project = items[0]
                    project_slug = project.get("id", project_slug)
                    log(f"Resolved project (best match) to ID: {project_slug}")

        project_id = project.get("id", project_slug) if project else project_slug

        # Always write /tmp/repo_url if we have one — both modes need it.
        if project:
            repo_url = (project.get("repo_url") or "").strip()
            if repo_url:
                import re
                if re.match(r"^(https?://|git@|ssh://)[^\s;|&$`]+$", repo_url):
                    Path("/tmp/repo_url").write_text(repo_url, encoding="utf-8")
                    log(f"Project repo: {repo_url}")
                else:
                    log(f"Skipping invalid repo URL: {repo_url!r}")

        # In repo-url-only mode, stop here — caller will git clone before
        # running us again in full mode to write PROJECT_CONTEXT.md.
        if repo_url_only:
            return

        stats = fetch(client, f"/v1/projects/{project_id}/stats/")

        workplans_resp = fetch(client, f"/v1/projects/{project_id}/workplans/")
        workplans = None
        if isinstance(workplans_resp, dict):
            workplans = workplans_resp.get("results", [])
        elif isinstance(workplans_resp, list):
            workplans = workplans_resp

    # Write PROJECT_CONTEXT.md
    content = build_context_md(project, stats, workplans)
    context_path = workdir / "PROJECT_CONTEXT.md"
    context_path.write_text(content, encoding="utf-8")
    log(f"Wrote {context_path}")


if __name__ == "__main__":
    main()
