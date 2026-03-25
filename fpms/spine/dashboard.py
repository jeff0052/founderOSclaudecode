"""L0 全局看板树渲染 — render_dashboard。

PRD FR-3: 提供 Agent "周边视野"的全局工作状态视图。

Zone 0 (顶部): 收件箱节点 (无父节点)，最多显示 5 个，其余显示数量。
Zone 1: 活跃业务树，按 parent_id 树形缩进展示。

Status icons:
  inbox   → 📥
  active  → ▶
  waiting → ⏳
  done    → ✅
  dropped → ❌

Risk decorations:
  blocked  → 🚨blocked
  at_risk  → 🚨at-risk
  stale    → ⚠️stale
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Callable, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from .store import Store

from .models import Node, RiskMarks
from .risk import compute_risk_marks_batch


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_STATUS_ICONS: Dict[str, str] = {
    "inbox":   "📥",
    "active":  "▶",
    "waiting": "⏳",
    "done":    "✅",
    "dropped": "❌",
}

_ZONE0_MAX = 5

# Risk severity rank: higher = worse (used for sorting)
_RISK_SEVERITY: Callable[[RiskMarks], int] = lambda m: (
    3 if m.blocked else
    2 if m.at_risk else
    1 if m.stale else
    0
)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def _estimate_tokens(text: str) -> int:
    """Rough token count: len(text) // 4."""
    return len(text) // 4


def _render_node_line(
    node: Node,
    depth: int,
    risk_marks: RiskMarks,
    is_last: bool,
) -> str:
    """Render a single node as a tree line.

    Format: {indent}{connector}{icon} {node_id}: {title} {risk_decorations} {deadline_info}

    depth=0 → no connector prefix (root level).
    depth>0 → uses ├─ or └─ (is_last).
    """
    icon = _STATUS_ICONS.get(node.status, "▶")

    # Build risk decoration string
    risk_parts: List[str] = []
    if risk_marks.blocked:
        risk_parts.append("🚨blocked")
    if risk_marks.at_risk:
        risk_parts.append("🚨at-risk")
    if risk_marks.stale:
        risk_parts.append("⚠️stale")
    risk_str = " ".join(risk_parts)

    # Build deadline info string
    deadline_str = ""
    if risk_marks.deadline_hours is not None:
        h = risk_marks.deadline_hours
        if h < 0:
            deadline_str = f"(过期{abs(h):.0f}h)"
        else:
            deadline_str = f"(剩余{h:.0f}h)"

    # Build the content part
    parts = [f"{icon} {node.id}: {node.title}"]
    if risk_str:
        parts.append(risk_str)
    if deadline_str:
        parts.append(deadline_str)
    content = " ".join(parts)

    # Build indentation
    if depth == 0:
        return content

    # depth >= 1: indent with 2 spaces per level above the connector level
    # Level 1: "  ├─ content" or "  └─ content"
    # Level 2: "    ├─ content" or "    └─ content"
    connector = "└─" if is_last else "├─"
    indent = "  " * depth
    return f"{indent}{connector} {content}"


def _get_root_nodes(store: "Store") -> List[Node]:
    """Return active tree root nodes (is_root=True OR (parent_id=None AND status≠inbox)), non-archived."""
    # is_root=True nodes
    roots_by_flag = store.list_nodes(
        filters={"is_root": True, "archived": False},
        limit=200,
    )

    # parent_id=None, status≠inbox, non-archived
    # list_nodes doesn't directly support "parent_id IS NULL" — query directly
    cols = store._node_columns()
    rows = store._conn.execute(
        "SELECT * FROM nodes WHERE parent_id IS NULL AND status != 'inbox' AND archived_at IS NULL"
    ).fetchall()

    from .store import _row_to_node
    orphan_roots = [_row_to_node(r, cols) for r in rows]

    # Merge, deduplicate by id, prefer is_root=True if duplicated
    seen: Dict[str, Node] = {}
    for n in roots_by_flag:
        seen[n.id] = n
    for n in orphan_roots:
        if n.id not in seen:
            seen[n.id] = n

    return list(seen.values())


# ---------------------------------------------------------------------------
# Internal rendering helpers
# ---------------------------------------------------------------------------

def _sort_siblings(
    siblings: List[Node],
    risk_map: Dict[str, RiskMarks],
) -> List[Node]:
    """Sort siblings: blocked > at-risk > stale > none, then by status_changed_at desc."""
    def sort_key(n: Node) -> Tuple[int, str]:
        marks = risk_map.get(n.id, RiskMarks())
        severity = _RISK_SEVERITY(marks)
        # Negate severity so highest sorts first (sort ascending, so negate)
        return (-severity, -(len(n.status_changed_at or "")))

    # Use a stable sort with a proper comparator
    def sort_key_v2(n: Node) -> Tuple[int, str]:
        marks = risk_map.get(n.id, RiskMarks())
        severity = _RISK_SEVERITY(marks)
        changed_at = n.status_changed_at or ""
        # We want desc severity (higher = first), then desc status_changed_at
        return (-severity, changed_at)

    return sorted(siblings, key=sort_key_v2, reverse=False)
    # Note: (-severity, changed_at) sorted ascending means highest severity first,
    # and within same severity, earlier changed_at comes first (which is ASC).
    # For "desc status_changed_at", we negate the string or use a tuple trick.
    # Let's redo this properly:


