# PRD V2: FounderOS 认知引擎

*从独立系统到跨工具认知层 — 只做 GitHub/Notion/Telegram 做不了的事*

---

## 1. V1 → V2 的核心转变

| | V1 | V2 |
|--|----|----|
| **定位** | 独立的项目管理系统 | 跨工具的认知引擎 |
| **数据存储** | 自建 SQLite + MD | 数据留在外部工具，只存认知层独有的数据 |
| **任务管理** | 自己实现状态机、看板 | GitHub Projects / Notion 负责，FounderOS 读取 |
| **文档** | 自己存 narrative MD | Notion 负责文档，FounderOS 只存压缩摘要和因果链 |
| **沟通** | Telegram Bot 是入口 | 不变，Telegram 仍是主交互入口 |
| **价值** | 全栈替代 | 做胶水和大脑 — 连接、理解、记忆、提醒 |

---

## 2. 边界定义：什么该做，什么不该做

### 2.1 不做（外部工具已经做好的）

| 能力 | 交给谁 | 理由 |
|------|--------|------|
| 任务创建/编辑/看板 | GitHub Projects | UI 成熟，移动端好用，免费 |
| 文档/知识库 | Notion | 编辑体验好，模板丰富，搜索强 |
| 实时沟通 | Telegram | 已有 Bot，Founder 习惯用 |
| 日历/提醒 | Notion Calendar 或系统日历 | 不重造 |
| CI/CD、代码管理 | GitHub | 不重造 |

### 2.2 只做（外部工具做不了的）

| 能力 | 为什么外部工具做不了 | FounderOS 怎么做 |
|------|---------------------|-----------------|
| **跨工具因果链** | GitHub 不知道 Notion 里的决策，Notion 不知道 GitHub 的 blocker | 维护节点间的依赖关系图，节点指向外部工具的具体对象 |
| **Context 组装** | 没有工具能把 GitHub Issue + Notion 文档 + Telegram 历史按焦点任务组装成工作台 | DCP 从多个源拉取，按 context 组成规则组装 |
| **跨时间记忆** | Notion 3个月前的笔记不会自动浮现，GitHub 旧 Issue 沉没 | 压缩 + 叙事保留 + Anti-Amnesia 主动唤起 |
| **主动校验** | 没有工具会在你做子任务时提醒"父目标已经变了" | 中途校验 + 退出上报机制 |
| **全局健康感知** | 每个工具只看自己那部分，没有跨工具的 rollup | Heartbeat 跨源扫描，生成全局状态 |
| **认知压缩** | 工具只存原始数据，不会自动抽象出"这段时间发生了什么" | 规则压缩 + LLM 压缩 |

---

## 3. 架构概览

```
┌─────────────────────────────────────────────────┐
│                  Founder (人类)                   │
│                  via Telegram                     │
└──────────────────────┬──────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────┐
│              认知层 (FounderOS Core)              │
│                                                   │
│  ┌───────────┐ ┌───────────┐ ┌────────────────┐ │
│  │  Context   │ │  Memory   │ │   Heartbeat    │ │
│  │  Engine    │ │  Engine   │ │   (主动校验)    │ │
│  └─────┬─────┘ └─────┬─────┘ └───────┬────────┘ │
│        │             │               │           │
│  ┌─────▼─────────────▼───────────────▼────────┐ │
│  │           Spine Engine (脊髓)                │ │
│  │     DCP 装载 / 写回 / 压缩 / Rollup         │ │
│  └─────────────────────┬──────────────────────┘ │
└────────────────────────┬────────────────────────┘
                         │
┌────────────────────────▼────────────────────────┐
│              连接层 (Adapters)                    │
│                                                   │
│  ┌──────────┐ ┌──────────┐ ┌──────────────────┐ │
│  │ GitHub   │ │ Notion   │ │ Telegram         │ │
│  │ Adapter  │ │ Adapter  │ │ Adapter          │ │
│  │          │ │          │ │ (已有 Bot)        │ │
│  └──────────┘ └──────────┘ └──────────────────┘ │
└─────────────────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────┐
│              外部工具 (数据源)                     │
│                                                   │
│  GitHub Projects    Notion Pages    Telegram Chat │
│  Issues/PRs         Databases       Messages      │
└─────────────────────────────────────────────────┘
```

---

## 4. 节点模型变化

V1 的节点是自建的，所有字段自己存。V2 的节点变成**指针 + 认知层独有数据**。

### 4.1 节点结构

