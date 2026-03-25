# FounderOS 全阶段任务拆解

*按 PRD-context-lifecycle §4 原则拆解：每个任务 context ≤ 100k tokens（执行型），在信息边界处切割。*

---

## 拆解方法论回顾

```
Step 1: 识别任务类型 → 确定 token 预算
  执行型 100k / 分析型 150k / 检索型 500k（见 SYSTEM-CONFIG.md）

Step 2: 估算 context 载荷
  固定开销 ~5k + 任务 context ~10k + 工作载荷 = 总计

Step 3: 总计 > 预算 × 85%？
  是 → 找信息边界（不同域 > 不同文件 > 不同 PRD > 不同阶段），拆
  否 → 粒度合适，可执行

Step 4: 每个子任务自给自足
  拿起来不需要额外翻找就能开工
```

---

## 全局依赖图

> v0 骨架引擎的详细拆解见 `v0-task-breakdown.md`，此处只覆盖 v1 ~ M3。

```
v1 认知层（前置：v0 全部完成）
├── T1.1 risk.py + rollup.py ───────┐
├── T1.2 dashboard.py ──────────────┤ 并行
│                                   ↓
├── T1.3 heartbeat.py ──────────────┤ 依赖 T1.1
├── T1.4 focus.py ──────────────────┤ 并行
│                                   ↓
├── T1.5 bundle.py（Context 组装）──┤ 依赖 T1.1~T1.4
├── T1.6 archive.py + recovery.py ──┤ 并行
└── T1.7 v1 集成验证 ──────────────┘ 依赖全部

M1 GitHub 集成
├── T-M1.1 Adapter 基础设施 ────────┐
├── T-M1.2 GitHub Adapter ──────────┤ 依赖 T-M1.1
├── T-M1.3 跨源 Context 装载 ───────┤ 依赖 T-M1.2
└── T-M1.4 M1 集成验证 ────────────┘ 依赖全部

M2 Notion + 跨源
├── T-M2.1 Notion Adapter ──────────┐
├── T-M2.2 跨源 Heartbeat + Rollup ─┤ 依赖 T-M2.1
├── T-M2.3 compression.py ──────────┤ 并行
└── T-M2.4 M2 集成验证 ────────────┘ 依赖全部

M3 写回闭环
├── T-M3.1 write_comment 写回 ──────┐
├── T-M3.2 状态映射配置化 ──────────┤ 并行
├── T-M3.3 离线降级 + 队列 ─────────┤ 依赖 T-M3.1
├── T-M3.4 Assembly Trace 完善 ─────┤ 并行
└── T-M3.5 M3 集成验证 ────────────┘ 依赖全部
```

---

## v1: 认知层

### T1.1 risk.py + rollup.py

**类型**: 执行型（100k）
**信息边界**: 同一领域（风险检测 + 状态冒泡紧耦合，放一起）

| Context 包项目 | 来源 | 估算 tokens |
|---------------|------|------------|
| CLAUDE.md | 固定 | ~5k |
| PRD-functional §FR-4（风险标记） | PRD | ~5k |
| PRD-functional §FR-3（状态冒泡 rollup） | PRD | ~5k |
| INTERFACES.md §risk.py + §rollup.py 签名 | 架构 | ~5k |
| store.py 接口签名（依赖） | 上游 | ~5k |
| 测试文件 | TW产出 | ~15k |
| **总计** | | **~40k** ✅ |

**测试重点**:
- `blocked` / `at-risk` / `stale` 检测逻辑
- rollup 递归冒泡：子全 done → 父 done；子有 blocked → 父标记 at-risk
- stale 阈值引用 SYSTEM-CONFIG `heartbeat.stale_threshold`
- 多层嵌套 rollup 正确性

**产出**: `spine/risk.py` + `spine/rollup.py` + 测试

---

### T1.2 dashboard.py

**类型**: 执行型（100k）
**信息边界**: 不同领域 — 渲染/展示 vs 计算逻辑

| Context 包项目 | 来源 | 估算 tokens |
|---------------|------|------------|
| CLAUDE.md | 固定 | ~5k |
| PRD-functional §FR-7（L0 全局视图） | PRD | ~5k |
| INTERFACES.md §dashboard.py 签名 | 架构 | ~3k |
| store.py + risk.py + rollup.py 接口签名 | 上游 | ~8k |
| 测试文件 | TW产出 | ~10k |
| **总计** | | **~31k** ✅ |

