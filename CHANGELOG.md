# FounderOS 变更日志

*每次需求迭代后更新此文件。记录"改了什么 + 为什么改"。*

---

## 2026-03-23 — v0.3.4

### Bug 修复

| 问题 | 修复 |
|------|------|
| `shift_focus` 只写 session_state，不更新 FocusScheduler | `handle_shift_focus` 现在调用 `FocusScheduler.shift_focus()`，L1/L2 正常加载 |

### 改进

| 项 | 内容 |
|-----|------|
| `SpineEngine.shift_focus()` | 新增公共方法，MCP tool 不再直接访问私有属性 |
| `ToolHandler.set_focus_scheduler()` | 新增 setter，和 `set_adapter_registry()` 模式一致 |
| 类型注解 | `_focus_scheduler: Optional["FocusScheduler"]` |
| `.gitignore` | `fpms/narratives/` 目录不再跟踪（运行时数据） |

### 测试

- 新增 2 tests（FocusScheduler 路径 + archived 节点 ValueError）
- 总计 667 tests 全绿

### 发布

- PyPI: focalpoint 0.3.4
- ClawHub: focalpoint-memory 0.3.4
- 三平台版本统一

---

## 2026-03-22 — v0.3.1 Hotfix

### Bug 修复

| 问题 | 修复 |
|------|------|
| `index_narrative` 覆盖 `knowledge_text` 为空 | 保留已有 `knowledge_text`（与 `index_knowledge` 对称） |
| `append_log` 后 narrative 内容不可搜索 | `handle_append_log` 后自动调用 `index_narrative` |
| `set_knowledge` 后 knowledge 内容不可搜索 | MCP tool 后自动调用 `index_knowledge` |
| FTS5 查询含特殊字符时报错 | `_build_fts_query` 清理 `"*(){}[]:^~` 和保留词 |
| LIKE 查询含 `%` `_` 时多匹配 | 转义 LIKE 元字符 + `ESCAPE '\\'` |
| FTS 索引失败时静默无日志 | 3 处 `except` 改为 `logging.warning` |

### 新增

| 项 | 内容 |
|-----|------|
| `delete_knowledge` MCP tool | 删除知识文档 + 自动更新 FTS 索引（第 22 个 tool） |
| CJK 搜索 fallback | `_search_like_content` 对中文内容做 LIKE 回退搜索 |

### 文档

| 文档 | 内容 |
|------|------|
| `docs/marketing/PRODUCT-INTRO.md` | 产品介绍 + 竞品分析（Mem0/Zep/Letta/CrewAI/openclaw-pm） |
| `docs/marketing/USAGE-GUIDE.md` | 完整使用指南 + 23 tools 速查 |
| `docs/WORK-MODE-GUIDE.md` | Work Mode 使用方法（工作台 + 三省 + 知识 + 分类日志） |

### 测试

- 新增 8 tests（FTS 自动索引 3 + knowledge 索引 3 + delete_knowledge 2）
- 总计 665 tests 全绿

### 发布

- PyPI: focalpoint 0.3.1
- ClawHub: focalpoint-memory 0.3.1（23 tools）
- MCP Server instructions 加入 Work Mode Protocol 使用指南

---

## 2026-03-22 — v0.3 Work Mode 开发完成

### 新增模块

| 模块 | 位置 | 内容 |
|------|------|------|
| knowledge.py | fpms/spine/knowledge.py | 知识文档 CRUD + 父节点继承（set/get/delete/list） |
| 角色 prompts | fpms/prompts/{strategy,review,execution}.md | 三省角色的 system prompt |
| FTS5 索引 | fpms/spine/schema.py + store.py | SQLite FTS5 全文搜索（标题 + narrative + knowledge） |

### 修改模块

