# FPMS v0 — 详细任务分配表

## 执行顺序

```
Phase 3.5: Scaffold（骨架生成）
  → 主 agent 一次性生成全部骨架
  ↓
Phase 3.6: Invariant Tests（铁律测试）
  → 1 个 Test Writer agent
  ↓
Phase 4: Build v0（分 3 批）
  第1批（无依赖，并行）: Task 1 + Task 2
  第2批（依赖第1批）: Task 3 + Task 4
  第3批（依赖第2批）: Task 5 + Task 6
```

---

## Phase 3.5: Scaffold

**执行者**: 主 agent（我）直接生成，不 spawn
**时间**: 10 分钟
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

## Phase 3.6: Invariant Tests

**执行者**: 1 个 Test Writer agent
**模型**: Opus（铁律测试质量最重要）
**时间**: 20-30 分钟

### Context 包

给这个 agent 的内容：
1. `CLAUDE.md` 全文
2. PRD 第 306-325 行（系统不变量 Invariants）
3. PRD 第 1049-1098 行（附录 7：关键不变量验收清单）
4. `INTERFACES.md` 中 models.py + store.py + validator.py 的签名

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
你是一个测试架构师。为 FPMS 系统编写不变量测试套件。

## 项目速查
{CLAUDE.md}

## 系统不变量（来自 PRD）
{PRD 306-325行}

## 验收清单（来自 PRD 附录 7）
{PRD 1049-1098行}

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

## Phase 4 Build: 第 1 批（并行）

### Task 1: schema.py + models.py

**依赖**: 无
**并行**: 可与 Task 2 并行

#### Test Writer Agent

**模型**: Sonnet
**时间**: 10-15 分钟

**Context 包**:
1. `CLAUDE.md` 全文
2. PRD 第 254-300 行（FR-0: 数据分层 + 持久化分层）
3. PRD 第 326-366 行（FR-1: 统一分形节点模型）
4. `INTERFACES.md` 中 schema.py + models.py + Pydantic 输入模型段
5. `ARCHITECTURE.md` 中 SQLite Schema 段

**测试重点**:
- 建表成功，CHECK 约束生效
- Node dataclass 字段完整
- Edge dataclass 字段完整
- Pydantic 输入模型校验（类型强转、非法值拒绝、ISO8601 格式）
- XOR CHECK 约束（is_root=1 AND parent_id IS NOT NULL → 拒绝）
- audit_outbox 表存在
- recent_commands 表存在
- WAL 模式启用

**产出**: `tests/test_schema.py` + `tests/test_models.py`

#### Implementer Agent

**模型**: Sonnet
**时间**: 15-20 分钟

**Context 包**:
1. `CLAUDE.md` 全文
2. 同上 PRD 段
3. `INTERFACES.md` 中 schema.py + models.py 段
4. Test Writer 的测试文件
5. 骨架文件

**铁律**: 不改测试文件，不改接口签名

**产出**: `spine/schema.py` + `spine/models.py`

---

### Task 2: narrative.py

**依赖**: 无
**并行**: 可与 Task 1 并行

#### Test Writer Agent

**模型**: Sonnet
**时间**: 10-15 分钟

**Context 包**:
1. `CLAUDE.md` 全文
2. PRD 第 367-423 行（FR-2: 叙事体上下文）
3. `INTERFACES.md` 中 narrative.py 段

**测试重点**:
- append_narrative 追加格式正确
- append_narrative 不覆盖已有内容（append-only）
- read_narrative 按条数截取
- read_narrative 按天数截取
- read_compressed / write_compressed 读写
- write_repair_event 写入修复记录
- 文件不存在时自动创建
- 并发 append 不丢数据（文件锁）

**产出**: `tests/test_narrative.py`

#### Implementer Agent

**模型**: Sonnet
**时间**: 15-20 分钟

**Context 包**: CLAUDE.md + PRD 段 + INTERFACES.md narrative 段 + 测试文件 + 骨架

**产出**: `spine/narrative.py`

---

## Phase 4 Build: 第 2 批（依赖第 1 批）

### Task 3: store.py

**依赖**: schema.py + models.py（第 1 批产出）

#### Test Writer Agent

**模型**: Opus（store 是核心，测试质量要高）
**时间**: 15-20 分钟

**Context 包**:
1. `CLAUDE.md` 全文
2. PRD 第 855-883 行（FR-11: 写入流程与一致性）
3. PRD 第 306-325 行（系统不变量，特别是 Invariant #3 提交原子性）
4. `INTERFACES.md` 中 store.py + command_executor.py 段
5. `ARCHITECTURE.md` 中 Transactional Outbox + Idempotency Protocol + Concurrency Model 段
6. 第 1 批产出的 schema.py + models.py（实现，非骨架）

**测试重点**:
- create_node 写入 DB + audit_outbox（同一事务）
- get_node / list_nodes 查询正确
- update_node 更新 updated_at
- add_edge / remove_edge / get_edges
- get_children / get_parent / get_dependencies / get_dependents / get_siblings
- get_ancestors / get_descendants（递归）
- `with store.transaction():` 正常 commit
- `with store.transaction():` 异常自动 rollback
- 事务内崩溃不留脏数据
- write_event 写入 audit_outbox
- flush_events 从 outbox → events.jsonl
- flush 后 flushed=1
- session_state get/set
- command_id 幂等：相同 id 返回上次结果
- WAL 模式下读写不互锁

