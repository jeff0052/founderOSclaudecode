# FocalPoint — Roadmap

*从记忆引擎到 AI 认知操作系统的分阶段交付计划。*

---

## 产品定位

FocalPoint = AI 认知操作系统 = 记忆 + 注意力管理 + 工作流编排

详见 `1-vision/ADR-product-direction.md`

---

## 总览

```
第一层：记忆引擎（已完成）
v0 ──→ v1 ──→ M1 ──→ M2 ──→ M3 ──→ MCP + 发布
骨架     认知    GitHub   Notion   写回    PyPI/ClawHub

第二层：知识层 + 工作台（已完成）
v0.3 ✅
知识文档 + 工作台 + 三省 Protocol + 全文搜索

第三层：协作层（未来）
v0.4+
多 Agent 协调 + 跨 Agent 共享记忆
```

---

## 第一层：记忆引擎

### v0: 骨架引擎 ✅

**目标**：写入、校验、恢复能稳定工作。

| 模块 | 职责 | 状态 |
|------|------|------|
| `schema.py` | SQLite 建表、CHECK 约束、WAL 模式 | ✅ |
| `models.py` | Pydantic 输入校验、Node/Edge/ToolResult | ✅ |
| `store.py` | CRUD + 事务 + audit outbox + 幂等 | ✅ |
| `validator.py` | 状态迁移 + DAG 防环 + XOR | ✅ |
| `tools.py` | 15 个 Tool handlers | ✅ |
| `narrative.py` | Append-only MD + repair | ✅ |
| `command_executor.py` | 串行执行器 + 幂等 | ✅ |

验收：258 tests 全绿。

### v1: 认知层 ✅

**目标**：系统能思考 — 风险、冒泡、看板、心跳、焦点、认知包。

| 模块 | 职责 | 状态 |
|------|------|------|
| `risk.py` | blocked / at-risk / stale 检测 | ✅ |
| `rollup.py` | 递归冒泡 | ✅ |
| `dashboard.py` | L0 全局看板 | ✅ |
| `heartbeat.py` | 告警 + Anti-Amnesia | ✅ |
| `focus.py` | 焦点仲裁 + LRU + 衰减 | ✅ |
| `bundle.py` | L0/L_Alert/L1/L2 组装 + 裁剪 | ✅ |
| `archive.py` | 归档扫描 + unarchive | ✅ |
| `recovery.py` | 冷启动全流程 | ✅ |

验收：510 tests 全绿。

### M1: GitHub Adapter ✅

**目标**：跨工具认知 — 感知 GitHub 上的任务状态。

| 交付物 | 状态 |
|--------|------|
| BaseAdapter ABC + AdapterRegistry | ✅ |
| GitHubAdapter（sync_node / list_updates） | ✅ |
| 跨源 Context 装载 | ✅ |
| 状态映射（Open→active, Closed→done） | ✅ |
| 离线降级 v1 | ✅ |
| 真实 GitHub API 验证 | ✅ |

验收：560 tests 全绿。

### M2: Notion Adapter ✅（部分）

**目标**：多源感知 — GitHub + Notion 同时作为数据源。

| 交付物 | 状态 |
|--------|------|
| NotionAdapter（sync_node / list_updates） | ✅ |
| 真实 Notion API 验证 | ✅ |
| Heartbeat 同步触发 | ⏳ 延后（改为事件驱动，见 SYSTEM-CONFIG） |
| 跨源 rollup | ⏳ 延后（等实际混用场景） |
| 压缩引擎 | ⏳ 延后（等节点量增长后再做） |

验收：584 tests 全绿。

### M3: 写回闭环 ✅（部分）

**目标**：双向闭环 — Agent 的操作能写回外部工具。

| 交付物 | 状态 |
|--------|------|
| write_comment（GitHub + Notion） | ✅ |
| 真实写回验证 | ✅ |
| 状态映射配置化 | ⏳ 延后（硬编码够用） |
| 离线降级完善 | ⏳ 延后 |
| Token budget 优化 | ✅ 已在 v0.3 完成（role budgets） |
| Assembly Trace 完善 | ⏳ 延后 |

### MCP Server + 发布 ✅

