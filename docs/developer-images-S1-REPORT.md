# Spike S1 Report: Harness Install Recipes

**Date:** 2026-04-17
**Status:** Complete
**Resolves:** KU-5 (Gemini install command), KU-11 (Pi auth), KU-12 (Gemini yolo flag), KU-13 (Gemini config path). Provides UU-1 mitigation evidence.

## Method

Fresh container from `node:20-bookworm-slim` (Debian 12 bookworm, Node 20.20.1, npm 10.8.2). Installed all three harnesses, then inspected versions, flags, auth env vars, and config directory behavior. Reproduced with and without coexistence.

## Bottom line

- All three install via `npm install -g <package>`, work in the same container together, no conflicts.
- Combined added size (on top of 18 MB empty `node_modules`): **350 MB** (+64 Claude, +176 Pi, +111 Gemini).
- Each writes config to a predictable dotdir in `$HOME` — bind-mount of `/home/agent/` is sufficient for persistence.
- Gemini is `@google/gemini-cli`, auth via `GEMINI_API_KEY`, headless flag `-y/--yolo` (or `--approval-mode yolo`).
- Pi's default provider is **google** (Gemini) but it reads any of 6 provider API-key env vars. The `pidev` z.ai setup works because Pi honors `ANTHROPIC_API_KEY` / `ANTHROPIC_OAUTH_TOKEN` when pointed at an Anthropic-compatible base URL.

## Per-harness install recipes

### Claude Code

| Property | Value |
|---|---|
| npm package | `@anthropic-ai/claude-code` |
| Binary | `/usr/local/bin/claude` |
| Version at spike | `2.1.112` |
| Install size added | 64 MB |
| Version flag | `claude --version` |
| Non-interactive prompt | `claude -p "<prompt>"` (with `--output-format json`) |
| JSON output flag | `--output-format json` (also `stream-json`) |
| Skip permission prompt | `--dangerously-skip-permissions` (or `--permission-mode bypassPermissions`) |
| Session resume | `--continue` / `--resume` |
| Config dir | `~/.claude/` (lazy — not created at `--version`) |
| MCP config | `~/.claude.json` (via `mcpServers` key) or `--mcp-config <file>` flag |
| Auth env | `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, plus existing vafi pattern `CLAUDE_CREDENTIALS` (env var containing `~/.claude/.credentials.json` contents; materialized by entrypoint) |
| Base URL override | `ANTHROPIC_BASE_URL` |

Dockerfile line:
```dockerfile
RUN npm install -g @anthropic-ai/claude-code
```

Pin a version:
```dockerfile
RUN npm install -g @anthropic-ai/claude-code@2.1.112
```

### Pi

| Property | Value |
|---|---|
| npm package | `@mariozechner/pi-coding-agent` |
| Binary | `/usr/local/bin/pi` |
| Version at spike | `0.67.6` |
| Install size added | 176 MB (largest — bundles multi-provider model support) |
| Version flag | `pi --version` |
| Non-interactive prompt | `pi -p "<prompt>"` (or `--print`) |
| JSON output flag | `--mode json` (modes: `text`, `json`, `rpc`) |
| Skip permission prompt | No explicit flag — Pi's tool model is different: `--tools <comma-list>` **opt-in** (default: `read,bash,edit,write`). Use `--no-tools` to disable, or a restricted list for read-only. No yolo-style gate to bypass. |
| Session resume | `--continue` / `--resume` / `--session <path>` / `--no-session` (ephemeral) |
| Config dir | `~/.pi/` (created on first `--version` invocation) |
| Session storage | `~/.pi/agent/sessions/` |
| MCP config | Not a file — use `pi install npm:pi-mcp-adapter` (first time) then `pi install <mcp-source>` to register MCP servers as pi extensions. Settings live in `~/.pi/agent/settings.json`. Per-project override: `.pi/settings.json` with `pi install -l <source>`. |
| Auth env (multi-provider) | `ANTHROPIC_API_KEY`, `ANTHROPIC_OAUTH_TOKEN`, `OPENAI_API_KEY`, `AZURE_OPENAI_API_KEY` (+ 3 more Azure vars), `GEMINI_API_KEY`, `GROQ_API_KEY` |
| Default provider | `google` (i.e. Gemini) |
| Base URL override | Provider-specific (`AZURE_OPENAI_BASE_URL`, `ANTHROPIC_BASE_URL` via OpenAI-SDK compat) |

Dockerfile lines:
```dockerfile
RUN npm install -g @mariozechner/pi-coding-agent
# Optional — for MCP support (replicates existing fleet pattern):
USER root
RUN pi install npm:pi-mcp-adapter
# Pi writes settings.json under /root/.pi when run as root; copy to agent user:
RUN mkdir -p /home/agent/.pi/agent && \
    cp /root/.pi/agent/settings.json /home/agent/.pi/agent/settings.json && \
    chown -R agent:agent /home/agent/.pi