**测试重点**:
- L0 树形渲染输出格式正确
- 包含 risk_mark、进度百分比
- 大树（100+ 节点）渲染不超时
- 归档节点不出现在活跃视图

**产出**: `spine/dashboard.py` + 测试

---

### T1.3 heartbeat.py

**类型**: 执行型（100k）
**信息边界**: 不同领域 — 定时扫描 vs 风险计算

| Context 包项目 | 来源 | 估算 tokens |
|---------------|------|------------|
| CLAUDE.md | 固定 | ~5k |
| PRD-functional §FR-8（心跳） + §FR-9（Anti-Amnesia） | PRD | ~8k |
| SYSTEM-CONFIG.md §heartbeat + §anti_amnesia | 配置 | ~3k |
| INTERFACES.md §heartbeat.py 签名 | 架构 | ~3k |
| risk.py + rollup.py 接口签名（依赖） | 上游 | ~5k |
| store.py 接口签名 | 上游 | ~5k |
| 测试文件 | TW产出 | ~12k |
| **总计** | | **~41k** ✅ |

**测试重点**:
- 扫描间隔读取 SYSTEM-CONFIG（不硬编码）
- stale 节点检测 + 告警生成
- Anti-Amnesia：遗忘节点提醒 + 去重（不重复提醒同一个节点）
- 打断条件：depended_by ≥ 阈值 / deadline 临近

**产出**: `spine/heartbeat.py` + 测试

---

### T1.4 focus.py

**类型**: 执行型（100k）
**信息边界**: 不同领域 — 注意力管理 vs 扫描告警

| Context 包项目 | 来源 | 估算 tokens |
|---------------|------|------------|
| CLAUDE.md | 固定 | ~5k |
| PRD-functional §FR-6（焦点仲裁） | PRD | ~8k |
| PRD-context-lifecycle §5（焦点切换） | PRD | ~5k |
| SYSTEM-CONFIG.md §focus | 配置 | ~2k |
| INTERFACES.md §focus.py 签名 | 架构 | ~3k |
| store.py 接口签名 | 上游 | ~5k |
| 测试文件 | TW产出 | ~12k |
| **总计** | | **~40k** ✅ |

**测试重点**:
- 主焦点上限 1、次焦点上限 2（读 SYSTEM-CONFIG）
- Stash LIFO 压栈/弹出
- Stash 衰减超时 → 写入叙事并移除
- shift_focus 切换后旧焦点进 stash

**产出**: `spine/focus.py` + 测试

---

### T1.5 bundle.py（Context 组装）

**类型**: 执行型（100k）
**信息边界**: 依赖 T1.1~T1.4 全部，但本身是独立的"组装"逻辑

| Context 包项目 | 来源 | 估算 tokens |
|---------------|------|------------|
| CLAUDE.md | 固定 | ~5k |
| PRD-functional §FR-10（Context 组装 + Assembly Trace） | PRD | ~10k |
| PRD-context-lifecycle §3（生命周期） | PRD | ~8k |
| SYSTEM-CONFIG.md §budget | 配置 | ~3k |
| INTERFACES.md §bundle.py 签名 | 架构 | ~5k |
| risk.py + rollup.py + dashboard.py + heartbeat.py + focus.py 接口签名 | 上游 | ~15k |
| store.py + narrative.py 接口签名 | 上游 | ~8k |
| 测试文件 | TW产出 | ~15k |
| **总计** | | **~69k** ✅ |

**测试重点**:
- L0 / L_Alert / L1 / L2 四层组装顺序正确
- Token 裁剪：总 budget 超限时按优先级裁剪
- Assembly Trace 生成：loaded_nodes、tokens_per_layer、trimmed_items
- assembly_traces.jsonl 写入 + 7 天保留
- 空数据库（冷启动）不崩溃

**产出**: `spine/bundle.py` + 测试

---

### T1.6 archive.py + recovery.py

**类型**: 执行型（100k）
**信息边界**: 同一领域（数据生命周期管理 — 归档 + 冷启动恢复紧耦合）

| Context 包项目 | 来源 | 估算 tokens |
|---------------|------|------------|
| CLAUDE.md | 固定 | ~5k |
| PRD-functional §FR-6（归档） + §FR-12（冷启动恢复） | PRD | ~8k |
| SYSTEM-CONFIG.md §archive | 配置 | ~2k |
| INTERFACES.md §archive.py + §recovery.py 签名 | 架构 | ~5k |
| store.py + bundle.py 接口签名 | 上游 | ~8k |
| 测试文件 | TW产出 | ~12k |
| **总计** | | **~40k** ✅ |

