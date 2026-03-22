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
| **V3** | **认知引擎 + 外部工具集成** | **← 我们在这** |
| V4 | 自动化公司操作系统 | 未来 |

---

## 三个核心组件

### 1. FPMS — Focal Point Memory System

**是什么**: 认知引擎 — 跨工具的注意力分配和记忆系统

**不是什么**: 不是项目管理工具。任务管理交给 GitHub Projects / Notion 等外部工具。

**做什么**:
- **跨工具因果链**: 维护节点间依赖关系，节点指向外部工具对象（GitHub Issue、Notion Page 等）
- **Context 组装**: 把散落在多个工具里的信息按焦点任务组装成工作台
- **跨时间记忆**: 压缩、叙事保留、Anti-Amnesia 主动唤起
- **主动校验**: 执行中发现偏差时主动提醒
- **全局健康感知**: 跨工具心跳扫描，生成全局状态看板

**核心设计**:
- 节点 = 指针（指向外部工具对象）+ 认知层独有数据（why、depends_on、narrative）
- 外部工具的数据以外部为准，认知层的数据以 FounderOS 为准
- SQLite + WAL 存储认知层数据（不重复存储外部工具已有的数据）
- 所有写入通过 Tool Call（LLM 不直接碰存储）
- 眼球模型：L0 看板 → L1 近景 → L2 焦点

**当前状态**: v0.1.0 已发布（567 测试全绿）— 核心引擎 + GitHub Adapter（已验证真实 API） + MCP Server (18 tools)

**发布渠道**:
- PyPI: `pip install focalpoint`
- ClawHub: `clawhub install focalpoint-memory`
- GitHub: `jeff0052/founderOSclaudecode`

**代码位置**: `fpms/` | **MCP Server**: `focalpoint` 或 `python3.11 -m fpms.mcp_server` | **API**: `from fpms.spine import SpineEngine`

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
  ├─ FocalPoint 认知引擎 [active]        ← v0.1.0 发布 (PyPI + ClawHub)，GitHub 集成已验证
  │   ├─ M2 Notion 集成 [inbox]
  │   └─ M3 写回闭环 [inbox]
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