| 模块 | 变更 |
|------|------|
| narrative.py | `append_narrative` 新增 `category` 参数，header 格式变为 `## {ts} [{event_type}] [{category}]`；`read_narrative` 新增 `categories` 过滤参数 |
| models.py | 新增 `NARRATIVE_CATEGORIES` 常量（decision/feedback/risk/technical/progress/general） |
| tools.py | `handle_append_log` 校验并传递 category；`handle_search_nodes` 新增 `query` 参数路由到 FTS |
| bundle.py | `assemble()` 新增 `role` 参数；按角色过滤 narrative category；按角色分配 token 预算；execution 角色跳过 L0 |
| __init__.py | `get_context_bundle` 新增 `role` 参数；新增 `activate_workbench`（无状态工作台）、`sansei_review`（三省 Protocol）、`_sort_subtasks_by_deps`（拓扑排序）、`_load_role_prompt`；新增 `_knowledge_dir` 属性 |
| mcp_server.py | 更新 3 tools（append_log +category, get_context_bundle +role, search_nodes +query）；新增 3 tools（activate_workbench, set_knowledge, get_knowledge） |
| schema.py | 新增 `fts_index` FTS5 虚拟表 |
| store.py | 新增 `search_fts`、`_ensure_fts_indexed`、`index_narrative`、`index_knowledge`、`_search_like_fallback` |

### 角色化上下文过滤

| 角色 | 看到的 narrative categories | token 预算 | L0 |
|------|---------------------------|-----------|-----|
| strategy（中书省） | decision, feedback | 8,000 | 2,000 |
| review（门下省） | risk, progress | 8,000 | 1,000 |
| execution（尚书省） | technical, progress | 8,000 | 0（跳过） |
| all（默认） | 全部 | 10,000 | 自动 |

### 三省 Protocol

- `sansei_review(node_id, proposal, review_verdict, engineer_verdict)` — 门下省 + 尚书省并行审查
- 两者都通过才批准，任一打回记入 narrative（risk/technical category）
- 打回计数持久化在 session_state，超过 3 次 `escalate_to_human=True`

### 工作台 (activate_workbench)

一次调用返回完整工作上下文：
- `goal` — 节点标题
- `knowledge` — 继承解析后的知识文档
- `context` — 角色过滤后的 Context Bundle
- `subtasks` — 按依赖拓扑排序的子任务
- `suggested_next` — 第一个未完成的子任务
- `role_prompt` — 角色 system prompt
- `token_budget` — 当前角色的预算分配

### MCP Tools 变更

| 操作 | Tool | 变更 |
|------|------|------|
| 更新 | append_log | 新增 `category` 参数 |
| 更新 | get_context_bundle | 新增 `role` 参数 |
| 更新 | search_nodes | 新增 `query` 参数（FTS） |
| 新增 | activate_workbench | 工作台激活 |
| 新增 | set_knowledge | 写入知识文档 |
| 新增 | get_knowledge | 读取知识文档（含继承） |

### 测试

- 新增 73 tests（knowledge 16 + narrative category 12 + FTS 7 + bundle filtering 7 + workbench 10 + tools category 3 + 三省 9 + misc 9）
- 总计 657 tests 全绿
- 原有 584 tests 全部通过（向后兼容）

### 已知限制

- CJK 全文搜索需空格分词（unicode61 tokenizer 限制）
- 三省 Protocol 当前接受外部传入的 verdict，未内置 LLM 调用

---

## 2026-03-22 — 产品方向升级 + v0.3 Work Mode 设计

### 产品方向决策

**FocalPoint 从"记忆引擎"升级为"AI 认知操作系统"。**

- FocalPoint = 记忆 + 注意力管理 + 工作流编排
- 这就是 FounderOS 最初的愿景，从记忆引擎做起，现在加上认知层
- 详见 `1-vision/ADR-product-direction.md`

### v0.3 Work Mode 设计完成

经过深度讨论（记录在 `docs/milestones/2026-03-22-focalpoint-and-work-mode.md`），确定了 v0.3 的 5 个功能模块：

| 模块 | 说明 |
|------|------|
| 知识文档层（knowledge.py） | 节点挂载 MD 知识文档 + 子节点继承父节点 |
| 工作台（workbench.py） | 一次函数调用准备所有上下文，无状态 |
| 三省 Protocol | 中书（决策）+ 门下（经验教训）+ 尚书（工程评审+执行），并行审查 |
| Narrative category | append_log 加 category 标签（decision/feedback/risk/technical/progress/general） |
| 全文搜索 | SQLite FTS5，替代软关联 |

