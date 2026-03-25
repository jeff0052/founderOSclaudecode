# FPMS 使用指南

> Focal Point Memory System — AI 助手的持久化认知记忆引擎

---

## 一、这是什么

FPMS 是一个 **给 AI 助手装配长期记忆的引擎**。

AI 助手（如 Claude、GPT）每次对话都是"失忆"的：它不记得你昨天聊了什么、你的项目进展到哪、哪些任务被卡住了。FPMS 解决这个问题——它让 AI 助手在每次对话开始时自动获得一份"认知简报"，包含：

- 你所有项目和任务的全局视图
- 当前最紧急的告警（截止日期、阻塞、停滞）
- 你正在关注的焦点任务的完整上下文
- 历史决策和操作日志

**一句话总结：FPMS 让 AI 助手拥有跨会话的持久记忆和主动风险感知。**

---

## 二、核心概念

### 2.1 Node（节点）

所有工作项都是 Node，类型分 5 级：

| 类型 | 粒度 | 例子 |
|------|------|------|
| `goal` | 愿景级 | "完成 FounderOS 第一版" |
| `project` | 项目级 | "FPMS 记忆引擎" |
| `milestone` | 里程碑 | "v1 认知层完成" |
| `task` | 执行级 | "实现 heartbeat 模块" |
| `unknown` | 未分类 | 快速捕捉的想法 |

节点之间形成 **树形结构**（parent 关系）和 **依赖网**（depends_on 关系）。

### 2.2 状态机

每个节点有 5 种状态，迁移规则严格：

```
inbox → active → done
  ↓       ↓
  →    waiting → done
                  ↓
               dropped
```

- `inbox`：新捕获，尚未开始
- `active`：正在进行
- `waiting`：等待外部条件
- `done`：完成
- `dropped`：放弃

### 2.3 四层认知包（Context Bundle）

每次对话开始，FPMS 组装一个认知包注入 AI 的 system prompt：

| 层 | 内容 | 用途 |
|----|------|------|
| **L0 Dashboard** | 全局树状图 + 状态图标 | 让 AI 知道"全局长什么样" |
| **L_Alert** | Top 3 紧急告警 | 让 AI 知道"什么最紧急" |
| **L1 Neighborhood** | 焦点节点的父/子/依赖/兄弟 | 让 AI 知道"相关的有什么" |
| **L2 Focus** | 焦点节点详情 + 历史日志 | 让 AI 知道"现在该做什么" |

### 2.4 Heartbeat（心跳）

定时扫描所有活跃节点，自动发现：

- 截止日期临近（< 48h）
- 被阻塞（依赖未完成）
- 停滞（> 72h 无变化）
- 遗忘（Anti-Amnesia：24h 无实质操作）

---

## 三、适用场景

### 适合

| 场景 | 说明 |
|------|------|
| **个人项目管理** | 跟踪多个并行项目的状态、截止日期、阻塞关系 |
| **AI 助手长期记忆** | 让 Claude/GPT 跨会话记住你的项目进展 |
| **决策日志** | 自动记录每次状态变更和操作原因，可追溯 |
| **风险预警** | 被动遗忘的任务会被主动推送告警 |
| **多源同步** | GitHub Issues/PRs 状态自动同步到统一视图 |
| **创始人/独立开发者** | 一个人管多个项目，需要 AI 辅助跟踪全局 |

### 不适合

| 场景 | 原因 |
|------|------|
| 团队协作工具 | 当前设计面向单人（Founder），无多用户权限 |
| 替代 Jira/Linear | FPMS 不是项目管理 UI，它是 AI 的认知后端 |
| 实时协作编辑 | 无 WebSocket/实时同步机制 |
| 大规模数据（万级节点） | SQLite 单文件，适合数百个活跃节点的规模 |

---

## 四、使用方式

### 4.1 作为 Python 库直接调用

```python
from fpms.spine import SpineEngine

# 初始化引擎
engine = SpineEngine(
    db_path="./data/fpms.db",        # SQLite 数据库路径
    events_path="./data/events.jsonl", # 审计日志路径
    narratives_dir="./data/narratives", # 叙事文件目录
)

# 冷启动（首次 / 重启后调用）
bundle = engine.bootstrap()
print(bundle.l0_dashboard)  # 全局视图
print(bundle.l_alert)       # 告警

# 创建一个项目
result = engine.execute_tool("create_node", {
    "title": "FPMS v2 开发",
    "node_type": "project",
    "is_root": True,
    "summary": "完成 FPMS 第二版，支持多源同步",
})
project_id = result.data["id"]

# 创建子任务
result = engine.execute_tool("create_node", {
    "title": "实现 Notion adapter",
    "node_type": "task",
    "parent_id": project_id,
})
task_id = result.data["id"]

# 激活任务
engine.execute_tool("update_status", {
    "node_id": task_id,
    "new_status": "active",
    "reason": "开始 M2 开发",
})

# 获取当前认知包（注入 AI system prompt）
bundle = engine.get_context_bundle(user_focus=task_id)
# bundle.l0_dashboard  → 全局树
# bundle.l_alert       → 告警
# bundle.l1_neighborhood → 邻域
# bundle.l2_focus      → 焦点详情

# 执行心跳扫描
hb = engine.heartbeat()
# hb["alerts"]          → 告警列表
# hb["focus_suggestion"] → 建议关注的节点
```

