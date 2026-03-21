# 认知引擎 v0 — 详细任务分配表

*v0 目标：证明骨架引擎（写入、校验、恢复）能稳定工作。*
*任务拆解标准：每个子任务 context ≤ budget.execution（当前 100k tokens），见 SYSTEM-CONFIG.md。*

---

## 执行顺序

```
Phase 1: Scaffold（骨架生成）
  → 主 agent 一次性生成全部骨架
  ↓
Phase 2: Invariant Tests（铁律测试）
  → 1 个 Test Writer agent
  ↓
Phase 3: Build v0（分 3 批）
  第1批（无依赖，并行）: Task 1 + Task 2
  第2批（依赖第1批）: Task 3 + Task 4
  第3批（依赖第2批）: Task 5 + Task 6
```

---

## Phase 1: Scaffold

**执行者**: 主 agent 直接生成，不 spawn
**产出**: 全部 v0 模块的骨架文件（可 import，不可运行）

```
fpms/spine/
├── __init__.py
├── schema.py          # 骨架
├── models.py          # 骨架
├── store.py           # 骨架
├── validator.py       # 骨架
├── tools.py           # 骨架
├── narrative.py       # 骨架
└── command_executor.py  # 骨架
```

---

## Phase 2: Invariant Tests

**执行者**: 1 个 Test Writer agent
**模型**: Opus（铁律测试质量最重要）

### Context 包

| 项目 | 来源 | 估算 tokens |
|------|------|------------|
| CLAUDE.md 全文 | 固定 | ~5k |
| PRD-functional §FR-0 "系统不变量（Invariants）" | PRD | ~5k |
| PRD-functional §附录 7 "关键不变量验收清单" | PRD | ~5k |
| INTERFACES.md §models.py + §store.py + §validator.py 签名 | 架构 | ~10k |
| **总计** | | **~25k** ✅ |

### 产出

```
tests/invariants/
├── test_invariant_dag.py              # DAG 永不成环
├── test_invariant_xor.py              # is_root XOR parent_id
├── test_invariant_atomic_commit.py    # DB + outbox 原子性
├── test_invariant_status_machine.py   # 状态迁移合法性
├── test_invariant_archive_hot_zone.py # 归档不破坏热区
├── test_invariant_derived_isolation.py # 写路径不读派生
├── test_invariant_idempotency.py      # command_id 幂等
└── conftest.py                        # 共享 fixtures
```

### Prompt

```
你是一个测试架构师。为 FounderOS 认知引擎编写不变量测试套件。

## 项目速查
{CLAUDE.md}

## 系统不变量（来自 PRD-functional §FR-0 "系统不变量（Invariants）"）
{对应章节内容}

## 验收清单（来自 PRD-functional §附录 7 "关键不变量验收清单"）
{对应章节内容}

## 可用接口
{INTERFACES.md: models + store + validator 签名}

## 约束
- 每个不变量一个独立测试文件
- 每个文件覆盖：正常路径 + 违反路径 + 边界路径
- 使用 pytest，fixtures 放 conftest.py
- 骨架文件已存在，可以 import
- 这些测试现在应该全部 FAIL（实现还不存在）
- 这些测试永远不允许被后续 coding agent 修改
```

---

## Phase 3 Build: 第 1 批（并行）

### Task 1: schema.py + models.py

**依赖**: 无
**并行**: 可与 Task 2 并行

#### Test Writer Agent

**模型**: Sonnet

**Context 包**:

| 项目 | 来源 | 估算 tokens |
|------|------|------------|
| CLAUDE.md 全文 | 固定 | ~5k |
| PRD-functional §FR-0 "事实源与派生物边界" | PRD | ~5k |
| PRD-functional §FR-1 "统一分形节点模型" | PRD | ~5k |
| INTERFACES.md §schema.py + §models.py + Pydantic 输入模型 | 架构 | ~8k |
| ARCHITECTURE.md §SQLite Schema | 架构 | ~5k |
| **总计** | | **~28k** ✅ |