**测试重点**:
- 自动归档：done 超过 7 天 + 入度=0 → 归档
- 归档不破坏热区（invariant）
- unarchive 恢复 + status_changed_at 更新
- 冷启动恢复：DB → 组装 context → 输出可用认知包

**产出**: `spine/archive.py` + `spine/recovery.py` + 测试

---

### T1.7 v1 集成验证

**类型**: 分析型（150k）— 不写新代码，验证全局
**信息边界**: 跨全部模块的端到端验证

| Context 包项目 | 来源 | 估算 tokens |
|---------------|------|------------|
| CLAUDE.md | 固定 | ~5k |
| v0-acceptance.md | 验收 | ~3k |
| 全部 v0 + v1 模块实现 | 实现 | ~80k |
| 端到端测试脚本 | 新写 | ~15k |
| **总计** | | **~103k** ✅（分析型 150k 预算内） |

**验收场景**:
1. 冷启动 → 组装认知包 → 注入 prompt → Agent 可用
2. 创建多级节点树 → 修改子节点状态 → rollup 冒泡正确
3. 节点超时 → heartbeat 扫描 → 告警生成 → L_Alert 层注入
4. 切换焦点 → stash 保存 → 衰减超时 → 写入叙事
5. 归档 → unarchive → 重新进入热区

---

## M1: GitHub 集成

### T-M1.1 Adapter 基础设施

**类型**: 执行型（100k）
**信息边界**: 不同领域 — 基础设施（接口定义 + 基类） vs 具体实现

| Context 包项目 | 来源 | 估算 tokens |
|---------------|------|------------|
| CLAUDE.md | 固定 | ~5k |
| PRD-cognitive-engine §3~§5（架构 + 节点模型 + Adapter 接口） | PRD | ~12k |
| INTERFACES.md §Adapter 接口 | 架构 | ~8k |
| store.py + models.py 接口签名 | 上游 | ~8k |
| 测试文件 | TW产出 | ~10k |
| **总计** | | **~43k** ✅ |

**交付物**:
- `spine/adapters/__init__.py`
- `spine/adapters/base.py` — BaseAdapter ABC、NodeSnapshot、SourceEvent dataclass
- `spine/adapters/registry.py` — Adapter 注册/发现机制
- Node 模型扩展验证（source/source_id/source_url 字段已存在于 schema）

**测试重点**:
- BaseAdapter 接口不可实例化（ABC）
- Registry 注册 / 获取 / 未注册时报错
- NodeSnapshot 和 SourceEvent 数据结构校验

---

### T-M1.2 GitHub Adapter

**类型**: 执行型（100k）
**信息边界**: 不同领域 — GitHub API 交互 vs 基础设施

| Context 包项目 | 来源 | 估算 tokens |
|---------------|------|------------|
| CLAUDE.md | 固定 | ~5k |
| PRD-cognitive-engine §5（Adapter 接口）+ §6（同步策略） | PRD | ~8k |
| SYSTEM-CONFIG.md §sync | 配置 | ~3k |
| base.py + registry.py 实现（T-M1.1 产出） | 上游 | ~8k |
| GitHub REST API 参考（Issues/PRs 端点） | 外部参考 | ~10k |
| 测试文件 | TW产出 | ~15k |
| **总计** | | **~49k** ✅ |

**交付物**:
- `spine/adapters/github_adapter.py`
- 实现 `sync_node` / `list_updates` / `search`
- 状态映射：Open → active / Closed → done / Label:blocked → risk_mark:blocked

**测试重点**:
- sync_node：给定 `octocat/repo#42` → 拉取 Issue → 返回 NodeSnapshot
- list_updates：返回指定时间后的变更事件
- 状态映射正确性（含边界：无 Label 时默认映射）
- API 超时 → 返回 cached 结果 + warning
- API 认证失败 → 明确错误信息

---

### T-M1.3 跨源 Context 装载

**类型**: 执行型（100k）
**信息边界**: 不同领域 — Context 组装（bundle.py 扩展） vs Adapter 实现

