# FPMS 全局架构图

## 系统全景

```
┌─────────────────────────────────────────────────────────┐
│                    LLM (Brain / 大脑)                    │
│         读认知包 → 思考 → 发出 Tool Call 指令             │
└──────────────────────┬──────────────────────────────────┘
                       │ Tool Call JSON
                       ▼
┌─────────────────────────────────────────────────────────┐
│              SpineEngine (脊髓引擎 / 总控)                │
│                                                         │
│  ┌─────────┐  接收 Tool Call，路由到对应 handler          │
│  │ tools.py│─────────────────────────────────┐          │
│  └────┬────┘                                 │          │
│       │                                      │          │
│       ▼                                      ▼          │
│  ┌──────────┐  校验一切规则              ┌────────┐     │
│  │validator │  • 状态迁移合法性          │ store  │     │
│  │  .py     │  • DAG 全息防环            │  .py   │     │
│  │          │  • XOR (root/parent)       │        │     │
│  │          │  • 活跃域隔离              │ SQLite │     │
│  │          │  • 子节点终态检查          │   +    │     │
│  └──────────┘                            │events  │     │
│       │                                  │.jsonl  │     │
│       │ 校验通过                          └───┬────┘     │
│       ▼                                      │          │
│  ┌───────────┐  追加叙事                     │          │
│  │narrative  │  append-only                  │          │
│  │  .py      │  失败→repair                  │          │
│  └───────────┘                               │          │
│                                              │          │
│  ════════════════════════════════════════════════════    │
│  ║           读路径 (派生计算层)              ║          │
│  ════════════════════════════════════════════════════    │
│                                              │          │
│  ┌────────┐  ┌────────┐  ┌──────────┐       │          │
│  │risk.py │  │rollup  │  │dashboard │       │          │
│  │        │  │  .py   │  │   .py    │       │          │
│  │blocked │  │递归冒泡 │  │ L0 树形  │       │          │
│  │at-risk │  │自底向上 │  │  渲染    │  ◄────┘          │
│  │stale   │  │含归档子 │  │排序+截断 │  从 SQLite       │
│  └───┬────┘  └───┬────┘  └────┬─────┘  读取事实        │
│      │           │            │                         │
│      └───────────┼────────────┘                         │
│                  ▼                                      │
│  ┌──────────────────────────┐                           │
│  │      heartbeat.py        │                           │
│  │  • 复用 risk 引擎 (DRY)  │                           │
│  │  • 生成告警 Top 3        │                           │
│  │  • 去重 + Anti-Amnesia   │                           │
│  │  • 候选焦点建议          │                           │
│  └────────────┬─────────────┘                           │
│               ▼                                         │
│  ┌──────────────────────────┐                           │
│  │       focus.py           │                           │
│  │  • 焦点仲裁 (4级优先级)  │                           │
│  │  • LRU 淘汰 (max 3)     │                           │
│  │  • 3天衰减               │                           │
│  └────────────┬─────────────┘                           │
│               ▼                                         │
│  ┌──────────────────────────┐                           │
│  │       bundle.py          │  认知包组装               │
│  │                          │                           │
│  │  L0: dashboard (500-1k)  │                           │
│  │  L_Alert: top 3 (500)    │                           │
│  │  L1: 近景关联 (1-3k)     │                           │
│  │  L2: 焦点上下文 (2-5k)   │                           │
│  │  裁剪铁律: 因果 > 关系   │                           │
│  └────────────┬─────────────┘                           │
│               │                                         │
│  ┌────────────┴─────────────┐                           │
│  │     recovery.py          │  冷启动                   │
│  │  SQLite→L0→Heartbeat     │                           │
│  │  →Focus→Bundle→Push      │                           │
│  └──────────────────────────┘                           │
│                                                         │
│  ┌──────────────────────────┐  ┌──────────────────┐     │
│  │     archive.py           │  │ compression.py   │     │
│  │  • 归档扫描 (Heartbeat)  │  │ • 后台异步       │     │
│  │  • 4条件检查             │  │ • 规则优先       │     │
│  │  • unarchive + 免死金牌  │  │ • 乐观并发控制   │     │
│  └──────────────────────────┘  └──────────────────┘     │
│                                                         │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│                    持久化存储层                           │
│                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │   SQLite DB   │  │ events.jsonl │  │ narratives/   │  │
│  │              │  │              │  │               │  │
│  │  nodes       │  │  审计事件     │  │ {id}.md       │  │
│  │  edges       │  │  (与DB原子)  │  │ {id}.comp.md  │  │
│  │  session_    │  │              │  │               │  │
│  │    state     │  │              │  │ append-only   │  │
│  │              │  │              │  │               │  │
│  │ [派生表]     │  │              │  │               │  │
│  │ narrative_   │  │              │  │               │  │
│  │   index      │  │              │  │               │  │
│  │ global_view_ │  │              │  │               │  │
│  │   cache      │  │              │  │               │  │
│  └──────────────┘  └──────────────┘  └───────────────┘  │
│                                                         │
│  主提交 = SQLite + events.jsonl (原子)                    │
│  叙事 = 事务外补齐 (repair if fail)                      │
│  派生 = 随时可从事实重建                                  │
└─────────────────────────────────────────────────────────┘
```

## 数据流：写路径 (Tool Call)