**测试重点**:
- 建表成功，CHECK 约束生效
- Node dataclass 字段完整（含 `source` / `source_id` / `source_url` / `source_synced_at` / `source_deleted` / `needs_compression` / `compression_in_progress` / `no_llm_compression` / `tags`）
- Edge dataclass 字段完整
- Pydantic CreateNodeInput 校验（类型强转、非法 node_type 拒绝、ISO8601 deadline 格式、`source` / `source_id` / `source_url` 字段存在）
- Pydantic UpdateStatusInput / UpdateFieldInput 非法值拒绝
- XOR CHECK 约束（is_root=1 AND parent_id IS NOT NULL → 拒绝）
- audit_outbox 表存在
- recent_commands 表存在
- WAL 模式启用
- ToolResult 包含 `warnings` 和 `suggestion` 字段
- Alert / ContextBundle dataclass 结构正确

**产出**: `tests/test_schema.py` + `tests/test_models.py`

#### Implementer Agent

**模型**: Sonnet

**Context 包**: CLAUDE.md + 同上 PRD 章节 + INTERFACES.md 对应段 + Test Writer 产出的测试文件 + 骨架文件

**铁律**: 不改测试文件，不改接口签名

**产出**: `spine/schema.py` + `spine/models.py`

---

### Task 2: narrative.py

**依赖**: 无
**并行**: 可与 Task 1 并行

#### Test Writer Agent

**模型**: Sonnet

**Context 包**:

| 项目 | 来源 | 估算 tokens |
|------|------|------------|
| CLAUDE.md 全文 | 固定 | ~5k |
| PRD-functional §FR-2 "叙事体上下文" | PRD | ~5k |
| INTERFACES.md §narrative.py 签名 | 架构 | ~3k |
| **总计** | | **~13k** ✅ |

**测试重点**:
- append_narrative 追加格式 `## {timestamp} [{event_type}]\n{content}`
- append_narrative 不覆盖已有内容（append-only 验证）
- read_narrative 按条数截取（last_n_entries）
- read_narrative 按天数截取（since_days）
- read_compressed / write_compressed 正确读写
- write_repair_event 写入修复记录
- 文件不存在时自动创建目录和文件
- 并发 append 不丢数据（文件锁）

**产出**: `tests/test_narrative.py`

#### Implementer Agent

**模型**: Sonnet

**Context 包**: CLAUDE.md + PRD §FR-2 + INTERFACES.md narrative 段 + 测试文件 + 骨架

**产出**: `spine/narrative.py`

---

## Phase 3 Build: 第 2 批（依赖第 1 批）

### Task 3: store.py

**依赖**: schema.py + models.py（第 1 批产出）

#### Test Writer Agent

**模型**: Opus（store 是核心，测试质量要高）

**Context 包**:

| 项目 | 来源 | 估算 tokens |
|------|------|------------|
| CLAUDE.md 全文 | 固定 | ~5k |
| PRD-functional §FR-11 "受约束写入 — 写入流程与一致性" | PRD | ~5k |
| PRD-functional §FR-0 "系统不变量（Invariants）"（特别是 #3 原子性） | PRD | ~3k |
| INTERFACES.md §store.py + §command_executor.py 签名 | 架构 | ~8k |
| ARCHITECTURE.md §Transactional Outbox + §Idempotency + §Concurrency | 架构 | ~8k |
| 第 1 批产出的 schema.py + models.py（实现） | 上游 | ~10k |
| **总计** | | **~39k** ✅ |

**测试重点**:
- create_node 写入 DB + audit_outbox（同一事务）
- create_node 含 `source` / `source_id` / `source_url` 字段持久化
- get_node / list_nodes 查询正确
- list_nodes 按 `source` 过滤（查所有 GitHub 节点）
- update_node 更新 updated_at + 支持更新 `source_synced_at` / `source_deleted` / `needs_compression` / `tags`
- add_edge / remove_edge / get_edges
- get_children / get_parent / get_dependencies / get_dependents / get_siblings
- get_ancestors / get_descendants（递归）
- `with store.transaction():` 正常 commit
- `with store.transaction():` 异常自动 rollback
- 事务内崩溃不留脏数据
- write_event 写入 audit_outbox
- flush_events 从 outbox → events.jsonl + flushed=1
- session_state get/set
- command_id 幂等：相同 id 返回上次结果
- WAL 模式下读写不互锁