USER agent
```

Note the owner-migration dance is the same pattern as `~/GitHub/vafi/images/pi/Dockerfile:27-30`.

### Gemini

| Property | Value |
|---|---|
| npm package | `@google/gemini-cli` |
| Binary | `/usr/local/bin/gemini` |
| Version at spike | `0.38.1` (latest; host has `0.31.0`) |
| Install size added | 111 MB |
| Version flag | `gemini --version` (or `-v`) |
| Non-interactive prompt | `gemini -p "<prompt>"` (or `--prompt`) |
| JSON output flag | `--output-format json` (also `stream-json`) |
| Skip permission prompt | `-y / --yolo` (shorthand) or `--approval-mode yolo` (explicit; alternatives: `default`, `auto_edit`, `plan` read-only) |
| Session resume | `--resume latest` or `--resume <index>` |
| Config dir | `~/.gemini/` (created on first `--version` invocation) |
| MCP config | Managed via `gemini mcp add/remove/list/enable/disable` subcommands; stored in `~/.gemini/`. Also `--allowed-mcp-server-names <array>` flag to restrict at invocation. |
| Auth env | `GEMINI_API_KEY` |
| ACP mode | `--experimental-acp` (agent communication protocol) |

Dockerfile line:
```dockerfile
RUN npm install -g @google/gemini-cli
```

Pin a version:
```dockerfile
RUN npm install -g @google/gemini-cli@0.38.1
```

## Coexistence verification (UU-1 mitigation)

All three installed into the **same** `node:20-bookworm-slim` container, in sequence, with no errors:

```
/usr/local/lib
├── @anthropic-ai/claude-code@2.1.112
├── @google/gemini-cli@0.38.1
├── @mariozechner/pi-coding-agent@0.67.6
├── corepack@0.34.6
└── npm@10.8.2
```

`which claude pi gemini` → all resolve. No overlapping binaries in `/usr/local/bin`. Node modules trees are namespaced by org, so no directory collisions.

## Size summary

| Stage | `node_modules` size |
|---|---|
| Fresh `node:20-bookworm-slim` | 18 MB |
| + Claude | 82 MB (+64) |
| + Pi | 258 MB (+176) |
| + Gemini | 368 MB (+111) |

**Implication for fat-image option (already rejected in design doc):** +350 MB if we reversed that decision. Reaffirms the layered approach — each leaf carries only its harness (~65-180 MB on top of the shared body).

## Comparative flag map (for dispatcher script `/opt/vf-harness/run.sh`)

| Intent | Claude | Pi | Gemini |
|---|---|---|---|
| Headless prompt | `-p` | `-p` (or `--print`) | `-p` (or `--prompt`) |
| JSON output | `--output-format json` | `--mode json` | `--output-format json` |
| Skip tool approval | `--dangerously-skip-permissions` | (use `--tools` instead — different model) | `-y` |
| Session resume | `--continue` / `--resume` | `--continue` / `--resume` | `--resume latest` |
| Ephemeral session | (no equivalent; use fresh cwd) | `--no-session` | (resume disabled by default) |
| MCP config injection | `--mcp-config <file>` | `pi install <mcp-src>` (runtime), or settings.json | `gemini mcp add` (runtime), or settings file |

Pi's absence of a "yolo" flag is the biggest asymmetry. In practice the `/opt/vf-harness/run.sh` dispatcher should restrict Pi's tools explicitly via `--tools` rather than try to bypass a prompt that doesn't exist.

## Auth injection pattern (recommended)

Each context launcher already injects env unconditionally; the fresh data tells us the leaf entrypoint should accept:

```
# Universal
ANTHROPIC_API_KEY        # Claude native, Pi via Anthropic provider
ANTHROPIC_OAUTH_TOKEN    # Pi alternative; also Claude in some configs
ANTHROPIC_BASE_URL       # z.ai support
CLAUDE_CREDENTIALS       # vafi pattern — claude entrypoint materializes ~/.claude/.credentials.json
OPENAI_API_KEY           # Pi via OpenAI
GEMINI_API_KEY           # Gemini native, Pi via google provider
GROQ_API_KEY             # Pi via Groq (rare)

