# FPMS Module Interface Contracts

每个模块暴露的公共函数签名。Coding agent 只需要看它依赖的上游接口，不需要看实现。

---

## models.py — 数据模型

```python
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, field_validator

# --- Pydantic Models (Tool Call 输入校验) ---

class CreateNodeInput(BaseModel):
    """create_node Tool Call 的输入。Pydantic 自动做类型强转和校验。"""
    title: str
    node_type: str = "unknown"
    parent_id: Optional[str] = None
    is_root: bool = False
    summary: Optional[str] = None
    why: Optional[str] = None
    next_step: Optional[str] = None
    owner: Optional[str] = None
    deadline: Optional[str] = None

    @field_validator("node_type")
    @classmethod
    def check_node_type(cls, v: str) -> str:
        allowed = {"goal", "project", "milestone", "task", "unknown"}
        if v not in allowed:
            raise ValueError(f"node_type 必须是 {allowed} 之一，收到 '{v}'")
        return v

    @field_validator("deadline")
    @classmethod
    def check_deadline_format(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            # 验证 ISO 8601 格式
            from datetime import datetime as dt
            try:
                dt.fromisoformat(v)
            except ValueError:
                raise ValueError(f"deadline 必须是 ISO 8601 格式，收到 '{v}'。示例: '2026-03-20T18:00:00+08:00'")
        return v

class UpdateStatusInput(BaseModel):
    """update_status Tool Call 的输入。"""
    node_id: str
    new_status: str
    reason: Optional[str] = None
    is_root: Optional[bool] = None

    @field_validator("new_status")
    @classmethod
    def check_status(cls, v: str) -> str:
        allowed = {"inbox", "active", "waiting", "done", "dropped"}
        if v not in allowed:
            raise ValueError(f"status 必须是 {allowed} 之一，收到 '{v}'")
        return v

class UpdateFieldInput(BaseModel):
    """update_field Tool Call 的输入。"""
    node_id: str
    field: str
    value: Optional[str] = None

    @field_validator("field")
    @classmethod
    def check_field(cls, v: str) -> str:
        allowed = {"title", "summary", "why", "next_step", "owner", "deadline", "node_type"}
        if v not in allowed:
            raise ValueError(f"可修改字段: {allowed}，收到 '{v}'")
        return v

# --- Internal Dataclasses (内部数据传递) ---

@dataclass
class Node:
    id: str
    title: str
    status: str  # inbox|active|waiting|done|dropped
    node_type: str  # goal|project|milestone|task|unknown
    is_root: bool = False
    parent_id: Optional[str] = None
    summary: Optional[str] = None
    why: Optional[str] = None
    next_step: Optional[str] = None
    owner: Optional[str] = None
    deadline: Optional[str] = None  # ISO 8601
    is_persistent: bool = False
    created_at: str = ""      # ISO 8601 UTC
    updated_at: str = ""
    status_changed_at: str = ""
    archived_at: Optional[str] = None

@dataclass
class Edge:
    source_id: str
    target_id: str
    edge_type: str  # parent|depends_on
    created_at: str = ""

@dataclass
class ToolResult:
    success: bool
    command_id: str              # 幂等标识，调用方传入
    event_id: Optional[str] = None  # audit_outbox 中的事件 id
    data: Optional[dict] = None
    error: Optional[str] = None
    suggestion: Optional[str] = None  # Actionable: 下一步该调什么 Tool
    affected_nodes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)  # 非阻断警告

@dataclass
class Alert:
    node_id: str
    alert_type: str  # blocked|at_risk|stale|anti_amnesia
    message: str
    severity: int  # 1=highest
    first_seen: str  # ISO 8601

@dataclass
class ContextBundle:
    l0_dashboard: str       # markdown
    l_alert: str            # markdown
    l1_neighborhood: str    # markdown
    l2_focus: str            # markdown
    total_tokens: int
    focus_node_id: Optional[str] = None
```

---

## schema.py — 数据库初始化

```python
def init_db(db_path: str) -> sqlite3.Connection:
    """创建/打开 SQLite 数据库，建表，启用 WAL 模式。
    如果表已存在则跳过。返回连接对象。"""

def get_connection(db_path: str) -> sqlite3.Connection:
    """获取已初始化的数据库连接。"""
```

---

## store.py — 数据持久化