**产出**: `tests/test_store.py`

#### Implementer Agent

**模型**: Sonnet

**Context 包**: CLAUDE.md + PRD 章节 + INTERFACES.md store 段 + ARCHITECTURE.md 相关段 + schema.py + models.py + 测试文件

**产出**: `spine/store.py` + `spine/command_executor.py`

---

### Task 4: validator.py

**依赖**: schema.py + models.py + store.py（第 1-2 批产出）

#### Test Writer Agent

**模型**: Opus（校验器是安全核心）

**Context 包**:

| 项目 | 来源 | 估算 tokens |
|------|------|------------|
| CLAUDE.md 全文 | 固定 | ~5k |
| PRD-functional §FR-5 "状态引擎与级联推导"（§5.1~§5.5） | PRD | ~8k |
| PRD-functional §FR-0 "系统不变量（Invariants）" | PRD | ~3k |
| PRD-functional §附录 7（拓扑安全 + 状态引擎段） | PRD | ~5k |
| INTERFACES.md §validator.py 签名 | 架构 | ~5k |
| store.py 接口签名（不给实现） | 上游 | ~5k |
| **总计** | | **~31k** ✅ |

**测试重点**:
- 合法状态迁移全部通过
- 非法状态迁移全部拒绝（含 actionable error message）
- inbox→active 缺 summary → 拒绝 + 建议 "请先调用 update_field"
- inbox→active 缺 parent_id 且非 root → 拒绝
- inbox→waiting 合法（需 summary + parent/root）
- →done 有活跃子节点 → 拒绝 + 列出未完成子节点
- →dropped 有活跃子节点 → 允许 + 返回 warning
- done→active 缺 reason → 拒绝
- dropped→inbox 缺 reason → 拒绝
- DAG 环路检测（parent 环 + depends_on 环 + 跨维度环）
- DAG 检测用 WITH RECURSIVE CTE（验证 SQL 而非 Python DFS）
- XOR 约束：is_root=True + parent_id≠None → 拒绝
- 活跃域检查：attach 到已归档节点 → 拒绝
- 自依赖：node depends_on 自己 → 拒绝
- 所有 ValidationError 包含 code + message + suggestion

**产出**: `tests/test_validator.py`

#### Implementer Agent

**模型**: Sonnet

**Context 包**: CLAUDE.md + PRD 章节 + INTERFACES.md validator 段 + store.py 接口签名 + 测试文件

**产出**: `spine/validator.py`

---

## Phase 3 Build: 第 3 批（依赖第 2 批）

### Task 5: tools.py（全部 15 Tool handlers）

**依赖**: store.py + validator.py + narrative.py（第 1-2 批全部产出）

#### Test Writer Agent

**模型**: Opus（最大模块，需要最高精度）

**Context 包**:

| 项目 | 来源 | 估算 tokens |
|------|------|------------|
| CLAUDE.md 全文 | 固定 | ~5k |
| PRD-functional §FR-11 "受约束写入" | PRD | ~8k |
| PRD-functional §FR-6 "拓扑安全归档"（unarchive 相关） | PRD | ~5k |
| PRD-functional §FR-10 "可观测性（Assembly Trace）" | PRD | ~5k |
| INTERFACES.md §tools.py + Pydantic 输入模型 | 架构 | ~8k |
| store.py + validator.py + narrative.py 接口签名 | 上游 | ~10k |
| **总计** | | **~41k** ✅ |

**测试重点（15 个 Tool 每个至少 3 个 case）**:

**写入 Tool（10 个）**:
- `create_node`: 正常创建（含 source/source_id/source_url）/ 缺必填字段 / Pydantic 校验拒绝
- `update_status`: 合法迁移 / 非法迁移被拒 / is_root=true 自动清 parent
- `update_field`: 正常更新 / 禁止字段被拒 / summary 更新
- `attach_node`: 正常挂载 / 已有 parent 原子替换 / 归档目标拒绝 / DAG 环拒绝
- `detach_node`: 正常脱离 / 无 parent 时的行为
- `add_dependency`: 正常 / 自依赖拒绝 / 环路拒绝 / 归档目标拒绝
- `remove_dependency`: 正常 / 不存在的依赖
- `append_log`: 正常追加 / 不重置 Anti-Amnesia 计时器
- `unarchive`: 正常解封 + status_changed_at=NOW() / 带 new_status / 非归档节点
- `set_persistent`: 正常设置 / 取消设置

**运行时 Tool（2 个）**:
- `shift_focus`: 切换焦点
- `expand_context`: 扩展上下文

**只读 Tool（3 个）**:
- `get_node`: 存在 / 不存在
- `search_nodes`: 按 status / parent_id / source 过滤 + 分页 / summary 默认不含
- `get_assembly_trace`: 查询最近 N 条 Assembly Trace

**幂等性**:
- 相同 command_id 调用两次 → 返回相同结果

**产出**: `tests/test_tools.py`

#### Implementer Agent

**模型**: Sonnet（或 Opus 如果 Sonnet 搞不定）

**Context 包**: CLAUDE.md + PRD 章节 + INTERFACES.md tools 段 + 全部上游模块实现 + 测试文件

**产出**: `spine/tools.py`

---

### Task 6: 集成验证

**依赖**: 全部 v0 模块
**执行者**: 主 agent，不 spawn

**步骤**:
1. 运行全部 invariant tests → 必须全绿
2. 运行全部单元测试 → 必须全绿
3. 端到端冒烟测试：
   - 创建 3 个节点（goal → project → task）
   - 建立 parent 关系
   - 建立 dependency
   - 状态迁移 inbox → active → done
   - 验证 narrative 文件生成
   - 验证 audit_outbox 有记录
   - flush events → 验证 events.jsonl
   - 验证幂等（重复调用）
   - 创建指向外部源的节点（source="github"）→ 验证 source_* 字段持久化
   - 验证 tags 字段读写
   - 验证 needs_compression / source_deleted 字段更新
4. Spec Review：对照 v0-acceptance.md 验收清单逐条确认
5. 汇报结果

---

## 汇总

| 阶段 | 任务 | Agent 数 | 模型 | 预计时间 |
|------|------|---------|------|---------|
| 1 | Scaffold | 0（主 agent） | - | 10 min |
| 2 | Invariant Tests | 1 Test Writer | Opus | 20-30 min |
| 3.1 | Task 1 + Task 2 | 4（2 对 TW+Impl） | Sonnet | 20-30 min |
| 3.2 | Task 3 + Task 4 | 4（2 对 TW+Impl） | Opus/Sonnet | 30-40 min |
| 3.3 | Task 5 + Task 6 | 2（1 对 TW+Impl）+ 主 agent | Opus/Sonnet | 40-50 min |

**总计**: ~10 个 agent sessions，预计 2-3 小时
**你需要做的**: 每批完成后看汇报，说"继续"

---

## 与其他文档的关系

- **v0-acceptance.md** — v0 的完整验收清单，Task 6 集成验证时逐条对照
- **TASK-DECOMPOSITION.md** — v1 ~ M3 的任务拆解（本文只覆盖 v0）
- **ROADMAP.md** — 全阶段里程碑概览
- **INTERFACES.md** — 所有模块的公共函数签名（本文引用的接口来源）
- **SYSTEM-CONFIG.md** — 所有可调参数（本文中的阈值、预算等不硬编码，引用此文件）

---

## 变更记录

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-03-20 | v1 | 初版 |
| 2026-03-21 | v2 | 重写：FPMS → 认知引擎；行号引用 → 章节引用；补全 Node 新字段（source_* / compression / tags）测试覆盖；Tool 数量 14 → 15（加 get_assembly_trace）；加 source 过滤测试；Phase 编号重排 |
