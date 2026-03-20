# FPMS 分形项目管理系统 — 技术架构文档 V3.1

**版本**: V3.1 | **日期**: 2026-03-15  
**设计范式**: 大小脑解耦 · 控制反转(IoC) · 确定性优先 · SQLite嵌入式引擎  
**审核来源**: GPT / Gemini / Grok 共8轮架构审核后的最终收敛版  
**V3.0→V3.1变更**: 持久化方式从"内存SQLite投影"切换为"嵌入式SQLite为主+MD为叙事层"

---

## 1. 架构愿景

### 1.1 一句话定义

**以嵌入式SQLite管理项目骨架（关系/状态/元数据），以Markdown管理项目血肉（叙事/历史），让AI Agent拥有持续的项目上下文意识——零外部服务依赖、零Token基建税、零运维成本。**

### 1.2 核心设计原则

| 原则 | 含义 | 来源 |
|------|------|------|
| **确定性优先** | 状态冒泡、环检测、死锁拦截等逻辑100%由Python代码完成，绝不交给LLM | Gemini |
| **控制反转(IoC)** | 数据主动找CPU，不是CPU摸黑找数据。Agent被唤醒前Context已组装好 | Gemini |
| **多语种持久化** | 骨架用SQLite（结构化查询/事务/关系），血肉用MD（叙事/人类可读/LLM原生） | V3.1新增 |
| **0 Token基建税** | 状态推导、依赖寻址、全局投影等系统运维操作零LLM调用 | 全部 |
| **胖代码瘦DB** | SQL只做查询和批量更新，业务逻辑(冒泡规则/迁移规则)在Python中可见可调试 | Gemini |
| **精准胜于全面** | 5k精准Context > 50k泛泛Context，每个token必须服务于当前任务 | PRD |

### 1.3 V3.0→V3.1 关键变更

| 维度 | V3.0 (内存投影) | V3.1 (嵌入式SQLite) | 变更理由 |
|------|----------------|-------------------|---------|
| SQLite持久化 | ❌ 纯内存，不落盘 | ✅ fpms.db文件 | 不重复计算已知结果 |
| 启动速度 | ~10-20ms(重建投影) | ~1ms(直接打开) | 节点多时差距更大 |
| 事实源 | MD Frontmatter(SSoT) | **SQLite为主，MD为叙事层** | 工程学正道 |
| 崩溃恢复 | 重建(安全但慢) | WAL自动恢复(安全且快) | 生产级可靠性 |
| Scale上限 | ~200节点(投影瓶颈) | 5000+节点(无感) | 为未来预留 |
| Schema演进 | 批量改Frontmatter | ALTER TABLE一句话 | 维护成本极低 |
| Git追踪 | ✅ 完美(纯文本) | ⚠️ MD完美 + events.jsonl补偿DB | 可接受的trade-off |

### 1.4 关键架构创新

**DCP (Deterministic Context Push) — 确定性上下文注入**

传统Agent系统使用PSP（概率性语义拉取）：Agent醒来后摸黑搜索，N+1查询，Token浪费严重。

FPMS使用DCP：Agent被唤醒的前一毫秒，脊髓层基于SQLite图计算，以当前焦点为中心遍历，瞬间组装完美的Context Bundle直接Push给Agent。

```
PSP模式: Agent醒来 → search("Anext进度") → 阅读 → search("法务进度") → ...
DCP模式: Agent醒来 → Context Bundle已在System Prompt里 → 直接回答
```

**多语种持久化 (Polyglot Persistence)**

```
SQLite (骨架)                    MD (血肉)
┌─────────────────────┐         ┌─────────────────────┐
│ id, status          │         │ 叙事时间线            │
│ parent_id           │         │ 背景描述              │
│ depends_on          │    +    │ 关键事件              │
│ deadline, owner     │         │ 决策记录              │
│ priority            │         │ Append-Only历史       │
│ background_summary  │         │                       │
└─────────────────────┘         └─────────────────────┘
 → 关系计算/冒泡/查询/事务        → LLM读取/人类阅读/Git追踪
 → 机器擅长的交给数据库           → 人/AI擅长的交给文件
```