def _sort_siblings_correct(
    siblings: List[Node],
    risk_map: Dict[str, RiskMarks],
) -> List[Node]:
    """Sort siblings: blocked > at-risk > stale > none desc, then status_changed_at desc."""
    def sort_key(n: Node) -> Tuple[int, str]:
        marks = risk_map.get(n.id, RiskMarks())
        severity = _RISK_SEVERITY(marks)
        changed_at = n.status_changed_at or ""
        # Negate severity for descending order (higher severity first)
        # For status_changed_at desc: negate the string isn't possible,
        # but we can flip by returning it negated as a trick via a wrapper.
        # Simplest: use tuple (-severity, -changed_at_as_epoch) — but we have ISO strings.
        # Since ISO strings sort lexicographically in the same order as time,
        # we can reverse the changed_at sort by putting a negated proxy.
        # For strings we can't negate, so we return it to sort ascending by prefix,
        # then reverse the whole list per group. Instead: just return negative severity
        # and the ISO string as-is, then reverse=True on the overall list would flip
        # everything. Better: use a compound key with a special wrapper.
        return (-severity, changed_at)

    # Sort ascending by (-severity, changed_at) means:
    #   - severity 3 (blocked) sorts before severity 0 (none) ✓ (because -3 < -0)
    #   - within same severity, earlier changed_at comes first (ASC) ✗ we want DESC
    # To get DESC changed_at within same severity without extra complexity:
    # We sort by (-severity, changed_at) ascending — this gives us severity DESC correct,
    # but changed_at ASC (oldest first). The spec says "status_changed_at desc" (newest first).
    # Fix: use a custom comparator via functools.cmp_to_key.
    import functools

    def cmp(a: Node, b: Node) -> int:
        marks_a = risk_map.get(a.id, RiskMarks())
        marks_b = risk_map.get(b.id, RiskMarks())
        sev_a = _RISK_SEVERITY(marks_a)
        sev_b = _RISK_SEVERITY(marks_b)
        if sev_a != sev_b:
            return sev_b - sev_a  # higher severity first
        # Same severity: sort by status_changed_at descending
        ca = a.status_changed_at or ""
        cb = b.status_changed_at or ""
        if ca > cb:
            return -1  # a first (newer)
        elif ca < cb:
            return 1   # b first (newer)
        return 0

    return sorted(siblings, key=functools.cmp_to_key(cmp))


def _collect_all_nodes(store: "Store") -> List[Node]:
    """Collect all non-archived nodes."""
    return store.list_nodes(filters={"archived": False}, limit=10000)


def _build_children_map(all_nodes: List[Node]) -> Dict[str, List[Node]]:
    """Build a map of parent_id → list of children."""
    children_map: Dict[str, List[Node]] = {}
    for node in all_nodes:
        if node.parent_id is not None:
            if node.parent_id not in children_map:
                children_map[node.parent_id] = []
            children_map[node.parent_id].append(node)
    return children_map


def _has_risk_in_subtree(
    node_id: str,
    children_map: Dict[str, List[Node]],
    risk_map: Dict[str, RiskMarks],
) -> bool:
    """Return True if this node or any descendant has a risk mark."""
    marks = risk_map.get(node_id, RiskMarks())
    if marks.blocked or marks.at_risk or marks.stale:
        return True
    for child in children_map.get(node_id, []):
        if _has_risk_in_subtree(child.id, children_map, risk_map):
            return True
    return False


