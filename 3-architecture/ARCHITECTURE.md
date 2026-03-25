# FPMS Architecture Document

## Module Decomposition

spine.py is organized into these logical modules (can be single file or package):

```
spine/
├── __init__.py          # Public API: SpineEngine class
├── schema.py            # SQLite schema, migrations, table definitions
├── models.py            # Node, Edge, SessionState dataclasses
├── store.py             # Database layer (CRUD, transactions, events.jsonl)
├── narrative.py         # Markdown narrative read/write/repair
├── tools.py             # Tool Call handlers (the 14 tools)
├── validator.py         # All validation: DAG check, status transitions, XOR
├── risk.py              # Risk mark computation (blocked/at-risk/stale)
├── rollup.py            # Recursive rollup_status computation
├── heartbeat.py         # Heartbeat scan, alert generation, dedup
├── focus.py             # Focus scheduler, arbitration, decay
├── bundle.py            # Context bundle assembly (L0/L_Alert/L1/L2)
├── dashboard.py         # Global dashboard generation (FR-3 tree rendering)
├── archive.py           # Archive scanning, unarchive logic
├── recovery.py          # Cold start / bootstrap flow (FR-13)
└── compression.py       # Narrative compression (FR-12, async worker)
```

## Component Dependency Graph

```
                    ┌─────────────┐
                    │  SpineEngine │  (public API, orchestrator)
                    └──────┬──────┘
                           │
          ┌────────────────┼────────────────┐
          │                │                │
     ┌────┴────┐    ┌─────┴─────┐    ┌─────┴─────┐
     │  tools  │    │ recovery  │    │ heartbeat │
     └────┬────┘    └─────┬─────┘    └─────┬─────┘
          │               │                │
    ┌─────┼───────┐   ┌───┼────┐      ┌───┴────┐
    │     │       │   │   │    │      │        │
┌───┴──┐┌─┴──┐┌──┴─┐│┌──┴─┐┌─┴──┐┌──┴──┐┌───┴───┐
│store ││vali││narr│││dash ││bund││focus ││ risk  │
│      ││dato││ati │││board││le  ││      ││       │
└──┬───┘└─┬──┘└──┬─┘│└──┬─┘└─┬──┘└──┬───┘└───┬───┘
   │      │      │  │   │    │      │        │
   │   ┌──┴──────┴──┘   │    │      │    ┌───┘
   │   │                 │    │      │    │
┌──┴───┴─┐           ┌──┴────┴──────┴────┴──┐
│ SQLite │           │      rollup.py       │
│  + FS  │           │  (reads from store)  │
└────────┘           └──────────────────────┘
```

## Data Flow: Tool Call Write Path

```
Agent → Tool Call JSON
  │
  ▼
tools.py: parse + route to handler
  │
  ▼
validator.py: check preconditions
  ├─ Status transition legality (FR-5.1)
  ├─ DAG cycle detection (unified parent+depends_on graph)
  ├─ XOR constraint (is_root vs parent_id)
  ├─ Active domain isolation (no archived targets)
  ├─ Child state check (for done/dropped transitions)
  │
  ▼ (all checks pass)
store.py: BEGIN TRANSACTION
  ├─ Write to SQLite facts (nodes/edges)
  ├─ Write to events.jsonl (audit)
  └─ COMMIT  ← Main commit point
  │
  ▼ (post-commit)
narrative.py: append to narratives/{node_id}.md
  ├─ Success → done
  └─ Failure → write repair event, continue
  │
  ▼
rollup.py: recompute affected subtree
risk.py: recompute affected nodes
dashboard.py: refresh global view
  │
  ▼
Return structured result to Agent
```

## Data Flow: Context Bundle Assembly

```
recovery.py / heartbeat trigger
  │
  ▼
focus.py: resolve current focus set
  ├─ User-driven (highest priority)
  ├─ Event-driven (from L_Alert)
  ├─ Time-driven (from heartbeat candidates)
  └─ Historical (from session_state)
  │
  ▼
bundle.py: assemble context
  │
  ├─ Phase 1: L0 (dashboard.py → tree render, ~500-1k tokens)
  ├─ Phase 2: L_Alert (heartbeat.py → top 3 alerts, ~500 tokens)
  ├─ Phase 3: L1 (graph traversal from focus)
  │   ├─ parent summary
  │   ├─ children Top15 (by risk priority)
  │   ├─ depends_on Top10
  │   ├─ depended_by Top10
  │   └─ siblings Top10
  ├─ Phase 4: L2 (focus node full context)
  │   ├─ All skeleton fields
  │   ├─ compressed_summary (if exists)
  │   └─ Recent narrative (3 days or 5 entries)
  └─ Phase 5: Cross-node time neighbors
  │
  ▼
Token budget check + trim (iron law: causality > relationships)
  │
  ▼
Serialized markdown string → inject into LLM prompt
```

