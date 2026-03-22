# FocalPoint v0.3.4 — 稳定化、发布与真实验证

> 2026-03-23 | 从开发完成到产品上线的最后一公里

---

## 这次做了什么

v0.3 的代码昨天写完了。今天做的是：**把它变成一个真正能用的产品。**

---

## 三个阶段

### 阶段一：修 Gap

用验收清单对照实际实现，发现两个 gap：

1. **FTS 搜索是假的** — `append_log` 和 `set_knowledge` 写完内容后没有触发索引更新。全文搜索只能搜到标题，搜不到 narrative 和 knowledge 内容。更糟糕的是，`index_narrative` 每次重建时会把 `knowledge_text` 覆盖为空——两个索引方法互相踩。
2. **`delete_knowledge` 没暴露** — 函数写了，MCP tool 没加。

修复时 reviewer 又发现了 3 个防御性问题：LIKE 查询没转义元字符、FTS5 查询没清理特殊字符、异常被静默吞掉没日志。一并修了。

### 阶段二：真实环境测试

在 OpenClaw + Telegram 上装了 focalpoint 测试。发现 `shift_focus` 是坏的：

**表面症状：** 调 shift_focus 返回成功，但 L1/L2 显示 "No focus node selected"。

**根因：** 代码里有两条不同的状态管理路径。`shift_focus` MCP tool 通过 `execute_tool` 走 `ToolHandler`，写 `session_state`。但 `get_context_bundle` 从 `FocusScheduler` 读状态。两个系统各管各的，没有打通。

**修复过程经历了三轮 review：**
- 第一轮：修了 MCP 层但没修 ToolHandler 层
- 第二轮：修了 ToolHandler 但 FocusScheduler 注入顺序错了、缺类型注解、MCP 层直接访问私有属性
- 第三轮：加了 setter 方法、公共 API、两个新测试。reviewer 发现 narrative 测试残留被 commit。清理后通过。

这个 bug 说明了一个架构问题：**同一个操作有多条代码路径时，状态不一致是必然的。** MCP tool → execute_tool → ToolHandler 是一条路径，MCP tool → engine 直接方法是另一条。shift_focus 的修复是打补丁，根本解决需要统一路由——但会动到架构，现阶段不值得。

### 阶段三：产品化

把一个"能跑的代码"变成一个"能发布的产品"：

- **README 全面重写** — 还叫 FPMS、`pip install fpms`、18 tools。全部更新为 FocalPoint、23 tools、竞品对比、Work Mode 说明
- **Marketing 文档** — 产品介绍（中文，带竞品分析）+ 使用指南（中英文）
- **ClawHub SKILL.md** — 从 34 行扩展到 280 行，全英文，完整竞品对比表、架构说明、23 tools 分类速查
- **CLAUDE.md 更新** — 从 177 行扩展到 240 行，补齐 v0.3 所有功能的技术说明
- **版本统一** — PyPI/ClawHub/GitHub 全部对齐到 0.3.4
- **GitHub 公开** — 从 private 改为 public
- **PyPI 自动发布** — 配置了 `.pypirc`，以后不用手动输 token

---

## 竞品调研

做了完整的市场调研，结论：

**FocalPoint 占据了一个空白位置。** 不是记忆层（Mem0/Zep），不是编排框架（LangGraph/CrewAI），不是平台功能（Claude/OpenAI），不是配置工具（openclaw-pm）。是唯一一个把任务管理 + 主动告警 + 知识继承 + 角色化上下文 + 审查流程做成统一 MCP 包的产品。

市场规模：Agentic AI 市场 2025 年 62.7 亿美元，2030 年预计 284.5 亿美元（CAGR 35%）。

OpenViking（字节跳动，15K stars）在自动记忆提取上做得比我们好——会话结束时自动分析对话内容存入记忆，不需要用户说"记一下"。这个能力我们还没有。

---

## 白皮书对照

对比了白皮书（FounderOS 七大模块）和当前产品：

**已实现 ~40%：** State（节点状态）、Missions（任务执行）、Stability（心跳+告警+三省）。

**未实现 ~60%：** Signals（外部信号感知）、Interpretation（信号解释）、Office 体系（6 个 Agent 角色）、Constitution（公司宪法）、Kill Switch（熔断）、文明等级、UI 驾驶舱。

**方向偏移：** 白皮书描述的是"一人公司操作系统"（支付业务专用），当前产品是"通用 AI 认知引擎"。这个偏移是有意的——先做通用工具，验证后再垂直化。

---

## 决策记录

| 决策 | 选择 | 理由 |
|------|------|------|
| Token efficiency 作为核心指标 | 记录但不立即优化 | 需要真实项目数据才能量化 |
| execute_tool 路由统一 | 延后 | 会动架构，需要注入 SpineEngine 到 ToolHandler，有循环依赖风险 |
| 命名统一（fpms vs focalpoint） | 延后 | 改动大、风险高、没有用户反馈 |
| GitHub 公开 | 改为 public | 赛道主流是开源，BSL 已保护商用 |
| Interview 流程 | 设计完成，待实现 | 5 步：Context 自动搜 → Open → Specific → Edge → Output |
| 自动记忆提取 | 记录为未来方向 | 借鉴 OpenViking，等真实项目验证需求 |

---

## 数字

| 指标 | 昨天（v0.3.0） | 今天（v0.3.4） |
|------|---------------|---------------|
| Tests | 657 | 667 |
| MCP tools | 21 | 23 |
| Bug fixes | 0 | 5（FTS 索引×3 + shift_focus + 查询清理） |
| 文档文件 | ~15 | ~22 |
| PyPI 版本 | 0.3.0 | 0.3.4 |
| GitHub | private | **public** |
| ClawHub SKILL.md | 34 行 | 280 行 |

---

## 下一步

不再加功能。拿 v0.3.4 跑一个真实项目（Personal Landing Page），验证：

1. Workbench 准备的上下文够不够用
2. 角色过滤合不合理
3. 三省流程实际跑起来顺不顺
4. Token efficiency 量化数据
5. AI 是否足够主动（还是每次都要用户提醒"记一下"）

用了才知道缺什么。

---

*从"代码写完"到"产品能用"，中间差的不是功能，是打磨：修 bug、写文档、统一版本、公开仓库、配自动发布。这些事不性感，但决定了一个项目是"demo"还是"产品"。*
