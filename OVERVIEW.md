# FounderOS — 系统全景

*给任何 Agent 的第一份文件：读完这个，你就知道我们在建什么。*

---

## 一句话

FounderOS 是创始人的公司控制系统。它让一个人管得住一家越来越复杂的公司。

---

## 核心循环

```
State + Signal → Decision → Action → New State
```

- **State**: 公司当前状态（项目进度、指标、风险）
- **Signal**: 外部变化（市场、合作伙伴、政策、用户反馈）
- **Decision**: Founder 做出的关键决策（每周 ≤3 个）
- **Action**: Agent 执行决策
- **New State**: 执行后公司进入新状态，循环继续

Founder 提供 Vision + Judgment，AI 提供 Execution，FounderOS 提供 Control。

---

## 演进阶段

| 版本 | 形态 | 状态 |
|------|------|------|
| V1 | 手动系统（Notion/文档） | 已验证 |
| V2 | AI 辅助分析 | 已验证 |
| **V3** | **Agent 执行系统** | **← 我们在这** |
| V4 | 自动化公司操作系统 | 未来 |

---

## 三个核心组件

### 1. FPMS — Focal Point Memory System

**是什么**: 项目管理引擎 + State 层的物理实现

**做什么**:
- 管理所有项目/任务的状态、依赖、层级关系
- 实时计算风险（blocked / at-risk / stale）
- 渲染全局看板（CEO 视角一屏看全公司）
- 心跳扫描 + 主动告警
- 为每个 Agent 组装认知包（焦点模型 L0/L1/L2）

**核心设计**:
- SQLite + WAL 为 source of truth
- 所有写入通过 Tool Call（LLM 不直接碰存储）
- DAG 拓扑（无环）、状态机（合法迁移）、原子提交
- 眼球模型：L0 看板（全局一行字）→ L1 近景（父/子/兄弟）→ L2 焦点（完整叙事）

**当前状态**: v1 完成，494 测试全绿，已接入 OpenClaw

**代码位置**: `fpms/` | **CLI**: `python3 fpms/spine.py`

---

### 2. Memory Architecture — 五层记忆模型

**是什么**: 公司级记忆系统的架构设计

**为什么需要**: 公司不能只靠聊天记录。需要分层、分域、分权、可审计的记忆。

**五层 + 临时层**:

```
Layer 1  Constitution    公司宪法（Mission/原则/审批规则）     最稳定，全局只读
Layer 2  Fact            客观事实（状态/指标/事件）           FPMS 实现了任务状态部分
Layer 3  Judgment        对事实的解释（判断/评估/建议）        必须附依据+置信度
Layer 4  Office Memory   各 Office 专属工作记忆              CTO workspace 是第一个
Layer 5  Narrative       对外口径（投资人/合作方/监管）        与 Fact 强隔离
Layer 6  Temporary       临时上下文（session/草稿/缓存）      默认不入库
```

**六条原则**:
1. 事实优先
2. 事实与判断分离
3. 内部状态与外部口径分离
4. 分域访问（不同 Office 读写不同内容）
5. 临时上下文默认不入库
6. 所有关键记忆可追溯

**当前状态**: 架构设计完成，FPMS 覆盖 Layer 2 的任务状态切片，CTO Agent 将成为 Layer 4 的第一个实例

**文档位置**: `fpms/docs/FounderOS-Memory-Architecture-V1.md`

---

### 3. Office 体系 — Agent 角色

**是什么**: FounderOS 的执行层，每个 Office 是一个专职 Agent 角色

**设计原则**:
- 每个 Office 有独立 workspace（= Layer 4 Office Memory）
- 共享 Layer 2 Fact（通过 FPMS）
- 遵守 Layer 1 Constitution
- 按角色裁剪 memory 读取范围（不是全量塞给模型）

**已规划的 Office**:

| Office | 角色 | 状态 |
|--------|------|------|
| Product & Engineering (CTO) | 技术方案 + 编码 + 质量 | PRD V2 完成，待搭建 |
| Operations | 商户运营 + 部署 + 客户支持 | 未来 |
| Capital | 融资 + 财务 + 投资人关系 | 未来 |
| Compliance | 合规 + KYC/AML + 监管沟通 | 未来 |
| Risk | 风控 + 欺诈检测 + 异常处理 | 未来 |
| Growth | 市场 + 品牌 + 外部沟通 | 未来 |

**Founder（Jeff）** 不是 Office，是整个系统的 Decision 层 — 所有 Office 向他汇报，他做最终决策。

---

## 关系图

```
┌─────────────────────────────────────────────────┐
│                  FounderOS                       │
│                                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐      │
│  │ Signal   │  │ State    │  │ Decision │      │
│  │ (外部)    │→│ (FPMS)   │→│ (Founder)│      │
│  └──────────┘  └──────────┘  └─────┬────┘      │
│                                     │            │
│                              ┌──────▼──────┐    │
│                              │   Action     │    │
│                              │  (Offices)   │    │
│                              └──────┬──────┘    │
│                    ┌────────────────┼────────┐  │
│                    ▼                ▼        ▼  │
│              ┌─────────┐    ┌─────────┐  ┌───┐ │
│              │CTO Agent│    │Ops Agent│  │...│ │
│              └────┬────┘    └─────────┘  └───┘ │
│                   │                              │
│         ┌─────────▼──────────┐                  │
│         │  Memory Arch 五层   │                  │
│         │ Constitution       │                  │
│         │ Fact (FPMS)        │                  │
│         │ Judgment           │                  │
│         │ Office Memory      │                  │
│         │ Narrative          │                  │
│         └────────────────────┘                  │
└─────────────────────────────────────────────────┘
```

---

## 开发方法论

所有 FounderOS 组件遵循同一套开发流程：

```
Phase 0 需求 [Founder确认] → Phase 1 架构 [Founder确认] → Phase 2 脚手架 [自主]
→ Phase 3 铁律测试 [自主] → Phase 4 TDD分批实现 [自主] → Phase 5 集成验收 [Founder确认]
```

关键约束：
- **文档先于代码** — CLAUDE.md 是代码库的灵魂
- **测试先于实现** — TDD，铁律测试永不修改
- **所有写入通过 Tool Call** — LLM 不直接碰存储
- **FPMS 全程追踪** — 每个 task 的状态变更可审计

---

## 当前公司看板

```
📁 FounderOS [active]
  ├─ FPMS 分形项目管理系统 [active]     ← v1 完成，已接入
  ├─ CTO Agent [active]                ← PRD V2 完成，待搭建
  └─ 支付系统 [inbox]                   ← 收单/发卡/钱包/跨境/稳定币
```

---

## 文档索引

| 文档 | 位置 | 内容 |
|------|------|------|
| 本文件 | `docs/OVERVIEW.md` | 系统全景 |
| 白皮书 V2 | `docs/FounderOS-WhitePaper-V2.md` | 愿景 + 四模块 + 文明等级 |
| Memory Architecture | `docs/FounderOS-Memory-Architecture-V1.md` | 五层记忆模型 |
| CTO Agent PRD | `docs/CTO-AGENT-PRD-V2.md` | 第一个 Office 的完整规格 |
| FPMS PRD | `docs/FPMS-PRD-FINAL.md` | 项目管理引擎规格 |
| FPMS 架构 | `docs/ARCHITECTURE-V3.1.md` | FPMS 技术架构 |
| v0 验收 | `docs/v0-acceptance.md` | FPMS 验收清单 |

---

*读完这个文件，你应该知道：我们在建什么（FounderOS）、建到哪了（V3 Agent 执行阶段）、下一步做什么（搭建 CTO Agent）。*
