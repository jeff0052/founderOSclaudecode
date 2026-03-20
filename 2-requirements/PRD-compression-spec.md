# PRD: 叙事压缩操作规格

*FR-12 的操作级补充，定义 Narrative 格式、压缩算法、LLM Fallback、调度模型*

---

## 定位

本文档不重复 FR-12 已定义的内容（触发条件、并发控制 Anti-TOCTOU、防套娃水位线、原始叙事保护）。本文档解决的问题是：**拿到一个节点的原始叙事后，具体怎么压缩、压缩成什么样、谁来调度。**

前置依赖：PRD-functional-v4 FR-12、PRD-context-lifecycle-v1 §3.3

---

## 1. Narrative 原始格式规范

### 1.1 文件位置与命名

```
narratives/
  {node_id}.md              ← 原始叙事（append-only）
  {node_id}.compressed.md   ← 压缩摘要（可覆写）
```

### 1.2 原始叙事文件结构

```markdown
---
node_id: task-a1b2
created_at: 2026-01-15T10:00:00+08:00
last_entry_at: 2026-03-18T14:30:00+08:00
entry_count: 47
---

## 2026-03-18

- [status_change] active → blocked | 等待合作方 API 文档更新 | by:agent
- [info] 已发送催促邮件给对接人张三 | by:agent

## 2026-03-15

- [decision] 采用方案B（多币种+成本可控） | reason:方案A不支持多币种,方案C成本超预算 | by:founder
- [info] 方案B的技术评审通过 | by:agent

## 2026-03-10

- [blocker] 合作方 API 文档过时，无法继续对接 | impact:阻塞核心接口开发 | by:agent
- [info] 已联系合作方技术负责人 | by:agent
- [info] 合作方承诺48h内更新文档 | by:agent
```

### 1.3 Entry 格式

每条叙事是一行，格式：

```
- [{type}] {内容} | {key}:{value} | {key}:{value} | by:{author}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `type` | 是 | `status_change` / `decision` / `blocker` / `correction` / `info` |
| 内容 | 是 | 自由文本，一句话描述事件 |
| `reason` | decision 必填 | 决策原因 |
| `impact` | blocker 建议填 | 影响范围 |
| `by` | 是 | `agent` / `founder` / `system` / `compressor` |

### 1.4 日期分组

按日期降序排列（最新在前）。同一天的条目按时间降序。Frontmatter 的 `last_entry_at` 和 `entry_count` 每次 append 时更新。

---

## 2. 规则压缩算法

### 2.1 总体流程

```
输入: 原始叙事文件中 last_compressed_at 之后的所有 entries
  ↓
Step 1: 分类 — 按 type 标签将 entries 分为 5 类
  ↓
Step 2: 保留 — 提取必须保留的条目（status_change, decision, blocker, correction）
  ↓
Step 3: 合并 — 将 info 类条目合并
  ↓
Step 4: 组装 — 按压缩输出格式生成结果
  ↓
Step 5: 判定 — 检查压缩率，决定是否需要 LLM Fallback
  ↓
输出: compressed.md 内容
```

### 2.2 分类规则

Entry 的 `type` 标签即分类依据。如果叙事条目缺少 type 标签（历史数据兼容），按以下关键词推断：

| 关键词模式 | 推断类型 |
|-----------|----------|
| 含 `→` 且涉及状态词（active/blocked/done/cancelled） | `status_change` |
| 含 `决定`/`选定`/`采用`/`确认` | `decision` |
| 含 `阻塞`/`blocked`/`等待`/`卡在` | `blocker` |
| 含 `纠正`/`修正`/`之前判断有误`/`更正` | `correction` |
| 其他 | `info` |

### 2.3 保留规则（必留类）

`status_change`、`decision`、`blocker`、`correction` 四类条目**原文保留**，不做内容修改。但：
- 移除冗余的上下文信息（如果原文重复了其他条目已说明的背景）
- 保留所有 `reason` 和 `impact` 字段

### 2.4 合并规则（info 类）

info 类条目是压缩的主要目标。合并策略：

**Step A: 因果链检测**

如果一条 info 是后续 decision/blocker/status_change 的前因，标记为 `info_causal`，保留。

判定方法：如果一条 info 的内容被后续必留条目的 `reason` 字段引用或语义关联，则为因果链成员。

**Step B: 同主题合并**

剩余 info 按以下规则合并：
- 同一天、同一主题的多条 info → 合并为一条，保留最终结论
- 连续的进度更新（如"已完成 3/7"、"已完成 5/7"）→ 只保留最新一条
- 日常状态报告（无异常）→ 合并为 `[info] {日期范围}期间正常推进，无异常`

**Step C: 时间衰减**

超过 60 天的 info（非因果链成员）→ 直接丢弃（不进入压缩输出）

### 2.5 压缩率判定

```
压缩率 = 压缩后 token 数 / 压缩前 token 数

