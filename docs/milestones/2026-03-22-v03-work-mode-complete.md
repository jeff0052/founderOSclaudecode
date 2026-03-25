# FocalPoint v0.3 — Work Mode Milestone 总结

> 2026-03-22 | 从设计到交付，一个 session 完成

---

## 一句话

给 AI 一个工作台：开始任务前准备好目标、知识、计划，用三省制度保证决策质量。

---

## 做了什么

### 之前（v0.2）

FocalPoint 是一个记忆引擎。能记住节点、状态、依赖、叙事，能同步 GitHub 和 Notion。但 AI 拿到 context 后直接开干——没有准备阶段，没有角色分工，没有审查机制。

### 之后（v0.3）

FocalPoint 是一个 AI 认知操作系统。AI 开始任务前有准备阶段（workbench），不同角色看不同维度的信息（role filtering），决策经过三省审查才执行（sansei_review）。

### 具体交付

| 能力 | 实现 | 解决什么问题 |
|------|------|-------------|
| 知识文档层 | `knowledge.py` — CRUD + 父节点继承 | AI 缺少项目认知基底，只有执行日志没有设计文档 |
| 叙事分类 | `narrative.py` — 6 种 category | 所有 log 混在一起，无法按维度筛选 |
| 全文搜索 | `store.py` — SQLite FTS5 | 节点间没有软关联，需要时搜不到相关信息 |
| 角色过滤 | `bundle.py` — 按 role 过滤 narrative + 调整 token 预算 | 有限 token 里装了太多不相关的信息 |
| 工作台 | `__init__.py` — `activate_workbench()` | AI 没有"准备工作"的阶段，直接开干 |
| 三省 Protocol | `__init__.py` — `sansei_review()` | 没有审查机制，决策直接执行，踩坑后才发现 |
| 角色 prompts | `fpms/prompts/*.md` | 角色没有认知框架，不知道该关注什么 |
| MCP 工具 | `mcp_server.py` — 3 new + 3 updated | 新能力无法通过 MCP 暴露给 Claude Desktop |

---

## 关键数字

| 指标 | 数值 |
|------|------|
| 新增代码文件 | 5（knowledge.py, 3 prompts, fts schema） |
| 修改代码文件 | 7（narrative, models, store, bundle, tools, __init__, mcp_server） |
| 新增测试文件 | 5（test_knowledge, test_fts, test_workbench, test_sansei, narrative/tools additions） |
| 新增测试数 | 73 |
| 总测试数 | 657（全绿） |
| 回归测试 | 584 原有测试全部通过 |
| Git commits | 9 |
| MCP tools 总数 | 21（原 18 + 新 3） |

---

## 设计决策回顾

这些决策在设计阶段（同日早些时候）确认，开发中严格执行：

**1. 角色过滤数据，不只靠 prompt**

原则说"记忆没有角度"，但验收要求按 category 过滤。最终选择过滤——原因是 token 有限，装不相关的信息是浪费。strategy 角色不需要看 `stripe.PaymentIntent.create()`，execution 角色不需要看"80% 用户希望支持信用卡"。

**2. 工作台无状态**

`activate_workbench()` 是一次调用，不是持久对象。返回 goal + knowledge + context + subtasks + role_prompt + token_budget。用完即弃，下次调用重新组装。

**3. 软关联不做，靠搜索**

不预建节点间的弱关系。计算机的优势是精确检索，不是模拟神经网络。需要找"上次关于缓存的决策"时，FTS5 搜索就行。

**4. 三省并行审查**

中书省产出需求后，门下省（风险）和尚书省（工程）同时审。不串行，节省时间。两个都通过才执行。打回超 3 次通知人类——防止 AI 陷入死循环。

**5. narrative 记过程，knowledge 记结论**

"决定用 Stripe"两个地方都存：narrative 记"3月22日决定用 Stripe，原因是..."（过程），knowledge 记"支付方案：Stripe"（当前状态）。一个给审查者看历史，一个给执行者看现状。

---

## 开发过程

### 工具链

- **writing-plans skill** — 写 9-task 实现计划
- **plan-document-reviewer** — 发现 3 个 critical bug（FTS5 contentless 表、索引重建覆盖、旧格式兼容），修复后通过
- **subagent-driven-development** — 每个 task 派一个 sonnet subagent，TDD 执行
- **verification-before-completion** — 最终验收，657 tests + 验收场景手动跑通

### 执行节奏

```
设计讨论 + PRD + 验收清单     → 已在早些时候完成
加载需求 + 读代码             → 10 分钟
写计划 + reviewer 修复        → 15 分钟
Task 1-4（无依赖，顺序执行）  → 4 个 subagent
Task 5-8（有依赖，顺序执行）  → 4 个 subagent
验证 + 文档 + 版本号          → 5 分钟
```

### 遇到的问题

1. **FTS5 contentless 表不能 DELETE** — reviewer 发现，改为普通 FTS5 表
2. **`_rebuild_fts_titles` 每次搜索全量重建** — 改为增量索引（`_ensure_fts_indexed` 只补缺失的）
3. **CJK 分词** — unicode61 tokenizer 不支持无空格中文子串匹配。subagent 改为空格分词测试。生产环境可换 ICU tokenizer
4. **narrative header 格式变更** — 从 `[event_type]` 变为 `[event_type] [category]`，需要搜索修复所有现有测试断言

---

## 下一步

v0.3 完成了第二层（知识 + 工作台）。FocalPoint 三层架构：

```
第一层：记忆引擎          ✅ v0.2 已完成
第二层：知识层 + 工作台    ✅ v0.3 刚完成 ← 你在这里
第三层：多 Agent 协作      📥 mile-0b12 待开始
```

待做：
- [ ] 发布 v0.3.0 到 PyPI
- [ ] 更新 ClawHub skill
- [ ] 在实际项目中验证 workbench + 三省 Protocol 的效果
- [ ] 设计 v0.4：多 Agent 任务分配和协调
