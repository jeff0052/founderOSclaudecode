# PRD: Work Mode — 知识层 + 工作台 + 三省 Protocol

> FocalPoint v0.3 核心功能需求
> 设计思路演进详见 `docs/milestones/2026-03-22-focalpoint-and-work-mode.md`

## 一句话总结

给 AI agent 一个工作台：开始任务前自动准备好目标、知识背景和执行计划。用三省制度保证需求经过决策、经验审查和工程评审后才执行。

---

## 核心设计原则

1. **记忆就是记忆，没有角度。** 三个角色看同样的数据，差异在思维方式，不在数据过滤。
2. **工作台无状态。** 一次函数调用，不是持久对象。拆分成一个 context 能闭环的最小单元。
3. **注意力精度优先。** 一个角色只关注一件事，不混合职责。
4. **narrative 记过程，knowledge 记结论。** 两个都存，各有用途。

---

## 一、知识文档层（Knowledge Layer）

### 是什么

每个节点可挂载 Markdown 知识文档，描述工作项的背景、设计和蓝图。

### 存储

```
data/knowledge/
└── {node_id}/
    ├── overview.md        → 是什么、为什么做
    ├── requirements.md    → 具体要做什么
    ├── architecture.md    → 怎么做的设计
    └── {自定义名}.md      → 可扩展，任意命名
```

### 哪些节点需要

| 节点类型 | 需要知识文档 |
|---------|------------|
| goal | 是 |
| project | 是 |
| milestone | 可选（大 milestone 可能有自己的设计文档） |
| task | 不需要（summary + narrative 够了） |

### 继承机制

子节点没有的知识文档，沿 parent_id 往上找。自己有的覆盖父节点的。

```
project "FocalPoint"
├── overview.md              ← 项目概述
├── requirements.md          ← 项目需求
├── architecture.md          ← 项目架构
│
├── milestone "Work Mode"
│   ├── requirements.md      ← 覆盖：Work Mode 的具体需求
│   └── architecture.md      ← 覆盖：工作台的设计
│                               overview 继承自项目
│
└── task "实现 knowledge.py"
    → 自己没有 knowledge
    → 往上找 milestone → requirements.md ✅
    → 再往上找 project → overview.md ✅
```

### API

```python
# 写入
engine.set_knowledge(node_id, doc_type="overview", content="...")
engine.set_knowledge(node_id, doc_type="competitive_analysis", content="...")  # 自定义类型

# 读取（自动继承）
docs = engine.get_knowledge(node_id)
# → {"overview": "...", "requirements": "...", "architecture": "..."}

# 读取特定类型
overview = engine.get_knowledge(node_id, doc_type="overview")

# 删除
engine.delete_knowledge(node_id, doc_type="overview")
```

---

## 二、工作台（Workbench）

### 是什么

AI 开始任务前的上下文准备。一次函数调用，返回所有需要的信息。无状态。

### API

```python
workbench = engine.activate_workbench(node_id, role="execution")

workbench = {
    "goal": "...",              # why + summary
    "knowledge": {              # 知识文档（继承解析后）
        "overview": "...",
        "requirements": "...",
        "architecture": "...",
    },
    "context_bundle": {...},    # Context Bundle（L0/L1/L2）
    "subtasks": [...],          # 子任务（按依赖排序）
    "suggested_next": "...",    # 建议先做哪个
    "role_prompt": "...",       # 角色 prompt
}
```

### 工作台大小

工作台 = 一个 context 下能闭环的最小单元。大小取决于任务本身，不是固定值。任务太大就拆解，拆到一次对话能做完为止。

### 工作流

```
1. activate_workbench(node_id, role)  → 返回工作台
2. AI 读取 role_prompt → 进入角色
3. AI 读取 knowledge → 理解背景
4. AI 读取 context_bundle → 了解当前状态
5. AI 读取 subtasks → 知道该做什么
6. 执行
7. 完成后 → update_status("done")
8. 决策 → 同时写 append_log（过程）+ set_knowledge（结论）
```

---

## 三、三省 Protocol

### 角色定义

```
中书省（Maker）     → 需求决策：该不该做？做什么？
门下省（Reviewer）  → 经验教训：会不会踩坑？历史上出过什么事？
尚书省（Engineer）  → 工程评审：做得了吗？怎么做最优？+ 执行
```

各管一件事，不混合。保持注意力精度。

### 流转 Protocol