```python
class Store:
    def __init__(self, db_path: str, events_path: str):
        """初始化 Store，连接 SQLite + events.jsonl 路径。"""

    # --- Node CRUD ---
    def create_node(self, node: Node) -> Node:
        """插入新节点。自动生成 id/timestamps。原子写入 DB + events。"""

    def get_node(self, node_id: str) -> Node | None:
        """按 id 查询单个节点。"""

    def update_node(self, node_id: str, fields: dict) -> Node:
        """更新节点指定字段。自动更新 updated_at。原子写入 DB + events。"""

    def list_nodes(self, filters: dict | None = None,
                   order_by: str = "updated_at",
                   limit: int = 50, offset: int = 0) -> list[Node]:
        """条件查询节点列表。filters 支持 status/node_type/parent_id/is_root/archived。"""

    # --- Edge CRUD ---
    def add_edge(self, edge: Edge) -> Edge:
        """添加边。原子写入 DB + events。"""

    def remove_edge(self, source_id: str, target_id: str, edge_type: str) -> bool:
        """删除边。返回是否删除成功。"""

    def get_edges(self, node_id: str, edge_type: str | None = None,
                  direction: str = "outgoing") -> list[Edge]:
        """查询节点关联的边。direction: outgoing|incoming|both。"""

    # --- Graph Queries ---
    def get_children(self, node_id: str, include_archived: bool = False) -> list[Node]:
        """获取直接子节点。"""

    def get_parent(self, node_id: str) -> Node | None:
        """获取父节点。"""

    def get_dependencies(self, node_id: str) -> list[Node]:
        """获取 depends_on 目标节点列表。"""

    def get_dependents(self, node_id: str) -> list[Node]:
        """获取依赖本节点的节点列表（反向）。"""

    def get_siblings(self, node_id: str) -> list[Node]:
        """获取同级节点（同 parent）。"""

    def get_all_edges(self) -> list[Edge]:
        """获取全部边，用于 DAG 检测。"""

    def get_ancestors(self, node_id: str) -> list[str]:
        """获取所有祖先节点 id（递归向上）。"""

    def get_descendants(self, node_id: str) -> list[str]:
        """获取所有后代节点 id（递归向下）。"""

    # --- Session State ---
    def get_session(self, key: str) -> dict | None:
        """读取 session_state 中的 JSON 值。"""

    def set_session(self, key: str, value: dict) -> None:
        """写入 session_state。"""

    # --- Transaction (Context Manager) ---
    @contextmanager
    def transaction(self) -> Generator[None, None, None]:
        """事务上下文管理器。用法: with store.transaction(): ...
        成功自动 commit，异常自动 rollback。
        禁止使用裸 begin/commit/rollback。"""

    # --- Audit Outbox ---
    def write_event(self, event: dict) -> None:
        """写入审计事件到 audit_outbox 表（SQLite 内）。
        必须在 transaction() 上下文内调用。
        事后由 flush_events() 异步写入 events.jsonl。"""

    def flush_events(self) -> int:
        """将 audit_outbox 中未 flush 的事件写入 events.jsonl。
        返回 flush 的事件数。可在心跳或 post-commit 时调用。"""
```

---

## validator.py — 校验层

```python
class ValidationError(Exception):
    """校验失败时抛出。包含 code, message, suggestion。
    message 必须是 Actionable Error：告诉 LLM 哪里错了 + 下一步该调什么工具。"""
    code: str       # e.g. "MISSING_SUMMARY", "CYCLE_DETECTED"
    message: str    # 人/LLM 可读的完整错误描述
    suggestion: str # 修复建议，e.g. "请先调用 update_field(...) 补充 summary"

def validate_status_transition(current: str, target: str, node: Node,
                                children: list[Node]) -> None:
    """校验状态迁移合法性。不合法则 raise ValidationError（含 actionable suggestion）。
    - inbox→active/waiting: 需要 summary + (parent_id OR is_root)
    - →done: 所有子节点必须终态
    - →dropped: 警告但允许（返回 warnings）
    - done→active / dropped→inbox: 需要 reason
    """

def validate_dag_safety(store: Store, source_id: str, target_id: str,
                         edge_type: str) -> None:
    """统一 DAG 环路检测（合并 parent + depends_on 图）。
    使用 SQLite WITH RECURSIVE CTE 在数据库层检测环路。
    有环则 raise ValidationError。"""

def validate_xor_constraint(is_root: bool, parent_id: str | None) -> None:
    """检查 is_root 和 parent_id 互斥。违反则 raise ValidationError。"""

def validate_active_domain(node: Node) -> None:
    """检查目标节点非归档状态。已归档则 raise ValidationError。"""

def validate_attach(store: Store, node_id: str, new_parent_id: str) -> None:
    """综合校验 attach: 活跃域 + DAG 安全 + XOR。"""

def validate_dependency(store: Store, source_id: str, target_id: str) -> None:
    """综合校验 add_dependency: 活跃域 + DAG 安全 + 不能自依赖。"""
```

