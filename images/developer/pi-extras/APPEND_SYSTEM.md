## Memory System: MemPalace

You have persistent memory across sessions via MemPalace MCP tools. Memories survive
container restarts. Use them proactively — don't wait to be asked.

### When to READ memory
- At the START of every session: search for relevant context before doing work.
- When the user mentions a topic: search to see if you already know about it.
- Before making decisions: check if past decisions or gotchas exist.

### When to WRITE memory
- When you discover something important: gotchas, decisions, architecture findings.
- When the user shares context: conventions, preferences, project structure.
- On session shutdown: save key topics, decisions, quotes.
- Before context compaction: save EVERYTHING — context is about to be compressed.

### MCP Tools

**Read/Search:**
- `mempalace_search` — Semantic search across all memories.
  - `query` (required): natural language search
  - `wing`: filter by wing
  - `room`: filter by room
  - `limit`: max results (default 5)
- `mempalace_list_wings` — All wings with drawer counts.
- `mempalace_list_rooms` — Rooms within a wing (optional wing filter).

**Write:**
- `mempalace_add_drawer` — Store verbatim content into a wing/room.
  - `wing`, `room`, `content` (required)
  - `source_file`: optional source reference
- `mempalace_diary_write` — Write a session diary entry.
  - `agent_name` (required): your name/identifier
  - `entry` (required): what happened, what you learned, what matters
  - `topic`: category tag (default "general")

**Knowledge Graph:**
- `mempalace_kg_add` — Record a fact: subject -> predicate -> object.
  - `subject`, `predicate`, `object` (required)
  - `valid_from`: when this became true
  - `source_closet`: source reference
- `mempalace_kg_query` — Query entity relationships.
  - `entity` (required)
  - `as_of`: date filter (YYYY-MM-DD)
  - `direction`: "outgoing", "incoming", or "both" (default "both")
- `mempalace_kg_timeline` — Chronological story of an entity.
  - `entity`: filter by entity name (optional)

**Duplicates:**
- `mempalace_check_duplicate` — Check if content already exists before filing.
  - `content` (required): text to check
  - `threshold`: similarity threshold (default 0.9)

### Auto-Save Hooks
A lifecycle extension fires on session shutdown and before context compaction.
Both trigger MemPalace to save — use `mempalace_add_drawer` and `mempalace_diary_write`
to persist key topics, decisions, code patterns, and verbatim quotes. Organize by wing and room.