如果压缩率 > 0.7（压缩效果不足 30%）：
  → 说明大部分条目都是必留类，规则压缩已尽力
  → 不触发 LLM Fallback（因为没有多少可压的内容）

如果压缩率 < 0.3 且必留条目中有长叙事链（单条 > 200 tokens）：
  → 触发 LLM Fallback 对长叙事链做二次摘要
```

---

## 3. 压缩输出文件格式

### 3.1 文件结构

```markdown
---
node_id: task-a1b2
compressed_at: 2026-03-20T02:00:00+08:00
covers: 2026-01-15T10:00:00+08:00 ~ 2026-03-17T23:59:59+08:00
source_entry_range: 1-42
source_entry_count: 42
output_entry_count: 12
method: rule
compression_ratio: 0.28
---

## 关键决策

- [2026-03-15] 采用方案B（多币种+成本可控） | 方案A不支持多币种,方案C成本超预算

## 状态变迁

- [2026-03-18] active → blocked | 等待合作方 API 文档更新
- [2026-03-01] draft → active | 技术评审通过，正式启动

## 阻塞记录

- [2026-03-10] 合作方 API 文档过时 | 已联系技术负责人，承诺48h更新 | 已解决(2026-03-12)

## 纠偏记录

（本周期无）

## 背景摘要

- 2026-01-15 ~ 2026-02-28 期间完成方案调研，正常推进无异常
- 合作方响应速度慢（平均48h），是持续风险因素
```

### 3.2 Frontmatter 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `node_id` | string | 对应节点 ID |
| `compressed_at` | ISO 8601 | 本次压缩执行时间 |
| `covers` | 时间范围 | 本次压缩覆盖的叙事时间窗口 |
| `source_entry_range` | string | 原始条目序号范围 |
| `source_entry_count` | int | 压缩前条目数 |
| `output_entry_count` | int | 压缩后条目数 |
| `method` | `rule` / `llm` / `rule+llm` | 生成方式 |
| `compression_ratio` | float | token 压缩率 |

### 3.3 Section 顺序

固定为：关键决策 → 状态变迁 → 阻塞记录 → 纠偏记录 → 背景摘要。空 section 用`（本周期无）`标注，不省略 section 标题（保持结构一致，方便程序解析）。

### 3.4 增量追加

压缩文件支持增量。每次新压缩的内容**追加到对应 section 末尾**（按时间升序），frontmatter 更新 `covers` 范围和计数。不重写整个文件。

---

## 4. LLM Fallback 规格

### 4.1 触发条件

仅在以下场景触发：

1. 必留条目中存在**长叙事链**（单条 > 200 tokens，或因果链 > 5 条且总 token > 1000）
2. 规则压缩后压缩率仍 < 0.3，且长叙事链是主要原因

不触发的场景：
- 规则压缩率 > 0.3（已经够好）
- 规则压缩率 > 0.7（没什么可压的）
- 当前节点处于 primary focus（不在焦点节点上做 LLM 压缩，避免竞争）

### 4.2 Prompt 模板

```
你是一个项目管理助手，负责将详细的任务叙事压缩为高密度摘要。

## 规则
1. 保留所有决策及其原因
2. 保留当前未解决的风险和阻塞
3. 保留状态变更的时间线
4. 丢弃中间过程、已解决且无后续影响的问题、日常正常运转记录
5. 输出格式必须与以下模板一致

## 输入叙事
{entries}

## 输出模板
### 摘要
- [日期] 事件描述

