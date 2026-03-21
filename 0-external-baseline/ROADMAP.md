# Roadmap

## 路线原则

我们不先做一个完整的 standalone FPMS，再去接外部工具。

我们从第一阶段就按“外部工具为事实源”实现。

## Phase 0 — 文档与模型收口

目标：统一产品边界和数据归属。

交付物：
- 本文件夹 4 份基线文档
- 统一术语：FPMS = cognitive layer，不再定义为 project management engine
- 统一数据归属表
- 统一同步与降级策略

验收：
- 新 agent 只读本文件夹即可理解当前主线
- 与旧文档冲突时有明确裁决规则

## Phase 1 — GitHub-first Cognitive MVP

目标：先围绕 GitHub 建立最小认知闭环。

交付物：
- GitHub Adapter
- 本地 node_ref + graph + summary/why 存储
- focus + heartbeat + L0/L1/L2 bundle
- comment 写回能力
- 缓存降级能力

验收：
- 给定一个 GitHub issue，FounderOS 能拉状态、补 why、建立依赖、组装 context
- GitHub 短暂不可用时，仍能用缓存继续工作
- Founder 可以通过 Telegram/Agent 查看重点任务与风险

## Phase 2 — Notion Context Integration

目标：把文档上下文接进来，而不是只看任务状态。

交付物：
- Notion Adapter
- 跨 GitHub / Notion 的 context merge
- 决策摘要与文档压缩
- cross-tool dependency 支持

验收：
- 焦点任务的 context 中同时出现 GitHub 状态和 Notion 决策材料
- Agent 可以解释“现在做什么”和“为什么这么做”

## Phase 3 — Telegram Control Layer

目标：让 Founder 真正通过自然语言控制，而不是手动翻工具。

交付物：
- Telegram 交互协议
- 告警推送
- shift_focus / explain / summarize / report
- 中途校验与退出上报

验收：
- Founder 用 Telegram 就能看到重点风险、切换焦点、收到异常上报
- Agent 的关键发现能推送给 Founder，而不是留在某个工具角落里

## Phase 4 — Writeback and Reliability

目标：把系统从“只读认知层”升级成“有限闭环认知层”。

交付物：
- comment / summary 写回外部
- 状态映射配置化
- 重试队列与离线恢复
- Assembly Trace 可观测性

验收：
- 退出上报可稳定写回 GitHub / Notion
- 网络抖动时请求不丢失
- 可以解释某次 context 是如何被组装出来的

## 明确不做的顺序

以下事情不应排在前面：
- 自建任务管理 UI
- 自建完整状态机并要求所有业务迁移进来
- 先做多 Office 自动化再验证单 Founder 工作流
- 先做全量本地知识库再验证 context bundle 价值

## 当前推荐优先级

1. GitHub-first cognitive MVP
2. Notion context integration
3. Telegram control layer
4. 写回与可靠性
5. 多 Office 与更高层自动化
