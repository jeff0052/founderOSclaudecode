# FounderOS V4 — 文档索引

> FounderOS：一人公司操作系统，用 AI Agent 替代 COO/CTO 角色。

## 文档结构

```
V4/
├── README.md              ← 你在这里
├── OVERVIEW.md            ← 项目全局状态（每轮迭代更新）
├── GLOSSARY.md            ← 术语表（所有专有概念的统一定义）
├── CHANGELOG.md           ← 变更日志（每轮迭代改了什么+为什么）
├── SYSTEM-CONFIG.md       ← 系统参数配置（所有可调数值集中管理）
│
├── 1-vision/              ← 为什么做，做什么
│   ├── WhitePaper.md          愿景白皮书
│   ├── PRD-philosophy.md      设计哲学（DCP、确定性、人类意识映射）
│   └── PRD-goals.md           核心目标和成功标准
│
├── 2-requirements/        ← 具体要做什么
│   ├── PRD-functional.md      功能需求（FR-1 ~ FR-14）
│   ├── PRD-nfr.md             非功能需求（性能、安全、可靠性）
│   ├── PRD-context-lifecycle.md   Context 生命周期（装载→校验→执行→写回）
│   ├── PRD-compression-spec.md    压缩策略规格
│   ├── PRD-cognitive-engine.md    V2 认知引擎（跨工具集成层）
│   ├── PRD-cto-agent.md          CTO Agent 需求
│   └── USER-SCENARIOS.md         用户场景（8 个核心使用场景）
│
├── 3-architecture/        ← 怎么做
│   ├── ARCHITECTURE.md        FPMS 架构设计
│   ├── ARCHITECTURE-V3.1.md   Memory 六层架构 + DCP 模型
│   ├── INTERFACES.md          MCP Tool 接口定义
│   └── architecture-diagram.md    架构图
│
└── 4-implementation/      ← 开发规范
    ├── CLAUDE.md              Claude Agent 开发指南和约束
    ├── v0-task-breakdown.md   V0 任务分解（6 Task + Agent 分配）
    └── v0-acceptance.md       V0 验收清单（4 层 checklist）
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

## 版本说明

- **V1 (Standalone)**: FPMS 独立系统，自己存储所有数据（SQLite + MD）
- **V2 (Cognitive Engine)**: 跨工具认知引擎，集成 GitHub/Notion/Lark 等外部工具，只做它们做不到的事