---

## 2. 系统拓扑架构

### 2.1 三层总览

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 LAYER 3 · 认知层                      3 模块
 非确定性 · LLM · 按需计费
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 ① 决策引擎    ② 叙事生成器    ③ 语义摘要器
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
      ↑ Context Bundle (Push)  ↓ Tool Call
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 LAYER 2 · 运行时内核                  7 模块
 确定性 · 纯Python · 0 Token · 毫秒级
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 ④ SQLite引擎     ⑤ 状态机      ⑥ 焦点选择器
 ⑦ Bundle组装器   ⑧ Risk扫描器   ⑨ 投影引擎
                  ⑩ 写入协调器
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
      ↑ SQL查询           ↓ DB事务 + MD追加
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 LAYER 1 · 存储层                      4 模块
 嵌入式SQLite + 纯文本MD · 100%数据主权
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 ⑪ fpms.db(骨架)  ⑫ MD叙事文件  ⑬ 事件日志
                  ⑭ 归档冷冻区
 + 派生视图: global_view / focus_view / alert_view
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### 2.2 完整模块清单

| # | 层级 | 模块 | 类型 | 核心职责 | LLM | Token |
|---|------|------|------|---------|-----|-------|
| ① | 认知 | 决策引擎 | 非确定性 | 意图理解 → Tool指令输出 | ✅ 旗舰 | 按需 |
| ② | 认知 | 叙事生成器 | 非确定性 | 状态变更 → 人类可读叙事 | ✅ 旗舰 | 按需 |
| ③ | 认知 | 语义摘要器 | 非确定性 | 超长日志 → 精炼摘要(规则优先,Ollama fallback) | ✅ Ollama | 免费 |
| ④ | 内核 | SQLite引擎 | 确定性 | DB连接管理/图查询/递归CTE/环检测 | ❌ | $0 |
| ⑤ | 内核 | 状态机 | 确定性 | 状态迁移规则/冒泡/级联解锁/健康度/风险标记 | ❌ | $0 |
| ⑥ | 内核 | 焦点选择器 | 确定性 | 焦点仲裁/时间衰减/事件驱动/用户指定 | ❌ | $0 |
| ⑦ | 内核 | Bundle组装器 | 确定性 | L2焦点全文+L1近景摘要+L0全局概览+token预算 | ❌ | $0 |
| ⑧ | 内核 | Risk扫描器 | 确定性 | deadline检测/stale检测/blocked升级/优先级调整 | ❌ | $0 |
| ⑨ | 内核 | 投影引擎 | 确定性 | 多视图生成(global/focus/alert)/L0缓存 | ❌ | $0 |
| ⑩ | 内核 | 写入协调器 | 确定性 | DB事务→MD追加→事件日志→归档检查(单向写入流) | ❌ | $0 |
| ⑪ | 存储 | fpms.db | 事实源(骨架) | 节点关系/状态/元数据(ACID事务) | - | - |
| ⑫ | 存储 | MD叙事文件 | 事实源(血肉) | 叙事时间线/背景描述(Append-Only) | - | - |
| ⑬ | 存储 | 事件日志 | 事实源(审计) | 结构化JSON审计轨迹(可回放/可调试) | - | - |
| ⑭ | 存储 | 归档冷冻区 | 事实源(冷) | Done+7天+入度=0的节点冷存储 | - | - |

**统计: 14个模块 (认知3 + 内核7 + 存储4) + 3个派生视图**

---

## 3. 数据模型

### 3.1 SQLite Schema (fpms.db)

