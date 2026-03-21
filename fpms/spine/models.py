"""数据模型 — Node, Edge, ToolResult dataclasses + Pydantic 输入校验模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from pydantic import BaseModel, field_validator


# ---------------------------------------------------------------------------
# Pydantic Models (Tool Call 输入校验)
# ---------------------------------------------------------------------------

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
    source: str = "internal"
    source_id: Optional[str] = None
    source_url: Optional[str] = None

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
            from datetime import datetime as dt

            try:
                dt.fromisoformat(v)
            except ValueError:
                raise ValueError(
                    f"deadline 必须是 ISO 8601 格式，收到 '{v}'。"
                    "示例: '2026-03-20T18:00:00+08:00'"
                )
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


# ---------------------------------------------------------------------------
# Internal Dataclasses (内部数据传递)
# ---------------------------------------------------------------------------

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
    created_at: str = ""  # ISO 8601 UTC
    updated_at: str = ""
    status_changed_at: str = ""
    archived_at: Optional[str] = None
    # 外部源指针
    source: str = "internal"
    source_id: Optional[str] = None
    source_url: Optional[str] = None
    source_synced_at: Optional[str] = None
    source_deleted: bool = False
    # 压缩控制
    needs_compression: bool = False
    compression_in_progress: bool = False
    no_llm_compression: bool = False
    # 标签
    tags: list[str] = field(default_factory=list)


@dataclass
class Edge:
    source_id: str
    target_id: str
    edge_type: str  # parent|depends_on
    created_at: str = ""


@dataclass
class ToolResult:
    success: bool
    command_id: str
    event_id: Optional[str] = None
    data: Optional[dict] = None
    error: Optional[str] = None
    suggestion: Optional[str] = None
    affected_nodes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class Alert:
    node_id: str
    alert_type: str  # blocked|at_risk|stale|anti_amnesia
    message: str
    severity: int  # 1=highest
    first_seen: str  # ISO 8601


@dataclass
class ContextBundle:
    l0_dashboard: str
    l_alert: str
    l1_neighborhood: str
    l2_focus: str
    total_tokens: int
    focus_node_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Cognitive Layer Dataclasses (v1)
# ---------------------------------------------------------------------------

@dataclass
class RiskMarks:
    blocked: bool = False
    at_risk: bool = False
    stale: bool = False
    blocked_by: list[str] = field(default_factory=list)
    deadline_hours: float | None = None


@dataclass
class RollupResult:
    node_id: str
    rollup_status: str  # inbox|active|waiting|done|dropped
    has_risk_children: bool = False
    risk_summary: list[str] = field(default_factory=list)


@dataclass
class FocusState:
    primary: str | None = None
    secondary: list[str] = field(default_factory=list)
    stash: list[dict] = field(default_factory=list)  # [{node_id, stashed_at, reason}]
    last_touched: dict[str, str] = field(default_factory=dict)  # node_id → ISO timestamp


@dataclass
class HeartbeatAlert:
    alert_type: str  # urgent_deadline|critical_blocked|deadline_warning|stale_warning|inbox_stale
    severity: int    # 1=highest, 5=lowest
    node_id: str
    message: str
    suggested_action: str


@dataclass
class DedupeRecord:
    alert_type: str
    node_id: str
    last_pushed_at: str   # ISO timestamp
    last_acted_at: str    # ISO timestamp — reset ONLY on substantive action


@dataclass
class HeartbeatResult:
    alerts: list[HeartbeatAlert] = field(default_factory=list)
    focus_candidates: list[str] = field(default_factory=list)
    archive_candidates: list[str] = field(default_factory=list)
    nodes_scanned: int = 0


# ---------------------------------------------------------------------------
# Adapter Data Structures (M1)
# ---------------------------------------------------------------------------

@dataclass
class NodeSnapshot:
    """External source snapshot — returned by Adapter.sync_node()."""
    source: str            # "github" | "notion"
    source_id: str         # external object ID (e.g. "octocat/repo#42")
    title: str
    status: str            # mapped to FounderOS status
    source_url: str | None = None
    assignee: str | None = None
    updated_at: str | None = None  # ISO 8601
    labels: list[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict)  # full API response for extensibility


@dataclass
class SourceEvent:
    """External source event — returned by Adapter.list_updates()."""
    source: str
    source_id: str
    event_type: str        # "status_change" | "comment" | "label_change" | "assigned" | "deleted"
    timestamp: str         # ISO 8601
    data: dict = field(default_factory=dict)
