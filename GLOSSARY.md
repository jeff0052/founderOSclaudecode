# FounderOS 术语表

*所有文档中出现的专有概念，统一定义在这里。如有歧义，以本文件为准。*

---

## 系统架构

| 术语 | 定义 | 首次出现 |
|------|------|---------|
| **FounderOS** | 一人公司操作系统。Founder 提供 Vision + Judgment，AI 提供 Execution，FounderOS 提供 Control | WhitePaper |
| **FPMS** | Focal Point Memory System，焦点记忆项目管理引擎。State 层的物理实现，管理任务状态、依赖、层级关系 | PRD-functional |
| **Office** | Agent 角色单位。每个 Office 是一个专职 Agent（如 CTO、Operations），有独立 workspace | OVERVIEW |
| **Founder** | 系统的唯一人类决策者（Jeff）。不是 Office，是 Decision 层 | OVERVIEW |

## 认知模型

| 术语 | 定义 | 首次出现 |
|------|------|---------|
| **DCP** | Deterministic Context Push。确定性主动推流。由脊髓引擎组装好 context 推给 LLM，而非让 LLM 自己检索（RAG Pull） | PRD-philosophy |
| **Context Bundle（认知包）** | 脊髓引擎为当前焦点任务组装的完整工作台。包含自身骨架 + 向上目标 + 向下进展 + 横向依赖 + 历史决策 | PRD-context-lifecycle §2 |
| **脊髓引擎（Spine Engine）** | 底层确定性代码，负责 context 组装、状态计算、rollup、DAG 校验等。对应人类"小脑"——不需要 LLM 参与的自动化协调 | PRD-philosophy |
| **眼球模型（Foveal Model）** | 多分辨率 context 加载策略。焦点=中央凹（全量），近景=周边视觉（摘要），全局=背景大盘（一句话状态） | PRD-philosophy |
| **Focus（焦点）** | 当前 Agent 深度关注的唯一任务节点。加载 100% 全量 context | PRD-functional FR-7 |
| **Saccade（扫视）** | 焦点切换动作。类比人眼的快速扫视运动 | PRD-functional FR-7 |

## 分辨率层级

| 术语 | 定义 | 内容 |
|------|------|------|
| **L0（看板层）** | 全局概览，一行字 per 节点 | title + status + risk_mark |
| **L1（近景层）** | 父/子/兄弟/依赖节点 | title + status + summary（一段话摘要） |
| **L2（焦点层）** | 当前焦点节点 | 全量骨架 + 叙事 + 依赖详情 |
| **L_Alert（告警层）** | 独立于焦点的紧急信息 | blocked/at_risk/stale 节点列表 |

## 记忆层级（六层模型）

| 术语 | 层级 | 定义 | 稳定性 |
|------|------|------|--------|
| **Constitution（宪法层）** | Layer 1 | 公司 Mission、原则、审批规则。对应人类末那识（稳定人格） | 最稳定，极少变更 |
| **Fact（事实层）** | Layer 2 | 客观事实：状态、指标、事件。FPMS 实现了任务状态部分 | 随操作变更 |
| **Judgment（判断层）** | Layer 3 | 对事实的解释：判断、评估、建议。必须附依据+置信度 | 可修正 |
| **Office Memory（工作记忆层）** | Layer 4 | 各 Office 专属工作记忆。CTO workspace 是第一个实例 | 按 Office 隔离 |
| **Narrative（叙事层）** | Layer 5 | 对外口径：投资人/合作方/监管。与 Fact 强隔离 | 按受众定制 |
| **Temporary（临时层）** | Layer 6 | 临时上下文：session、草稿、缓存。默认不入库 | 最不稳定 |

## 节点与拓扑

| 术语 | 定义 | 首次出现 |
|------|------|---------|
| **Node（节点）** | FPMS 的基本单元。统一 Schema，可以是 goal/project/task/signal 等任何粒度 | PRD-functional FR-1 |
| **DAG** | Directed Acyclic Graph，有向无环图。节点间的 parent-child 和 dependency 关系必须保持无环 | PRD-functional FR-1 |
| **Edge（边）** | 节点间的关系。类型包括 parent（层级）和 depends_on（依赖） | PRD-functional FR-1 |
| **Rollup（冒泡）** | 子节点状态变更时自动向上重算父节点状态。是事务内的确定性计算，不读缓存 | PRD-functional FR-5 |
| **Risk Mark（风险标记）** | 系统自动计算的节点风险状态：blocked / at_risk / stale / on_track | PRD-functional FR-5 |
| **Archive（归档）** | 硬终态。done 后 7 天 + 入度=0 自动归档。只能通过 unarchive 恢复到 inbox | PRD-functional FR-6 |