| Context 包项目 | 来源 | 估算 tokens |
|---------------|------|------------|
| CLAUDE.md | 固定 | ~5k |
| PRD-cognitive-engine §7（Context 装载跨源拉取） | PRD | ~5k |
| PRD-context-lifecycle §3.1（装载阶段） | PRD | ~5k |
| bundle.py 实现（v1 产出） | 上游 | ~15k |
| github_adapter.py 实现（T-M1.2 产出） | 上游 | ~10k |
| store.py 接口签名 | 上游 | ~5k |
| 测试文件 | TW产出 | ~12k |
| **总计** | | **~57k** ✅ |

**交付物**:
- bundle.py 扩展：装载时检测 node.source → 调用对应 Adapter.sync_node → 合并
- Assembly Trace 新增 `sync_status` 字段
- 离线降级 v1：Adapter 失败 → 用缓存 + `[数据可能过时]` 标注

**测试重点**:
- 本地节点 + GitHub 节点混合装载 → context 包完整
- GitHub 节点实时同步 → 最新标题/状态
- Adapter 超时 → 降级使用缓存，不阻塞
- Assembly Trace 记录同步耗时 + 成功/失败状态

---

### T-M1.4 M1 集成验证

**类型**: 分析型（150k）

**验收场景**:
1. 创建指向 GitHub Issue 的节点 → sync_node → context 包含外部数据
2. GitHub Issue 状态变更 → list_updates 捕获 → 本地节点同步
3. 本地节点 + GitHub 节点混合组成的树 → rollup 正确
4. 断网 → 降级使用缓存 → 不崩溃
5. Assembly Trace 完整记录跨源装载过程

---

## M2: Notion + 跨源

### T-M2.1 Notion Adapter

**类型**: 执行型（100k）

| Context 包项目 | 来源 | 估算 tokens |
|---------------|------|------------|
| CLAUDE.md | 固定 | ~5k |
| PRD-cognitive-engine §5~§6 | PRD | ~8k |
| base.py + registry.py + github_adapter.py（参考实现） | 上游 | ~20k |
| Notion API 参考（Pages/Databases 端点） | 外部参考 | ~10k |
| 测试文件 | TW产出 | ~12k |
| **总计** | | **~55k** ✅ |

**交付物**:
- `spine/adapters/notion_adapter.py`
- 实现 `sync_node` / `list_updates` / `search`
- Notion Page 属性映射 → FounderOS 节点字段

---

### T-M2.2 跨源 Heartbeat + Rollup

**类型**: 执行型（100k）

| Context 包项目 | 来源 | 估算 tokens |
|---------------|------|------------|
| CLAUDE.md | 固定 | ~5k |
| heartbeat.py + rollup.py 实现（v1 产出） | 上游 | ~20k |
| github_adapter.py + notion_adapter.py 接口签名 | 上游 | ~10k |
| SYSTEM-CONFIG.md §heartbeat + §sync | 配置 | ~3k |
| 测试文件 | TW产出 | ~12k |
| **总计** | | **~50k** ✅ |

**交付物**:
- heartbeat.py 扩展：扫描时同时触发外部同步（频率 = sync.poll_interval）
- rollup.py 扩展：子节点跨 GitHub + Notion 时冒泡仍然正确
- 同步结果缓存（避免 heartbeat 每次都请求外部 API）

---

### T-M2.3 compression.py

**类型**: 执行型（100k）
**信息边界**: 完全不同的领域 — 压缩 vs 同步

| Context 包项目 | 来源 | 估算 tokens |
|---------------|------|------------|
| CLAUDE.md | 固定 | ~5k |
| PRD-compression-spec 全文 | PRD | ~15k |
| SYSTEM-CONFIG.md §compress | 配置 | ~3k |
| narrative.py 实现（v0 产出） | 上游 | ~10k |
| store.py 接口签名 | 上游 | ~5k |
| 测试文件 | TW产出 | ~15k |
| **总计** | | **~53k** ✅ |

**交付物**:
- `spine/compression.py`
- 规则压缩（合并连续同状态日志、删除冗余）
- LLM Fallback（规则压缩后仍超标 → 调用 LLM 生成摘要）
- 压缩触发条件：context token 超过 budget（不是对话轮数）

---

### T-M2.4 M2 集成验证

**类型**: 分析型（150k）

**验收场景**:
1. Notion Page 变更 → FounderOS 节点同步更新
2. 跨 GitHub + Notion 的节点树 → rollup 正确
3. Heartbeat 一次扫描同时检查 GitHub + Notion + 本地节点
4. 叙事压缩后 context 缩小到目标比例

---

## M3: 写回闭环

### T-M3.1 write_comment 写回