---

## narrative.py — 叙事文件管理

```python
def append_narrative(narratives_dir: str, node_id: str,
                      timestamp: str, event_type: str,
                      content: str, mentions: list[str] | None = None) -> bool:
    """追加一条叙事到 narratives/{node_id}.md。
    格式: ## {timestamp} [{event_type}]\n{content}
    返回是否写入成功。失败时不抛异常，返回 False。"""

def read_narrative(narratives_dir: str, node_id: str,
                    last_n_entries: int | None = None,
                    since_days: int | None = None) -> str:
    """读取叙事内容。支持按条数或天数截取。"""

def read_compressed(narratives_dir: str, node_id: str) -> str | None:
    """读取压缩摘要 {node_id}.compressed.md。不存在返回 None。"""

def write_compressed(narratives_dir: str, node_id: str, content: str) -> None:
    """写入压缩摘要。"""

def write_repair_event(narratives_dir: str, node_id: str,
                        original_event: dict, error: str) -> None:
    """写入修复事件记录。当 narrative 写入失败时调用。"""
```

---

## risk.py — 风险标记计算

```python
@dataclass
class RiskMarks:
    blocked: bool       # depends_on 有非 done 目标
    at_risk: bool       # deadline < NOW()+48h
    stale: bool         # status_changed_at < NOW()-7d
    blocked_by: list[str]  # 阻塞来源 node_ids

def compute_risks(node: Node, dependencies: list[Node]) -> RiskMarks:
    """计算单个节点的风险标记。纯函数，无副作用。
    终态节点返回全 False。"""

def batch_compute_risks(store: Store, node_ids: list[str] | None = None) -> dict[str, RiskMarks]:
    """批量计算风险标记。node_ids=None 时计算所有活跃节点。"""
```

---

## rollup.py — 状态冒泡

```python
def compute_rollup(store: Store, node_id: str) -> str:
    """递归计算 rollup_status。
    规则: active > waiting > (skip inbox) > done > dropped
    归档子节点计入分母。返回 status 字符串。"""

def batch_compute_rollup(store: Store, root_ids: list[str] | None = None) -> dict[str, str]:
    """批量计算 rollup。root_ids=None 时计算所有根节点的子树。"""
```

---

## dashboard.py — 全局看板

```python
def render_dashboard(store: Store, max_tokens: int = 1000) -> str:
    """生成 L0 全局看板 markdown。
    - 树形缩进
    - 风险排序（blocked > at_risk > stale > normal）
    - 每个节点: status emoji + title + rollup + risk marks
    - 超预算时截断末尾 + 加 "...and N more"
    """
```

---

## heartbeat.py — 心跳扫描

```python
@dataclass
class HeartbeatResult:
    alerts: list[Alert]            # Top 3 排序后的告警
    focus_candidates: list[str]    # 建议焦点 node_ids
    suppressed_count: int          # 被去重压制的告警数

def scan(store: Store, session_state: dict) -> HeartbeatResult:
    """执行心跳扫描。
    - 复用 risk.py 计算
    - 去重（和 session_state.last_alerts 比对）
    - Anti-Amnesia: 24h 未处理的高优告警重推
    - append_log 不重置 Anti-Amnesia 计时器
    """
```

---

## focus.py — 焦点调度

```python
@dataclass
class FocusResult:
    primary: str | None            # 主焦点 node_id
    secondaries: list[str]         # 次焦点 (max 2)
    reason: str                    # 仲裁原因

def arbitrate(store: Store, session_state: dict,
              user_request: str | None = None,
              alert_candidates: list[str] | None = None) -> FocusResult:
    """焦点仲裁。
    优先级: user_request > alert_candidates > time_driven > historical
    LRU 淘汰: 焦点池 max 3
    衰减: 3 天无操作自动降级
    """

def shift_focus(store: Store, node_id: str) -> FocusResult:
    """用户主动切换焦点。最高优先级。"""
```

---

## bundle.py — 认知包组装

```python
def assemble(store: Store, focus: FocusResult,
             dashboard_md: str, alerts_md: str,
             max_tokens: int = 10000) -> ContextBundle:
    """组装完整认知包。
    顺序: L0 → L_Alert → L1 → L2
    裁剪铁律: 因果 > 关系
    裁剪顺序: siblings → children → depended_by → depends_on → parent
    """

def estimate_tokens(text: str) -> int:
    """估算 token 数。1 token ≈ 0.75 words (EN), ≈ 0.6 chars (CN)。"""
```