```sql
-- 启用WAL模式（并发安全+崩溃恢复）
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- 节点表（骨架）
CREATE TABLE nodes (
    id                  TEXT PRIMARY KEY,
    title               TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'active'
                        CHECK(status IN ('active','waiting','blocked','done','dropped')),
    parent_id           TEXT,
    owner               TEXT,
    priority            TEXT DEFAULT 'medium'
                        CHECK(priority IN ('low','medium','high','critical')),
    deadline            TEXT,      -- ISO 8601
    created             TEXT NOT NULL, -- ISO 8601
    updated             TEXT NOT NULL, -- ISO 8601, 每次变更自动更新
    background_summary  TEXT,      -- 一句话摘要，供L1近景使用
    md_path             TEXT NOT NULL, -- 对应MD文件路径
    FOREIGN KEY (parent_id) REFERENCES nodes(id) ON DELETE SET NULL
);

-- 依赖关系表（弱边）
CREATE TABLE dependencies (
    from_id     TEXT NOT NULL,  -- 被阻塞方
    to_id       TEXT NOT NULL,  -- 阻塞方
    created     TEXT NOT NULL,  -- 创建时间
    PRIMARY KEY (from_id, to_id),
    FOREIGN KEY (from_id) REFERENCES nodes(id) ON DELETE CASCADE,
    FOREIGN KEY (to_id) REFERENCES nodes(id) ON DELETE CASCADE
);

-- 焦点记录表
CREATE TABLE focus (
    node_id     TEXT PRIMARY KEY,
    reason      TEXT,           -- 为什么聚焦
    since       TEXT NOT NULL,  -- 何时开始聚焦
    FOREIGN KEY (node_id) REFERENCES nodes(id) ON DELETE CASCADE
);

-- 索引
CREATE INDEX idx_nodes_status ON nodes(status);
CREATE INDEX idx_nodes_parent ON nodes(parent_id);
CREATE INDEX idx_nodes_deadline ON nodes(deadline);
CREATE INDEX idx_nodes_updated ON nodes(updated);
CREATE INDEX idx_deps_to ON dependencies(to_id);
```

### 3.2 MD叙事文件格式

每个节点对应一个`.md`文件，存储在`fpms/nodes/`目录下。  
**文件名**: `{id}.md` (例: `anext-7f2a.md`)

Frontmatter作为**只读镜像**（方便人类和LLM直接阅读，真相在DB中）：

```markdown
---
# 只读镜像 — 真相在fpms.db中，勿手动修改此区域
id: anext-7f2a
title: "Anext 信贷协议最终审核"
status: blocked
parent_id: macro-0a1b
depends_on: [legal-5x2p]
owner: Jeff
priority: high
deadline: "2026-03-20T18:00:00Z"
---

# Anext 信贷协议 - 叙事时间线

## 背景
Anext寻求700万信贷额度，用于扩大KA商户覆盖。
初始条件：8.2%利率，需要公司担保。

## 关键事件 (Append-Only)

**2026-03-10 09:30** - 初始条件
- Charles提出8.2%年化利率
- 要求Uniweb公司作为担保方
- 授信额度700万，12个月期限

**2026-03-12 14:15** - 利率谈判成功
- Jeff推回利率过高问题
- Charles同意降至7.8%
- 但坚持需要连带担保条款

**2026-03-13 16:45** - [BLOCKED] 法务介入
- 发现担保条款涉及"连带无限责任"
- 转交法务team (legal-5x2p) 进行风险评估
```

### 3.3 状态集与迁移规则

```
         ┌──────────────────────────┐
         │                          │
         ▼                          │
     ┌────────┐    ┌─────────┐    ┌─────────┐
     │ active │───→│ waiting │───→│ blocked │
     └───┬────┘    └────┬────┘    └────┬────┘
         │              │              │
         │              │         (阻塞解除时
         │              │          自动回active)
         ▼              ▼
     ┌────────┐    ┌─────────┐
     │  done  │    │ dropped │
     └────────┘    └─────────┘
      (终态)        (终态)
```

| 当前状态 | 可迁移到 | 约束 |
|---------|---------|------|
| active | waiting, blocked, done, dropped | 无 |
| waiting | active, blocked, done, dropped | 无 |
| blocked | active | **仅当所有depends_on全done时**，由状态机自动执行 |
| done | - | 终态，7天+入度=0后归档 |
| dropped | - | 终态，立即从活跃index移除 |

### 3.4 关系类型

| 类型 | 存储位置 | 冒泡 | 用途 |
|------|---------|------|------|
| **强边** (parent_id) | nodes表 | ✅ 参与冒泡 | 层级归属，子→父状态传播 |
| **弱边** (depends_on) | dependencies表 | ❌ 不参与冒泡 | 阻塞警告+级联解锁 |

