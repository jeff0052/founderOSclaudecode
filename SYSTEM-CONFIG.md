# FounderOS 系统参数配置

*所有可调参数集中管理。模型能力增强或运营经验积累后，在这里统一调整。PRD 文档只定义规则，引用本文件的数值。*

---

## 调整原则

1. **改参数只改这一份文件** — PRD 和架构文档引用这里的值，不各自硬编码
2. **改完记录原因** — 底部变更记录写清楚为什么改、改前是多少
3. **改前评估影响** — 参数之间有依赖关系（标注在备注列），改一个可能影响另一个

---

## 1. Context 预算

*按任务难度弹性伸缩：1M 精度不够就缩减到 500k → 200k → 20k → 5k，聚焦信噪比。*

| 参数 | 当前值 | 单位 | 说明 | 备注 |
|------|--------|------|------|------|
| `budget.execution` | 100,000 | tokens | 执行型任务（写代码、做决策）的 context 上限 | 超过 = 必须拆解 |
| `budget.analysis` | 150,000 | tokens | 分析型任务（读文档、写方案）的 context 上限 | |
| `budget.retrieval` | 500,000 | tokens | 检索型任务（找信息、对比方案）的 context 上限 | |
| `budget.full` | 1,000,000 | tokens | 全量深度分析（需要完整上下文的复杂推理） | = model.max_context_window |
| `budget.default` | 100,000 | tokens | 未指定类型时的默认预算 | = budget.execution |
| `budget.min` | 5,000 | tokens | 最小注入量（简单原子操作） | 低于此值信息不足 |
| `budget.fixed_overhead` | 5,000 | tokens | 固定开销（Constitution + CLAUDE.md + L0 + L_Alert） | 不可压缩 |
| `budget.task_context_max` | 15,000 | tokens | 任务 context（骨架+叙事+依赖）的建议上限 | 超过 = 触发压缩 |
| `budget.workload_ratio` | 0.85 | ratio | 工作载荷占总预算的比例 | 1 - fixed - context |

**预算梯度**：`5k → 20k → 100k → 200k → 500k → 1M`。系统默认从 `budget.execution`(100k) 开始，任务过于简单时下降，精度不够时上升。

## 1b. 角色 Token 预算

*v0.3: 工作台按角色分配不同的 token 预算。*

| 角色 | 总预算 | L0 | L1 | L2 | 说明 |
|------|--------|-----|------|------|------|
| `execution` | 8,000 | 0 | 3,000 | 5,000 | 执行者不需要全局看板 |
| `strategy` | 8,000 | 2,000 | 3,000 | 3,000 | 决策者需要全局视野 |
| `review` | 8,000 | 1,000 | 2,000 | 5,000 | 审核者聚焦细节 + 少量全局 |
| `all` | 10,000 | 自动 | 自动 | 自动 | 默认，向后兼容 |

## 1c. Narrative Categories

*v0.3: 叙事条目按 category 分类，角色按需过滤。*

| category | 含义 | 可见角色 |
|----------|------|---------|
| `decision` | 决策记录 | strategy, all |
| `feedback` | 用户/市场反馈 | strategy, all |
| `risk` | 风险/教训 | review, all |
| `technical` | 技术细节 | execution, all |
| `progress` | 进度更新 | review, execution, all |
| `general` | 默认 | all |

## 1d. 三省 Protocol

| 参数 | 当前值 | 说明 |
|------|--------|------|
| `sansei.max_rejections` | 3 | 打回超过此次数通知人类 |
| `sansei.review_mode` | parallel | 门下省 + 尚书省并行审查（不串行） |

## 2. 压缩策略

| 参数 | 当前值 | 单位 | 说明 | 备注 |
|------|--------|------|------|------|
| `compress.narrative_max_entries` | 5 | 条 | 装载时保留的最近叙事条数 | 超出的被压缩摘要替代 |
| `compress.narrative_max_days` | 3 | 天 | 装载时保留的最近叙事天数 | 与 max_entries 取较大值 |
| `compress.target_ratio` | 0.1 | ratio | 压缩目标：压缩后 ≤ 原文 10% | |
| `compress.preserve_decisions` | true | bool | 压缩时是否保留所有决策记录 | 决策+原因不可丢弃 |
| `compress.preserve_risks` | true | bool | 压缩时是否保留未解决的风险 | |

## 3. 焦点与注意力

| 参数 | 当前值 | 单位 | 说明 | 备注 |
|------|--------|------|------|------|
| `focus.max_primary` | 1 | 个 | 同时的主焦点数量 | |
| `focus.max_secondary` | 2 | 个 | 同时的次焦点数量 | L1 摘要级 |
| `focus.stash_max` | 2 | 个 | 暂存区最大容量（LIFO） | |
| `focus.stash_decay_hours` | 24 | 小时 | 暂存超时后写入叙事并移除 | |

## 4. 打断与告警

| 参数 | 当前值 | 单位 | 说明 | 备注 |
|------|--------|------|------|------|
| `alert.interrupt_depended_by` | 3 | 个 | blocked 节点的 depended_by 达到此值时触发打断 | 爆炸半径阈值 |
| `alert.interrupt_deadline_hours` | 24 | 小时 | at_risk 且 deadline 在此时间内触发打断 | |

