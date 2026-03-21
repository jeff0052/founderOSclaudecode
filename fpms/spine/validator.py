"""校验层 — 状态迁移, DAG 环路检测, XOR 约束, 活跃域隔离, Actionable Errors。"""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from .models import Node
    from .store import Store

# ---------------------------------------------------------------------------
# Legal transition map: current_status -> set of allowed target statuses
# ---------------------------------------------------------------------------
_LEGAL_TRANSITIONS = {
    "inbox": {"active", "waiting", "dropped"},
    "active": {"waiting", "done", "dropped"},
    "waiting": {"active", "done", "dropped"},
    "done": {"active"},
    "dropped": {"inbox"},
}

# Terminal states: nodes in these states count as "finished"
_TERMINAL_STATES = {"done", "dropped"}


class ValidationError(Exception):
    """校验失败时抛出。包含 code, message, suggestion。
    message 必须是 Actionable Error：告诉 LLM 哪里错了 + 下一步该调什么工具。"""

    def __init__(self, code: str, message: str, suggestion: str):
        self.code = code
        self.message = message
        self.suggestion = suggestion
        super().__init__(message)


def validate_status_transition(
    current: str,
    target: str,
    node: "Node",
    children: "List[Node]",
    reason: Optional[str] = None,
) -> "List[str]":
    """校验状态迁移合法性。不合法则 raise ValidationError（含 actionable suggestion）。
    返回 warnings 列表（例如 dropped 有活跃子节点时的警告）。
    - inbox→active/waiting: 需要 summary + (parent_id OR is_root)
    - →done: 所有子节点必须终态
    - →dropped: 警告但允许
    - done→active / dropped→inbox: 需要 reason
    """
    warnings: List[str] = []

    # 1. Check if transition is legal at all
    allowed = _LEGAL_TRANSITIONS.get(current)
    if allowed is None or target not in allowed:
        raise ValidationError(
            code="ILLEGAL_TRANSITION",
            message=f"状态迁移 {current}→{target} 不合法。"
            f"从 {current} 只能迁移到: {sorted(_LEGAL_TRANSITIONS.get(current, set()))}",
            suggestion=f"请选择合法的目标状态: {sorted(_LEGAL_TRANSITIONS.get(current, set()))}",
        )

    # 2. Preconditions for leaving inbox → active or waiting
    if current == "inbox" and target in ("active", "waiting"):
        if not node.summary:
            raise ValidationError(
                code="MISSING_SUMMARY",
                message=f"节点 {node.id} 缺少 summary，无法从 inbox 迁移到 {target}。",
                suggestion=f"请先调用 update_field(node_id='{node.id}', field='summary', value='...') 补充 summary",
            )
        if not node.parent_id and not node.is_root:
            raise ValidationError(
                code="MISSING_PARENT",
                message=f"节点 {node.id} 既不是 root 也没有 parent_id，无法从 inbox 迁移到 {target}。",
                suggestion=f"请先调用 update_field(node_id='{node.id}', field='is_root', value='true') "
                f"或通过 attach(node_id='{node.id}', parent_id='...') 设置父节点",
            )

    # 3. → done: all children must be terminal
    if target == "done":
        non_terminal = [c for c in children if c.status not in _TERMINAL_STATES]
        if non_terminal:
            ids = [c.id for c in non_terminal]
            raise ValidationError(
                code="ACTIVE_CHILDREN",
                message=f"节点 {node.id} 还有 {len(non_terminal)} 个非终态子节点: {ids}，无法标记为 done。",
                suggestion=f"请先将子节点 {ids} 迁移到 done 或 dropped 状态",
            )

    # 4. → dropped: warn if children are active, but allow
    if target == "dropped":
        active_children = [c for c in children if c.status not in _TERMINAL_STATES]
        if active_children:
            ids = [c.id for c in active_children]
            warnings.append(
                f"警告: 节点 {node.id} 有 {len(active_children)} 个非终态子节点: {ids}，"
                f"它们将成为孤儿节点。"
            )

    # 5. done→active: needs reason
    if current == "done" and target == "active":
        if not reason:
            raise ValidationError(
                code="MISSING_REASON",
                message=f"从 done→active 需要提供 reason（重新激活原因）。",
                suggestion=f"请调用 update_status(node_id='{node.id}', new_status='active', reason='...')",
            )

    # 6. dropped→inbox: needs reason
    if current == "dropped" and target == "inbox":
        if not reason:
            raise ValidationError(
                code="MISSING_REASON",
                message=f"从 dropped→inbox 需要提供 reason（恢复原因）。",
                suggestion=f"请调用 update_status(node_id='{node.id}', new_status='inbox', reason='...')",
            )

    return warnings