### 3.5 ID命名规则

| 组成 | 规则 | 示例 |
|------|------|------|
| 前缀 | 项目/类型简写，2-5字符 | anext, netst, legal, pdax |
| 分隔符 | `-` | - |
| 后缀 | 随机短哈希，4字符hex | 7f2a, 9k3l, 5x2p |
| 完整ID | `{prefix}-{hash}` | `anext-7f2a` |

### 3.6 事件日志格式

`fpms/events.jsonl` (JSON Lines, Append-Only):

```json
{"ts":"2026-03-15T14:03:00Z","op":"update_status","node":"legal-5x2p","from":"active","to":"done","actor":"agent"}
{"ts":"2026-03-15T14:03:00Z","op":"cascade_unblock","node":"anext-7f2a","from":"blocked","to":"active","trigger":"legal-5x2p→done"}
{"ts":"2026-03-15T14:03:00Z","op":"bubble_up","node":"macro-0a1b","result":"no_change","reason":"sibling netst-9k3l still waiting"}
```

### 3.7 目录结构

```
fpms/
├── docs/
│   ├── ARCHITECTURE-V3.1.md    # 本文档
│   └── PRD.md                  # 需求文档
├── fpms.db                     # SQLite (骨架：关系/状态/元数据)
├── nodes/                      # MD叙事文件 (血肉：时间线/历史)
│   ├── anext-7f2a.md
│   ├── legal-5x2p.md
│   ├── netst-9k3l.md
│   └── ...
├── views/                      # 派生视图 (只读，自动生成)
│   ├── global_view.md          # 全局看板 ≤50行
│   ├── focus_view.md           # 当前焦点详情
│   └── alert_view.md           # 风险/预警汇总
├── archive/                    # 归档冷冻 (Done+7天+入度=0)
│   ├── completed-task.md
│   └── ...
├── events.jsonl                # 事件日志 (Append-Only, 审计轨迹)
└── spine.py                    # 脊髓引擎 (全部运行时内核)
```

---

## 4. 核心工作流

### 4.1 上下文注入流 (Context Push / DCP)

```
用户提问: "Anext卡在哪了?"
    │
    ↓
④ SQLite引擎: 直接打开fpms.db (已持久化，~1ms)
    │
    ↓
⑥ 焦点选择器:
    SQL: SELECT id FROM nodes WHERE title LIKE '%Anext%' OR id LIKE '%anext%'
    → Focus = anext-7f2a
    │
    ↓
⑦ Bundle组装器:
    │
    ├── L2 焦点全文 (~800 tokens):
    │   读取 nodes/anext-7f2a.md 完整叙事
    │
    ├── L1 近景摘要 (~600 tokens):
    │   SQL: SELECT id, title, status, background_summary
    │        FROM nodes WHERE parent_id = (SELECT parent_id FROM nodes WHERE id='anext-7f2a')
    │   SQL: SELECT n.id, n.title, n.status, n.background_summary
    │        FROM dependencies d JOIN nodes n ON d.to_id = n.id
    │        WHERE d.from_id = 'anext-7f2a'
    │
    ├── L0 背景概览 (~500 tokens):
    │   引用⑨投影引擎的全局缓存
    │
    └── 预警注入 (~100 tokens):
        ⑧Risk扫描器:
        SQL: SELECT id, title, deadline FROM nodes
             WHERE status NOT IN ('done','dropped')
             AND deadline < datetime('now', '+48 hours')
    │
    ↓ Context Bundle (~2k tokens) Push到System Prompt
    │
    ↓
① 决策引擎(LLM): 基于完美上下文直接回答
```

### 4.2 状态变更流 (Safe Mutation)

