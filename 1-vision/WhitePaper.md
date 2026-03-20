# FounderOS 白皮书 V3

*A Control System for One-Person Companies*

---

## 一、愿景

FounderOS 是一人公司的底层操作系统。

在 AI 时代，一个 Founder 可以管理一家越来越复杂的公司。条件是：

- **人类提供 Vision + Judgment**
- **AI 提供 Execution**
- **FounderOS 提供 Control**

Founder 的核心价值集中在三个方面：

- **Vision** — 方向
- **Judgment** — 判断
- **Trust** — 被信任的个体

FounderOS 的使命：**放大 Founder 的认知能力和决策能力。**

---

## 二、核心循环

```
Environment
 ↓
Signals（感知外部变化）
 ↓
Interpretation（解释 + 过滤 + 权重）
 ↓
Decision（Founder 决策）
 ↓
Control（权限 + 约束 + 校验）
 ↓
Missions（Office 执行）
 ↓
Feedback（风险检测 + 结果验证）
 ↓
State Update（状态更新）
 ↓
[循环]
```

这个循环不断运行，使公司像一个生物系统一样演化。

---

## 三、七大核心模块

### 1. State（状态）

公司当前的客观状态。所有 State 必须可量化、可追踪。

每个业务线只保留 2-3 个核心指标。

| 业务线 | 核心指标 |
|--------|---------|
| 支付（收单） | Merchant Count, Monthly GMV, Net Profit |
| 支付（发卡） | Active Cards, Monthly Volume |
| 支付（跨境） | Corridor Count, Settlement Volume |

**实现**: FPMS 看板（任务状态）+ 业务 KPI 仪表盘（未来）

---

### 2. Signals（外部信号）

来自外部世界的重要变化。

**来源**: 市场、合作伙伴、投资人、技术、政策监管、用户反馈

**特点**: 不确定、不连续、可能改变战略

**数据结构**:
```
signal:
  source, type, description
  impact (1-5), confidence (0-1)
  created_at, expires_at
```

---

### 3. Interpretation（解释层）

Signal 是噪音，Decision 是压缩。中间必须有判断引擎。

**作用**:
- Signal 分类与权重评估
- 冲突信号处理
- 战略影响评估
- 把 Founder 的直觉结构化

**示例**:

| Signal | Interpretation | 结论 |
|--------|---------------|------|
| Binance 合作机会 | 高杠杆但慢，需长周期 | 战略储备 |
| 菲律宾 partner ready | 低杠杆但快验证 | 优先执行 |
| 稳定币监管变化 | 长期变量，影响 L3 路径 | 持续跟踪 |

**对应 Memory Architecture**: Layer 3 Judgment Memory

---

### 4. Decision（Founder 决策）

Founder 根据 State + Interpreted Signals 做出关键决策。

**决策分级**（解决 Founder 瓶颈问题）:

| 级别 | 决策者 | 范围 | 频率 |
|------|--------|------|------|
| **L0 — Founder Only** | Jeff | 战略方向、融资、重大人事、公司级风险 | 按需 |
| **L1 — Founder 确认** | Office 提案 → Jeff 确认 | 架构方向、新产品线、高风险变更 | 每周 ≤3 |
| **L2 — Office 自主 + 通知** | Office | 技术选型、日常运营、常规执行 | 持续 |
| **L3 — Agent 自主** | Agent | 代码实现、文档更新、状态同步 | 持续 |

**决策模板**（每个 L0/L1 决策必须包含）:
```
decision:
  what: 做什么
  why: 基于哪些 Signal + Interpretation
  expected_outcome: 预期结果
  time_horizon: 时间范围
  kill_condition: 什么情况下放弃
  owner: 谁负责执行
```

**核心原则**: Founder 每周只做少量高层决策。微观决策下放给 Office，系统不因等待 Founder 而停滞。

---

### 5. Control（控制层）

决策如何被执行、约束、分配、校验。