## 状态机

| 术语 | 定义 |
|------|------|
| **inbox** | 初始状态，任务已录入但未开始 |
| **active** | 正在执行中。进入条件：需要 summary + (parent OR root) |
| **waiting** | 等待外部条件（非自身 blocked） |
| **done** | 软终态，任务完成。可通过 reason 重新打开为 active |
| **dropped** | 放弃。可通过 reason 恢复为 inbox |
| **archived** | 硬终态。自动归档，只能 unarchive |

## Context 生命周期

| 术语 | 定义 | 首次出现 |
|------|------|---------|
| **装载（Load）** | 脊髓引擎根据焦点 node_id 组装 Context Bundle 的过程 | PRD-context-lifecycle §3.1 |
| **进入校验（Entry Check）** | 装载后、执行前确认焦点任务是否仍与父目标对齐 | PRD-context-lifecycle §3.2 |
| **中途校验（Mid-flight Check）** | 执行中发现重要信息时"抬头看全局"，确认方向正确 | PRD-context-lifecycle §3.3 |
| **写回（Commit）** | LLM 通过 tool call 将产出写入存储层。只写结论不写推理过程 | PRD-context-lifecycle §3.4 |
| **退出上报（Exit Report）** | 写回后评估是否有影响上层的发现需要冒泡 | PRD-context-lifecycle §3.5 |
| **压缩（Compress）** | 将累积叙事抽象为摘要，减少 token 占用 | PRD-context-lifecycle §3.6 |

## 人类意识映射

| 人类意识 | 系统对应 | 说明 |
|---------|---------|------|
| **末那识（Manas）** | Constitution（L1 记忆层） | 稳定的人格/价值观，永远在 context 里 |
| **阿赖耶识（Alaya）** | 长期存储（SQLite + MD） | 所有历史事实、判断、叙事的存储 |
| **大脑前叶** | LLM | 针对当下 context 做推理的器官 |
| **小脑** | 脊髓引擎 | 自动化协调，不需要 LLM 参与 |
| **脑干** | Heartbeat | 持续监控告警，不需要意识参与 |
| **感官器官** | Signals | 外部事件、消息、数据变化的输入 |

## 运行机制

| 术语 | 定义 | 首次出现 |
|------|------|---------|
| **Heartbeat（心跳）** | 系统定期扫描所有活跃节点，发现 blocked/at_risk/stale 并生成告警 | PRD-functional FR-9 |
| **Anti-Amnesia（反遗忘）** | 防止任务被遗忘的机制。长时间未更新的节点触发提醒 | PRD-functional FR-9 |
| **Stash（暂存区）** | 焦点被紧急打断时的临时保存区。LIFO，最多 2 个，超 24h 自动衰减 | PRD-context-lifecycle §5.2 |
| **Tool Call** | LLM 通过 14 个标准化工具（MCP）与 FPMS 交互的唯一方式。LLM 不直接碰存储 | PRD-functional FR-11 |
| **Idempotency（幂等）** | 相同 command_id 重复调用返回相同结果，不产生重复数据 | PRD-functional FR-11 |
| **Audit Outbox（审计发件箱）** | 所有写入操作的事件记录。与数据变更在同一事务内写入，保证一致性 | ARCHITECTURE |

## 开发流程

| 术语 | 定义 |
|------|------|
| **TDD** | Test-Driven Development，测试驱动开发。先写失败测试，再写最小实现 |
| **Invariant Tests（铁律测试）** | 系统级不变量测试。在实现之前就存在，永不允许被 coding agent 修改 |
| **RFC Protocol** | Coding Agent 发现接口签名无法满足需求时的正式变更提议流程 |
| **Scaffold（骨架）** | 全部模块的空壳文件（签名+类型+docstring+pass），让 import 从第一分钟就通 |

---

## 变更记录

| 日期 | 变更 |
|------|------|
| 2026-03-20 | 初版，覆盖所有 V4 文档中的专有术语 |