```
① 决策引擎输出: update_status("legal-5x2p", "done")
    │
    ↓
⑤ 状态机接管 (全部Python逻辑，SQL辅助查询):
    │
    ├── 1. 验证迁移合法性
    │      active→done ✅ (符合状态迁移规则)
    │
    ├── 2. 级联解锁 (Python逻辑 + SQL查询)
    │      SQL: SELECT from_id FROM dependencies WHERE to_id='legal-5x2p'
    │      结果: anext-7f2a 依赖 legal-5x2p
    │      
    │      SQL: SELECT d.to_id, n.status FROM dependencies d
    │           JOIN nodes n ON d.to_id = n.id
    │           WHERE d.from_id = 'anext-7f2a'
    │      检查: anext-7f2a的所有depends_on是否全done?
    │      → 全done → anext-7f2a: blocked→active ✅
    │
    ├── 3. 向上冒泡 (Python逻辑 + 递归CTE)
    │      SQL: WITH RECURSIVE ancestors(id, parent_id, depth) AS (
    │               SELECT id, parent_id, 0 FROM nodes WHERE id='legal-5x2p'
    │               UNION ALL
    │               SELECT n.id, n.parent_id, a.depth+1
    │               FROM nodes n JOIN ancestors a ON n.id = a.parent_id
    │           )
    │           SELECT id FROM ancestors WHERE depth > 0
    │      
    │      对每个祖先节点:
    │        SQL: SELECT status FROM nodes WHERE parent_id = :ancestor_id
    │        Python: 兄弟全done → 父done | 有blocked → 标记attention
    │
    └── 4. 健康度评估
           检查是否产生状态死锁/流程停滞
    │
    ↓
⑩ 写入协调器 (单向写入流，DB为主):
    │
    ├── Step 1: BEGIN TRANSACTION (SQLite)
    │   UPDATE nodes SET status='done', updated=:now WHERE id='legal-5x2p'
    │   UPDATE nodes SET status='active', updated=:now WHERE id='anext-7f2a'
    │   COMMIT
    │   → DB事务成功 = 状态变更生效 ✅
    │
    ├── Step 2: 更新MD Frontmatter只读镜像
    │   legal-5x2p.md → status: done
    │   anext-7f2a.md → status: active
    │   (即使失败，DB已正确，不影响系统正确性)
    │
    ├── Step 3: 追加事件日志
    │   events.jsonl ← {"op":"update_status", "node":"legal-5x2p", ...}
    │   events.jsonl ← {"op":"cascade_unblock", "node":"anext-7f2a", ...}
    │
    ├── Step 4: 触发⑨投影引擎
    │   重绘 views/global_view.md
    │   重绘 views/alert_view.md
    │
    └── Step 5: 检查归档条件
        legal-5x2p: Done + 入度=0? → 标记7天后移入archive/
    │
    ↓
② 叙事生成器(LLM):
    追加到 nodes/legal-5x2p.md:
    "**2026-03-15 14:03** - [DONE] 法务审核通过，阻塞解除"
    追加到 nodes/anext-7f2a.md:
    "**2026-03-15 14:03** - 法务审核通过，项目重新激活"
```

### 4.3 写入协调器的一致性保障

```
写入优先级（单向流，不可逆）:

  ① SQLite事务 (MUST) → 状态变更的唯一真相
  ② MD Frontmatter更新 (SHOULD) → 只读镜像，失败可补
  ③ 事件日志 (SHOULD) → 审计追溯，失败可补
  ④ 派生视图重绘 (MAY) → 随时可从DB重建

最坏情况分析:
  DB写成功 + MD写失败 = 状态正确，叙事缺一条记录 → 可补
  DB写成功 + 事件日志失败 = 状态正确，审计缺一条 → 可补
  DB写失败 = 全部回滚，什么都没发生 → 安全

结论: 只要DB事务成功，系统状态就是正确的。
```

---

## 5. 三类死锁防护

| 类型 | 检测模块 | 触发时机 | 机制 | 处理方式 |
|------|---------|---------|------|---------|
| **结构死锁** | ④ SQLite引擎 | 添加依赖时 | 递归CTE检测环路 | 拒绝写入，Error返回LLM |
| **状态死锁** | ⑤ 状态机 | 状态变更后 | 节点组合分析(互等/全blocked) | 标记`health=stalled` |
| **流程死锁** | ⑧ Risk扫描器 | 定期扫描 | `waiting/blocked` > 7天 | `attention_required=true` |

### 环路检测 (递归CTE):

