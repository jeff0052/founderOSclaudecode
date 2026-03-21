# FPMS — Focal Point Memory System

> AI 助手的持久化认知记忆引擎。让 Claude/GPT 拥有跨会话的长期记忆和主动风险感知。

## 当前状态

```
v0  骨架引擎          ✅ 完成 (258 tests)
v1  认知层            ✅ 完成 (510 tests)
M1  GitHub 集成       ✅ 完成 (560 tests)
MCP Server           ✅ 完成 (567 tests) — 18 tools, stdio transport
M2  Notion + 跨源     ⏳ 下一步
M3  写回闭环          ⏳ 计划中
```

## 快速开始

### 方式 1：MCP Server（推荐 — 接入 Claude Desktop / Code / OpenClaw）

```bash
# 启动 MCP Server（stdio transport）
python3.11 -m fpms.mcp_server

# 自定义数据路径
FPMS_DB_PATH=./data/fpms.db python3.11 -m fpms.mcp_server
```

Claude Desktop 配置 (`claude_desktop_config.json`):
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

### 方式 2：Python API

```python
from fpms.spine import SpineEngine

engine = SpineEngine(db_path="./data/fpms.db")
bundle = engine.bootstrap()          # 冷启动，获取认知包
print(bundle.l0_dashboard)           # 全局视图
print(bundle.l_alert)                # 告警

# 创建节点、变更状态、心跳扫描
engine.execute_tool("create_node", {"title": "My Project", "is_root": True})
engine.execute_tool("update_status", {"node_id": "...", "new_status": "active"})
hb = engine.heartbeat()              # 风险扫描
```

详细使用说明见 [docs/USAGE-GUIDE.md](docs/USAGE-GUIDE.md)

## 文档结构

```
V4/
├── README.md              ← 你在这里
├── OVERVIEW.md            ← 项目全局状态
├── GLOSSARY.md            ← 术语表
├── CHANGELOG.md           ← 变更日志
├── SYSTEM-CONFIG.md       ← 系统参数配置
│
├── docs/
│   └── USAGE-GUIDE.md     ← 产品使用指南（用途/场景/注意事项）
│
├── fpms/
│   ├── mcp_server.py      ← MCP Server 入口（18 tools）
│   └── spine/             ← 核心引擎（18 个模块，567 tests）
│
├── 1-vision/              ← 为什么做，做什么
│   ├── WhitePaper.md          愿景白皮书
│   ├── PRD-philosophy.md      设计哲学（DCP、确定性、人类意识映射）
│   └── PRD-goals.md           核心目标和成功标准
│
├── 2-requirements/        ← 具体要做什么
│   ├── PRD-functional.md      功能需求（FR-1 ~ FR-14）
│   ├── PRD-nfr.md             非功能需求（性能、安全、可靠性）
│   ├── PRD-context-lifecycle.md   Context 生命周期
│   ├── PRD-compression-spec.md    压缩策略规格
│   ├── PRD-cognitive-engine.md    V2 认知引擎
│   ├── PRD-cto-agent.md          CTO Agent 需求
│   └── USER-SCENARIOS.md         用户场景
│
├── 3-architecture/        ← 怎么做
│   ├── ARCHITECTURE.md        FPMS 架构设计
│   ├── ARCHITECTURE-V3.1.md   Memory 六层架构 + DCP 模型
│   ├── INTERFACES.md          MCP Tool 接口定义
│   └── architecture-diagram.md    架构图
│
└── 4-implementation/      ← 开发规范
    ├── CLAUDE.md              Claude Agent 开发指南
    ├── ROADMAP.md             开发路线图
    ├── TASK-DECOMPOSITION.md  任务拆解
    ├── v0-task-breakdown.md   V0 任务分解
    └── v0-acceptance.md       V0 验收清单
```

## 开发时加载哪些文档？

| 场景 | 必须加载 | 按需加载 |
|------|---------|---------|
| 任何开发任务 | OVERVIEW + CLAUDE.md | — |
| 写 FPMS 代码 | + PRD-functional + INTERFACES | + ARCHITECTURE |
| 写 Context/压缩 | + PRD-context-lifecycle + PRD-compression-spec | — |
| 写 Adapter/集成 | + PRD-cognitive-engine | — |
| 写 CTO Agent | + PRD-cto-agent | — |
| 需求讨论/设计 | + PRD-goals + PRD-philosophy | + WhitePaper |

## 任务完成后更新哪些文档？

| 变更类型 | 更新什么 |
|---------|---------|
| 实现了某个 FR | OVERVIEW 里的"当前状态" |
| 发现需求有歧义 | 对应的 PRD 文档 |
| 架构决策变更 | ARCHITECTURE 里加 ADR |
| 接口变更 | INTERFACES 同步更新 |
| 新增模块 | CLAUDE.md 更新开发指南 |

## 架构简图

```
AI 助手 (Claude Desktop / Code / OpenClaw)
    │
    ▼ MCP Tool Call (stdio)
┌──────────────────────────┐
│   mcp_server.py          │ ← 18 MCP tools (FastMCP)
│     ┌────────────────┐   │
│     │  SpineEngine   │   │ ← 总控入口
│     │ ┌─────┬──────┐ │   │
│     │ │Tools│Heart-│ │   │
│     │ │Exec │beat  │ │   │
│     │ │Store│Bundle│ │   │
│     │ │Valid│Risk  │ │   │
│     │ └─────┴──────┘ │   │
│     │ Adapters(GitHub)│   │
│     └────────────────┘   │
└──────────────────────────┘
    │
    ▼
  SQLite + Narrative MD
```

## 版本说明

- **V1 (Standalone)**: FPMS 独立系统，自己存储所有数据（SQLite + MD）
- **V2 (Cognitive Engine)**: 跨工具认知引擎，集成 GitHub/Notion/Lark 等外部工具，只做它们做不到的事