```yaml
node:
  # === 指针（指向外部工具的对象）===
  id: "task-a1b2"                          # FounderOS 内部 ID
  source: "github"                         # 数据源
  source_id: "octocat/repo#42"             # 外部工具的对象 ID
  source_url: "https://github.com/..."     # 外部工具的链接

  # === 从外部同步的字段（只读镜像）===
  title: "实现支付网关对接"                   # 同步自 GitHub Issue title
  status: "active"                          # 映射自 GitHub Project status
  assignee: "jeff"                          # 同步自 GitHub assignee
  updated_at: "2026-03-20T10:00:00+08:00"  # 外部最后更新时间

  # === 认知层独有字段（FounderOS 自己管理）===
  why: "Onta Network 需要自主收单能力"        # 为什么做这件事（向上因果）
  parent_id: "goal-x1y2"                    # 父节点（跨工具的层级关系）
  depends_on: ["task-b3c4"]                 # 依赖关系（跨工具）
  next_step: "等待合作方API文档"              # Agent/Founder 写入的下一步
  risk_marks: ["blocked"]                   # 风险标记
  summary: "方案B已选定，对接中"              # 当前摘要
  compressed_summary: "..."                 # 压缩后的历史摘要
  last_compressed_at: "2026-03-15T00:00:00" # 压缩游标
  no_llm_compression: false                 # 是否禁止 LLM 压缩
  tags: ["payments", "Q1"]                  # FounderOS 级标签
```

### 4.2 哪些字段同步，哪些自管

| 字段类别 | 来源 | 同步方向 | 冲突策略 |
|---------|------|---------|---------|
| title, status, assignee | 外部工具 | 外部 → FounderOS（只读） | 外部为准 |
| why, parent_id, depends_on | FounderOS | 不同步到外部 | FounderOS 独有 |
| next_step, summary | FounderOS | 可选写回外部（如 GitHub Issue comment） | FounderOS 为准 |
| narrative | FounderOS | 不同步 | FounderOS 独有 |

### 4.3 无源节点

不是所有节点都有外部源。纯认知层的节点（如战略目标、里程碑）可以 `source: "internal"`，行为与 V1 相同。

---

## 5. Adapter 接口规范

每个 Adapter 实现统一接口：

```
Adapter 接口:
  sync_node(source_id) → NodeSnapshot     # 拉取单个对象的最新状态
  list_updates(since: datetime) → [Event] # 拉取增量变更事件
  write_comment(source_id, text) → void   # 写入评论/备注（可选）
  search(query) → [NodeSnapshot]          # 搜索（可选）
```

### 5.1 GitHub Adapter

| 操作 | GitHub API | 说明 |
|------|-----------|------|
| sync_node | `GET /repos/{owner}/{repo}/issues/{number}` | 同步 Issue/PR 状态 |
| list_updates | `GET /repos/{owner}/{repo}/events` | 增量事件（status change, comment, label） |
| write_comment | `POST /repos/{owner}/{repo}/issues/{number}/comments` | 退出上报写回 GitHub |
| 状态映射 | Open→active, Closed→done, Label:blocked→blocked | 可配置映射表 |

### 5.2 Notion Adapter

| 操作 | Notion API | 说明 |
|------|-----------|------|
| sync_node | `GET /pages/{page_id}` 或 `GET /databases/{db_id}/query` | 同步页面/数据库条目 |
| list_updates | `POST /search` with filter `last_edited_time > since` | 增量变更 |
| write_comment | `PATCH /blocks/{block_id}/children` | 追加评论块 |
| 状态映射 | Notion status property → FounderOS status | 可配置映射表 |

### 5.3 Telegram Adapter

已有 Bot 实现。V2 中 Telegram 的角色不变：
- Founder 的交互入口
- 接收 Heartbeat 告警
- 发送/接收指令

不需要 sync_node（Telegram 不存任务数据）。

---

## 6. 同步策略

### 6.1 拉取模式

**选择：定时轮询 + 事件补充，不用 Webhook。**

理由：
- 一人公司规模小，轮询频率低（每 15 分钟）足够
- Webhook 需要公网入口，增加部署复杂度
- GitHub/Notion 的 API rate limit 对低频轮询足够

### 6.2 同步频率

| 场景 | 频率 | 触发方式 |
|------|------|---------|
| 常规同步 | 每 15 分钟 | Heartbeat 附带 |
| 焦点任务同步 | 每次 context 装载时 | DCP 装载时实时拉取 |
| 手动刷新 | Founder 指令 | Telegram 命令 `/sync` |

