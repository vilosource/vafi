# vf-harness hook bundles

Hook bundles are how tools (mempalace, vtf, …) wire themselves into a harness's hook system (Claude's `settings.json`, Pi's extensions, …) at container startup. Each init-\<harness\>.sh has a generic loop that reads the bundles in this directory and applies them to its own harness.

Scope: Claude Code's `Stop`/`PreCompact`/… events, Pi's `session_shutdown`/`session_before_compact` events. Add a new bundle when you want a tool to react to those events across containers — without editing three init scripts each time.

## Directory layout

Two parallel trees are scanned at init time. Both use the same schema.

```
/opt/vf-harness/hooks.d/<bundle>/       # image-owned (COPY'd + fetched at build)
$HOME/.vf-hooks.d/<bundle>/              # user-owned, bind-mounted via $HOME
```

Inside a bundle:

```
<bundle>/
  bundle.json                 # optional metadata (name, version, priority, description)
  claude/
    hooks.json                # fragment merged into ~/.claude/settings.json
    *.sh                      # scripts referenced by hooks.json
  pi/
    extensions/*.ts           # copied to ~/.pi/agent/extensions/vf-<bundle>-*.ts
  codex/                      # reserved; not yet wired by any init script
  # omit a harness subdir when the bundle has nothing for it
```

## Claude fragment schema (`claude/hooks.json`)

Shape matches the `hooks` key of [Claude Code's settings.json](https://docs.anthropic.com/en/docs/claude-code/hooks). Fragments are merged per-event; all bundles' entries for the same event coexist.

```json
{
  "hooks": {
    "Stop": [
      {
        "matcher": "*",
        "hooks": [
          { "type": "command", "command": "{{DIR}}/on-stop.sh", "timeout": 30 }
        ]
      }
    ],
    "PreCompact": [
      {
        "hooks": [
          { "type": "command", "command": "{{DIR}}/on-precompact.sh", "timeout": 30 }
        ]
      }
    ]
  }
}
```

Supported Claude events: `PreToolUse`, `PostToolUse`, `UserPromptSubmit`, `Stop`, `SubagentStop`, `PreCompact`, `SessionStart`, `SessionEnd`. A bundle can target any subset.

## Pi extensions (`pi/extensions/*.ts`)

Pi hooks are TypeScript extension files. The generic loop copies every `.ts` under `pi/extensions/` into `~/.pi/agent/extensions/` with a `vf-<bundle>-` filename prefix (e.g. `vf-mempalace-mempalace-hooks.ts`). The prefix makes cleanup idempotent on re-init.

Events pi supports: `session_shutdown`, `session_before_compact`.

## Template variables

Substituted at init time in `hooks.json` fragments (NOT in script files — if you need them in scripts, pass via args or env). Only these five are supported:

| Variable | Substitutes to |
|---|---|
| `{{DIR}}` | Absolute path to this bundle's harness subdir (e.g. `/opt/vf-harness/hooks.d/mempalace/claude`) |
| `{{BUNDLE}}` | Bundle name (e.g. `mempalace`) |
| `{{STATE}}` | `$HOME/.vf-hook-state/<bundle>/` (created if missing) |
| `{{WORKSPACE}}` | `/workspace` |
| `{{HOME}}` | `/home/agent` |

## State and logs

Each bundle gets a state directory at `$HOME/.vf-hook-state/<bundle>/`. Create it in your hook script (idempotent `mkdir -p`) and write state files + logs there. Survives container restarts because `$HOME` is bind-mounted.

Recommended log path: `$HOME/.vf-hook-state/<bundle>/log`.

## Env contract for hook scripts

A Claude hook script inherits the agent user's environment, including everything the launcher forwarded (`ANTHROPIC_API_KEY`, `GITLAB_TOKEN`, `VF_VTF_TOKEN`, `VF_HARNESS=claude`, …) plus two bundle-specific vars injected by the init loop:

- `VF_BUNDLE_NAME` — this bundle's name
- `VF_BUNDLE_STATE_DIR` — same as `{{STATE}}`

The script receives Claude's hook protocol input as JSON on stdin (`transcript_path`, `session_id`, `hook_event_name`, `stop_hook_active`, …) and must emit either `{}` or a decision JSON on stdout. See Claude Code's hook docs for details.

## Bundle metadata (`bundle.json`)

Optional. All fields are optional; the file itself can be omitted.

```json
{
  "name": "mempalace",
  "version": "0.6.2",
  "description": "Auto-save session memories to mempalace on Stop and PreCompact.",
  "priority": 50
}
```

- **priority** — lower runs first when multiple bundles hook the same event. Default `50`. Ties break alphabetically.

## Disabling bundles

Set at container launch via `VF_DISABLE_HOOKS`:

- `VF_DISABLE_HOOKS=all` — skip the loop entirely, no hooks wired.
- `VF_DISABLE_HOOKS=mempalace,vtf` — skip those bundles.

The launcher forwards this var automatically; no image rebuild needed.

## Testing a bundle without rebuilding the image

The user-owned tree at `$HOME/.vf-hooks.d/` is bind-mounted. To iterate:

```bash
# On host, in the repo:
mkdir -p ~/DR/home/agent/.vf-hooks.d
cp -r images/developer/hooks.d/my-bundle ~/DR/home/agent/.vf-hooks.d/

# Launch any context — bundle fires next event:
ogdr bash   # or vfdev, ogcli, pidev
vf-hooks     # inside the container, lists detected bundles
```

When happy, move the bundle into `images/developer/hooks.d/` and rebuild.

## Diagnosing a non-firing hook

Inside the container:

```bash
vf-hooks                         # lists bundles + wiring
cat ~/.claude/settings.json      # verify hooks block is present
tail ~/.vf-hook-state/<bundle>/log    # your script's own log
```

If a bundle's `hooks.json` is malformed JSON, init logs `[vf-harness] WARN: bundle X skipped (invalid claude/hooks.json: …)` to stderr during container start, and no entries are merged for that bundle. Fix the JSON and restart.

## Creating a new bundle

Use the scaffolding script:

```bash
./scripts/new-hook-bundle.sh my-bundle --harnesses claude,pi
```

It creates the directory layout with working templates, ready for you to edit.