> FounderOS = Decision System + Control System

**五个维度**:

| 维度 | 定义 |
|------|------|
| **Authority** | 谁有权执行 |
| **Constraints** | 必须满足什么前置条件 |
| **Validation** | 怎么判断执行成功 |
| **Override** | 谁可以强制改变方向 |
| **Escalation** | 出问题时的升级路径 |

**示例**:

| 维度 | Philippines real transaction test |
|------|----------------------------------|
| Authority | Ops Office 执行 |
| Constraints | 必须通过 Risk Office 风控检查 |
| Validation | ≥3 笔真实交易成功 |
| Override | Founder 可强制上线/终止 |
| Escalation | 失败 → CTO + Ops 联合 review |

---

### 6. Missions（执行任务）

Decision 的执行层。每个 Mission 包含：

```
mission:
  title, owner, deadline
  expected_result
  dependency（前置条件）
  risk_check（风控检查）
  validation_condition（完成标准）
  escalation_path（出问题找谁）
  decision_level（L0/L1/L2/L3）
```

**实现**: FPMS task 节点 + 依赖关系 + 风险标记

---

### 7. Stability（稳定系统）

防崩机制。平行于业务运转，专门监控系统本身。

#### 7a. Risk Feedback Loop

```
Mission → Execution → Risk Detection → Adjustment → Mission Update
```

不是做完才看，执行过程中持续检测。

#### 7b. System Health Metrics

| 指标 | 含义 |
|------|------|
| Execution Latency | Mission 从决策到完成的周期 |
| Decision Accuracy | 决策命中率（定期回顾） |
| Agent Reliability | Agent 执行成功率 |
| State Freshness | 数据更新及时性 |
| Token Efficiency | AI 资源消耗效率 |

#### 7c. Kill Switch（熔断机制）

| 级别 | 触发条件 | 动作 |
|------|---------|------|
| L1 警告 | 指标偏离预期 | 标记风险，继续执行 |
| L2 暂停 | 关键指标跌破阈值 | 暂停相关 Mission，等 Founder 确认 |
| L3 降级 | 系统性问题 | 回到上一稳定 State，减少复杂度 |
| L4 熔断 | 严重异常 | 全面暂停自动执行，回到手动模式 |

#### 7d. 高频异步中断

系统心跳不是 T+7（每周），而是：

| 检测频率 | 内容 |
|---------|------|
| 实时 | FPMS 风险标记（blocked/at-risk/stale） |
| 分钟级 | Agent 健康度、Token 消耗异常 |
| 小时级 | 业务指标偏离 |
| 每日 | 全量 State 核对 |
| 每周 | Founder 战略回顾（L0/L1 Decision Review） |

当核心指标跌破阈值或 Agent 遇到 Blocker 时，**随时触发 Founder 临时决策**，不等周会。

---

## 四、Memory Architecture（五层记忆模型）

FounderOS 的记忆不是"记住聊天内容"，是**公司的可计算记忆**。

```
Layer 1  Constitution    公司宪法（最高约束，全局只读）
Layer 2  Fact            客观事实（状态/指标/事件）
Layer 3  Judgment        对事实的解释（必须附依据+置信度）
Layer 4  Office Memory   各 Office 专属工作记忆
Layer 5  Narrative       对外口径（与 Fact 强隔离）
Layer 6  Temporary       临时上下文（默认不入库）
```

**六条原则**:
1. 事实优先
2. 事实与判断分离
3. 内部状态与外部口径分离
4. 分域访问
5. 临时上下文默认不入库
6. 所有关键记忆可追溯

**完整设计见**: `FounderOS-Memory-Architecture-V1.md`

---

## 五、Office 体系（执行层）

每个 Office 是一个专职 AI Agent 角色，拥有独立记忆、遵守公司宪法、通过 FPMS 与 CEO 同步状态。