## SQLite Schema (v1)

```sql
CREATE TABLE nodes (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'inbox'
        CHECK(status IN ('inbox','active','waiting','done','dropped')),
    node_type TEXT NOT NULL DEFAULT 'unknown'
        CHECK(node_type IN ('goal','project','milestone','task','unknown')),
    is_root INTEGER NOT NULL DEFAULT 0,
    summary TEXT,
    why TEXT,
    next_step TEXT,
    owner TEXT,
    deadline TEXT,  -- ISO 8601
    is_persistent INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,      -- ISO 8601 UTC
    updated_at TEXT NOT NULL,
    status_changed_at TEXT NOT NULL,
    archived_at TEXT,
    -- XOR constraint enforced in application layer
    parent_id TEXT REFERENCES nodes(id),
    CHECK(NOT (is_root = 1 AND parent_id IS NOT NULL))
);

CREATE TABLE edges (
    source_id TEXT NOT NULL REFERENCES nodes(id),
    target_id TEXT NOT NULL REFERENCES nodes(id),
    edge_type TEXT NOT NULL CHECK(edge_type IN ('parent','depends_on')),
    created_at TEXT NOT NULL,
    PRIMARY KEY (source_id, target_id, edge_type)
);

CREATE TABLE session_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,  -- JSON
    updated_at TEXT NOT NULL
);
-- Keys: 'focus_list', 'last_alerts'

-- Transactional Outbox (审计发件箱)
CREATE TABLE audit_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_json TEXT NOT NULL,   -- 完整事件 JSON
    created_at TEXT NOT NULL,
    flushed INTEGER NOT NULL DEFAULT 0  -- 0=待flush, 1=已写入events.jsonl
);

-- Derived tables (rebuildable)
CREATE TABLE narrative_index (
    node_id TEXT NOT NULL REFERENCES nodes(id),
    entry_offset INTEGER NOT NULL,  -- line number
    timestamp TEXT NOT NULL,
    event_type TEXT,
    mentions TEXT,  -- JSON array of referenced node_ids
    PRIMARY KEY (node_id, entry_offset)
);
```

## Concurrency Model (并发模型)

**v1 铁律：单 writer 串行。**

```
所有写操作 → CommandExecutor（串行队列）→ Store（单事务）
所有读操作 → 直接读 SQLite（WAL 模式，不阻塞写）
后台任务   → reader + async side effect，不直接写 facts
```

| 组件 | 角色 | 并发权限 |
|------|------|---------|
| tools.py (写入 Tool) | writer | 串行，通过 CommandExecutor |
| tools.py (读 Tool) | reader | 可并行 |
| heartbeat.py | reader | 可并行（只读 facts，写 session_state 串行） |
| compression.py | reader + side effect | 只读 facts，写 compressed.md（文件锁） |
| narrative.py | side effect | post-commit 串行 append |
| repair worker | side effect | 独立串行 |

- SQLite busy_timeout = 5000ms
- WAL 模式：多 reader + 单 writer 不阻塞
- 吞吐不是瓶颈，一致性和可解释性才是

## Idempotency Protocol (幂等协议)

每个 Tool Call 携带 `command_id`（调用方生成，UUID）。

```sql
CREATE TABLE recent_commands (
    command_id TEXT PRIMARY KEY,
    tool_name TEXT NOT NULL,
    result_json TEXT NOT NULL,   -- 上次执行的 ToolResult
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL     -- 24h 后可清理
);
```

执行流程：
1. 收到 Tool Call + command_id
2. 查 recent_commands：已存在 → 直接返回上次结果（幂等）
3. 不存在 → 正常执行 → 在同一事务内写入 recent_commands + facts + audit_outbox
4. 返回结果

崩溃恢复：
- DB 已 commit，narrative 未写 → repair worker 补写
- DB 未 commit → 无副作用，调用方重试即可
- audit_outbox 未 flush → flush worker 重启后补齐

## Derived Layer Isolation (派生层防污染)

**硬规则（写入 Code Review checklist）：**

1. 所有派生表/缓存统一命名 `derived_*` 或 `*_cache`
2. **写路径（tools.py → store.py）禁止读取任何派生表**
3. 写路径只读 facts（nodes, edges, recent_commands, audit_outbox）
4. 派生层随时可 DROP + 重建，不影响业务
5. Review checklist 加一条：`write path reads facts only`

