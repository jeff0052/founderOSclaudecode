# External-First Baseline

这组文档定义 FounderOS/FPMS 的当前主线：

**外部工具是事实源，FounderOS 是认知层与控制层。**

旧文档不删除，但从现在开始，凡是与本文件夹冲突的内容，**以本文件夹为准**。

## 这组文档解决什么问题

我们不再优先解决“如何自研一个项目管理系统”。

我们优先解决的是：
- Agent 跨 session 的认知连续性
- 跨 GitHub / Notion / Telegram 的上下文组装
- 跨工具因果链、依赖链和焦点管理
- 关键提醒、Anti-Amnesia 和中途校验
- Founder 的自然语言控制与审计

## 这组文档不做什么

- 不重写 GitHub / Notion 的任务和文档 UI
- 不自建完整任务录入和看板系统
- 不把 FounderOS 做成新的知识库或聊天工具
- 不要求先做完 standalone FPMS 再验证价值

## 文件说明

- `README.md`
  这组文档的入口与优先级说明
- `PRODUCT-BASELINE.md`
  产品边界、问题定义、能力归属、非目标
- `ARCHITECTURE.md`
  外部工具为事实源时的系统设计
- `ROADMAP.md`
  外部优先路线下的分阶段交付计划

## 文档优先级

1. 本文件夹中的文档
2. `/2-requirements/PRD-cognitive-engine.md`
3. 其他历史文档（仅供参考）

## 一句话定义

FounderOS 不是新的项目管理工具。

FounderOS 是架在外部工具之上的认知层与控制层：它连接事实、压缩历史、组装上下文、分配注意力，并帮助 Founder 与 Agent 做出更好的决策。
