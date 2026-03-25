# FocalPoint Work Mode 使用指南

## 一句话

Work Mode = 开始任务前先准备，重大决策先审查。

---

## 什么时候用

| 场景 | 用什么 |
|------|--------|
| 开始做一个任务 | `activate_workbench` |
| 新功能/重大变更 | 三省 Protocol |
| 记录决策/风险 | `append_log` + category |
| 保存设计文档 | `set_knowledge` |
| 找相关信息 | `search_nodes` + query |

---

## 1. 工作台（Workbench）

### 干什么用

AI 开始任务前，一次调用准备好所有上下文：目标、知识背景、当前状态、子任务列表、角色 prompt。

### 怎么用

直接告诉 AI：

```
"帮我做支付系统的 API 开发"
```

AI 会自动：
1. 调 `activate_workbench(node_id, role="execution")`
2. 读取返回的 role_prompt，进入执行者角色
3. 读取 knowledge 文档，理解设计背景
4. 按 subtasks 顺序执行

### 三个角色

| 角色 | 对应 | 什么时候用 | 看到什么 |
|------|------|-----------|---------|
| **strategy** | 中书省 | 决定做不做、做什么 | 决策记录 + 用户反馈 |
| **review** | 门下省 | 检查风险、翻历史 | 风险标注 + 进度 |
| **execution** | 尚书省 | 写代码、执行 | 技术细节 + 进度 |

切换角色：

```
"用 strategy 视角看一下这个项目"
→ activate_workbench(node_id, role="strategy")

"用 review 视角审查一下风险"
→ activate_workbench(node_id, role="review")
```

---

## 2. 三省 Protocol

### 干什么用

重大决策（新功能、架构变更、技术选型）经过三方审查才执行，避免拍脑袋。

### 流程

```
你提出需求
    ↓
AI 用 strategy 角色分析 → 产出需求文档
    ↓
AI 调 sansei_review 提交审查
    ├── 门下省：翻历史、查风险 → 通过/打回
    └── 尚书省：评估可行性 → 通过/打回
    ↓
两个都通过 → 开始执行
任一打回 → 回去修改
    ↓
打回超过 3 次 → 通知你介入
```

### 怎么触发

```
"这个功能走三省审查"
"帮我走一下三省 protocol"
"提交审查"
```

AI 会：
1. 用 strategy 角色写需求
2. 用 review 角色检查风险
3. 用 execution 角色评估可行性
4. 调 `sansei_review` 记录审查结果
5. 全部通过后开始执行

### 不需要走三省的

- 日常任务（改个 bug、加个日志）
- 状态更新
- 记录信息

---

## 3. 知识文档

### 干什么用

把设计结论存下来，子任务自动继承，不用每次重新解释。

### 怎么用

```
"把这个架构设计存到项目里"
→ set_knowledge(project_id, "architecture", "## 架构\n...")

"把需求文档存一下"
→ set_knowledge(project_id, "requirements", "## 需求\n...")
```

子任务会自动继承父节点的知识文档。比如：

```
project "支付系统"
├── overview.md        ← 项目概述
├── architecture.md    ← 架构设计
│
└── task "实现 API"
    → 自动继承 overview.md 和 architecture.md
    → AI 开始做这个 task 时，自动知道项目背景
```

### 三种基础类型

| 类型 | 放什么 |
|------|--------|
| `overview` | 是什么、为什么做 |
| `requirements` | 具体要做什么 |
| `architecture` | 怎么做的设计 |

也可以自定义：`set_knowledge(id, "competitive_analysis", "...")`

---

## 4. 分类日志

### 怎么用

```
"记一下我们决定用 Stripe"
→ append_log(node_id, "选了 Stripe，API 好，费率低", category="decision")

"标记一下这个风险"
→ append_log(node_id, "注意 PCI 合规要求", category="risk")
```

### 六种分类

| category | 用途 | 例子 |
|----------|------|------|
| `decision` | 决策记录 | "选了 Stripe" |
| `feedback` | 用户/市场反馈 | "80% 用户要信用卡支付" |
| `risk` | 风险/教训 | "上次这样做延期两周" |
| `technical` | 技术细节 | "用了 stripe.PaymentIntent" |
| `progress` | 进度更新 | "API 完成，待测试" |
| `general` | 默认 | 未分类的 log |

分类的作用：不同角色看到不同分类的日志。Strategy 看 decision + feedback，Execution 看 technical + progress。

---

## 5. 全文搜索

```
"找找之前关于缓存的决策"
→ search_nodes(query="缓存 决策")

"有没有关于支付的风险记录"
→ search_nodes(query="支付 风险")
```

搜索范围：节点标题 + 叙事内容 + 知识文档。

---

## 日常使用模板

### 开始新项目

```
你: "建一个项目跟踪电商改版，拆 3 个任务"
AI: create_node + 3 个子任务
你: "把产品需求存一下"
AI: set_knowledge(project_id, "requirements", ...)
```

### 每天工作

```
你: "继续做昨天的任务"
AI: bootstrap → activate_workbench → 继续上次的进度
你: "这个做完了"
AI: update_status → done, append_log(category="progress")
```

### 做决策

```
你: "我们要选支付方案，走三省"
AI: strategy 分析 → review 检查 → execution 评估 → sansei_review
你: "通过了就开始做"
AI: activate_workbench(role="execution") → 执行
```

### 结束对话

```
你: "今天先到这"
AI: append_log 记录进度 + set_knowledge 保存结论
    下次对话 bootstrap 时自动恢复
```
