# FocalPoint — AI Cognitive Operating System

## What This Is
A deterministic cognitive engine for AI Agents. Memory + attention management + workflow orchestration. Solves cross-session memory loss by organizing work into a DAG of fractal nodes with automatic context assembly, role-based thinking, and decision review workflows.

## Architecture: Brain-Spine Model
- **Brain** = LLM (reads context bundles, issues Tool Calls)
- **Spine** = `SpineEngine` (deterministic engine, all logic here, zero LLM involvement)
- LLM never touches storage directly. All mutations go through constrained Tool Calls.

## Storage: CQRS (3-layer) + Transactional Outbox
```
SQLite (persistent disk DB) ← Source of Truth (facts + audit_outbox)
events.jsonl                ← Audit trail (async flush from audit_outbox)
narratives/*.md             ← Append-only narratives (post-commit, repair if fails)
knowledge/{node_id}/*.md    ← Knowledge documents (design docs, requirements, etc.)
```
- **Main commit = SQLite only**（nodes + edges + audit_outbox 在同一事务内，100% 原子）
- **events.jsonl = 异步 flush**（心跳或 post-commit 从 audit_outbox 导出）
- **MD = post-commit side effect**（repair semantics, never rollback SQLite）
- **禁止在 SQLite 事务内直接写文件系统**（跨 DB+FS 原子性物理不可能）
- 事务必须用 `with store.transaction():` 上下文管理器（禁止裸 begin/commit）
- Derived views (global_view_cache, risk_cache, fts_index) are rebuildable from facts

## Data Layers (FR-0)
| Layer | Tables/Files | Loss Impact |
|-------|-------------|-------------|
| Business Facts | nodes, edges | Data loss — catastrophic |
| Runtime Persistent | session_state (focus, alerts, sansei counts) | UX degradation only |
| Audit | events.jsonl, repair log | Recovery capability lost |
| Derived | fts_index, *_cache | Rebuildable, zero loss |

**Iron law**: Runtime layer must NEVER drive business fact derivation.

## Node Schema (FR-1)
```python
# Core fields
id: str           # prefix-hash (e.g. "task-7f2a")
title: str        # required
status: str       # inbox|active|waiting|done|dropped
node_type: str    # goal|project|milestone|task|unknown
parent_id: str?   # strong edge (tree)
is_root: bool     # XOR with parent_id
summary: str?     # L0 cognitive interface
why: str?         # decision context
next_step: str?   # execution guidance
owner: str?
deadline: str?    # ISO 8601
created_at: str   # system-managed
updated_at: str   # system-managed
status_changed_at: str  # system-managed
archived_at: str? # system-managed
is_persistent: bool  # archive exemption

# External source pointer (GitHub Issue / Notion Page etc.)
source: str = "internal"     # "github" | "notion" | "internal"
source_id: str?              # external object ID (e.g. "octocat/repo#42")
source_url: str?             # external link
source_synced_at: str?       # last sync time
source_deleted: bool = False # external source deleted

# Compression control
needs_compression: bool = False
compression_in_progress: bool = False
no_llm_compression: bool = False

# Tags
tags: list[str] = []
```
- Edges table: `source_id, target_id, edge_type` (parent|depends_on)
- **is_root XOR parent_id** — enforced at DB level

## Status Machine (FR-5.1)
```
inbox → active, waiting, dropped
active → waiting, done, dropped
waiting → active, done, dropped
done → active (needs reason)
dropped → inbox (needs reason)
```
Preconditions:
- inbox → active/waiting: needs summary + (parent_id OR is_root)
- → done: all children must be in terminal state (done/dropped)
- → dropped: warn if children active, generate alerts for them
- done→active / dropped→inbox: must pass reason_log

## Risk Marks (FR-5.2) — computed, never stored
- `blocked`: self not terminal AND any depends_on target status ≠ done
- `at-risk`: deadline < NOW()+48h AND not terminal
- `stale`: active/waiting AND status_changed_at < NOW()-7d

## Rollup (FR-5.3) — recursive bottom-up
Priority rules (first match wins):
1. No children → own status
2. Any child rollup = active → active
3. Any child rollup = waiting → waiting (**inbox children excluded**)
4. All terminal, any done → done
5. All dropped → dropped

**Archived children MUST be included** in rollup (denominator preservation).

## DAG Safety (Invariant #2)
**Unified DAG Check**: merge parent_id + depends_on into single directed graph.
Child depends_on ancestor = REJECT (cross-dimensional deadlock).
**实现**: 使用 SQLite `WITH RECURSIVE` CTE 在数据库层检测，不拉全量边到 Python。

## Tools — 23 MCP tools

### Write Tools (11) — require reason, produce audit+narrative
create_node, update_status, update_field, add_dependency, remove_dependency,
attach_node, detach_node, append_log (with category), unarchive, set_persistent, set_knowledge