### 6.3 冲突处理

**原则：外部工具的数据以外部为准，认知层的数据以 FounderOS 为准。**

两者不会冲突，因为管的字段不重叠（4.2 节）。

唯一的边界情况：外部工具删除了一个对象。处理方式：
- 标记节点 `source_deleted = true`
- 认知层数据保留（依赖关系、叙事、压缩摘要不删）
- 在 L_Alert 通知 Founder

---

## 7. Context 组装变化

V1 的 context 全部从本地存储装载。V2 的 context 需要**跨源组装**。

### 7.1 装载流程

```
DCP 装载焦点任务 Context:

Step 1: 从本地读取节点的认知层数据（why, depends_on, narrative, summary）
Step 2: 从对应 Adapter 实时拉取最新外部状态（title, status, assignee）
Step 3: 合并为完整节点视图
Step 4: 对父节点、子节点、依赖节点重复 Step 1-3（摘要级，不拉全量）
Step 5: 按 context 组成规则组装 Context Bundle
```

### 7.2 Token 预算不变

组装规则和裁剪铁律与 V1 相同（lifecycle v1.1 §2）。跨源不影响 token 预算。

### 7.3 离线降级

如果 Adapter 拉取失败（API 不可用）：
- 使用上次同步的缓存数据
- 在 context 中标注 `[数据可能过时: 最后同步于 {时间}]`
- 不阻塞 Agent 工作

---

## 8. FounderOS 自己存什么

只存外部工具存不了的东西：

| 数据 | 存储方式 | 为什么不能放外部 |
|------|---------|----------------|
| 节点间依赖关系图 | SQLite edges 表 | 跨 GitHub/Notion 的关系，没有工具能表达 |
| why（因果链） | 节点字段 | GitHub Issue 没有"为什么做这件事"字段 |
| 叙事 narrative | MD 文件 | 跨工具的事件时间线，不属于任何单一工具 |
| 压缩摘要 | MD 文件 | 认知层产物 |
| Constitution（L1 人格） | 配置文件 | 系统行为准则 |
| Focus 状态 | SQLite | 跨工具的焦点追踪 |
| 同步缓存 | SQLite | 外部状态的本地镜像，用于离线降级 |

---

## 9. V1 功能在 V2 中的保留与变化

| V1 功能 | V2 状态 | 变化 |
|---------|---------|------|
| 状态机（5 状态） | **保留** | 但 status 的 source of truth 变成外部工具，FounderOS 做映射 |
| Risk marks | **保留** | 基于映射后的状态计算，逻辑不变 |
| Rollup | **保留** | 基于认知层的 parent_id 冒泡，不依赖外部工具的层级 |
| Context 生命周期 | **保留** | 装载增加跨源拉取步骤 |
| 校验机制 | **保留** | 不变 |
| 压缩 | **保留** | 不变 |
| Heartbeat | **扩展** | 增加 Adapter 同步触发 |
| 14 Tool 接口 | **调整** | create_node 增加 source/source_id 参数，其他逻辑不变 |
| Archive | **保留** | 不变 |

---

## 10. 与 V1 文档的关系

| V1 文档 | V2 关系 |
|---------|---------|
| PRD-functional-v4 | V2 继承所有 FR，仅修改 FR-1（节点模型）和 FR-11（工具接口） |
| PRD-context-lifecycle-v1.1 | V2 完全继承，装载步骤增加跨源拉取 |
| PRD-compression-spec-v1 | V2 完全继承，不变 |
| ARCHITECTURE | V2 新增连接层，认知层架构不变 |
| INTERFACES | V2 新增 Adapter 接口，其他不变 |

---

## 11. 实施路径

```
Phase 0: V1 standalone 先做完（当前计划不变）
  ↓
Phase 1: GitHub Adapter
  - 实现 sync_node / list_updates
  - 节点模型增加 source/source_id
  - Context 装载增加跨源拉取
  ↓
Phase 2: Notion Adapter
  - 实现 sync_node / list_updates
  - 状态映射配置
  ↓
Phase 3: 跨源 Heartbeat
  - 同步触发
  - 跨源 rollup
  ↓
Phase 4: 退出上报写回外部
  - write_comment 到 GitHub/Notion
```

---

## 变更记录

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-03-20 | v1 | 初版：从独立系统到认知引擎的转变，Adapter 架构，节点指针模型 |