请按以上模板输出，不要添加额外解释。
```

### 4.3 输出校验

LLM 输出必须满足：
1. **格式校验**：每行以 `- [日期]` 开头
2. **信息保真**：输出中的日期必须存在于输入的日期范围内
3. **长度约束**：输出 token < 输入 token × 0.5（至少压缩一半）
4. **无幻觉检查**：输出中提到的实体名（人名、方案名、数字）必须存在于输入中

校验失败 → 丢弃 LLM 输出，使用规则压缩结果。记录失败事件。

### 4.4 LLM 选择

- 默认：**Claude API（Haiku）** — 成本低、速度快、压缩质量足够
- 模型可配置（如需更高质量可切换 Sonnet）
- API 不可用时 → 跳过 LLM Fallback，只用规则压缩结果，下轮 Heartbeat 重试
- **数据安全注意**：压缩内容通过 Anthropic API 传输，如有高度敏感节点可在节点上标记 `no_llm_compression = true` 跳过 LLM Fallback

---

## 5. 调度模型

### 5.1 调度方式

**选择：Heartbeat 附带扫描，不独立 Cron。**

理由：
- 系统已有 Heartbeat 周期性检查机制（Anti-Amnesia, risk 重算）
- 压缩是低优先级任务，搭载在 Heartbeat 尾部即可
- 避免引入新的调度进程

### 5.2 扫描逻辑

每次 Heartbeat 执行完核心检查（risk, stale, anti-amnesia）后，进入压缩扫描：

```
Step 1: 查询 needs_compression = true 的节点列表
Step 2: 排除当前 primary/secondary focus 的节点
Step 3: 按优先级排序：
        - entry_count 越大越优先
        - last_compressed_at 越旧越优先
Step 4: 取 top-3（每轮最多处理 3 个节点，防止 Heartbeat 延迟）
Step 5: 对每个节点执行规则压缩
Step 6: 如需 LLM Fallback，提交异步任务（不阻塞 Heartbeat）
```

### 5.3 频率控制

- Heartbeat 默认周期：每小时一次
- 压缩扫描随 Heartbeat 触发，但每个节点**24 小时内最多压缩一次**（防止反复压缩正在活跃更新的节点）
- LLM Fallback 异步任务超时：60 秒。超时 → 丢弃，下轮重试

### 5.4 状态标记

| 标记 | 含义 | 谁设置 | 谁消费 |
|------|------|--------|--------|
| `needs_compression` | 节点叙事超标，需要压缩 | FR-2 膨胀检测 | 压缩调度器 |
| `last_compressed_at` | 上次压缩游标 | 压缩完成后 | 下次压缩时读取 |
| `compression_in_progress` | 正在压缩中（防并发） | 压缩开始时 | Heartbeat 跳过该节点 |

---

## 6. 端到端示例

### 场景

节点 `task-a1b2`，从 1月15日 创建到 3月20日，累积了 47 条叙事，触发 `needs_compression`。

### 流程

**Step 1: Heartbeat 扫描**
- Heartbeat 发现 `task-a1b2` 的 `needs_compression = true`
- 检查：不在 primary/secondary focus → 可以压缩
- 检查：`last_compressed_at = null`（从未压缩过）→ 处理全部 47 条

**Step 2: 读取原始叙事**
- 读取 `narratives/task-a1b2.md`
- 记录当前 `updated_at`（Anti-TOCTOU）
- 解析出 47 条 entries

**Step 3: 分类**
- status_change: 3 条
- decision: 2 条
- blocker: 2 条
- correction: 0 条
- info: 40 条

**Step 4: 保留必留条目**
- 7 条原文保留

**Step 5: 合并 info**
- 因果链检测：5 条 info 被后续 decision/blocker 引用 → 保留
- 同主题合并：15 条进度更新 → 合并为 3 条
- 时间衰减：8 条 60 天前的 info（非因果链）→ 丢弃
- 剩余 12 条 → 合并为 4 条背景摘要

**Step 6: 组装输出**
- 7（必留）+ 5（因果链 info）+ 3（合并进度）+ 4（背景）= 19 条
- 原始 47 条 → 19 条，压缩率约 0.4

**Step 7: 压缩率判定**
- 0.4 在 0.3~0.7 之间 → 不触发 LLM Fallback

**Step 8: Anti-TOCTOU 检查**
- 再次检查 `updated_at` → 未变 → 安全写入

**Step 9: 写入**
- 写入 `narratives/task-a1b2.compressed.md`
- 更新节点 `last_compressed_at = 2026-03-20T02:00:00+08:00`
- 清除 `needs_compression` 标记
- 清除 `compression_in_progress` 标记

---

## 变更记录

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-03-20 | v1 | 初版：Narrative 格式、规则压缩算法、输出格式、LLM Fallback、调度模型 |