### Read Tools (5)
get_node, search_nodes (filters + FTS5 full-text query), get_knowledge (with parent inheritance),
delete_knowledge, get_assembly_trace

### Cognitive Tools (4) — system-level, bypass execute_tool
bootstrap (cold start), heartbeat (risk scan), activate_workbench (role-filtered context prep),
get_context_bundle (4-layer assembly with role filtering)

### Review Tools (1)
sansei_review (Three-Province parallel review)

### Runtime Tools (2) — no audit trail
shift_focus (via FocusScheduler), expand_context

**Note**: Cognitive + Review tools are called directly on SpineEngine, not through execute_tool.
MCP layer routes them correctly. Python API users call engine methods directly (e.g. engine.heartbeat()).

## Knowledge Layer (v0.3)
```
knowledge/{node_id}/
├── overview.md        → what + why
├── requirements.md    → what to build
├── architecture.md    → how to build
└── {custom_name}.md   → extensible
```
- `set_knowledge(node_id, doc_type, content)` — write
- `get_knowledge(node_id, doc_type=None, inherit=True)` — read with parent chain inheritance
- `delete_knowledge(node_id, doc_type)` — delete + FTS re-index
- Child nodes inherit parent knowledge. Own docs override parent's for same doc_type.
- FTS5 auto-indexed on set/delete.

## Narrative Category (v0.3)
`append_log` supports `category` parameter:

| category | Meaning | Visible to roles |
|----------|---------|-----------------|
| `decision` | Decision records | strategy, all |
| `feedback` | User/market feedback | strategy, all |
| `risk` | Risks and lessons | review, all |
| `technical` | Technical details | execution, all |
| `progress` | Progress updates | review, execution, all |
| `general` | Default | all |

Header format: `## {timestamp} [{event_type}] [{category}]`
Old format (no category bracket) treated as `general` for backward compatibility.

## Role-Based Context (v0.3)
`get_context_bundle(role=)` and `activate_workbench(role=)` filter narrative by category:

| Role | Sees categories | Token budget | L0 |
|------|----------------|-------------|-----|
| strategy | decision, feedback | 8,000 | 2,000 |
| review | risk, progress | 8,000 | 1,000 |
| execution | technical, progress | 8,000 | 0 (skip) |
| all (default) | everything | 10,000 | auto |

## Workbench (v0.3)
```python
workbench = engine.activate_workbench(node_id, role="execution")
# Returns:
#   goal         — node title
#   knowledge    — inherited knowledge docs
#   context      — role-filtered Context Bundle text
#   subtasks     — dependency-sorted children (Kahn's topo sort)
#   suggested_next — first non-terminal subtask
#   role_prompt  — from fpms/prompts/{role}.md
#   token_budget — role-specific allocation
#   decisions    — (strategy only) decision log entries
#   risks        — (review only) risk log entries
```
Stateless. One call, no persistent object.

## Three-Province Protocol (v0.3)
```
Strategy (Maker)   → produce requirements
Review (Reviewer)  → check risks, historical lessons → approve/reject
Engineer (Executor) → evaluate feasibility → approve/reject

Both must approve. Either rejects → revise.
rejection_count persisted in session_state. > 3 → escalate_to_human=True.
```

`sansei_review(node_id, proposal, review_verdict, engineer_verdict)` — records result in narrative.

## Full-Text Search (v0.3)
- SQLite FTS5 virtual table: `fts_index(node_id, title, narrative_text, knowledge_text)`
- `search_nodes(query="...")` routes to `store.search_fts()`
- Auto-indexed on: `append_log` (narrative), `set_knowledge`/`delete_knowledge` (knowledge)
- CJK fallback: `_search_like_content` does LIKE search when FTS5 returns empty for non-ASCII
- FTS5 special characters stripped by `_build_fts_query`
- LIKE metacharacters escaped with `ESCAPE '\\'`

## Context Bundle (FR-10) — injection order
1. **L0** Global dashboard (~500-1k tokens) — skipped for execution role
2. **L_Alert** Top 3 heartbeat alerts (~500 tokens)
3. **L1** Focal neighborhood (~1-3k tokens) — children Top15, deps Top10, siblings Top10
4. **L2** Focus working context (~2-5k tokens) — narrative filtered by role categories

**Trim iron law**: When over budget, preserve focus causality (why/how) over relationship completeness.
Trim order: siblings → children → depended_by → depends_on → parent → L2 content (last resort)

## Heartbeat (FR-8)
- Reuses FR-5.2 risk engine (DRY)
- Anti-Amnesia: re-push high alerts after 24h if no substantive action
- append_log does NOT reset Anti-Amnesia timer
- Dedup state in session_state.last_alerts