### 4.2 作为 MCP Server 接入 AI 助手

适用于 Claude Desktop、Claude Code、OpenClaw 等支持 MCP 的客户端。

**内置 MCP Server** 封装了 18 个 tools（15 SpineEngine + 3 系统工具）：

```
写入工具 (10):
  create_node      — 创建节点
  update_status    — 变更状态
  update_field     — 修改字段
  attach_node      — 挂载到父节点
  detach_node      — 从父节点脱离
  add_dependency   — 添加依赖
  remove_dependency — 移除依赖
  append_log       — 追加日志
  unarchive        — 解封归档节点
  set_persistent   — 标记为不可归档

运行时工具 (2):
  shift_focus      — 切换焦点
  expand_context   — 扩展上下文

只读工具 (3):
  get_node         — 查询节点
  search_nodes     — 搜索节点
  get_assembly_trace — 查询组装轨迹

系统工具 (3):
  bootstrap        — 冷启动，获取完整认知包
  heartbeat        — 心跳扫描，检测风险
  get_context_bundle — 获取当前认知包
```

#### 启动 MCP Server

```bash
# 默认路径
python -m fpms.mcp_server

# 自定义数据路径
FPMS_DB_PATH=./data/fpms.db \
FPMS_EVENTS_PATH=./data/events.jsonl \
FPMS_NARRATIVES_DIR=./data/narratives \
python -m fpms.mcp_server
```

#### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `FPMS_DB_PATH` | `fpms/db/fpms.db` | SQLite 数据库路径 |
| `FPMS_EVENTS_PATH` | `fpms/events.jsonl` | 审计日志路径 |
| `FPMS_NARRATIVES_DIR` | `fpms/narratives` | 叙事文件目录 |

#### Claude Desktop 配置

在 `~/Library/Application Support/Claude/claude_desktop_config.json` 中添加：

```json
{
  "mcpServers": {
    "fpms": {
      "command": "python3.11",
      "args": ["-m", "fpms.mcp_server"],
      "cwd": "/path/to/MemoryFPMS/V4",
      "env": {
        "FPMS_DB_PATH": "./data/fpms.db",
        "FPMS_EVENTS_PATH": "./data/events.jsonl",
        "FPMS_NARRATIVES_DIR": "./data/narratives"
      }
    }
  }
}
```

#### Claude Code 配置

在项目根目录 `.claude/settings.json` 中添加：

```json
{
  "mcpServers": {
    "fpms": {
      "command": "python3.11",
      "args": ["-m", "fpms.mcp_server"],
      "cwd": "/path/to/MemoryFPMS/V4"
    }
  }
}
```

### 4.3 接入 OpenClaw

OpenClaw 支持 MCP，接入步骤：

1. 在 OpenClaw 设置中添加 MCP Server 配置（同 Claude Desktop 格式）
2. OpenClaw 的 Claude 即可通过 tool call 读写 FPMS
3. 建议在 OpenClaw 的 heartbeat 机制中定时调用 `heartbeat` tool

### 4.4 GitHub 集成

```python
from fpms.spine import SpineEngine
from fpms.spine.adapters.github_adapter import GitHubAdapter
from fpms.spine.adapters.registry import AdapterRegistry

engine = SpineEngine(db_path="./data/fpms.db")

# 注册 GitHub adapter
registry = AdapterRegistry()
github = GitHubAdapter(token="ghp_xxx")
registry.register("github", github)
engine.set_adapter_registry(registry)

# 创建跟踪 GitHub Issue 的节点
engine.execute_tool("create_node", {
    "title": "Fix login bug",
    "source": "github",
    "source_id": "myorg/myrepo#42",
    "source_url": "https://github.com/myorg/myrepo/issues/42",
})

# 从 GitHub 同步最新状态
engine.sync_all()
```

---

## 五、典型工作流

### 5.1 每日启动

```
1. engine.bootstrap()        → 获取冷启动认知包
2. 注入 bundle 到 AI 的 system prompt
3. AI 阅读 L0 全局视图 + L_Alert 告警
4. AI 主动询问："你的 X 任务截止日期是明天，需要处理吗？"
```

