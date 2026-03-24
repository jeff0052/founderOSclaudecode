# FocalPoint v0.4.0 — Analytics Dashboard + Interview 调研

> 2026-03-24 | 从"能用"到"能衡量" + 下一步方向调研

---

## 一句话

给 FocalPoint 加了健康检查和可视化面板，让用户（也包括自己）能看到系统是否被用好了。同时调研了 gstack 的 Interview 模式，为三省的输入质量问题找到了解决方案。

---

## 做了什么

### Analytics Dashboard

之前的 FocalPoint 跑在本地，没有任何监测能力。用户不知道自己是否在"正确使用"这个系统。

做了一个分析工具：

**健康评分（0-100）**，5 个维度：
- Node 管理 — 有没有积压、是否活跃
- 记录习惯 — log 有没有打 category（decision/risk/technical...）
- 知识沉淀 — project/goal 有没有 knowledge 文档
- Token 效率 — context 组装是否超预算、是否被裁剪
- 工具利用 — 是否用了 workbench、三省、搜索等高级功能

**HTML Dashboard** — 一个自包含的 HTML 文件，浏览器打开就能看：
- 环形评分图 + 5 维度卡片
- 快速统计（节点数、tool 调用次数、平均 token、日志条数...）
- 工具使用柱状图、节点状态分布、日志分类分布、每日活动图
- **节点浏览器** — 树形展示所有节点，点击查看叙事历史和知识文档

**三种使用方式：**
- CLI: `focalpoint-stats --html`（生成 HTML 面板）
- CLI: `focalpoint-stats`（终端文本报告）
- MCP: `get_stats`（Desktop 里调）

**架构对齐：** analytics 通过 SpineEngine 获取所有路径，不自己硬编码。CLI 和 MCP tool 读同一份数据。

### 真实数据首次分析

用 analytics 跑了真实 FPMS 数据（48 节点，通过 Desktop MCP 积累），首次得到量化评分：

```
Health Score: 64/100 (Good)

✅ Node Management: 9/10
❌ Recording Habits: 4/10 — 89% logs 没有 category
⚠️ Knowledge Docs: 7/10
✅ Token Efficiency: 10/10
❌ Tool Utilization: 2/10 — workbench/三省/搜索从未使用
```

发现了两个核心问题：
1. AI 不主动给 log 打 category — 需要 Interview/自动提取
2. 高级工具没人用 — 需要更好的引导或自动触发

### gstack Interview 调研

调研了 Garry Tan（YC CEO）的 gstack `/office-hours` skill：

**6 个 Forcing Questions（Startup Mode）：**

| # | 名称 | 核心问 |
|---|------|--------|
| Q1 | Demand Reality | 最强证据？谁会因为你消失而真正难受？ |
| Q2 | Status Quo | 用户现在怎么解决？成本多少？ |
| Q3 | Desperate Specificity | 具体到人名、职位、什么让他升职/被开除 |
| Q4 | Narrowest Wedge | 最小可付费版本，这周就能卖的 |
| Q5 | Observation & Surprise | 你看过用户真实使用吗？什么出乎意料？ |
| Q6 | Future-Fit | 3 年后世界变了，你更重要还是更不重要？ |

**关键设计原则：**
- 按产品阶段智能跳过问题
- 反谄媚——禁止说"interesting"，必须表态
- 逼两次——第一个答案是润色版，追问才是真实答案
- 逃生阀——不耐烦时最多再问 2 个

**和 FocalPoint 的结合点：**
- gstack 是无状态 skill（每次从零开始），FocalPoint 有记忆（跨 session 累积）
- Interview 结果存为 knowledge，三省的中书省可以直接引用
- 历史决策和教训在 FocalPoint 里有记录，门下省审查时自动检索

---

## 决策记录

| 决策 | 选择 | 理由 |
|------|------|------|
| Analytics 路径来源 | SpineEngine（不自己拼路径） | CLAUDE.md 设计原则：所有数据通过 SpineEngine 访问 |
| 健康评分不放 bootstrap | 不加 | 每次对话都算一遍浪费 token |
| 版本号跳到 0.4.0 | 跳 | 新增了独立功能模块（analytics），不是 patch |
| Interview 实现方式 | 先 prompt 层试效果 | 不确定具体问题模板，用了真实项目再优化 |
| 参考 gstack 但不复制 | 取精华 | gstack 无状态，我们有记忆，交互模式不同 |

---

## 数字

| 指标 | v0.3.4 | v0.4.0 |
|------|--------|--------|
| Tests | 667 | 690 |
| MCP tools | 23 | 24（+get_stats） |
| 新增文件 | — | fpms/analytics.py, tests/test_analytics.py |
| 修改文件 | — | mcp_server.py, pyproject.toml |
| Git commits | — | 3 |

---

## 下一步

两个方向明确了，但都需要真实项目数据才能做好：

1. **Interview 流程** — 参考 gstack 6 questions，在三省之前加需求澄清阶段
2. **AI 自动记录** — 参考 OpenViking 的自动提取，减少用户手动操作

**先用 v0.4.0 跑 Personal Landing Page 项目**，收集真实使用数据和 health score，再决定优化优先级。

---

*衡量比建设更难。功能做完了不代表用好了——64 分的健康评分说明工具做了很多，但用户（包括自己）还没学会怎么用。下一步不是加更多功能，是让现有功能被正确使用。*