## Archive (FR-6)
Conditions (ALL must be true): terminal status + 7d cooldown + no active dependents + no active descendants
**Hot zone consistency > archive efficiency** (intentional design)

## Cold Start (FR-13)
1. Open SQLite → 2. Generate L0 → 3. Heartbeat scan → 4. Focus arbitration → 5. Bundle assembly → 6. Push bootstrap context

## Key Behaviors
- **attach_node** on node with existing parent → atomic replace (detach old + attach new)
- **unarchive** always resets status_changed_at to NOW() (anti-GC-boomerang)
- **unarchive(new_status=)** → atomic unarchive + status transition
- **update_status(is_root=true)** → auto-clear parent_id
- **No delete_node** — use dropped → archive cycle
- **Active domain isolation**: attach/dependency targets must be non-archived
- **shift_focus** → calls FocusScheduler.shift_focus() which updates primary + secondary + stash
- **FTS auto-index** → append_log triggers index_narrative, set/delete_knowledge triggers index_knowledge
- **FTS non-fatal** → index failures logged via logging.warning, never block operations

## File Structure
```
fpms/
├── spine/
│   ├── __init__.py        # SpineEngine — public API entry point
│   ├── store.py           # CRUD, transactions, FTS search, audit outbox
│   ├── schema.py          # SQLite schema + FTS5 virtual table
│   ├── models.py          # Pydantic inputs + dataclasses (Node, Edge, ToolResult, etc.)
│   ├── tools.py           # 15 Tool handlers (write + runtime + read)
│   ├── command_executor.py # Serial executor + idempotency
│   ├── validator.py       # Status transitions, DAG safety, XOR
│   ├── narrative.py       # Append-only MD read/write + category filtering
│   ├── knowledge.py       # Knowledge doc CRUD + parent inheritance
│   ├── risk.py            # blocked/at-risk/stale detection
│   ├── rollup.py          # Recursive bottom-up status rollup
│   ├── dashboard.py       # L0 global tree view
│   ├── heartbeat.py       # Risk scan + Anti-Amnesia
│   ├── focus.py           # FocusScheduler (primary/secondary/stash/decay)
│   ├── bundle.py          # BundleAssembler (L0/L_Alert/L1/L2 + role filtering)
│   ├── archive.py         # Auto-archive scan
│   ├── recovery.py        # Cold start bootstrap
│   └── adapters/
│       ├── base.py        # BaseAdapter ABC + NodeSnapshot/SourceEvent
│       ├── registry.py    # Adapter registration/discovery
│       ├── github_adapter.py  # GitHub Issues sync + write-back
│       └── notion_adapter.py  # Notion Pages sync + write-back
├── prompts/
│   ├── strategy.md        # Strategy role prompt (Maker)
│   ├── review.md          # Review role prompt (Reviewer)
│   └── execution.md       # Execution role prompt (Engineer)
├── mcp_server.py          # FastMCP server — 23 tools, stdio transport
└── __init__.py
```

Runtime data (gitignored):
```
fpms/db/fpms.db            # SQLite persistent DB
fpms/narratives/*.md       # Append-only narratives
fpms/knowledge/{id}/*.md   # Knowledge documents
fpms/events.jsonl          # Audit log
fpms/assembly_traces.jsonl # Context assembly traces
```

## Code Style
- Python 3.11+, type hints everywhere
- SQLite via stdlib sqlite3 (no ORM)
- **Pydantic BaseModel** for all Tool Call input validation
- dataclass for internal data transfer
- Functions over classes where possible
- Explicit error types, never swallow exceptions
- **Actionable Errors**: all ValidationError must tell LLM what's wrong + which Tool to call next
- **事务用 Context Manager**: `with store.transaction():` — no bare begin/commit
- **单 writer 串行**: all writes through CommandExecutor serial queue
- **幂等**: each Tool Call carries command_id, duplicate calls return cached result
- **派生层防污染**: write path reads only facts (nodes/edges), never derived/cache tables
- **FTS non-fatal**: index updates wrapped in try/except with logging.warning
- All times in UTC internally, display with timezone offset
- Test with pytest (667 tests), aim for 1:1 test-to-code ratio

## Development
- Python: `/opt/homebrew/opt/python@3.11/bin/python3.11`
- Test: `/opt/homebrew/opt/python@3.11/bin/python3.11 -m pytest tests/ -v`
- Use superpowers skills for all non-trivial development
- Code directory: `/Users/ontanetwork/Documents/Onta Network/Founder OS/MemoryFPMS/V4/`

## Known Limitations
- `execute_tool` only routes 15 tools; cognitive tools (heartbeat, bootstrap, etc.) called directly on engine
- CJK full-text search requires LIKE fallback (unicode61 tokenizer limitation)
- Compression engine not implemented (deferred until narrative exceeds token budget)
- Three-Province review accepts external verdicts, does not invoke LLM internally
