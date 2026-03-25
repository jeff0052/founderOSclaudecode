"""递归自底向上状态汇总 — compute_rollup。

规则：
- 使用 store.get_children_all() 获取全部子节点（含已归档），保留分母。
- 排除 inbox 子节点参与汇总（FR-7）。
- 优先级: active > waiting > (终态: 任意 done → done，全部 dropped → dropped)。
- 叶节点返回自身 status。
- 使用单次计算内的 memoization cache 避免重复计算。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, Optional

if TYPE_CHECKING:
    from .models import Node, RiskMarks
    from .store import Store

from .models import RollupResult


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TERMINAL_STATES = frozenset({"done", "dropped"})


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_status(statuses: List[str]) -> str:
    """根据优先级规则从子节点状态列表推导汇总状态。

    优先级: active > waiting > (done/dropped 终态规则)
    终态规则: any done → done; all dropped → dropped
    """
    if not statuses:
        # Caller handles empty-after-exclusion fallback
        raise ValueError("_resolve_status called with empty list")

    if "active" in statuses:
        return "active"
    if "waiting" in statuses:
        return "waiting"

    # All must be terminal at this point
    if "done" in statuses:
        return "done"
    # All dropped
    return "dropped"


def _has_any_risk(marks: "RiskMarks") -> bool:
    """Check if a RiskMarks instance has any risk flag set."""
    return marks.blocked or marks.at_risk or marks.stale


def _describe_risk(child_id: str, marks: "RiskMarks") -> List[str]:
    """Generate human-readable risk descriptions for a child node."""
    descriptions: List[str] = []
    if marks.blocked:
        deps = ", ".join(marks.blocked_by) if marks.blocked_by else "unknown"
        descriptions.append(f"{child_id} blocked by: {deps}")
    if marks.at_risk:
        hours = f"{marks.deadline_hours:.1f}h" if marks.deadline_hours is not None else "unknown"
        descriptions.append(f"{child_id} at-risk: {hours} remaining")
    if marks.stale:
        descriptions.append(f"{child_id} stale")
    return descriptions


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_rollup(
    node_id: str,
    store: "Store",
    risk_marks_map: Optional[Dict[str, "RiskMarks"]] = None,
    _cache: Optional[Dict[str, RollupResult]] = None,
) -> RollupResult:
    """递归计算节点的 rollup 状态。

    Args:
        node_id:        目标节点 id。
        store:          Store 实例，通过 get_children_all() 读取子节点。
        risk_marks_map: 可选的 {node_id: RiskMarks} 映射，用于传播风险信息。
        _cache:         可选的 memoization 字典，在同一次调用中跨递归共享。
                        传入同一个 dict 对象即可启用。

    Returns:
        RollupResult，包含 rollup_status, has_risk_children, risk_summary。
    """
    # Initialize cache on first call
    if _cache is None:
        _cache = {}

    # Return cached result if already computed
    if node_id in _cache:
        return _cache[node_id]

    node = store.get_node(node_id)
    if node is None:
        # Fallback: return inbox for unknown node
        result = RollupResult(node_id=node_id, rollup_status="inbox")
        _cache[node_id] = result
        return result

    # Fetch all children including archived (denominator preservation)
    all_children = store.get_children_all(node_id)

    # Exclude inbox children (FR-7)
    eligible_children = [c for c in all_children if c.status != "inbox"]

    if not eligible_children:
        # Leaf node (or only inbox children) → use own status
        result = RollupResult(node_id=node_id, rollup_status=node.status)
        _cache[node_id] = result
        return result

    # Recursively compute rollup for each eligible child
    child_rollup_statuses: List[str] = []
    has_risk_children = False
    risk_summary: List[str] = []

    for child in eligible_children:
        child_result = compute_rollup(
            child.id, store,
            risk_marks_map=risk_marks_map,
            _cache=_cache,
        )
        child_rollup_statuses.append(child_result.rollup_status)

        # Propagate risk exposure from children
        if risk_marks_map is not None:
            child_marks = risk_marks_map.get(child.id)
            if child_marks is not None and _has_any_risk(child_marks):
                has_risk_children = True
                risk_summary.extend(_describe_risk(child.id, child_marks))

        # Propagate nested risk from child's own rollup result
        if child_result.has_risk_children:
            has_risk_children = True
            risk_summary.extend(child_result.risk_summary)

    rollup_status = _resolve_status(child_rollup_statuses)

    result = RollupResult(
        node_id=node_id,
        rollup_status=rollup_status,
        has_risk_children=has_risk_children,
        risk_summary=risk_summary,
    )
    _cache[node_id] = result
    return result