def validate_dag_safety(
    store: "Store", source_id: str, target_id: str, edge_type: str
) -> None:
    """统一 DAG 环路检测（合并 parent + depends_on 图）。
    使用 SQLite WITH RECURSIVE CTE 在数据库层检测环路。
    有环则 raise ValidationError。"""

    # Self-reference check
    if source_id == target_id:
        raise ValidationError(
            code="CYCLE_DETECTED",
            message=f"不能创建自引用边: {source_id} → {target_id}。",
            suggestion="请选择不同的 source 和 target 节点",
        )

    # Use the store's connection to run the CTE query
    conn = store._conn

    # Check if adding source_id → target_id would create a cycle.
    # A cycle exists if target_id can already reach source_id via existing
    # directed edges. We walk from target_id following outgoing edges
    # (source_id→target_id in the edges table).
    cycle_sql = """
    WITH RECURSIVE reachable(nid) AS (
        SELECT ?
        UNION
        SELECT e.target_id FROM edges e
        JOIN reachable r ON e.source_id = r.nid
    )
    SELECT 1 FROM reachable WHERE nid = ?
    LIMIT 1
    """
    row = conn.execute(cycle_sql, (target_id, source_id)).fetchone()
    if row is not None:
        raise ValidationError(
            code="CYCLE_DETECTED",
            message=f"添加边 {source_id}→{target_id} (type={edge_type}) 会创建环路。",
            suggestion="请检查节点关系图，选择不会形成环路的目标节点",
        )

    # Cross-dimension check: if edge_type is "depends_on",
    # check if target_id is an ancestor of source_id via parent edges
    # (child depends_on ancestor = deadlock)
    if edge_type == "depends_on":
        ancestor_sql = """
        WITH RECURSIVE ancestors(nid) AS (
            SELECT parent_id FROM nodes WHERE id = ?
            UNION
            SELECT n.parent_id FROM nodes n
            JOIN ancestors a ON n.id = a.nid
            WHERE n.parent_id IS NOT NULL
        )
        SELECT 1 FROM ancestors WHERE nid = ?
        LIMIT 1
        """
        row = conn.execute(ancestor_sql, (source_id, target_id)).fetchone()
        if row is not None:
            raise ValidationError(
                code="CYCLE_DETECTED",
                message=f"跨维度死锁: {source_id} 的祖先 {target_id} 不能作为其依赖目标。",
                suggestion="子节点不能依赖自己的祖先节点，请选择其他依赖目标",
            )


def validate_xor_constraint(is_root: bool, parent_id: Optional[str]) -> None:
    """检查 is_root 和 parent_id 互斥。违反则 raise ValidationError。"""
    if is_root and parent_id is not None:
        raise ValidationError(
            code="XOR_VIOLATION",
            message="is_root=True 和 parent_id 不能同时设置。根节点不能有父节点。",
            suggestion="请设置 is_root=False 或移除 parent_id",
        )


def validate_active_domain(node: "Node") -> None:
    """检查目标节点非归档状态。已归档则 raise ValidationError。"""
    if node.archived_at is not None:
        raise ValidationError(
            code="ARCHIVED_TARGET",
            message=f"目标节点 {node.id} 已归档 (archived_at={node.archived_at})，不能操作。",
            suggestion=f"请先取消归档节点 {node.id}，或选择一个未归档的目标节点",
        )


def validate_attach(store: "Store", node_id: str, new_parent_id: str) -> None:
    """综合校验 attach: 活跃域 + DAG 安全 + XOR。"""
    # 1. Get target node (new_parent_id), check active domain
    target_node = store.get_node(new_parent_id)
    if target_node is None:
        raise ValidationError(
            code="NODE_NOT_FOUND",
            message=f"目标父节点 {new_parent_id} 不存在。",
            suggestion="请检查 parent_id 是否正确",
        )
    validate_active_domain(target_node)

    # 2. Check DAG safety: the actual edge stored is (node_id → new_parent_id)
    #    using child → parent convention. Check that direction.
    validate_dag_safety(store, node_id, new_parent_id, edge_type="parent")


def validate_dependency(store: "Store", source_id: str, target_id: str) -> None:
    """综合校验 add_dependency: 活跃域 + DAG 安全 + 不能自依赖。"""
    # 1. Self-dependency check
    if source_id == target_id:
        raise ValidationError(
            code="SELF_DEPENDENCY",
            message=f"节点 {source_id} 不能依赖自身。",
            suggestion="请选择不同的目标节点作为依赖",
        )

    # 2. Get target node, check active domain
    target_node = store.get_node(target_id)
    if target_node is None:
        raise ValidationError(
            code="NODE_NOT_FOUND",
            message=f"目标节点 {target_id} 不存在。",
            suggestion="请检查 target_id 是否正确",
        )
    validate_active_domain(target_node)

    # 3. Check DAG safety
    validate_dag_safety(store, source_id, target_id, edge_type="depends_on")