```sql
-- 检查添加 :from_id → :to_id 依赖后是否成环
-- 思路：从to_id出发沿依赖链走，如果能走回from_id就是环
WITH RECURSIVE reachable(id) AS (
    SELECT :to_id
    UNION
    SELECT d.to_id FROM dependencies d
    JOIN reachable r ON d.from_id = r.id
)
SELECT EXISTS(SELECT 1 FROM reachable WHERE id = :from_id) AS has_cycle;
```

---

## 6. 眼球模型 (Foveal Vision)

### 6.1 三层分辨率

| 层级 | 隐喻 | 信息量 | Token预算 | 数据来源 |
|------|------|--------|----------|---------|
| **L2 焦点** | 注视点(中央凹) | 完整叙事+决策历史+依赖 | ~2.5k | MD文件全文读取 |
| **L1 近景** | 焦点旁边(副中央凹) | 摘要+状态+下一步+卡点 | ~1.5k | SQL查询parent/siblings/deps的background_summary |
| **L0 背景** | 视野边缘(周边视觉) | 一句话状态 | ~500 | ⑨投影引擎全局缓存 |

**关键原则: 模糊 ≠ 消失。** L0的节点只有一句话，但它们永远存在于全局视图中。Agent始终保持对整体画面的感知。

### 6.2 焦点驱动方式

| 驱动方式 | 描述 | 实现 |
|---------|------|------|
| **用户驱动** | Jeff提到某个项目/任务 | ⑥焦点选择器SQL匹配 |
| **时间驱动** | deadline < 48h | ⑧Risk扫描器自动升级 |
| **事件驱动** | 收到相关消息/邮件 | 外部事件触发 |
| **衰减机制** | >3天未接触 | ⑥焦点选择器自动降级(SQL: focus.since) |

### 6.3 Token预算总控

```
PRD约束: 系统总占用 < context window的5% = 10k tokens

实际分配:
  L0 全局概览     ~500 tokens   (⑨投影引擎)
  L1 近景摘要    ~1.5k tokens   (⑦Bundle: parent+siblings+deps)
  L2 焦点全文    ~2.5k tokens   (⑦Bundle: 当前节点完整叙事)
  预警注入        ~500 tokens   (⑧Risk扫描器)
  ────────────────────────────
  总计           ~5k tokens     ✅ 占2.5%，远低于10k上限
```

---

## 7. 约束合规性验证

| PRD约束 | V3.1合规性 | 说明 |
|---------|-----------|------|
| 不依赖外部数据库服务 | ✅ | sqlite3是Python标准库嵌入式引擎，零部署零运维 |
| Agent在OpenClaw框架内运行 | ✅ | spine.py通过exec Tool调用 |
| 不破坏MEMORY.md/memory/ | ✅ | FPMS数据在fpms/目录下，完全隔离 |
| Token预算<5% | ✅ | 实际~5k tokens，占2.5% |
| 人类可读 | ✅ | MD叙事文件直接cat/vim查看 |
| Git追踪 | ✅ | MD文件+events.jsonl完美diff；DB变更通过events.jsonl审计 |
| 零外部依赖 | ✅ | Python标准库(sqlite3, json) + PyYAML |

---

## 8. 需求覆盖矩阵

| 需求 | 描述 | 承载模块 | 状态 |
|------|------|---------|------|
| FR-1 | 统一节点模型 | ⑪fpms.db(nodes表) + ⑫MD叙事 | ✅ |
| FR-2 | 叙事体上下文 | ⑫MD叙事文件 + ②叙事生成器 | ✅ |
| FR-3 | 快速全局概览≤50行 | ⑨投影引擎 → global_view.md | ✅ |
| FR-4 | 按需深度加载 | ⑦Bundle组装器(L2读取MD) | ✅ |
| FR-5 | 状态冒泡 | ⑤状态机 + ④SQLite引擎(递归CTE) | ✅ |
| FR-6 | 智能遗忘/归档 | ⑤状态机 + ⑩写入协调器 → ⑭归档 | ✅ |
| FR-7 | Inbox快速捕获 | ①决策引擎 + ⑩写入协调器(parent_id=null) | ✅ |
| FR-8 | 主动提醒/Heartbeat | ⑧Risk扫描器 | ✅ |
| FR-9 | 眼球模型 | ⑥焦点选择器 + ⑦Bundle组装器 | ✅ |
| FR-10 | 30秒上下文恢复 | ④SQLite引擎(即时) + ⑥焦点 + ⑦Bundle | ✅ |
| NFR-1 | Context效率<10k | ⑦Bundle组装器(token预算控制) | ✅ |
| NFR-2 | Agent自主维护 | ①决策引擎 + ⑩写入协调器 | ✅ |
| NFR-3 | 渐进式增长 | ④SQLite引擎(动态Schema) | ✅ |
| NFR-4 | 容错 | ④引擎+⑤状态机(子节点为准重算)+WAL恢复 | ✅ |

