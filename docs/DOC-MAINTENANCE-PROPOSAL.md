# Doc Maintenance Strategy — Proposal

**Date:** 2026-04-17
**Problem:** Phase-tracked docs are write-once. Work gets done, docs don't get updated. The only source of truth becomes git history + agent memory, which requires forensic effort to reconstruct.

---

## Current Pain Points

1. **Checklist rot** — Rework plan has `- [ ]` for everything, but all items are done
2. **No status column** — Design doc phase tables list "what" and "depends on" but not "done/not done"
3. **Cross-repo blindness** — Chat widget work spans vafi + vtaskforge, no single doc tracks both
4. **Superseded docs stay active** — Implementation plan superseded by rework plan, but both look current
5. **Undocumented work** — Console terminal bug exists only in MemPalace

---

## Proposal: Three-Layer Tracking

### Layer 1: Living Status Doc (human-readable, in repo)

One file per project area: `docs/STATUS.md`

Structure:
```markdown
# Status — [Area Name]
Last updated: 2026-04-17 (by: claude, session: xyz)

## Active Work
| Item | Status | Commit | Date |
|------|--------|--------|------|

## Backlog
| Item | Priority | Blocked by |
|------|----------|-----------|

## Completed (recent)
| Item | Commit | Date |
|------|--------|------|
```

**Rules:**
- Updated at end of every work session that changes status
- "Last updated" line always current — stale = visible
- Completed items roll off to an archive section after 30 days
- Agent updates this as part of deploy/verify workflow

### Layer 2: MemPalace Knowledge Graph (machine-readable, cross-session)

Use `mempalace_kg_add` to record phase transitions:

```
subject: "chat-widget-R8"
predicate: "completed"
object: "vafi:85a2bda + vtf:5f95591"
valid_from: "2026-04-16"
```

**Benefits:**
- Survives context loss between sessions
- Queryable: "what's the status of X?" → instant answer without git forensics
- Timeline view via `kg_timeline`
- Can detect conflicts: if a doc says "not started" but KG says "completed", flag it

**Rules:**
- Every phase completion → `kg_add` with commit hash
- Every bug fix → `kg_add` linking issue ID to fix commit
- Session diary captures work-in-progress for items not yet complete

### Layer 3: Doc Lifecycle Labels (in-doc metadata)

Add a frontmatter block to every design/plan doc:

```markdown
---
status: completed | active | superseded | deferred
superseded_by: agent-bridge-REWORK-PLAN.md  # if applicable
last_verified: 2026-04-17
---
```

**Rules:**
- `superseded` docs get a banner at top linking to the replacement
- `completed` docs are frozen — changes go to a new doc
- `deferred` docs state why and what would trigger resumption
- `last_verified` is updated whenever someone audits the doc

---

## Workflow: How It Works In Practice

### During a work session:
1. **Start:** Agent searches MemPalace for current status, reads `STATUS.md`
2. **Work:** Normal development flow
3. **Complete a phase:** 
   - Commit code
   - Update `STATUS.md` (move item from Active → Completed)
   - `kg_add` the completion event
   - Update the source design doc's checklist if it has one
4. **End of session:** Diary entry captures what changed

### On audit (periodic or on-demand):
1. Agent runs git log against STATUS.md claims
2. Flags any discrepancies (doc says TODO but code exists, or vice versa)
3. Updates STATUS.md and KG
4. Reports to user

### On doc creation:
1. New design docs get frontmatter with `status: active`
2. Phase tables include a Status column from day one
3. Old doc gets `status: superseded` and a banner

---

## Concrete Next Steps

1. **Update the 6 stale docs now** — Add FIXED/DONE markers, check off checklists, add superseded banners
2. **Create `docs/STATUS.md`** — Single status dashboard for all vafi work areas
3. **Backfill MemPalace KG** — Record all completed phases with commits and dates
4. **Add frontmatter** to existing docs with lifecycle labels
5. **Adopt the workflow** — Agent updates STATUS.md + KG as part of every completion

---

## What This Doesn't Solve

- **VTF self-tracking** — Platform work isn't tracked in VTF itself (eating own dog food). Separate decision.
- **Cross-repo STATUS** — vtaskforge has its own docs. Could add STATUS.md there too, or consolidate in one repo.
- **Automated enforcement** — No CI check that STATUS.md matches reality. Relies on agent discipline.

---

## Cost/Benefit

| Approach | Effort per session | Benefit |
|----------|-------------------|---------|
| Update STATUS.md | ~2 min | Anyone can see what's done/remaining in 10 seconds |
| KG entries | ~1 min | Agent instantly knows status without git forensics |
| Doc frontmatter | ~30 sec | Stale docs are visibly labeled, no more confusion |
| Do nothing | 0 | Next audit takes 30+ min of git archaeology (this session) |