**产出**: `tests/test_store.py`

#### Implementer Agent

**模型**: Sonnet
**时间**: 20-30 分钟

**Context 包**: CLAUDE.md + PRD 段 + INTERFACES.md store 段 + ARCHITECTURE.md 相关段 + schema.py + models.py + 测试文件

**产出**: `spine/store.py` + `spine/command_executor.py`

---

### Task 4: validator.py

**依赖**: schema.py + models.py + store.py（第 1-2 批产出）

#### Test Writer Agent

**模型**: Opus（校验器是安全核心）
**时间**: 15-20 分钟

**Context 包**:
1. `CLAUDE.md` 全文
2. PRD 第 548-630 行（FR-5: 状态引擎 5.1-5.5）
3. PRD 第 306-325 行（系统不变量）
4. PRD 第 1049-1098 行（附录 7 验收清单，特别是拓扑安全 + 状态引擎段）
5. `INTERFACES.md` 中 validator.py 段
6. store.py 的接口签名（不给实现）

**测试重点**:
- 合法状态迁移全部通过
- 非法状态迁移全部拒绝（含 actionable error message）
- inbox→active 缺 summary → 拒绝 + 建议 "请先调用 update_field"
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
**时间**: 20-30 分钟

**Context 包**: CLAUDE.md + PRD 段 + INTERFACES.md validator 段 + store.py 接口签名 + 测试文件

**产出**: `spine/validator.py`

---

## Phase 4 Build: 第 3 批（依赖第 2 批）

### Task 5: tools.py（全部 14 Tool handlers）

**依赖**: store.py + validator.py + narrative.py（第 1-2 批全部产出）

#### Test Writer Agent

**模型**: Opus（最大模块，需要最高精度）
**时间**: 20-30 分钟

**Context 包**:
1. `CLAUDE.md` 全文
2. PRD 第 802-883 行（FR-11: 受约束写入）
3. PRD 第 631-661 行（FR-6: 拓扑安全归档，unarchive 相关）
4. `INTERFACES.md` 中 tools.py 段 + Pydantic 输入模型段
5. store.py + validator.py + narrative.py 的接口签名

**测试重点（14 个 Tool 每个至少 3 个 case）**:

**写入 Tool (10 个)**:
- create_node: 正常创建 / 缺必填字段 / Pydantic 校验拒绝
- update_status: 合法迁移 / 非法迁移被拒 / is_root=true 自动清 parent
- update_field: 正常更新 / 禁止字段被拒 / summary 更新
- attach_node: 正常挂载 / 已有 parent 原子替换 / 归档目标拒绝 / DAG 环拒绝
- detach_node: 正常脱离 / 无 parent 时的行为
- add_dependency: 正常 / 自依赖拒绝 / 环路拒绝 / 归档目标拒绝
- remove_dependency: 正常 / 不存在的依赖
- append_log: 正常追加 / 不重置 Anti-Amnesia 计时器
- unarchive: 正常解封 + status_changed_at=NOW() / 带 new_status / 非归档节点
- set_persistent: 正常设置 / 取消设置

**运行时 Tool (2 个)**:
- shift_focus: 切换焦点
- expand_context: 扩展上下文

**只读 Tool (2 个)**:
- get_node: 存在 / 不存在
- search_nodes: 按 status / parent_id / 分页 / summary 默认不含

**幂等性**:
- 相同 command_id 调用两次 → 返回相同结果

**产出**: `tests/test_tools.py`

#### Implementer Agent

**模型**: Sonnet（或 Opus 如果 Sonnet 搞不定）
**时间**: 30-45 分钟

**Context 包**: CLAUDE.md + PRD 段 + INTERFACES.md tools 段 + 全部上游模块实现 + 测试文件

**产出**: `spine/tools.py`

---

### Task 6: 集成验证

**依赖**: 全部 v0 模块

**执行者**: 主 agent（我），不 spawn

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
4. Spec Review：对照 PRD 验收清单逐条确认
5. 向 Jeff 汇报结果

---

## 总览

| 阶段 | 任务 | Agent 数 | 模型 | 预计时间 |
|------|------|---------|------|---------|
| 3.5 | Scaffold | 0（我做） | - | 10 min |
| 3.6 | Invariant Tests | 1 Test Writer | Opus | 20-30 min |
| 4.1 | Task 1 + Task 2 | 4（2对 TW+Impl） | Sonnet | 20-30 min |
| 4.2 | Task 3 + Task 4 | 4（2对 TW+Impl） | Opus/Sonnet | 30-40 min |
| 4.3 | Task 5 + Task 6 | 2（1对 TW+Impl）+ 我 | Opus/Sonnet | 40-50 min |

**总计**: ~10 个 agent sessions，预计 2-3 小时
**你需要做的**: 每批完成后看汇报，说"继续"
