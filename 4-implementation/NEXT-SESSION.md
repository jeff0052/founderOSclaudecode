# 下一个 Session 的任务：FocalPoint v0.3 — 知识层 + 工作台 + 三省 Protocol

> 开新对话时加载此文件。所有上下文都在这里。

---

## 产品方向

FocalPoint = AI 认知操作系统 = 记忆 + 注意力管理 + 工作流编排

详见：`1-vision/ADR-product-direction.md`
设计思路演进：`docs/milestones/2026-03-22-focalpoint-and-work-mode.md`

---

## 当前已完成

- FocalPoint v0.2.0 已发布 PyPI（`pip install focalpoint`）
- 584 tests 全绿
- 记忆引擎完成：节点管理、状态机、Heartbeat、Context Bundle、GitHub/Notion 双向同步
- MCP Server 18 tools，已接入 Claude Desktop + ClawHub

---

## 本次要做的（v0.3）

完整需求文档：`2-requirements/PRD-work-mode.md`
验收清单：`4-implementation/v03-acceptance.md`

### 5 个功能模块

#### 1. 知识文档层（knowledge.py）— 新增模块

每个节点可挂载 Markdown 知识文档。子节点继承父节点的，自己有的覆盖。

```
data/knowledge/{node_id}/
├── overview.md
├── requirements.md
├── architecture.md
└── {自定义名}.md       ← 可扩展
```

API：
- `set_knowledge(node_id, doc_type, content)`
- `get_knowledge(node_id, doc_type=None)` — 带继承
- `delete_knowledge(node_id, doc_type)`

goal/project 需要知识文档，task 不需要。

#### 2. 工作台（workbench.py）— 新增模块

一次函数调用准备所有上下文。无状态。

```python
workbench = engine.activate_workbench(node_id, role="execution")
# 返回：goal, knowledge, context_bundle, subtasks, suggested_next, role_prompt
```

工作台大小 = 一个 context 能闭环的最小单元。

#### 3. Narrative Category — 修改 narrative.py

`append_log` 加 `category` 参数。

枚举：`decision | feedback | risk | technical | progress | general`

不影响角色视角（角色看所有 log），只是打标签方便查找。

#### 4. 全文搜索 — 修改 store.py

用 SQLite FTS5 实现。搜标题 + narrative + knowledge。

```python
search_nodes(query="缓存 决策")  # 新增 query 参数
```

替代"软关联" — 不预建节点间弱关系，搜索即可找到。

#### 5. 三省 Protocol — 新增逻辑

```
中书省（Maker）     → 产出需求文档
门下省（Reviewer）  → 翻历史教训、检查风险
尚书省（Engineer）  → 工程评审 + 执行

流程：中书产出 → 门下+尚书并行审查 → 都通过才执行
打回 ≤ 3 次，超过通知人类
```

角色 prompt 文件：
```
fpms/prompts/
├── strategy.md     ← 中书省
├── review.md       ← 门下省
└── execution.md    ← 尚书省
```

**核心原则：数据不过滤，角色 prompt 决定思维方式。**

---

## 实现顺序

```
1. knowledge.py（知识文档读写 + 继承）       ← 无依赖
2. narrative category（append_log 加字段）   ← 无依赖
3. 全文搜索（store.py + FTS5）              ← 无依赖
   ↑ 1-3 可并行

4. 角色 prompt 文件                         ← 无依赖
5. workbench.py（调用 1 + 4 + 现有 bundle） ← 依赖 1, 4
6. 三省 protocol 逻辑                       ← 依赖 5
7. MCP tools（3 新 + 2 更新）               ← 依赖 1-6
8. 测试 + 发布 v0.3.0                      ← 依赖全部
```

---

## 核心设计决策（已确认，不要重新讨论）

1. **记忆没有角度** — 三个角色看同样的数据，差异在 prompt
2. **工作台无状态** — 一次调用，不是持久对象
3. **知识文档可扩展** — 基础三种 + 自由命名
4. **narrative 和 knowledge 都存** — 一个记过程，一个记结论
5. **软关联不做** — 靠全文搜索替代
6. **三省并行审查** — 不串行，门下和尚书同时审
7. **≤3 次打回** — 超过通知人类
8. **注意力精度优先** — 一个角色只关注一件事

---

## 关键文件

| 文件 | 作用 |
|------|------|
| `2-requirements/PRD-work-mode.md` | 完整需求文档 |
| `4-implementation/v03-acceptance.md` | 验收测试用例 |
| `1-vision/ADR-product-direction.md` | 产品方向决策 |
| `docs/milestones/2026-03-22-focalpoint-and-work-mode.md` | 设计思路演进 |
| `SYSTEM-CONFIG.md` | 系统参数 |
| `4-implementation/CLAUDE.md` | 开发规范 |

## 开发规范

- 用 superpowers skills
- Python 3.11：`/opt/homebrew/opt/python@3.11/bin/python3.11`
- 测试：`/opt/homebrew/opt/python@3.11/bin/python3.11 -m pytest tests/ -v`
- 代码目录：`/Users/ontanetwork/Documents/Onta Network/Founder OS/MemoryFPMS/V4/`

## 预估工时

1.5 - 2 天