```
中书省产出需求文档
     ↓
门下省 + 尚书省 并行审查
├── 门下省：翻历史教训、检查风险 → 通过/打回
└── 尚书省：评估工程可行性、提出优化 → 通过/打回
     ↓
两个都通过 → 尚书省产出验收文档 → 开始执行
任一打回 → 标注理由 → 回中书省修改
     ↓
打回循环 ≤ 3 次
超过 3 次 → 高危，暂停，通知人类介入
```

### 角色 Prompt

每个角色有独立的 prompt 文件：

```
fpms/prompts/
├── strategy.md    ← 中书省：关注用户痛点、投入产出比、优先级
├── review.md      ← 门下省：关注历史教训、风险项、不可逆操作
└── execution.md   ← 尚书省：关注工程可行性、成本、方案优化、验收
```

**数据不过滤。** 三个角色看同样的数据，prompt 决定思考方式。

### 审查产出

| 角色 | 输入 | 输出 |
|------|------|------|
| 中书省 | 用户反馈 / 市场信号 | 需求文档（存入 knowledge） |
| 门下省 | 需求文档 + 历史教训 | 通过/打回 + 风险标注 |
| 尚书省 | 需求文档 + 工程现状 | 通过/打回 + 验收文档 + 执行 |

---

## 四、Narrative Category

### 目的

给 log 打标签，方便后续按类型查找（不影响角色视角，角色看到所有 log）。

### 改动

`append_log` 新增 `category` 参数：

```python
append_log(node_id, content="选了 Stripe", category="decision")
```

### 枚举值

| category | 含义 | 例子 |
|----------|------|------|
| `decision` | 决策记录 | "选了 Stripe" |
| `feedback` | 用户/市场反馈 | "80% 用户要信用卡支付" |
| `risk` | 风险/教训 | "上次这样做延期两周" |
| `technical` | 技术细节 | "用了 stripe.PaymentIntent" |
| `progress` | 进度更新 | "API 完成，待测试" |
| `general` | 默认 | 未分类的 log |

---

## 五、全文搜索

### 目的

替代"软关联"。不预建节点间的弱关系，需要时搜索找到相关内容。

### 改动

```python
# 现在
search_nodes(filters={"status": "active"})  # 只能按字段

# 加上
search_nodes(query="缓存 决策")  # 搜标题 + narrative + knowledge
```

使用 SQLite FTS5，不需要外部依赖。

---

## 需要改什么

| 改动 | 新增/修改 | 影响范围 |
|------|----------|---------|
| `knowledge.py` | 新增模块 | 知识文档读写 + 继承 |
| `workbench.py` | 新增模块 | 工作台组装 |
| `narrative.py` | 修改 | append_log 加 category |
| `store.py` | 修改 | 加 FTS5 全文搜索 |
| `mcp_server.py` | 修改 | 新增 3 tools + 更新 2 tools |
| `fpms/prompts/*.md` | 新增文件 | 三个角色 prompt |

## 不改什么

- Node 模型 — 不变
- SQLite schema（节点表）— 不变
- 状态机 — 不变
- Heartbeat — 不变
- Context Bundle（bundle.py）— 不变
- Adapter（GitHub/Notion）— 不变
- 现有 15 个 MCP tools — 不变

---

## 验收标准

### 知识文档
1. set_knowledge 写入成功
2. get_knowledge 能继承父节点的知识
3. 子节点有自己的文档时覆盖父节点的
4. 自定义类型名能正常存取

### 工作台
5. activate_workbench 返回完整结构（goal/knowledge/context/subtasks/role_prompt）
6. subtasks 按依赖排序
7. suggested_next 返回第一个可执行的子任务
8. role_prompt 包含对应角色的完整内容

### 三省 Protocol
9. 打回带理由
10. 打回超过 3 次标记高危
11. 两个审查者都通过后才能执行

### Narrative Category
12. category 存储和查询正常
13. 默认 "general"
14. 无效 category 拒绝

### 全文搜索
15. 能搜到标题中的关键词
16. 能搜到 narrative 中的关键词
17. 能搜到 knowledge 中的关键词

### 向后兼容
18. 不调用新功能时，行为和 v0.2 完全一致
19. 现有 584 tests 全绿

---

## 工作量估算

| 改动 | 预估 |
|------|------|
| knowledge.py（读写 + 继承） | 2 小时 |
| workbench.py（工作台组装） | 2-3 小时 |
| narrative 加 category | 1 小时 |
| 全文搜索（FTS5） | 2 小时 |
| 3 个新 MCP tools | 1 小时 |
| 角色 prompt 文件 | 1 小时 |
| 三省 protocol 逻辑 | 2 小时 |
| 测试 | 3 小时 |
| **总计** | **1.5 - 2 天** |