```
Agent 发出: update_status(node_id="task-7f2a", new_status="done", reason={...})
  │
  ▼
① tools.py: 解析参数，路由到 handle_update_status()
  │
  ▼
② validator.py: 
  ├─ 状态迁移合法？ active→done ✓
  ├─ 有子节点？→ 全部终态？ ✓
  ├─ reason 必传？ ✓
  └─ 全部通过
  │
  ▼
③ store.py: BEGIN TRANSACTION
  ├─ UPDATE nodes SET status='done', status_changed_at=NOW()
  ├─ INSERT INTO events.jsonl {tool:"update_status", ...}
  └─ COMMIT ← 主提交点
  │
  ▼
④ narrative.py: 追加到 narratives/task-7f2a.md
  ├─ 成功 → 继续
  └─ 失败 → 写 repair event，不回滚
  │
  ▼
⑤ 级联计算（在内存中，从 SQLite 读）
  ├─ rollup.py: 父节点 rollup_status 重算
  ├─ risk.py: depended_by 节点 blocked 重算
  └─ dashboard.py: 全局看板刷新
  │
  ▼
⑥ 返回: {success: true, affected: ["task-7f2a", "proj-3c1d"]}
```

## 数据流：读路径 (认知包组装)

```
触发: Session 启动 / 焦点切换 / Heartbeat

  ▼
① recovery.py: 打开 SQLite，加载活跃拓扑
  │
  ▼
② dashboard.py: 生成 L0 全局看板
  │  └─ 树形渲染 + 风险排序 + 截断 (500-1k tokens)
  │
  ▼
③ heartbeat.py: 扫描风险 → 生成告警
  │  ├─ 复用 risk.py 的计算结果
  │  ├─ 去重 (session_state.last_alerts)
  │  └─ 输出 Top 3 L_Alert (~500 tokens)
  │
  ▼
④ focus.py: 仲裁焦点
  │  ├─ 用户驱动 > 事件驱动 > 时间驱动 > 历史残留
  │  └─ 输出: primary_focus + secondary_focus[]
  │
  ▼
⑤ bundle.py: 组装认知包
  │  ├─ L0:     dashboard 输出
  │  ├─ L_Alert: heartbeat 输出
  │  ├─ L1:     图遍历 (parent + children Top15 + deps Top10 + siblings Top10)
  │  ├─ L2:     焦点骨架 + compressed_summary + 近期叙事
  │  └─ 裁剪:   超预算时 siblings→children→depended_by→depends_on→parent
  │
  ▼
⑥ 序列化为 Markdown → 注入 LLM prompt (5-10k tokens 典型)
```

## 模块依赖关系

```
独立模块（零依赖，可最先写）:
  schema.py ─── models.py ─── risk.py ─── narrative.py

第二层（依赖 schema/models）:
  store.py ◄── schema + models
  validator.py ◄── schema + models
  rollup.py ◄── schema + models

第三层（依赖第二层）:
  tools.py ◄── store + validator + narrative
  dashboard.py ◄── rollup + risk
  heartbeat.py ◄── risk + store(session_state)
  focus.py ◄── store(session_state)
  archive.py ◄── store + validator

第四层（依赖第三层）:
  bundle.py ◄── dashboard + focus + heartbeat + narrative
  recovery.py ◄── 全部模块
  compression.py ◄── narrative + store（后台异步，可最后做）
```

## 14 个 Block 详细分解

```
Block 1: schema.py + models.py
  输入: FR-0 数据分层 + FR-1 节点字段表
  输出: SQLite 建表 + Python dataclass
  行数: ~200
  验收: 表能建，CHECK 约束生效

Block 2: store.py
  输入: FR-11 提交语义表
  输出: CRUD + 事务封装 + events.jsonl 原子写入
  行数: ~300
  验收: 主提交原子性，events 和 DB 同步

Block 3: validator.py
  输入: FR-5.1 状态机 + 不变量 1-6
  输出: 所有校验函数
  行数: ~400
  验收: 非法迁移拒绝，环路检测，XOR 互斥

Block 4: tools.py (写入部分)
  输入: FR-11 Tool 表 + validator 接口 + store 接口
  输出: 14 个 Tool handler
  行数: ~600
  验收: 每个 Tool 能调用并返回结构化结果

Block 5: narrative.py
  输入: FR-2 叙事规则
  输出: append + repair + 格式化模板
  行数: ~200
  验收: append-only 不可覆盖，repair 生成

Block 6: risk.py
  输入: FR-5.2 三个公式
  输出: compute_risks(node_id) → {blocked, at_risk, stale}
  行数: ~100
  验收: 终态不算 blocked，dropped 不解锁

Block 7: rollup.py
  输入: FR-5.3 五条规则
  输出: compute_rollup(node_id) → rollup_status
  行数: ~150
  验收: 递归正确，含归档子节点，排除 inbox

Block 8: dashboard.py
  输入: FR-3 渲染规则
  输出: render_dashboard() → markdown string
  行数: ~200
  验收: 树形缩进，风险排序，500-1k tokens

Block 9: heartbeat.py
  输入: FR-8
  输出: scan() → alerts[] + focus_candidates[]
  行数: ~200
  验收: 去重，Anti-Amnesia 24h，append_log 不重置

Block 10: focus.py
  输入: FR-9
  输出: arbitrate() → {primary, secondaries[]}
  行数: ~200
  验收: 4 级优先级，LRU 淘汰，3 天衰减

Block 11: bundle.py
  输入: FR-10 组装规则
  输出: assemble(focus) → context_bundle string
  行数: ~500
  验收: L0→L2 顺序，Top15/10 截断，裁剪铁律

Block 12: archive.py
  输入: FR-6
  输出: scan_archive_candidates() + unarchive()
  行数: ~200
  验收: 4 条件，免死金牌，原子解封

Block 13: recovery.py
  输入: FR-13
  输出: bootstrap() → context_bundle
  行数: ~200
  验收: 6 步流程，局部降级不阻断

Block 14: 集成测试
  输入: 附录 7 全部 checklist
  输出: tests/ 目录
  行数: ~2000
  验收: 所有 checklist 项绿灯
```
