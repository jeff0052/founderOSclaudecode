# Architecture Baseline

## 总体架构

```
GitHub / Notion / Telegram
        │
        ▼
Adapters / Sync Layer
        │
        ▼
FounderOS Cognitive Core
  - local graph
  - summaries
  - focus
  - alerts
  - compression
  - bundle assembly
        │
        ▼
Founder / Agent
```

## 设计立场

FounderOS 不拥有完整业务事实。

FounderOS 拥有的是“认知层状态”：跨工具关系、压缩记忆、焦点、提醒、上下文编排。

## 本地存什么

本地 SQLite 或本地文件只保存以下内容：
- `node_ref`
  - `node_id`
  - `source`
  - `source_id`
  - `source_url`
- `cognitive_fields`
  - `why`
  - `summary`
  - `next_step`
  - `owner_override`（仅当外部没有统一 owner）
- `graph`
  - `parent_id`
  - `depends_on`
- `runtime`
  - `focus_list`
  - `stash`
  - `last_alerts`
- `compression`
  - `compressed_summary`
  - `last_compressed_at`
  - `no_llm_compression`
- `sync_cache`
  - `cached_title`
  - `cached_status`
  - `source_synced_at`
  - `source_deleted`

## 不本地重复存什么

默认不把以下内容作为本地主事实源：
- 外部工具的任务主状态
- 外部正文全文
- 外部评论全文
- 外部附件
- 外部审计全历史

需要时可以缓存，但缓存只用于：
- 降级读取
- token 裁剪
- 最近一次同步快照

## 读路径

1. 选择当前 focus。
2. 读取本地认知层数据。
3. 对 focus 及其近邻节点实时拉取外部快照。
4. 本地认知层与外部快照合并。
5. 组装 L0 / L_Alert / L1 / L2。
6. 注入 Agent prompt 或返回 Founder 查看。

## 写路径

### 写本地

FounderOS 直接写本地认知层：
- why
- summary
- depends_on
- parent
- focus
- alerts dedup
- compressed_summary

### 写外部

FounderOS 只在以下场景写回外部：
- append comment / report
- write decision summary
- 明确授权的状态同步

默认策略：
- comment 写回可以先做
- status 双向同步后做
- 永远不要默认覆盖外部正文

## 同步策略

- 常规轮询：15 分钟
- focus 实时刷新：开启
- 同步失败：读取缓存并标记“可能过时”
- 外部删除：本地保留认知层，但标记 `source_deleted=true`

## 核心模块

- `adapters/`
  GitHub / Notion / Telegram 连接层
- `sync/`
  轮询、缓存、状态映射、降级
- `graph/`
  cross-tool parent / dependency
- `memory/`
  summary / why / compressed_summary
- `attention/`
  focus / stash / alert dedup
- `bundle/`
  Context Bundle 组装
- `writeback/`
  comment / summary 写回外部

## 最重要的不变量

1. 外部工具状态是事实源，本地镜像不是。
2. 本地 graph 与 cognitive fields 是 FounderOS 的核心资产。
3. 缓存丢失可以重建，graph 与 why 不可以随意覆盖。
4. 外部写回失败不影响本地认知层一致性。
5. Adapter 不可用时，系统降级但不应完全不可用。

## v1 只做哪些外部工具

- GitHub: 任务与代码执行主状态
- Notion: 文档与方案上下文
- Telegram: Founder 交互入口与提醒触达

## 暂不做

- 双向强一致状态同步
- 多人协作权限系统
- 外部工具全文镜像仓库
- 通用 RAG 平台
