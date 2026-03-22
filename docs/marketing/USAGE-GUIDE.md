# FocalPoint 使用指南

---

## 快速开始

### 安装

```bash
pip install focalpoint
```

### 接入 Claude Desktop

编辑 `~/Library/Application Support/Claude/claude_desktop_config.json`：

```json
{
  "mcpServers": {
    "fpms": {
      "command": "focalpoint"
    }
  }
}
```

重启 Claude Desktop。开始对话时，AI 会自动调用 `bootstrap` 加载记忆。

### 接入 OpenClaw

搜索 `focalpoint-memory`，一键安装。

---

## 基本概念

### 节点（Node）

FocalPoint 里所有东西都是节点。节点有层级：

```
goal        → 大目标（"产品上线"）
  project   → 项目（"支付系统"）
    milestone → 里程碑（"Stripe 集成"）
      task  → 具体任务（"实现 API"）
```

每个节点有：
- **状态**：inbox → active → waiting → done / dropped
- **叙事**：时间线式的操作日志
- **知识文档**：设计文档、需求文档等（可选）
- **依赖**：这个任务依赖哪些其他任务

### 状态生命周期

```
inbox ──→ active ──→ done
  │         │         ↑
  │         ↓         │
  │      waiting ─────┘
  │         │
  ↓         ↓
dropped ← ─┘
```

- `inbox`：还没开始
- `active`：正在做
- `waiting`：等别的事情
- `done`：完成
- `dropped`：放弃

---

## 日常使用

### 开始新对话

每次打开新对话，说一句就行：

```
"bootstrap"
```

AI 会加载全局状态：项目树、告警、当前焦点。你不需要提醒它"我们上次做到哪了"。

### 创建项目

```
"建一个项目跟踪支付系统开发，拆成 3 个任务：设计 API、实现集成、写测试"
```

AI 会：
1. 创建 project 节点 "支付系统"
2. 创建 3 个 task 子节点
3. 自动设置父子关系

### 跟踪进度

```
"API 设计完了"
→ AI 调用 update_status(node_id, "done")

"集成任务开始做了"
→ AI 调用 update_status(node_id, "active")

"现在卡在等第三方审核"
→ AI 调用 update_status(node_id, "waiting")
```

### 记录决策

```
"记一下：我们选了 Stripe，因为 API 更好、费率更低"
→ AI 调用 append_log(node_id, content, category="decision")
```

两周后：
```
"我们为什么选 Stripe？"
→ AI 搜索决策记录，找到当时的理由
```

### 检查状态

```
"项目什么情况？"
→ AI 调用 heartbeat，扫描全局状态
→ 返回：哪些任务 blocked、哪些 stale、哪些 at-risk
```

---

## 高级功能

### 知识文档

把设计结论存下来，不用每次对话重新解释：

```
"把这个架构设计存到项目里"
```

三种基础类型：

| 类型 | 放什么 |
|------|--------|
| overview | 是什么、为什么做 |
| requirements | 具体要做什么 |
| architecture | 怎么做的设计 |

子任务**自动继承**父节点的知识文档：

```
project "支付系统"
├── overview.md       ← 项目背景
├── architecture.md   ← 架构设计
│
└── task "实现 API"
    → 自动看到项目的 overview 和 architecture
    → 不需要你再解释一遍
```

也可以自定义类型：

```
"把竞品分析存到项目知识里，类型叫 competitive_analysis"
```

### 工作台（Workbench）

AI 开始做任务前，一次调用准备好所有上下文：

```
"帮我做支付 API 开发"
```

AI 自动调用 `activate_workbench`，拿到：
- **goal** — 任务目标
- **knowledge** — 相关知识文档（含继承）
- **context** — 当前状态、邻居节点、告警
- **subtasks** — 子任务列表（按依赖排序）
- **suggested_next** — 建议先做哪个
- **role_prompt** — 角色思维指南

### 三个角色

同一个项目，不同角色看到不同视角：

**中书省（Strategy）** — 决策者视角
```
"用 strategy 视角看一下这个项目"
→ 看到：决策记录、用户反馈、投入产出比
→ 思考：该不该做？优先级？范围多大？
```

**门下省（Review）** — 审查者视角
```
"用 review 视角审查一下风险"
→ 看到：风险标注、进度、历史教训
→ 思考：会不会踩坑？有什么不可逆操作？
```

**尚书省（Execution）** — 执行者视角
```
"帮我做这个任务"
→ 看到：技术细节、进度、代码上下文
→ 思考：怎么做最优？验收标准是什么？
```

### 三省 Protocol

重大决策（新功能、架构变更、技术选型）走三省审查：

```
你："这个功能走三省审查"

Step 1: AI 用 Strategy 角色分析
→ 产出需求文档，判断值不值得做

Step 2: AI 提交审查（门下省 + 尚书省并行）
├── 门下省：翻历史、查风险 → 通过/打回
└── 尚书省：评估可行性 → 通过/打回

Step 3: 两个都通过 → 开始执行
        任一打回 → 回去修改
        打回超 3 次 → 通知你介入
```

不需要走三省的：日常 bug 修复、状态更新、记录信息。