---

## 9. 模块间数据流

```
用户提问
  │
  ↓
④ SQLite引擎 ← 直接读取 ← ⑪ fpms.db
  │
  ├→ ⑥ 焦点选择器 (SQL匹配 + 规则仲裁)
  │     │
  │     ↓
  ├→ ⑦ Bundle组装器
  │     ├← SQL查询骨架 (L1摘要) ← ④ SQLite引擎
  │     ├← 读取MD全文 (L2叙事) ← ⑫ MD叙事文件
  │     └← 引用L0缓存 ← ⑨ 投影引擎
  │     │
  │     ↓ Context Bundle (Push)
  │
  ├→ ⑧ Risk扫描器 (SQL: deadline/stale查询) → 预警注入Bundle
  │
  ↓
① 决策引擎 (LLM)
  │
  ├→ 回答用户
  │
  └→ Tool Call: update_status() / create_node() / append_log()
        │
        ↓
  ⑤ 状态机 ← SQL查询辅助 ← ④ SQLite引擎
        │
        ├→ 迁移合法性验证 (Python规则)
        ├→ 级联解锁计算 (SQL查询 + Python逻辑)
        ├→ 向上冒泡计算 (递归CTE + Python规则)
        ├→ 健康度评估 (Python规则)
        │
        ↓
  ⑩ 写入协调器 (单向写入流)
        │
        ├→ Step 1: DB事务 → ⑪ fpms.db (MUST，状态真相)
        ├→ Step 2: 更新Frontmatter → ⑫ MD叙事文件 (SHOULD，只读镜像)
        ├→ Step 3: 追加 → ⑬ 事件日志 (SHOULD，审计)
        ├→ Step 4: 触发 → ⑨ 投影引擎 → views/*.md (MAY，派生)
        ├→ Step 5: 检查归档 → ⑭ 归档冷冻区
        │
        └→ 通知 → ② 叙事生成器(LLM)
                      │
                      └→ 追加叙事到 ⑫ MD叙事文件
```

---

## 10. 关键架构决策记录 (ADR)

| # | 决策 | 选择 | 备选 | 理由 | 来源 |
|---|------|------|------|------|------|
| 1 | 持久化方式 | **SQLite(骨架)+MD(血肉)** | 纯MD Frontmatter / 纯SQLite | 多语种持久化：机器擅长的给DB，人/AI擅长的给文件 | V3.1 |
| 2 | SQLite角色 | **持久化嵌入式引擎** | 内存投影(V3.0) | 不重复计算已知结果，Scale到5000+节点 | V3.1 |
| 3 | 事实源 | **DB为主，MD为叙事层** | MD为主(V3.0) | DB事务保证状态一致性，MD失败不影响正确性 | V3.1 |
| 4 | LLM隔离层 | 最外层(认知层) | 混合在脊髓层 | 最不稳定的变化隔离在外，Clean Architecture | Grok |
| 5 | 环检测归属 | ④SQLite引擎(递归CTE) | ⑤状态机 | 图结构性质≠业务逻辑 | Gemini |
| 6 | 叙事压缩 | 规则优先,Ollama fallback | 纯LLM / 纯规则 | 90%确定性，极端才用LLM | Grok |
| 7 | 焦点与组装 | 独立模块⑥⑦ | 合并为一个 | 选择和拼装是独立决策 | Gemini |
| 8 | 状态冒泡 | SQL查询+Python规则 | SQL触发器 | 触发器是反模式，胖代码瘦DB | Gemini |
| 9 | 全局看板 | 派生视图(只读) | 事实源 | 不是SSoT，禁止手动编辑 | GPT+Gemini |
| 10 | 事件日志 | JSONL Append-Only | SQLite表 | 纯文本Git友好，可回放/可调试 | GPT |
| 11 | 死锁分类 | 3类(结构/状态/流程) | 笼统"死锁拦截" | 精确定义避免实现混乱 | Gemini |
| 12 | Git追踪策略 | MD+events.jsonl | 纯文本(V3.0) | DB变更通过事件日志审计，MD提供人类可读diff | V3.1 |
| 13 | 双写一致性 | 单向流(DB→MD→Log) | 两阶段提交 | DB为真相，其余可补偿，简化工程 | V3.1 |