### 5.2 工作过程中

```
1. 用户和 AI 讨论任务
2. AI 调用 update_status / update_field 记录进展
3. AI 调用 append_log 记录决策原因
4. AI 调用 shift_focus 切换到下一个任务
```

### 5.3 定时心跳

```
1. engine.heartbeat()        → 扫描风险
2. 发现截止日期 < 48h      → 推送 at_risk 告警
3. 发现任务 72h 无更新      → 推送 stale 告警
4. 发现 24h 无实质操作      → 触发 Anti-Amnesia 提醒
```

### 5.4 归档清理

```
1. 完成的任务 7 天后自动归档
2. 归档节点不出现在 L0 视图中
3. 需要时可 unarchive 恢复
4. is_persistent 节点永不被归档
```

---

## 六、注意事项

### 6.1 数据安全

- **所有数据存本地**：SQLite + 文件系统，不外传
- **定期备份 db 文件**：`fpms.db` 是唯一的事实源（Source of Truth）
- **narratives 目录也要备份**：包含所有操作日志，不可重建
- **events.jsonl 可选备份**：审计日志，用于合规追溯

### 6.2 性能边界

- 建议活跃节点数 < 500，总节点数 < 5000
- 心跳扫描全量遍历活跃节点，节点越多越慢
- L0 Dashboard 渲染整棵树，深度 > 5 层时可能超 token 预算
- SQLite WAL 模式支持并发读，但写入串行

### 6.3 状态一致性

- **所有写操作必须通过 `execute_tool()`**：不要直接操作 SQLite
- **不要手动编辑 narrative 文件**：append-only 格式，手动编辑可能破坏读取
- **幂等保证**：每个 command_id 24h 内只执行一次，重复调用返回缓存结果
- **事务原子性**：单次 tool call 要么全部成功，要么全部回滚

### 6.4 AI 集成注意

- **Context Bundle 有 token 预算**：不是所有信息都会注入，系统会按优先级裁剪
- **Heartbeat 需要定时触发**：FPMS 不自带定时器，需要宿主（如 OpenClaw heartbeat、cron job）触发
- **Anti-Amnesia 依赖 heartbeat**：如果从不调用 heartbeat()，遗忘检测不会工作
- **GitHub Adapter 需要 token**：需要有 repo 读权限的 Personal Access Token
- **离线降级**：外部源不可达时，bundle 仍然可以组装，只跳过同步

### 6.5 当前限制

| 限制 | 说明 | 计划 |
|------|------|------|
| ~~无内置 MCP Server~~ | ✅ 已内置 `fpms.mcp_server`，18 tools | 已完成 |
| GitHub 只读 | 不支持从 FPMS 写回 GitHub comment | M3 写回闭环 |
| 无 Notion 支持 | 仅支持 GitHub 作为外部源 | M2 Notion adapter |
| 无 Web UI | 纯 Python API，无可视化界面 | 后续考虑 |
| 单用户 | 无多用户隔离 | 设计定位为个人工具 |
| 无 LLM 压缩 | narrative 压缩需要外部 LLM 调用，当前未接入 | M2 |

---

## 七、文件结构

```
fpms/
├── mcp_server.py           # MCP Server 入口（18 tools, stdio transport）
├── spine/
│   ├── __init__.py          # SpineEngine 入口
│   ├── models.py            # 数据模型
│   ├── schema.py            # SQLite DDL
│   ├── store.py             # 存储层
│   ├── validator.py         # 校验层
│   ├── narrative.py         # 叙事日志
│   ├── tools.py             # 15 个 tool handler
│   ├── command_executor.py  # 幂等执行器
│   ├── risk.py              # 风险计算
│   ├── rollup.py            # 状态汇总
│   ├── heartbeat.py         # 心跳扫描
│   ├── focus.py             # 焦点调度
│   ├── dashboard.py         # 全局视图
│   ├── bundle.py            # 认知包组装
│   ├── archive.py           # 归档管理
│   ├── recovery.py          # 冷启动
│   └── adapters/
│       ├── base.py          # Adapter 抽象基类
│       ├── registry.py      # Adapter 注册中心
│       └── github_adapter.py # GitHub 同步

data/                         # 运行时数据（需备份）
├── fpms.db                   # SQLite 数据库
├── events.jsonl              # 审计日志
└── narratives/               # 节点叙事文件
    ├── {node_id}.md
    └── ...
```

---

## 八、依赖

```
Python >= 3.11
pydantic >= 2.0
httpx >= 0.24        # GitHub adapter
mcp[cli] >= 1.2.0   # MCP Server (FastMCP)
```

SQLite 为 Python 内置，无需额外安装。