---

## archive.py — 归档管理

```python
def scan_archive_candidates(store: Store) -> list[str]:
    """扫描满足归档条件的节点 id 列表。
    条件: 终态 + 7d 冷却 + 无活跃依赖者 + 无活跃后代。
    排除 is_persistent=True。"""

def archive_nodes(store: Store, node_ids: list[str]) -> int:
    """执行归档。设置 archived_at=NOW()。返回归档数量。"""

def unarchive_node(store: Store, node_id: str,
                    new_status: str | None = None) -> Node:
    """解封节点。强制 status_changed_at=NOW()（防 GC 回旋镖）。
    可选原子设置新状态。"""
```

---

## recovery.py — 冷启动

```python
def bootstrap(store: Store, narratives_dir: str,
              max_tokens: int = 10000) -> ContextBundle:
    """冷启动全流程。
    1. 打开 SQLite
    2. 生成 L0 (dashboard)
    3. Heartbeat 扫描
    4. Focus 仲裁
    5. Bundle 组装
    6. 返回可注入的认知包
    局部降级不阻断（某步失败跳过，降级组装）。"""
```

---

## compression.py — 叙事压缩

```python
def compress_narrative(narratives_dir: str, node_id: str,
                        max_output_tokens: int = 500) -> str:
    """压缩叙事。
    优先规则压缩（去重复、去格式、保留关键事件）。
    规则不够时调用 LLM fallback。
    输出写入 {node_id}.compressed.md。
    幂等：多次调用结果一致。"""

def should_compress(narratives_dir: str, node_id: str,
                     threshold_tokens: int = 2000) -> bool:
    """判断是否需要压缩。当前叙事超过 threshold 才返回 True。"""
```

---

## command_executor.py — 串行命令执行器

```python
class CommandExecutor:
    def __init__(self, store: Store):
        """初始化串行执行器。所有写操作必须通过这里。"""

    def execute(self, command_id: str, tool_name: str, params: dict) -> ToolResult:
        """串行执行一个 Tool Call。
        1. 幂等检查：command_id 已存在 → 返回上次结果
        2. Pydantic 校验输入
        3. 路由到 ToolHandler
        4. 在同一事务内写入 facts + audit_outbox + recent_commands
        5. Post-commit: narrative append + flush events
        """
```

---

## tools.py — Tool Call 处理器

```python
class ToolHandler:
    def __init__(self, store: Store, validator_module, narrative_module,
                 risk_module, rollup_module, dashboard_module):
        """初始化，注入所有依赖。"""

    def handle(self, tool_name: str, params: dict) -> ToolResult:
        """路由 Tool Call 到对应 handler。返回 ToolResult。"""

    # --- Write Tools ---
    def handle_create_node(self, params: dict) -> ToolResult: ...
    def handle_update_status(self, params: dict) -> ToolResult: ...
    def handle_update_field(self, params: dict) -> ToolResult: ...
    def handle_attach_node(self, params: dict) -> ToolResult: ...
    def handle_detach_node(self, params: dict) -> ToolResult: ...
    def handle_add_dependency(self, params: dict) -> ToolResult: ...
    def handle_remove_dependency(self, params: dict) -> ToolResult: ...
    def handle_append_log(self, params: dict) -> ToolResult: ...
    def handle_unarchive(self, params: dict) -> ToolResult: ...
    def handle_set_persistent(self, params: dict) -> ToolResult: ...

    # --- Runtime Tools ---
    def handle_shift_focus(self, params: dict) -> ToolResult: ...
    def handle_expand_context(self, params: dict) -> ToolResult: ...

    # --- Read Tools ---
    def handle_get_node(self, params: dict) -> ToolResult: ...
    def handle_search_nodes(self, params: dict) -> ToolResult: ...
```

---

## SpineEngine — 总控入口

```python
class SpineEngine:
    def __init__(self, db_path: str = "fpms/db/fpms.db",
                 events_path: str = "fpms/events.jsonl",
                 narratives_dir: str = "fpms/narratives"):
        """初始化引擎。创建 Store + 加载所有模块。"""

    def execute_tool(self, tool_name: str, params: dict) -> ToolResult:
        """执行 Tool Call。入口方法。"""

    def get_context_bundle(self, user_focus: str | None = None) -> ContextBundle:
        """获取当前认知包。可选指定焦点。"""

    def heartbeat(self) -> HeartbeatResult:
        """执行心跳。返回告警和焦点建议。"""

    def bootstrap(self) -> ContextBundle:
        """冷启动。返回初始认知包。"""
```