def _render_tree(
    node: Node,
    depth: int,
    is_last: bool,
    children_map: Dict[str, List[Node]],
    risk_map: Dict[str, RiskMarks],
    lines: List[str],
    token_budget: int,
    current_tokens: List[int],  # mutable int via list
) -> None:
    """Recursively render a node and its children into lines.

    Applies token budget: folds healthy children when over budget.
    Risky subtrees (blocked/at-risk/stale) are always expanded.
    """
    marks = risk_map.get(node.id, RiskMarks())
    line = _render_node_line(node, depth=depth, risk_marks=marks, is_last=is_last)
    lines.append(line)
    current_tokens[0] += _estimate_tokens(line)

    children = children_map.get(node.id, [])
    if not children:
        return

    # Sort children by risk severity desc, then status_changed_at desc
    sorted_children = _sort_siblings_correct(children, risk_map)

    n = len(sorted_children)
    over_budget = current_tokens[0] >= token_budget

    if over_budget:
        # Separate risky vs healthy children
        risky = [c for c in sorted_children if _has_risk_in_subtree(c.id, children_map, risk_map)]
        healthy = [c for c in sorted_children if not _has_risk_in_subtree(c.id, children_map, risk_map)]

        # Always render risky children
        for i, child in enumerate(risky):
            is_last_child = (i == len(risky) - 1) and not healthy
            _render_tree(child, depth + 1, is_last_child, children_map, risk_map,
                         lines, token_budget, current_tokens)

        # Fold healthy children
        if healthy:
            indent = "  " * (depth + 1)
            fold_line = f"{indent}  ... [折叠] {len(healthy)} 个正常子项"
            lines.append(fold_line)
            current_tokens[0] += _estimate_tokens(fold_line)
    else:
        # Render all children normally; may fold mid-way if budget exceeded
        for i, child in enumerate(sorted_children):
            is_last_child = (i == n - 1)
            is_risky = _has_risk_in_subtree(child.id, children_map, risk_map)

            if current_tokens[0] >= token_budget and not is_risky:
                # Count remaining healthy children and fold them
                remaining_healthy = [
                    c for c in sorted_children[i:]
                    if not _has_risk_in_subtree(c.id, children_map, risk_map)
                ]
                if remaining_healthy:
                    indent = "  " * (depth + 1)
                    fold_line = f"{indent}  ... [折叠] {len(remaining_healthy)} 个正常子项"
                    lines.append(fold_line)
                    current_tokens[0] += _estimate_tokens(fold_line)
                    # Still render any remaining risky children after folded batch
                    remaining_risky = [
                        c for c in sorted_children[i:]
                        if _has_risk_in_subtree(c.id, children_map, risk_map)
                    ]
                    for j, rc in enumerate(remaining_risky):
                        _render_tree(rc, depth + 1, j == len(remaining_risky) - 1,
                                     children_map, risk_map, lines, token_budget, current_tokens)
                    break
            else:
                _render_tree(child, depth + 1, is_last_child, children_map, risk_map,
                             lines, token_budget, current_tokens)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def render_dashboard(
    store: "Store",
    risk_module=None,
    max_tokens: int = 1000,
) -> str:
    """Render the L0 global dashboard tree.

    Args:
        store:       Store instance.
        risk_module: Optional module with compute_risk_marks_batch(nodes, store, now).
                     Defaults to fpms.spine.risk.
        max_tokens:  Token budget for Zone 1 tree (~500-1000).

    Returns:
        Rendered dashboard string.
    """
    now = datetime.now(timezone.utc)

    # Resolve risk module
    if risk_module is None:
        from . import risk as _risk_mod
        risk_module = _risk_mod

    # -----------------------------------------------------------------------
    # Collect all non-archived nodes
    # -----------------------------------------------------------------------
    all_nodes = _collect_all_nodes(store)

    # Build risk map for all nodes
    risk_map = risk_module.compute_risk_marks_batch(all_nodes, store, now=now)

    # -----------------------------------------------------------------------
    # Zone 0: Inbox nodes (no parent, status=inbox)
    # -----------------------------------------------------------------------
    inbox_nodes = [
        n for n in all_nodes
        if n.status == "inbox" and n.parent_id is None
    ]
    # Sort by updated_at desc (most recent first)
    inbox_nodes.sort(key=lambda n: n.updated_at or "", reverse=True)

    zone0_lines: List[str] = []
    shown_inbox = inbox_nodes[:_ZONE0_MAX]
    overflow_count = len(inbox_nodes) - len(shown_inbox)

    for node in shown_inbox:
        zone0_lines.append(f"[收件箱] {node.id}: {node.title}")

    if overflow_count > 0:
        zone0_lines.append(f"  ... 还有 {overflow_count} 条收件箱消息")

    # -----------------------------------------------------------------------
    # Zone 1: Business tree
    # -----------------------------------------------------------------------
    root_nodes = _get_root_nodes(store)

    # Build children map (only non-archived nodes)
    children_map = _build_children_map(all_nodes)

    # Sort root nodes by risk severity desc, then status_changed_at desc
    root_nodes = _sort_siblings_correct(root_nodes, risk_map)

    zone1_lines: List[str] = []
    current_tokens = [0]

    for i, root in enumerate(root_nodes):
        is_last = (i == len(root_nodes) - 1)
        _render_tree(
            node=root,
            depth=0,
            is_last=is_last,
            children_map=children_map,
            risk_map=risk_map,
            lines=zone1_lines,
            token_budget=max_tokens,
            current_tokens=current_tokens,
        )

    # -----------------------------------------------------------------------
    # Assemble output
    # -----------------------------------------------------------------------
    sections: List[str] = []

    if zone0_lines:
        sections.append("\n".join(zone0_lines))

    if zone1_lines:
        sections.append("\n".join(zone1_lines))

    if not sections:
        return ""

    return "\n".join(sections)