---

## 11. Sprint规划

### Sprint 1 (P0): 写链路核心 — "焊笼子再放猛兽"
- ④ SQLite引擎: DB初始化 + Schema + 基础CRUD + 递归CTE
- ⑤ 状态机: 冒泡 + 级联解锁 + 迁移验证 + 健康度
- ⑩ 写入协调器: DB事务 → MD Frontmatter更新 → 事件日志
- ⑨ 投影引擎: global_view.md从DB查询生成

**验收标准**: 命令行执行`python3 spine.py update_status legal-5x2p done`，自动完成级联解锁+冒泡+事件记录+看板重绘

### Sprint 2 (P1): 接入Agent — "放猛兽进笼子"
- ① 决策引擎: OpenClaw Shell Tool集成
- ② 叙事生成器: 状态变更→叙事追加到MD
- ⑦ Bundle组装器: L0+L1+L2完整组装
- ⑥ 焦点选择器: SQL匹配 + 衰减机制

**验收标准**: Jeff在Telegram说"Anext怎么样了"，Agent自动组装Context Bundle并准确回答

### Sprint 3 (P2): 长线运维 — "让笼子自己转"
- ⑧ Risk扫描器: deadline/stale/blocked检测
- ③ 语义摘要器: 规则压缩 + Ollama fallback
- ⑭ 归档冷冻: 自动归档逻辑
- ⑥ 焦点选择器增强: 时间驱动 + 事件驱动

**验收标准**: Heartbeat自动检测到deadline<48h的任务并主动提醒Jeff

---

## 12. 与OpenViking对比

```
                    FPMS V3.1        OpenViking
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
定位              项目管理认知OS      通用上下文数据库
模块数             14                 18
语言栈            纯Python           Python+Go+Rust+C++
外部API依赖        0                  4(Embedding+VLM)
Token基建税       $0/月              持续消耗
持久化            SQLite+MD          viking://专有协议
计算引擎          嵌入式SQLite        Embedding+向量检索
上下文寻址        DCP(确定性Push)    PSP(概率性Pull)
状态冒泡          ✅ 内置             ❌ 不支持
业务语义          ✅ 项目管理         ❌ 通用存储
Git追踪           ✅ MD+事件日志      ❌ 专有格式
Scale             5000+节点          无限(但依赖重型基建)
部署复杂度        单文件spine.py     Server+AGFS+DB
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## 附录: 版本演进记录

| 版本 | 日期 | 关键变更 |
|------|------|---------|
| V1.0 | 2026-03-15 | 初始架构：纯文件系统，12模块 |
| V2.0 | 2026-03-15 | Gemini审核：职责边界修正，13模块 |
| V2.1 | 2026-03-15 | GPT+Grok审核：事件日志+写入协调器，14模块 |
| V3.0 | 2026-03-15 | Gemini突破：内存SQLite投影，MD Frontmatter合体 |
| **V3.1** | **2026-03-15** | **工程优化：SQLite持久化为主+MD为叙事层，Scale到5000+** |

---

*本文档经GPT/Gemini/Grok共8轮架构审核，所有关键决策均有据可查。*  
*最后更新: 2026-03-15 V3.1*