### 全文搜索

搜索范围覆盖标题、叙事和知识文档：

```
"找找之前关于缓存的决策"
→ search_nodes(query="缓存 决策")

"有没有关于支付的风险记录"
→ search_nodes(query="支付 风险")
```

### 依赖管理

任务之间可以设置依赖：

```
"测试任务依赖 API 任务"
→ add_dependency(source=测试, target=API)
```

效果：
- API 没完成时，测试任务标记为 **blocked**
- heartbeat 扫描时会告警
- workbench 按依赖排序子任务

---

## 六种日志分类

记录信息时带上分类，方便后续按角色过滤：

```
"记一下我们决定用 Stripe"
→ category="decision"

"80% 用户要信用卡支付"
→ category="feedback"

"上次这样做延期两周"
→ category="risk"

"用了 stripe.PaymentIntent.create()"
→ category="technical"

"API 完成，待测试"
→ category="progress"

"日常笔记"
→ category="general"（默认）
```

---

## 使用模板

### 模板 1：项目启动

```
你："建一个项目跟踪电商改版"
AI：创建 project 节点

你："拆成 3 个任务：重构商品页、优化结算流程、上线灰度测试"
AI：创建 3 个 task，设置依赖关系

你："把产品需求存一下"
AI：set_knowledge(project_id, "requirements", 需求内容)

你："把架构设计也存一下"
AI：set_knowledge(project_id, "architecture", 架构内容)
```

### 模板 2：每天工作

```
你："继续做昨天的任务"
AI：bootstrap → 加载状态 → activate_workbench → 准备上下文
   "上次做到商品页重构，API 已完成，前端待开发"

你："前端做完了"
AI：update_status → done
    append_log(category="progress", "前端重构完成")

你："开始做结算流程"
AI：activate_workbench(结算任务, role="execution")
    → 读取知识文档 → 按子任务顺序执行
```

### 模板 3：做决策

```
你："我们要选支付方案"
AI：activate_workbench(project_id, role="strategy")
    → 分析各方案优劣

你："走三省审查"
AI：
    Strategy → "建议用 Stripe，理由：API 好、费率低、文档全"
    Review → "通过。注意 PCI 合规要求，建议不自己存卡号"
    Execution → "通过。预计 2 天集成，用 PaymentIntent API"
    → sansei_review 记录：通过

你："开始做"
AI：activate_workbench(role="execution") → 执行
```

### 模板 4：结束对话

```
你："今天先到这"
AI：append_log(category="progress", "今日进度：完成了 X、Y、Z")
    set_knowledge("overview", 更新后的项目概述)
    → 下次对话 bootstrap 时自动恢复所有状态
```

---

## 常见问题

**Q: 数据存在哪？**
本地。SQLite 文件 + Markdown 文件。不上传任何云服务。

**Q: 支持哪些 AI？**
任何支持 MCP 协议的 AI。目前验证过：Claude Desktop、OpenClaw。

**Q: 需要联网吗？**
不需要。FocalPoint 完全本地运行。GitHub/Notion 同步是可选功能。

**Q: 节点太多了怎么办？**
完成的节点 7 天后自动归档，不影响活跃视图。标记 `is_persistent` 可以防止归档。

**Q: 和 Claude 内置记忆冲突吗？**
不冲突。Claude 内置记忆记偏好和事实，FocalPoint 管理项目和任务。互补的。

**Q: 能多人用吗？**
目前是单用户设计（本地 SQLite）。多 Agent 协作是 v0.4 规划。

---

## 23 个 MCP Tools 速查

### 写入
| 工具 | 功能 |
|------|------|
| `create_node` | 创建节点（project/task/goal/milestone） |
| `update_status` | 改状态（inbox/active/waiting/done/dropped） |
| `update_field` | 改字段（title/summary/why/deadline 等） |
| `attach_node` | 挂载到父节点 |
| `detach_node` | 从父节点脱离 |
| `add_dependency` | 添加依赖关系 |
| `remove_dependency` | 移除依赖关系 |
| `append_log` | 追加日志（带 category） |
| `unarchive` | 恢复归档节点 |
| `set_persistent` | 设置归档豁免 |
| `set_knowledge` | 写入知识文档 |

### 读取
| 工具 | 功能 |
|------|------|
| `get_node` | 查询节点详情 |
| `search_nodes` | 搜索节点（过滤 + 全文搜索） |
| `get_knowledge` | 读取知识文档（含继承） |
| `delete_knowledge` | 删除知识文档 |
| `get_assembly_trace` | 查看上下文组装轨迹 |
| `expand_context` | 展开节点上下文 |

### 认知
| 工具 | 功能 |
|------|------|
| `bootstrap` | 冷启动加载全局状态 |
| `heartbeat` | 扫描风险 + 告警 |
| `activate_workbench` | 准备工作上下文 |
| `get_context_bundle` | 获取角色化上下文包 |

### 审查
| 工具 | 功能 |
|------|------|
| `sansei_review` | 三省 Protocol 审查 |

### 运行时
| 工具 | 功能 |
|------|------|
| `shift_focus` | 切换焦点节点 |
