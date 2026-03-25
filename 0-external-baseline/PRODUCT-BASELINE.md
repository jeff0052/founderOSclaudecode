# Product Baseline

## 一句话

FounderOS 是外部工具之上的认知层与控制层。

它不负责替代 GitHub、Notion、Telegram；它负责把这些工具里的信息变成 Agent 和 Founder 都能直接工作的“认知工作台”。

## 核心问题

我们要解决的不是任务 CRUD，而是以下问题：

1. Agent 跨 session 后，无法快速恢复对项目与决策脉络的理解。
2. 信息分散在多个工具里，Agent 和 Founder 需要手动拼接上下文。
3. 外部工具能存事实，但不能表达跨工具因果链、依赖关系和注意力优先级。
4. 长周期项目会被遗忘，缺少跨工具的主动提醒和异常上报。
5. Founder 需要的是控制能力，不是再维护一套新的任务系统。

## 产品边界

| 能力 | 外部工具负责 | FounderOS 负责 |
|------|-------------|----------------|
| 任务主状态 | GitHub Projects / Issue / Notion DB | 读取、映射、缓存，不作为主事实源 |
| 文档正文 | Notion / GitHub / 外部文档系统 | 摘要、压缩、上下文抽取 |
| 评论与讨论 | GitHub / Telegram / Notion comments | 跨工具聚合、决策提炼、必要时写回 |
| 跨工具依赖 | 无统一承载者 | FounderOS 本地维护 |
| why / summary / focus | 外部工具通常没有统一模型 | FounderOS 本地维护 |
| Anti-Amnesia / Heartbeat | 单工具局部提醒 | FounderOS 跨工具提醒 |
| Founder 控制入口 | Telegram / Agent 对话 | FounderOS 负责解释、校验、编排 |

## 数据归属

### 外部工具是事实源

以下信息默认以外部工具为准：
- title
- status
- assignee / owner（如果外部已有）
- 正文内容
- 评论历史
- 原始更新时间

### FounderOS 是认知源

以下信息由 FounderOS 自己维护：
- cross-tool parent / dependency 关系
- why
- summary
- next_step
- focus / stash / alert dedup
- compressed_summary
- sync cache 与 stale 标记
- Founder/Agent 的决策摘要

## 关键原则

1. 外部工具优先，不重造轮子。
2. FounderOS 只存外部工具存不了、算不出来、拼不起来的东西。
3. 外部状态可以缓存，但缓存不是事实源。
4. 写回外部是能力，不是前提。
5. 本地认知层必须可审计、可回滚、可降级。

## 非目标

- 自建新的任务管理 UI
- 自建新的文档编辑器
- 自建新的聊天系统
- 把所有业务状态重新迁移进本地数据库
- 在 v0/v1 做多 Office 自动化公司操作系统

## v1 成功标准

- Founder 能在 5 分钟内看到跨工具全局状态与重点风险。
- Agent 能围绕焦点任务自动组装跨工具 Context Bundle。
- 关键依赖和 why 不再散落在多个工具里只能靠人脑记忆。
- 外部工具短暂不可用时，系统可降级为缓存读取而不瘫痪。
- Founder 不需要为系统再维护一套平行任务数据。
