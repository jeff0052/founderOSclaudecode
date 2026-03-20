# FPMS — Focal Point Memory System

## What This Is
A deterministic project management engine for AI Agents. Solves cross-session memory loss by organizing work into a DAG of fractal nodes with automatic context assembly.

## Architecture: Brain-Spine Model
- **Brain** = LLM (reads context bundles, issues Tool Calls)
- **Spine** = `spine.py` (deterministic engine, all logic here, zero LLM involvement)
- LLM never touches storage directly. All mutations go through constrained Tool Calls.

## Storage: CQRS (3-layer) + Transactional Outbox
```
SQLite (persistent disk DB) ← Source of Truth (facts + audit_outbox)
events.jsonl                ← Audit trail (async flush from audit_outbox)
narratives/*.md             ← Append-only narratives (post-commit, repair if fails)
```
- **Main commit = SQLite only**（nodes + edges + audit_outbox 在同一事务内，100% 原子）
- **events.jsonl = 异步 flush**（心跳或 post-commit 从 audit_outbox 导出）
- **MD = post-commit side effect**（repair semantics, never rollback SQLite）
- **禁止在 SQLite 事务内直接写文件系统**（跨 DB+FS 原子性物理不可能）
- 事务必须用 `with store.transaction():` 上下文管理器（禁止裸 begin/commit）
- Derived views (global_view_cache, risk_cache, etc.) are rebuildable from facts

## Data Layers (FR-0)
| Layer | Tables/Files | Loss Impact |
|-------|-------------|-------------|
| Business Facts | nodes, edges | Data loss — catastrophic |
| Runtime Persistent | session_state (focus, alerts) | UX degradation only |
| Audit | events.jsonl, repair log | Recovery capability lost |
| Derived | *_cache, *_index | Rebuildable, zero loss |

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

## Tools (FR-11) — v1 minimum set
### Write Tools (require reason, produce audit+narrative)
create_node, update_status, update_field, add_dependency, remove_dependency,
attach_node, detach_node, append_log, unarchive, set_persistent

### Runtime Tools (no audit trail)
shift_focus, expand_context

### Read-only Tools
get_node, search_nodes (supports parent_id filter, pagination limit/offset)

## Key Behaviors
- **attach_node** on node with existing parent → atomic replace (detach old + attach new)
- **unarchive** always resets status_changed_at to NOW() (anti-GC-boomerang)
- **unarchive(new_status=)** → atomic unarchive + status transition
- **update_status(is_root=true)** → auto-clear parent_id
- **No delete_node** — use dropped → archive cycle
- **Active domain isolation**: attach/dependency targets must be non-archived

## Context Bundle (FR-10) — injection order
1. **L0** Global dashboard (~500-1k tokens)
2. **L_Alert** Top 3 heartbeat alerts (~500 tokens)
3. **L1** Focal neighborhood (~1-3k tokens) — children Top15, deps Top10, siblings Top10
4. **L2** Focus working context (~2-5k tokens)
5. Cross-node time-neighbor references

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

## File Structure
```
fpms/
├── spine.py              # Main engine
├── db/
│   └── fpms.db           # SQLite persistent DB
├── narratives/
│   ├── {node_id}.md      # Append-only narratives
│   └── {node_id}.compressed.md  # Compressed summaries
├── events.jsonl           # Audit log
└── docs/
    └── PRD-functional-v4.md  # Full PRD (1098 lines)
```

## Code Style
- Python 3.11+, type hints everywhere
- SQLite via stdlib sqlite3 (no ORM)
- **Pydantic BaseModel** for all Tool Call input validation (替代 dataclass 做输入层)
- dataclass 仅用于内部数据传递
- Functions over classes where possible
- Explicit error types, never swallow exceptions
- **Actionable Errors**: 所有 ValidationError 必须告诉 LLM 哪里错了 + 下一步调什么 Tool 修复
- **事务用 Context Manager**: `with store.transaction():` 不允许裸 begin/commit
- **单 writer 串行**: 所有写操作通过 CommandExecutor 串行队列，不允许并发写
- **幂等**: 每个 Tool Call 携带 command_id，重复调用返回上次结果
- **派生层防污染**: 写路径禁止读 derived_*/cache 表，只读 facts（nodes/edges）
- All times in UTC internally, display with timezone offset
- Test with pytest, aim for 1:1 test-to-code ratio