## 5. Heartbeat 与 Anti-Amnesia

| 参数 | 当前值 | 单位 | 说明 | 备注 |
|------|--------|------|------|------|
| `heartbeat.interval` | 30 | 分钟 | Heartbeat 兜底扫描间隔（无操作时） | 有写操作时事件驱动触发，无操作时按此间隔兜底 |
| `heartbeat.event_driven` | true | bool | 是否在写操作后自动触发 heartbeat | update_status/create_node/append_log 后触发 |
| `heartbeat.stale_threshold` | 72 | 小时 | 活跃节点超过此时间未更新 = stale | |
| `anti_amnesia.reminder_interval` | 48 | 小时 | 被遗忘节点的提醒间隔 | |

## 6. 外部同步

| 参数 | 当前值 | 单位 | 说明 | 备注 |
|------|--------|------|------|------|
| `sync.poll_interval` | 15 | 分钟 | 常规轮询外部工具的间隔 | 与 heartbeat.interval 联动 |
| `sync.focus_realtime` | true | bool | 焦点任务装载时实时拉取外部状态 | DCP 装载时触发 |
| `sync.cache_ttl` | 60 | 分钟 | 同步缓存有效期（离线降级用） | |

## 7. 归档

| 参数 | 当前值 | 单位 | 说明 | 备注 |
|------|--------|------|------|------|
| `archive.auto_days` | 7 | 天 | done 状态超过此天数自动归档 | 需同时满足入度=0 |
| `archive.require_zero_indegree` | true | bool | 自动归档前是否要求无活跃依赖 | |

## 8. 拆解

| 参数 | 当前值 | 单位 | 说明 | 备注 |
|------|--------|------|------|------|
| `decompose.auto_suggest` | true | bool | 脊髓引擎检测超预算时是否自动建议拆解 | 通过 L_Alert 注入 |
| `decompose.overlap_warning_ratio` | 0.5 | ratio | 两个子任务 context 重叠超过此比例时警告 | 可能切割点选错 |

## 9. 模型

| 参数 | 当前值 | 单位 | 说明 | 备注 |
|------|--------|------|------|------|
| `model.default` | claude-sonnet-4-20250514 | - | 默认使用的模型 | |
| `model.max_context_window` | 1,000,000 | tokens | 模型最大上下文窗口 | 预算上限不应超过此值 |
| `model.token_estimate_en` | 1.3 | tokens/word | 英文 token 估算系数 | |
| `model.token_estimate_zh` | 2.0 | tokens/char | 中文 token 估算系数 | |

## 10. Token Efficiency

*核心衡量标准。在真实项目中追踪，用数据驱动优化。对标 OpenViking 的 80% token 削减。*

| 参数 | 当前值 | 单位 | 说明 | 备注 |
|------|--------|------|------|------|
| `token_efficiency.injection_target` | 4,000 | tokens | 单次 context 注入的目标上限 | 当前实际 ~8,000-10,000，需优化 |
| `token_efficiency.utilization_target` | 0.6 | ratio | 注入的 context 中 AI 实际引用的比例目标 | ≥60% 才算高效 |
| `token_efficiency.track_per_task` | true | bool | 是否追踪每个 task 的 token 消耗 | 复盘用 |

**待追踪指标（需真实项目数据）：**

| 指标 | 定义 | 当前状态 |
|------|------|---------|
| `context_injection_tokens` | 每次 bootstrap/workbench/get_context_bundle 注入多少 token | 未量化 |
| `context_utilization_rate` | AI 输出中引用了注入 context 的比例 | 未量化 |
| `tokens_per_task_completion` | 完成一个 task 从 active → done 平均消耗多少 token | 未量化 |
| `wasted_context_ratio` | 注入但未被 AI 使用的 context 比例 | 未量化 |

**优化方向（待验证后实施）：**
1. 按需加载替代全量推送
2. 对话内容压缩后再存储
3. Assembly Trace 追踪 context 命中率
4. L1 邻居按相关性排序而非全量加载

---

## 变更记录

| 日期 | 参数 | 旧值 | 新值 | 原因 |
|------|------|------|------|------|
| 2026-03-20 | - | - | - | 初版，所有参数首次定义 |
| 2026-03-22 | `heartbeat.interval` | 15 | 30 | 单 agent 场景 15 分钟太频繁，改为 30 分钟兜底 + 事件驱动 |
| 2026-03-22 | `heartbeat.event_driven` | - | true | 新增：写操作后自动触发心跳，减少空跑 |
| 2026-03-22 | `role budgets` | - | §1b | v0.3: 新增角色 token 预算分配 |
| 2026-03-22 | `narrative categories` | - | §1c | v0.3: 新增叙事分类 + 角色可见性 |
| 2026-03-22 | `sansei.*` | - | §1d | v0.3: 新增三省 Protocol 参数 |
| 2026-03-22 | `token_efficiency.*` | - | §10 | v0.3.2: 新增 token 效率指标体系，待真实项目数据验证 |