### 关键设计决策

1. **记忆没有角度** — 三个角色看同样的数据，差异在 role prompt 的思维方式
2. **工作台无状态** — 一次调用返回，不是持久对象
3. **知识文档可扩展** — 基础三种（overview/requirements/architecture）+ 自由命名
4. **narrative 记过程，knowledge 记结论** — 两个都存
5. **软关联不做** — 计算机的优势是精确检索，不是模拟神经网络
6. **三省保留** — 注意力精度优先，一个角色只关注一件事
7. **并行审查** — 门下+尚书同时审，不串行
8. **≤3 次打回** — 超过通知人类

### 新增文档

| 文件 | 内容 |
|------|------|
| `1-vision/ADR-product-direction.md` | 产品方向决策记录 |
| `2-requirements/PRD-work-mode.md` | v0.3 完整需求文档 |
| `4-implementation/NEXT-SESSION.md` | 下一个 session 的任务包 |
| `4-implementation/v03-acceptance.md` | v0.3 验收清单 |
| `docs/milestones/2026-03-22-focalpoint-and-work-mode.md` | 设计思路演进（完整讨论过程） |

### 其他更新

- ROADMAP 重写：从五阶段线性改为三层架构（记忆→知识+工作台→协作）
- OVERVIEW 更新：产品定位、演进阶段、公司看板
- v0.2.0 发布到 PyPI（含 Notion adapter + BSL license + 新 README）
- Heartbeat 频率从 15 分钟改为 30 分钟 + 事件驱动（SYSTEM-CONFIG）

---

## 2026-03-22 — M3 写回闭环 + M2 Notion 集成

### M3: Write-Back（FPMS → GitHub/Notion）

| 模块 | 变更 |
|------|------|
| base.py | 新增 `write_status()` 可选方法 |
| github_adapter.py | 实现 `write_status()`（close/reopen issue）、`write_comment()`、`_patch()`、`_post()`、`_reverse_map_status()` |
| notion_adapter.py | 实现 `write_status()`（更新页面 Status 属性）、`write_comment()`（追加 paragraph block）、`_patch()`、`_reverse_map_status()` |
| tools.py | `handle_update_status` 后自动触发 write-back，失败不阻塞（离线降级） |
| __init__.py | `set_adapter_registry` 同时注入 ToolHandler |

### M2: Notion 集成

| 模块 | 内容 |
|------|------|
| notion_adapter.py | NotionAdapter — sync_node（页面同步）、list_updates（数据库查询）、状态映射 |

### 真实 API 验证

- GitHub: 3 个 issue 同步成功（jeff0052/founderOSclaudecode）
- Notion: 3 个页面同步成功 + 写回状态 "In progress" + 写回评论 验证通过

### 测试

- 新增 29 tests（Notion 17 + write-back 12）
- 总计 596 tests 全绿

---

## 2026-03-22 — FocalPoint v0.1.0 发布

### 产品发布

| 渠道 | 地址 | 安装方式 |
|------|------|---------|
| PyPI | pypi.org/project/focalpoint | `pip install focalpoint` |
| ClawHub | focalpoint-memory | `clawhub install focalpoint-memory` |
| GitHub | jeff0052/founderOSclaudecode | `git clone` |

### 关键里程碑

- **产品改名**: FPMS → FocalPoint（对外品牌名，代码内部保持 fpms）
- **License**: MIT → BSL 1.1（防止竞品直接商用，4 年后转 Apache 2.0）
- **GitHub 集成真实验证**: 用 `jeff0052/founderOSclaudecode` repo 的 3 个真实 issue 完成端到端同步测试
- **README 重写**: 加入竞品对比（Mem0/Zep/Letta/OpenViking）、目标用户、5 个 use case
- **Claude Desktop 接入验证**: MCP Server stdio transport 成功连接

### 新增文件

| 文件 | 内容 |
|------|------|
| pyproject.toml | Python 打包配置（hatchling） |
| LICENSE | BSL 1.1 |
| clawhub-skill/focalpoint-memory/SKILL.md | ClawHub skill 定义 |