| 交付物 | 状态 |
|--------|------|
| MCP Server 22 tools（FastMCP） | ✅ |
| Claude Desktop 接入 | ✅ |
| PyPI 发布（`pip install focalpoint`） | ✅ v0.3.1 |
| ClawHub 发布 | ✅ |

---

## 第二层：知识层 + 工作台

### v0.3: Work Mode ✅

**目标**：给 AI 一个工作台 — 知识背景 + 角色化思维 + 三省审查 Protocol。

详细需求：`2-requirements/PRD-work-mode.md`
验收清单：`4-implementation/v03-acceptance.md`
Milestone 总结：`docs/milestones/2026-03-22-v03-work-mode-complete.md`

| 交付物 | 状态 |
|--------|------|
| **knowledge.py** — 知识文档层 + 继承 | ✅ |
| **activate_workbench** — 无状态工作台 | ✅ |
| **三省 Protocol** — sansei_review 并行审查 | ✅ |
| **narrative category** — 6 种分类 | ✅ |
| **全文搜索** — SQLite FTS5 | ✅ |
| **角色 prompt** — strategy/review/execution | ✅ |
| **角色过滤** — bundle 按 role 过滤 narrative + token 预算 | ✅ |
| **MCP tools** — 新增 4 个 + 更新 3 个（共 22 tools） | ✅ |
| **FTS 自动索引** — append_log/set_knowledge 自动更新搜索索引 | ✅ v0.3.1 |
| **delete_knowledge** — 删除知识文档 MCP tool | ✅ v0.3.1 |
| **查询清理** — FTS5/LIKE 特殊字符处理 + 日志记录 | ✅ v0.3.1 |

验收：665 tests 全绿。v0.3.1 版本。

---

## 第三层：协作层（未来）

### v0.4+: 多 Agent 协作

**目标**：让多个 AI agent 像团队一样协作。

| 方向 | 说明 |
|------|------|
| 多 Agent 任务分配 | 尚书省自动拆解任务分配给多个 worker agent |
| 跨 Agent 共享记忆 | 多个 agent 读写同一个 FocalPoint 实例 |
| 并发控制 | 多 agent 同时写入时的冲突处理 |
| Agent 间通信 | 一个 agent 的产出自动传递给下一个 |

前置条件：v0.3 完成 ✅ + 实际使用验证

---

## 延后事项

以下功能已确认延后，等实际使用中遇到瓶颈再做：

| 事项 | 延后原因 | 触发条件 |
|------|---------|---------|
| 压缩引擎 | 节点还没多到撑爆 token | narrative 超过 budget.task_context_max |
| 跨源 rollup | 还没真正混用 GitHub + Notion 树 | 用户有跨源父子树 |
| Heartbeat 同步触发 | 改为事件驱动（SYSTEM-CONFIG 已配） | 多 agent 高频操作 |
| 状态映射配置化 | 硬编码够用 | 用户需要自定义映射 |
| 离线降级完善 | 断网少见 | 用户反馈断网场景 |
| Assembly Trace 完善 | 调试用 | 需要可观测性排查 |

---

## 依赖关系

```
第一层：记忆引擎
v0 (Store/DAG/Tools) ✅
 └─► v1 (Risk/Heartbeat/Focus/Bundle) ✅
      └─► M1 (GitHub Adapter) ✅
           └─► M2 (Notion Adapter) ✅
                └─► M3 (写回闭环) ✅
                     └─► MCP + 发布 ✅

第二层：知识层 + 工作台
                          └─► v0.3 (Work Mode) ✅

第三层：协作层
                               └─► v0.4+ (多 Agent) ← 下一步
```

---

## 变更记录

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-03-20 | v1 | 初版：v0 → M3 五阶段 Roadmap |
| 2026-03-21 | v2 | M1 完成（560 tests） |
| 2026-03-22 | v3 | 产品方向升级为 AI 认知操作系统。新增第二层（v0.3 Work Mode）和第三层（v0.4+ 多 Agent）。M2/M3 部分交付，剩余延后。 |
| 2026-03-22 | v4 | v0.3 Work Mode 开发完成。657 tests。下一步：v0.4 多 Agent 协作。 |
| 2026-03-22 | v5 | v0.3.1 hotfix：FTS 自动索引、delete_knowledge MCP tool、查询清理。665 tests。22 MCP tools。PyPI/ClawHub 已发布。 |