| Office | 职责 |
|--------|------|
| **Product & Engineering (CTO)** | 技术方案、编码、质量、架构 |
| **Operations** | 商户运营、部署、客户支持 |
| **Capital** | 融资、财务、投资人关系 |
| **Compliance** | 合规、KYC/AML、监管沟通 |
| **Risk** | 风控、欺诈检测、异常处理 |
| **Growth** | 市场、品牌、外部沟通 |

**Founder 不是 Office** — 是整个系统的 Decision 层。

**每个 Office 的 Memory 权限**:
- 读 Constitution（全部）
- 读写 Fact（职责范围内）
- 写 Judgment（自己的，必须附依据）
- 读写 Office Memory（自己的）
- 读 Narrative（相关的）
- 不能跨 Office 改 Fact，不能改 Constitution

---

## 六、Civilization Map（文明等级）

长期层面定义文明等级。当关键指标突破阈值，系统进入新阶段。

### 支付文明路径

| Level | 阶段 | 关键指标 |
|-------|------|---------|
| L1 | Offline acquiring | 首笔真实交易完成 |
| L2 | Regional payment network | 多国节点在线 |
| L3 | Stablecoin settlement network | 链上清算上线 |
| L4 | Global payment infrastructure | 全球网络效应 |

**文明层的作用**: 战略叙事、团队方向、投资人沟通、系统演进节奏

---

## 七、UI 结构（驾驶舱）

```
┌─────────────────────────────────────────┐
│           FounderOS Cockpit             │
├──────────────┬──────────────────────────┤
│ State        │ Signals + Interpretation │
│ Dashboard    │ (按 Impact 排序)          │
│              │                          │
│ KPI 指标     │ Signal → 解释 → 建议      │
│ FPMS 看板    │                          │
├──────────────┼──────────────────────────┤
│ Decisions    │ Missions                 │
│ (本周 ≤3)    │ (按 Office 分组)          │
│              │                          │
│ L0/L1 决策   │ 进度 / 风险 / 阻塞        │
├──────────────┴──────────────────────────┤
│ System Health    │ Alerts               │
│ Agent 状态       │ 需要 Founder 介入的事   │
└─────────────────────────────────────────┘
```

---

## 八、三个原则

### 1. 极简

只关注：状态、信号、解释、决策、控制、执行、稳定。不追求功能堆叠。

### 2. 决策下放

Founder 只做 L0/L1 决策。L2/L3 下放给 Office 和 Agent。系统不因等待 Founder 而停滞。

### 3. 防崩优先

进攻靠 Vision，防守靠 Stability。Kill Switch 是底线，任何时候都可以回到手动模式。

---

## 九、演进路径

| 版本 | 形态 | 状态 |
|------|------|------|
| V1 | 手动系统（文档/Notion） | ✅ 已验证 |
| V2 | AI 辅助分析 | ✅ 已验证 |
| **V3** | **Agent 执行系统** | **← 当前阶段** |
| V4 | 自动化公司操作系统 | 未来 |

### V3 当前进度

| 组件 | 状态 |
|------|------|
| FPMS（State 引擎） | ✅ v1 完成，494 测试，已接入 |
| Memory Architecture | ✅ 五层设计完成 |
| CTO Agent（第一个 Office） | 📝 PRD V2 完成，待搭建 |
| Signal 结构化 | ❌ 待建 |
| Interpretation 层 | ❌ 待建 |
| Decision 模板化 | ❌ 待建 |
| Control 层 | ⚠️ CTO PRD 有部分定义 |
| Stability / Kill Switch | ⚠️ FPMS 心跳覆盖部分 |

---

## 十、最终目标

让一个 Founder 可以管理一个越来越复杂的系统。

这不是管理工具，不是 AI 助手，不是 SaaS 产品。

**这是人类第一次把"公司控制权结构化"。**

---

*FounderOS V3 — 基于白皮书 V2 + Memory Architecture V1 + V2.5 架构增强 + Gemini 压力测试，统一为完整的操作系统级文档。*
