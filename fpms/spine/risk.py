"""风险标记计算 — blocked, at_risk, stale 的纯函数计算，不存储。

规则：
- blocked: 节点非终态 AND 任意 depends_on 目标状态 ≠ done。
  注意：dropped 不解除阻塞（只有 done 才解锁）。
- at_risk: deadline < NOW()+48h AND 非终态。
- stale: status in (active, waiting) AND status_changed_at 超过 72 小时。
- 终态节点（done/dropped）永远不获得任何风险标记。

SYSTEM-CONFIG 常量：
  heartbeat.stale_threshold = 72h
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING, Dict, List, Optional

if TYPE_CHECKING:
    from .models import Node
    from .store import Store

from .models import RiskMarks


# ---------------------------------------------------------------------------
# Constants (SYSTEM-CONFIG)
# ---------------------------------------------------------------------------

_TERMINAL_STATES = frozenset({"done", "dropped"})
_STALE_THRESHOLD_HOURS = 72        # heartbeat.stale_threshold
_AT_RISK_HORIZON_HOURS = 48        # deadline warning window


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_iso(ts: str) -> datetime:
    """Parse an ISO 8601 timestamp string to an aware datetime (UTC if no tz)."""
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_risk_marks(
    node: "Node",
    store: "Store",
    now: Optional[datetime] = None,
) -> RiskMarks:
    """计算单个节点的风险标记。

    纯函数：不修改任何状态，不写 DB，仅读取依赖关系。

    Args:
        node:  要计算的节点。
        store: Store 实例，用于查询依赖节点状态。
        now:   可注入的"当前时间"（UTC aware）。默认为 datetime.now(utc)。

    Returns:
        RiskMarks dataclass，所有字段默认 False/空。
    """
    if now is None:
        now = _now_utc()

    # Terminal nodes never get risk marks
    if node.status in _TERMINAL_STATES:
        return RiskMarks()

    marks = RiskMarks()

    # --- blocked ---
    deps = store.get_dependencies(node.id)
    blocked_by: List[str] = [
        dep.id for dep in deps if dep.status != "done"
    ]
    if blocked_by:
        marks.blocked = True
        marks.blocked_by = blocked_by

    # --- at_risk ---
    if node.deadline is not None:
        deadline_dt = _parse_iso(node.deadline)
        horizon = now + timedelta(hours=_AT_RISK_HORIZON_HOURS)
        hours_remaining = (deadline_dt - now).total_seconds() / 3600.0
        marks.deadline_hours = hours_remaining
        if deadline_dt < horizon:
            marks.at_risk = True

    # --- stale ---
    if node.status in ("active", "waiting") and node.status_changed_at:
        changed_at = _parse_iso(node.status_changed_at)
        age_hours = (now - changed_at).total_seconds() / 3600.0
        if age_hours > _STALE_THRESHOLD_HOURS:
            marks.stale = True

    return marks


def compute_risk_marks_batch(
    nodes: "List[Node]",
    store: "Store",
    now: Optional[datetime] = None,
) -> Dict[str, RiskMarks]:
    """批量计算一组节点的风险标记。

    Args:
        nodes: 节点列表。
        store: Store 实例。
        now:   可注入的当前时间（UTC aware）。

    Returns:
        dict: node_id → RiskMarks
    """
    if now is None:
        now = _now_utc()

    return {node.id: compute_risk_marks(node, store, now=now) for node in nodes}