违反此规则 = Spec Review 直接 FAIL。

## Implementation Priority (v0 → v1 → v2)

### v0: 最小可运行脊髓
**目标**：证明写入、校验、恢复能稳定工作。

模块：
1. `schema.py` — SQLite init + 建表（含 audit_outbox + recent_commands）
2. `models.py` — Node/Edge/ToolResult dataclasses + Pydantic 输入模型
3. `store.py` — CRUD + Context Manager 事务 + audit outbox + flush worker + 幂等检查
4. `validator.py` — 状态迁移 + DAG CTE 防环 + XOR + 活跃域 + Actionable Errors
5. `tools.py` — 全部 14 Tool handlers（串行 CommandExecutor）
6. `narrative.py` — Append-only MD + repair

**必须先行**：
- `test_invariant_dag.py` — DAG 永不成环
- `test_invariant_xor.py` — root/parent XOR 永不破
- `test_invariant_atomic_commit.py` — DB + outbox 原子性
- `test_invariant_archive_hot_zone.py` — archive 不破坏热区
- `test_invariant_runtime_never_drives_facts.py` — 写路径不读派生

**验收标准**：5 个 invariant test 全绿 + 全部 Tool 可调用。

### v1: 认知层
**目标**：系统能思考——风险、冒泡、看板、心跳、焦点、认知包。

模块：
7. `risk.py` — blocked/at-risk/stale
8. `rollup.py` — 递归冒泡
9. `dashboard.py` — L0 树形渲染
10. `heartbeat.py` — 告警 + Anti-Amnesia + 去重
11. `focus.py` — 焦点仲裁 + LRU + 衰减
12. `bundle.py` — L0/L_Alert/L1/L2 组装 + 裁剪
13. `archive.py` — 归档扫描 + unarchive
14. `recovery.py` — 冷启动全流程

**验收标准**：冷启动 → 组装认知包 → 注入 prompt 可用。

### v2: 打磨优化
**目标**：长期可持续性。

模块：
15. `compression.py` — 叙事压缩
16. Token budget 优化
17. 缓存策略（derived_* 表）
18. OpenClaw 集成（Tool 注册 + DCP hook + heartbeat 调度）

**验收标准**：性能基准测试 + 端到端集成。

## Key Design Decisions

1. **Single SQLite file on disk** (not :memory:) — survives process restarts
2. **Transactional Outbox（发件箱模式）** — 审计事件不直接写 events.jsonl！
   - 在 SQLite 中新增 `audit_outbox` 表
   - Tool Call 在同一个 SQLite 事务内写入 nodes + edges + audit_outbox → COMMIT（100% 原子性）
   - 事后异步 flush audit_outbox → events.jsonl（心跳或 post-commit hook）
   - 崩溃后重启从 DB 导出，绝不丢审计
   - **禁止在 SQLite 事务内直接写文件系统**（跨 DB+FS 原子性是物理上不可能的）
3. **Context Manager 事务封装** — 废弃显式 begin/commit/rollback
   - 强制使用 `with store.transaction():` 上下文管理器
   - 异常自动 rollback，防止 `database is locked` 死锁
   - Coding agent 无法遗漏 rollback
4. **No ORM** — raw SQL for predictability and performance
5. **Pydantic for Tool Call inputs** — LLM 传入的 JSON 通过 Pydantic BaseModel 校验，自动类型强转 + 详细报错（如 `"deadline 必须是 ISO8601 格式"`），内部数据传递仍用 dataclass
5. **Rollup computed on-demand** from fact tables, never cached as truth
6. **Risk marks never stored** — pure functions of current state + clock
7. **Recursive CTE 防环** — DAG 环路检测下推到 SQLite 层
   - 使用 `WITH RECURSIVE` 递归 CTE，一条 SQL 查出环路
   - 比 Python 全量拉边跑 DFS 快几个数量级
   - 不再需要 `get_all_edges()` 拉全量到内存
8. **Token estimation** via simple word-count heuristic (1 token ≈ 0.75 words for English, adjust for Chinese). 未来可替换为 tiktoken 精确计数
9. **ID generation**: `{node_type_prefix}-{4char_hex}` (e.g., `task-a1b2`), collision retry
10. **Actionable Errors** — validator 拒绝操作时，错误消息必须告诉 LLM：
    - 哪条规则被违反
    - 当前状态是什么
    - 下一步应该调用什么 Tool 来修复
    - 例：`"校验失败：inbox→active 需要 summary。请先调用 update_field(node_id=xxx, field='summary', value='...') 补充。"`