---

## 2026-03-22 — MCP Server 实现

### 新增模块

| 模块 | 位置 | 内容 |
|------|------|------|
| MCP Server | fpms/mcp_server.py | FastMCP 封装，18 tools（15 SpineEngine + heartbeat/bootstrap/get_context_bundle），stdio transport |

### 新增测试

| 测试文件 | 内容 |
|----------|------|
| tests/test_mcp_server.py | 7 tests — tool 注册验证、系统工具、错误处理、E2E 全流程 |

### 关键设计决策

1. **FastMCP 装饰器模式** — 每个 SpineEngine tool 对应一个 `@mcp.tool()` 函数，类型安全
2. **`_safe_tool` 装饰器** — 所有 tool 函数自动 catch 异常，返回结构化错误 JSON，不会崩溃 MCP server
3. **Engine 懒加载单例** — `_get_engine()` 避免 import-time 副作用，环境变量配置数据路径
4. **search_nodes 的 filters 为 JSON string** — MCP tool 参数必须是简单类型，服务端解析并校验

### 文档更新

| 文档 | 变更 |
|------|------|
| USAGE-GUIDE.md | §4.2 重写：MCP Server 启动方式、环境变量、Claude Desktop/Code/OpenClaw 配置示例 |
| CHANGELOG.md | 补充 MCP Server 记录 |

### 测试

- 新增 7 MCP tests
- 总计 567 tests 全绿

---

## 2026-03-21 — 产品使用指南 + 文档更新

### 新增文档

| 文档 | 位置 | 内容 |
|------|------|------|
| USAGE-GUIDE.md | docs/ | 完整产品使用指南：用途、核心概念、适用场景、使用方式（Python API / MCP / OpenClaw）、注意事项、当前限制 |

### 文档更新

| 文档 | 变更 |
|------|------|
| README.md | 重写为产品导向：新增快速开始、当前状态、架构简图、使用指南链接 |
| CHANGELOG.md | 补充本次文档更新记录 |

---

## 2026-03-21 — M1 GitHub 集成完成

### 新增模块

| 模块 | 位置 | 内容 |
|------|------|------|
| BaseAdapter ABC | fpms/spine/adapters/base.py | 统一 Adapter 接口（sync_node/list_updates/write_comment/search） |
| AdapterRegistry | fpms/spine/adapters/registry.py | Adapter 注册/发现/生命周期管理 |
| GitHubAdapter | fpms/spine/adapters/github_adapter.py | GitHub Issues/PRs 同步（httpx, 状态映射, source_id 解析） |
| NodeSnapshot | fpms/spine/models.py | 外部源快照数据结构 |
| SourceEvent | fpms/spine/models.py | 外部源事件数据结构 |

### 修改模块

| 模块 | 变更 |
|------|------|
| BundleAssembler | L2 装载时跨源同步 + 离线降级 + Assembly Trace 含 sync_status |
| SpineEngine | sync_source/sync_all 实现 + set_adapter_registry |

### 关键设计决策

1. **M1 只做 sync_node 拉取，list_updates 事件处理延迟到 M2**
   - 一人公司规模小，按需同步足够，事件驱动在 Heartbeat 里统一处理更干净

2. **离线降级：adapter 失败不阻塞，用缓存 + 标注"数据可能过时"**
   - 保证 Agent 永远能工作，哪怕外部 API 不可用

3. **assignee → owner 字段映射**
   - PRD §4.2 要求 title/status/assignee 从外部同步，assignee 对应 Node.owner

### 测试

- 新增 50 tests（adapter_base 11 + registry 6 + github_adapter 17 + bundle_cross_source 7 + m1_e2e 9）
- 总计 560 tests 全绿

---

## 2026-03-20 — 需求深化迭代

### 新增文档

