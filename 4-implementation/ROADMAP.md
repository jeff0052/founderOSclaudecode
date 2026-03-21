# FounderOS 认知引擎 — Roadmap

*从 v0 到可用系统的分阶段交付计划。每个里程碑独立可验收，后一阶段依赖前一阶段。*

---

## 总览

```
v0 ──→ v1 ──→ M1 ──→ M2 ──→ M3
骨架     认知    集成    扩展    闭环
```

| 里程碑 | 一句话目标 | 核心产出 | 前置条件 |
|--------|-----------|---------|---------|
| **v0** | 写入、校验、恢复能稳定工作 | 状态机 + DAG + Store + Tools + 审计 | 无 |
| **v1** | 系统能思考 | 风险 + 看板 + 心跳 + 焦点 + 认知包组装 | v0 全绿 |
| **M1** | 跨工具认知能力上线 | GitHub Adapter + 跨源 Context 装载 | v1 可用 |
| **M2** | 多源感知 | Notion Adapter + 跨源 Heartbeat + 跨源 rollup | M1 可用 |
| **M3** | 双向闭环 | 写回外部 + 状态映射配置化 + 离线降级 | M2 可用 |

---

## v0: 骨架引擎

**目标**：证明写入、校验、恢复能稳定工作。

### 模块清单

| 序号 | 模块 | 职责 |
|------|------|------|
| 1 | `schema.py` | SQLite 建表、CHECK 约束、WAL 模式 |
| 2 | `models.py` | Pydantic 输入校验、Node/Edge/ToolResult dataclass |
| 3 | `store.py` | CRUD + 事务 + audit outbox + flush + 幂等 |
| 4 | `validator.py` | 状态迁移 + DAG CTE 防环 + XOR + 活跃域 |
| 5 | `tools.py` | 15 个 Tool handlers（串行 CommandExecutor） |
| 6 | `narrative.py` | Append-only MD + repair |
| 7 | `command_executor.py` | 串行执行器：幂等检查 + 路由 + 事务封装 |

### 验收标准

- 7 个 invariant test 全绿（DAG 无环、XOR 互斥、原子提交、状态机合法、归档隔离、派生层隔离、幂等）
- 全部 Tool 可调用
- 详见 `v0-acceptance.md`

---

## v1: 认知层

**目标**：系统能思考 — 风险、冒泡、看板、心跳、焦点、认知包。

### 模块清单

| 序号 | 模块 | 职责 |
|------|------|------|
| 7 | `risk.py` | blocked / at-risk / stale 检测 |
| 8 | `rollup.py` | 递归冒泡（子 → 父状态传播） |
| 9 | `dashboard.py` | L0 全局看板树形渲染 |
| 10 | `heartbeat.py` | 告警 + Anti-Amnesia + 去重 |
| 11 | `focus.py` | 焦点仲裁 + LRU + 衰减 |
| 12 | `bundle.py` | L0 / L_Alert / L1 / L2 组装 + 裁剪 |
| 13 | `archive.py` | 归档扫描 + unarchive |
| 14 | `recovery.py` | 冷启动全流程 |

### 验收标准

- 冷启动 → 组装认知包 → 注入 prompt → Agent 可用
- Heartbeat 扫描 < 50ms（SYSTEM-CONFIG `heartbeat.interval`）
- 焦点仲裁输出正确的主/次焦点

---

## M1: 核心引擎 + GitHub Adapter

**目标**：FounderOS 能感知 GitHub 上的任务状态，跨源组装 Context。

### 交付物

| 项目 | 说明 |
|------|------|
| **节点模型扩展** | Node 含 `source` / `source_id` / `source_url` / `source_synced_at` / `source_deleted`（v0 建表时已预留） |
| **GitHub Adapter** | 实现 `sync_node` / `list_updates`，映射 Issue/PR 状态 → FounderOS 状态 |
| **跨源 Context 装载** | DCP 装载时：本地认知层数据 + Adapter 实时拉取 → 合并为完整节点视图 |
| **状态映射表** | GitHub `Open → active` / `Closed → done` / `Label:blocked → risk_mark:blocked`，可配置 |
| **离线降级 v1** | Adapter 拉取失败 → 用缓存 + 标注 `[数据可能过时]` |

### 验收标准

- 创建指向 GitHub Issue 的节点 → `sync_node` 拉取最新状态 → Context 包含外部标题和状态
- GitHub Issue 状态变更 → `list_updates` 捕获 → 本地节点状态同步更新
- Adapter 超时 → 降级使用缓存，不阻塞 Agent

---

## M2: Notion Adapter + 跨源 Heartbeat

**目标**：多源感知 — GitHub + Notion 同时作为数据源，Heartbeat 跨源扫描。

### 交付物

| 项目 | 说明 |
|------|------|
| **Notion Adapter** | 实现 `sync_node` / `list_updates`，同步 Notion Page / Database 条目 |
| **Heartbeat 同步触发** | Heartbeat 周期内附带执行外部同步（频率见 SYSTEM-CONFIG `sync.poll_interval`） |
| **跨源 rollup** | 子节点分布在 GitHub + Notion 时，rollup 仍然正确计算父节点状态 |
| **压缩引擎** | `compression.py` — 规则压缩 + LLM Fallback（详见 PRD-compression-spec） |

### 验收标准

- Notion Page 状态变更 → FounderOS 节点同步更新
- 跨 GitHub + Notion 的节点树 → rollup 状态正确
- Heartbeat 一次扫描同时检查 GitHub + Notion + 本地节点

---

## M3: 写回外部 + 完善

**目标**：双向闭环 — Agent 的退出上报和决策摘要能写回外部工具。

### 交付物

| 项目 | 说明 |
|------|------|
| **write_comment** | 退出上报写回 GitHub Issue Comment / Notion Block |
| **状态映射配置化** | YAML 配置文件定义外部状态 ↔ FounderOS 状态的映射规则 |
| **离线降级完善** | 队列化写回（离线时暂存，恢复后重试） |
| **Token budget 优化** | 基于实际运行数据调优 SYSTEM-CONFIG 各项预算 |
| **Assembly Trace 完善** | 可观测性面板：每次 Context 组装的加载/裁剪/同步追踪 |

### 验收标准

- Agent 完成任务 → 退出上报自动写入 GitHub Issue Comment
- 状态映射配置修改后 → 下次同步按新映射执行
- 断网 → 写回请求入队 → 恢复后自动重试成功

---

## 依赖关系

```
v0 (Store/DAG/Tools)
 └─► v1 (Risk/Heartbeat/Focus/Bundle)
      └─► M1 (GitHub Adapter + 跨源装载)
           └─► M2 (Notion Adapter + 跨源 Heartbeat + 压缩)
                └─► M3 (写回 + 配置化 + 离线降级)
```

每个阶段严格依赖前一阶段的验收通过。不跳阶段。

---

## 关键约束

1. **数据存储原则**：数据留在外部工具，FounderOS 只存认知层独有数据（因果链、依赖关系、压缩摘要）
2. **所有系统参数**：集中在 `SYSTEM-CONFIG.md`，PRD 只引用不硬编码
3. **任务拆解标准**：每个子任务的 Context 不超过 `budget.execution`（当前 100k tokens）
4. **外部工具边界**：任务管理 → GitHub Projects，文档 → Notion，沟通 → Telegram。FounderOS 只做跨工具认知层

---

## 变更记录

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-03-20 | v1 | 初版：v0 → v1 → M1 → M2 → M3 五阶段 Roadmap |
| 2026-03-21 | v2 | M1 完成：GitHub Adapter + 跨源 Context 装载 + 离线降级（560 tests） |