# Per-context non-auth (current pattern)
STITCH_API_KEY           # vfdev
MW_BOT_USER / MW_BOT_PASS # ogcli / ogdr MediaWiki
GITLAB_TOKEN / GITLAB_HOST
MEMPALACE_AUTO_INIT
```

The leaf image's `/opt/vf-harness/init.sh` runs at container start, reads whichever env vars apply to its harness, and writes the harness-specific config files (`~/.claude/.credentials.json`, `~/.pi/agent/settings.json`, etc.) into the bind-mounted `/home/agent/`. Env vars for other harnesses are simply ignored.

## First-run behavior summary

| Harness | `~/.$harness` created on first `--version`? |
|---|---|
| Claude | No (lazy — created on first real use) |
| Pi | Yes — `~/.pi/` appears after `pi --version` |
| Gemini | Yes — `~/.gemini/` appears after `gemini --version` |

So an entrypoint that wants to seed Pi or Gemini settings should do `mkdir -p ~/.pi/agent` (or `~/.gemini`) explicitly rather than relying on the CLI to create it. Claude's config dir we already create as part of the existing `/opt/vf-harness/init.sh`.

## Rumsfeld matrix updates

- **KU-5 resolved.** Gemini: `npm install -g @google/gemini-cli`.
- **KU-11 resolved.** Pi uses standard provider env vars (`ANTHROPIC_API_KEY` etc.); `pidev`'s z.ai setup works because z.ai is Anthropic-compatible. Not a unique auth story.
- **KU-12 resolved.** Gemini yolo: `-y` or `--approval-mode yolo`.
- **KU-13 resolved.** Gemini config dir: `~/.gemini/`. MCP via subcommands written into that dir.
- **UU-1 mitigated** (coexistence). No conflicts among the three in a shared `node_modules`.
- **New UU logged** (below): Pi doesn't have a binary yolo flag — dispatcher must use `--tools` for headless.

## Items surfaced during this spike

| # | Item | Next step |
|---|------|-----------|
| S1-OUT-1 | Pi MCP integration is a runtime `pi install` step, not a config file. Replicating `~/GitHub/vafi/images/pi/Dockerfile:21-30` pattern in `Dockerfile.pi` is necessary. | Copy the pattern verbatim into new `Dockerfile.pi`. |
| S1-OUT-2 | Pi's default provider is google (Gemini), so a brand-new laptop with only `GEMINI_API_KEY` set will work with both `pi` and `gemini` — no extra config needed. Worth a note in the launcher README. | Doc-level note. |
| S1-OUT-3 | Claude Code `--bare` mode exists (skips auto-memory, keychain reads, hooks). Could be useful for the headless fleet, less relevant for interactive laptop dev. | Flag for k8s fleet team if they want it; not needed here. |
| S1-OUT-4 | Gemini version on host (0.31.0) is behind npm latest (0.38.1). Re-running `npm install -g @google/gemini-cli` in the leaf build gets the fresh version. | Accept — each leaf build pins to whatever is current at build time. |
| S1-OUT-5 | The `pidev` launcher hardcodes `@harbor.viloforge.com/vafi/vafi-agent-pi:*`, not `vafi-developer:*`. It's using a **fleet** image, not a dev image. Out of step with `ogcli` / `ogdr` / `vfdev`. | Decision for Phase 3 (launcher refactor): does `pidev` keep using the fleet image, or migrate to `vafi-developer:pi`? Likely migrate, for consistency. |

## Files produced

- Full log of the coexistence run: `/tmp/s1-coexist.log` (stored locally, not committed).
- This report.

## Ready for next phase

With S1 complete we can author `Dockerfile.claude`, `Dockerfile.pi`, `Dockerfile.gemini` with confidence. Suggested next steps per the matrix priority list:

1. **S2** — base inheritance sanity check (KU-3).
2. **S3** — extract + rebuild round-trip (de-risks Phase 2).
3. **S5** — launcher dispatcher prototype (30 min; validates UX against existing images).
4. Then Phase 2 Dockerfile authoring.