| 文档 | 位置 | 内容 |
|------|------|------|
| PRD-context-lifecycle | 2-requirements/ | Context 生命周期（装载→校验→执行→校验→写回→上报→压缩） |
| PRD-compression-spec | 2-requirements/ | 压缩策略规格（Narrative MD 格式、规则基压缩、无 LLM） |
| PRD-cognitive-engine | 2-requirements/ | V2 认知引擎（跨工具集成层，Adapter 架构） |
| PRD-cto-agent | 2-requirements/ | CTO Agent 需求（第一个 Office 实例） |
| GLOSSARY | 根目录 | 术语表，统一所有专有概念定义 |
| USER-SCENARIOS | 2-requirements/ | 8 个用户场景，从 Founder 视角描述使用流程 |
| CHANGELOG | 根目录 | 本文件 |

### 关键设计决策

1. **Context 不是聊天记录，是工作台**
   - 定义了 context 的精确组成（自身骨架 + 向上 + 向下 + 横向 + 历史）
   - 明确了裁剪铁律：半残的全景不如完整的焦点

2. **生命周期从"读-做-写"扩展为六步循环**
   - 新增进入校验（开工前确认方向对齐）
   - 新增中途校验（执行中发现重要信息时"抬头看全局"）
   - 新增退出上报（关键发现向上冒泡，与 rollup 的 status 冒泡互补）
   - 灵感来源：人类做复杂任务时的"总分总"不是一次，而是反复抬头

3. **任务拆解 = Context 分形**
   - 拆解的判断标准：context 超预算 = 还没拆够
   - 拆解的目的不是管理，是让每个子任务的 context 自给自足

4. **V2 方向确定：不重造轮子，只做认知引擎**
   - V1 = Standalone FPMS（自己存所有数据）
   - V2 = 跨工具认知引擎（连接 GitHub/Notion/Lark，只做它们做不到的事）
   - V2 只做：跨工具因果链、Context 组装、压缩记忆、主动校验

5. **压缩策略确定：规则基，不用 LLM**
   - 节省成本、确定性可控、可审计
   - 三步压缩：时间过滤 → 结构化提取 → 模板渲染

### 审计修复

| 问题 | 修复 |
|------|------|
| 派生层隔离 vs rollup 矛盾 | 澄清：rollup 是事务内确定性计算，不是"读派生物" |
| done 是否为终态 | 澄清：done 是软终态，archived 是硬终态 |
| 焦点丢失行为未定义 | 定义：进入无焦点模式，只有 L0 + L_Alert |

### 文档重组

- 所有文档从散落状态整理为 4 层分类：vision / requirements / architecture / implementation
- 新建 README.md 作为总入口

---

## 2026-03-17 — V3 基础需求建立

### 文档

| 文档 | 内容 |
|------|------|
| PRD-functional | 14 个功能需求（FR-0 ~ FR-13），含状态机、DAG、Tool Call |
| PRD-nfr | 非功能需求（性能、安全、可靠性） |
| PRD-philosophy | 设计哲学（人类认知映射、DCP、眼球模型） |
| PRD-goals | 核心目标和成功标准 |
| ARCHITECTURE | FPMS 架构设计 |
| ARCHITECTURE-V3.1 | Memory 六层架构 + DCP 模型 |
| INTERFACES | MCP Tool 接口定义（14 个工具） |
| CLAUDE | Agent 开发规范 |
| WhitePaper | 愿景白皮书 |
| OVERVIEW | 系统全景 |
| v0-task-breakdown | V0 详细任务分解（6 Task + Agent 分配） |
| v0-acceptance | V0 验收清单（4 层 checklist） |

### 关键设计决策

1. **分形节点模型** — 统一 Schema，goal/project/task/signal 同构
2. **DCP Push 模型** — 脊髓引擎推送 context，禁止 RAG Pull
3. **14 Tool 写入路径** — LLM 通过标准化工具操作数据，不直接碰存储
4. **SQLite + WAL** — 单文件数据库，原子提交，WAL 读写不互锁
5. **眼球模型** — L0/L1/L2 三层分辨率 + L_Alert 独立告警

---

## 变更记录格式说明

每次迭代记录：
- **日期 + 标题**
- **新增/修改/删除了哪些文档**
- **关键设计决策**（决定了什么 + 为什么）
- **修复了什么问题**（如果有审计/review 反馈）