**类型**: 执行型（100k）

| Context 包项目 | 来源 | 估算 tokens |
|---------------|------|------------|
| CLAUDE.md | 固定 | ~5k |
| PRD-cognitive-engine §8（写回策略） | PRD | ~5k |
| PRD-context-lifecycle §3.5（退出上报） | PRD | ~3k |
| base.py（增加 write_comment 接口） | 上游 | ~5k |
| github_adapter.py + notion_adapter.py | 上游 | ~20k |
| 测试文件 | TW产出 | ~12k |
| **总计** | | **~50k** ✅ |

**交付物**:
- BaseAdapter 新增 `write_comment(node_id, content)` 方法
- GitHub: 写入 Issue Comment
- Notion: 写入 Page Block
- 退出上报自动触发写回

---

### T-M3.2 状态映射配置化

**类型**: 执行型（100k）

| Context 包项目 | 来源 | 估算 tokens |
|---------------|------|------------|
| CLAUDE.md | 固定 | ~5k |
| 当前硬编码的映射逻辑（github_adapter + notion_adapter） | 上游 | ~15k |
| YAML 配置设计 | 新设计 | ~5k |
| 测试文件 | TW产出 | ~10k |
| **总计** | | **~35k** ✅ |

**交付物**:
- `config/status_mappings.yaml` — 外部状态 ↔ FounderOS 状态映射规则
- Adapter 读取配置而非硬编码
- 支持自定义字段映射（不只是 status）

---

### T-M3.3 离线降级 + 队列

**类型**: 执行型（100k）

| Context 包项目 | 来源 | 估算 tokens |
|---------------|------|------------|
| CLAUDE.md | 固定 | ~5k |
| 当前降级逻辑（bundle.py + adapters） | 上游 | ~20k |
| write_comment 实现（T-M3.1 产出） | 上游 | ~10k |
| 测试文件 | TW产出 | ~12k |
| **总计** | | **~47k** ✅ |

**交付物**:
- 写回队列：离线时暂存到 SQLite `write_queue` 表
- 恢复后自动重试（指数退避）
- 重试上限 + 死信记录
- 缓存 TTL 引用 SYSTEM-CONFIG `sync.cache_ttl`

---

### T-M3.4 Assembly Trace 完善

**类型**: 执行型（100k）

| Context 包项目 | 来源 | 估算 tokens |
|---------------|------|------------|
| CLAUDE.md | 固定 | ~5k |
| PRD-functional §FR-10（Assembly Trace） | PRD | ~5k |
| bundle.py 实现 | 上游 | ~15k |
| 测试文件 | TW产出 | ~10k |
| **总计** | | **~35k** ✅ |

**交付物**:
- `get_assembly_trace` 查询工具完善
- 可观测性面板输出格式：加载了什么 / 多少 tokens / 裁剪了什么 / 同步状态
- 7 天自动清理
- 性能基准：每次装载的 Trace 开销 < 5ms

---

### T-M3.5 M3 集成验证

**类型**: 分析型（150k）

**验收场景**:
1. Agent 完成任务 → 退出上报 → GitHub Issue Comment 自动写入
2. 修改 status_mappings.yaml → 下次同步按新映射执行
3. 断网 → 写回入队 → 恢复后自动重试成功
4. Assembly Trace 完整记录全流程
5. 端到端：冷启动 → 装载跨源 context → 执行 → 写回外部 → 压缩 → 完成

---

## 汇总

| 阶段 | 任务数 | 并行度 | Agent Sessions | 预计时间 |
|------|-------|--------|---------------|---------|
| **v1** | 7 | 最多 2 并行 | ~12 | 3-4h |
| **M1** | 4 | 最多 1 并行 | ~7 | 2-3h |
| **M2** | 4 | 最多 2 并行 | ~7 | 2-3h |
| **M3** | 5 | 最多 2 并行 | ~9 | 3-4h |
| **总计** | **20** | | **~35** | **10-14h** |

> v0 另有 8 个任务（详见 `v0-task-breakdown.md`），预计 2-3h。

> **说明**：每个任务遵循 Test-First 模式（先 TW agent 写测试 → 再 Impl agent 实现 → 测试全绿），所以 Agent Sessions ≈ 任务数 × 2。集成验证由主 agent 执行，不额外 spawn。

---

## 变更记录

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-03-21 | v1 | 初版：v0~M3 全阶段 28 个任务拆解，含 token 预算估算 |
