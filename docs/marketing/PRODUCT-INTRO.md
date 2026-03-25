# FocalPoint — AI 认知操作系统

> 你的 AI 每次对话都是失忆的。FocalPoint 让它拥有记忆、注意力和工作纪律。

---

## 问题

AI Agent 有一个根本性缺陷：**无状态**。

每次对话开始，它都忘了你是谁、项目到哪了、上次做了什么决策、哪些任务卡住了。你得反复解释背景，手动提醒进度，自己跟踪哪些事情被遗漏了。

现有的解决方案只做了一半：

- **Mem0、Zep** — 记住了对话，但不知道你的项目在什么状态
- **LangGraph、CrewAI** — 编排了 Agent，但没有持久的认知能力
- **Claude/OpenAI 内置记忆** — 记住了偏好，但不会主动提醒你被卡住的任务
- **openclaw-pm** — 用 prompt 规则约束行为，但没有真正的数据引擎

它们都只是**记忆层**。记住了什么说过什么，但不管理什么需要做。

---

## FocalPoint 是什么

FocalPoint 不是记忆工具。它是 AI 的**认知操作系统**。

```
记忆层 → 记住说过什么
FocalPoint → 管理需要做什么、谁在做、卡在哪、下一步是什么
```

三个核心能力：

### 1. 结构化记忆

不是把对话存进向量库。而是用项目管理的方式组织 AI 的认知：

```
goal "产品上线"
├── project "支付系统"
│   ├── milestone "Stripe 集成"
│   │   ├── task "实现 API" — active
│   │   ├── task "写测试" — blocked（依赖 API）
│   │   └── task "部署" — inbox
│   └── knowledge/
│       ├── overview.md — 项目背景
│       ├── requirements.md — 需求文档
│       └── architecture.md — 架构设计
```

每个节点有状态（inbox → active → done）、依赖关系、叙事日志、知识文档。子节点自动继承父节点的知识。

### 2. 主动认知

FocalPoint 不等你问。它主动扫描：

- **blocked** — "API 任务已卡住 3 天，等设计评审"
- **stale** — "文档更新一周没人动了"
- **at-risk** — "部署任务明天截止，还没开始"
- **anti-amnesia** — "上次提醒过的问题还没处理，再次提醒"

别的工具存了记忆等你来取。FocalPoint 会**推着你往前走**。

### 3. 工作模式

AI 开始任务前，一次调用准备好所有上下文：

```python
workbench = activate_workbench(node_id, role="execution")
# 返回：目标、知识文档、上下文、子任务列表、角色 prompt
```

三个角色，三种思维方式：

| 角色 | 关注点 | 看到的数据 |
|------|--------|-----------|
| **中书省** Strategy | 该不该做？优先级？ | 决策记录 + 用户反馈 |
| **门下省** Review | 有什么风险？历史教训？ | 风险标注 + 进度 |
| **尚书省** Execution | 怎么做？验收标准？ | 技术细节 + 进度 |

重大决策走**三省 Protocol**：中书省产出需求 → 门下省+尚书省并行审查 → 两个都通过才执行。打回超 3 次，通知人类介入。

---

## 竞品对比

### 能力矩阵

| 能力 | Mem0 | Zep | Letta | CrewAI | Claude 内置 | openclaw-pm | **FocalPoint** |
|------|------|-----|-------|--------|------------|-------------|----------------|
| 持久记忆 | Yes | Yes | Yes | Yes | Yes | Yes | **Yes** |
| 任务生命周期管理 | - | - | - | 部分 | - | 部分 | **Yes** |
| 依赖图（DAG） | - | - | - | - | - | - | **Yes** |
| 主动告警 | - | - | - | - | - | - | **Yes** |
| 知识文档 + 继承 | - | - | - | - | 部分 | - | **Yes** |
| 角色化上下文 | - | - | - | 部分 | - | - | **Yes** |
| 全文搜索 | 向量 | 向量 | 向量 | - | - | - | **FTS5** |
| 审查流程 | - | - | - | - | - | - | **Yes** |
| MCP 原生 | - | - | - | - | 专有 | - | **Yes** |
| 自托管 | 部分 | 部分 | Yes | Yes | - | Yes | **Yes** |
| 外部依赖 | 向量库 | Neo4j | PostgreSQL | - | 云服务 | - | **无（纯 SQLite）** |

### 定位差异

```
Mem0/Zep        = 记忆层（存储 + 检索）
LangGraph/CrewAI = 编排层（Agent 调度）
Claude/OpenAI    = 平台功能（对话增强）
openclaw-pm      = 配置层（prompt 规则）
─────────────────────────────────────────
FocalPoint       = 认知操作系统（记忆 + 注意力 + 工作流）
```

没有竞品同时做到：结构化任务管理 + 主动告警 + 知识文档继承 + 角色化上下文 + 审查流程。

---

## 技术架构

### Brain-Spine 模型

```
Brain（LLM）          Spine（FocalPoint 引擎）
  │                      │
  │ ── Tool Call ──→     │ 校验 → 写入 SQLite → 叙事 → 审计
  │                      │
  │ ←── Context ────     │ 组装 L0/L1/L2 → 裁剪 → 注入 prompt
```

- **Brain** = LLM，只读上下文、发 Tool Call
- **Spine** = 确定性引擎，处理所有逻辑，LLM 不直接接触存储

### 存储

```
SQLite（事实层）     ← 唯一真相源
events.jsonl        ← 审计追踪
narratives/*.md     ← 追加式叙事
knowledge/{id}/*.md ← 知识文档
```

零外部依赖。没有向量库、没有 Redis、没有 PostgreSQL。一个 SQLite 文件就是全部。

### 23 个 MCP Tools

| 类别 | 工具 |
|------|------|
| 写入（11） | create_node, update_status, update_field, attach/detach_node, add/remove_dependency, append_log, unarchive, set_persistent, set_knowledge |
| 读取（5） | get_node, search_nodes, get_knowledge, get_assembly_trace, expand_context |
| 认知（4） | bootstrap, heartbeat, activate_workbench, get_context_bundle |
| 审查（1） | sansei_review |
| 运行时（1） | shift_focus |

---

## 数据说话

| 指标 | 数值 |
|------|------|
| 测试覆盖 | 667 tests |
| MCP Tools | 23 |
| 外部依赖 | 0（纯 SQLite） |
| 冷启动时间 | < 100ms |
| 支持的 LLM | 任意（通过 MCP 协议） |
| 支持的平台 | Claude Desktop, OpenClaw, 任何 MCP 客户端 |

---

## 安装

```bash
pip install focalpoint
```

30 秒接入 Claude Desktop：

```json
{
  "mcpServers": {
    "fpms": {
      "command": "focalpoint"
    }
  }
}
```

OpenClaw 用户直接搜索 `focalpoint-memory` 安装。

---

## 谁需要 FocalPoint

- **独立开发者** — 用 AI 做项目管理，跨会话不丢进度
- **AI 应用开发者** — 给自己的 Agent 加认知能力
- **团队 Lead** — 用三省 Protocol 让 AI 辅助决策审查
- **任何用 AI 做复杂工作的人** — 不想每次对话都从零开始

---

## 开源

MIT-adjacent（BSL 许可），完全自托管，数据在你本地。

GitHub: [github.com/jeff0052/founderOSclaudecode](https://github.com/jeff0052/founderOSclaudecode)
PyPI: [pypi.org/project/focalpoint](https://pypi.org/project/focalpoint/)
