"""validator.py 测试 — 状态迁移, DAG 环路检测, XOR 约束, 活跃域, 自依赖, Actionable Errors。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

import pytest

from fpms.spine.models import Node, Edge
from fpms.spine.schema import init_db
from fpms.spine.validator import (
    ValidationError,
    validate_active_domain,
    validate_attach,
    validate_dag_safety,
    validate_dependency,
    validate_status_transition,
    validate_xor_constraint,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_node(
    node_id: str = "n-001",
    title: str = "Test",
    status: str = "inbox",
    is_root: bool = False,
    parent_id: Optional[str] = None,
    summary: Optional[str] = None,
    archived_at: Optional[str] = None,
) -> Node:
    """Create a minimal Node for testing."""
    now = _now()
    return Node(
        id=node_id,
        title=title,
        status=status,
        node_type="task",
        is_root=is_root,
        parent_id=parent_id,
        summary=summary,
        created_at=now,
        updated_at=now,
        status_changed_at=now,
        archived_at=archived_at,
    )


class _MinimalStore:
    """Lightweight Store stand-in for validator tests.

    Only provides _conn and get_node — the two things validator.py needs.
    Uses a real SQLite database via schema.init_db.
    """

    def __init__(self, db_path: str):
        self._conn = init_db(db_path)
        self._nodes: dict[str, Node] = {}

    def insert_node(self, node: Node) -> None:
        """Insert a node into the DB and local cache."""
        now = _now()
        self._conn.execute(
            "INSERT INTO nodes (id, title, status, node_type, is_root, parent_id, "
            "summary, created_at, updated_at, status_changed_at, archived_at, "
            "source, source_deleted, needs_compression, compression_in_progress, "
            "no_llm_compression, tags) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                node.id, node.title, node.status, node.node_type,
                1 if node.is_root else 0,
                node.parent_id, node.summary,
                now, now, now, node.archived_at,
                "internal", 0, 0, 0, 0, "[]",
            ),
        )
        self._conn.commit()
        self._nodes[node.id] = node

    def insert_edge(self, source_id: str, target_id: str, edge_type: str) -> None:
        """Insert an edge into the DB."""
        now = _now()
        self._conn.execute(
            "INSERT INTO edges (source_id, target_id, edge_type, created_at) "
            "VALUES (?,?,?,?)",
            (source_id, target_id, edge_type, now),
        )
        self._conn.commit()

    def get_node(self, node_id: str) -> Optional[Node]:
        return self._nodes.get(node_id)

    def close(self) -> None:
        self._conn.close()


@pytest.fixture
def store(tmp_path):
    """Provide a _MinimalStore backed by a temp SQLite DB."""
    s = _MinimalStore(str(tmp_path / "test.db"))
    yield s
    s.close()


# ===========================================================================
# Status Transition Tests
# ===========================================================================

class TestStatusTransition:
    """validate_status_transition 测试。"""

    def test_inbox_to_active_legal(self):
        """inbox→active: 合法（有 summary + parent_id）。"""
        node = _make_node(summary="do stuff", parent_id="p-1")
        warnings = validate_status_transition("inbox", "active", node, [])
        assert warnings == []

    def test_inbox_to_active_missing_summary_reject(self):
        """inbox→active: 缺少 summary → reject + actionable suggestion。"""
        node = _make_node(parent_id="p-1", summary=None)
        with pytest.raises(ValidationError) as exc_info:
            validate_status_transition("inbox", "active", node, [])
        err = exc_info.value
        assert err.code == "MISSING_SUMMARY"
        assert "summary" in err.suggestion
        assert "update_field" in err.suggestion

    def test_inbox_to_active_missing_parent_and_not_root_reject(self):
        """inbox→active: 无 parent_id 且非 root → reject。"""
        node = _make_node(summary="ok", parent_id=None, is_root=False)
        with pytest.raises(ValidationError) as exc_info:
            validate_status_transition("inbox", "active", node, [])
        err = exc_info.value
        assert err.code == "MISSING_PARENT"

    def test_inbox_to_active_root_no_parent_legal(self):
        """inbox→active: is_root=True 无 parent_id → 合法。"""
        node = _make_node(summary="root goal", is_root=True)
        warnings = validate_status_transition("inbox", "active", node, [])
        assert warnings == []

    def test_inbox_to_waiting_legal(self):
        """inbox→waiting: 合法（有 summary + parent_id）。"""
        node = _make_node(summary="waiting for X", parent_id="p-1")
        warnings = validate_status_transition("inbox", "waiting", node, [])
        assert warnings == []

    def test_active_to_done_no_children_legal(self):
        """active→done: 无子节点 → 合法。"""
        node = _make_node(status="active", summary="x", parent_id="p-1")
        warnings = validate_status_transition("active", "done", node, [])
        assert warnings == []

    def test_active_to_done_with_active_children_reject(self):
        """active→done: 有活跃子节点 → reject + list children。"""
        node = _make_node(node_id="parent", status="active", summary="x", parent_id="p-1")
        child1 = _make_node(node_id="c-1", status="active")
        child2 = _make_node(node_id="c-2", status="done")
        with pytest.raises(ValidationError) as exc_info:
            validate_status_transition("active", "done", node, [child1, child2])
        err = exc_info.value
        assert err.code == "ACTIVE_CHILDREN"
        assert "c-1" in err.message

    def test_active_to_done_all_children_terminal_legal(self):
        """active→done: 所有子节点终态 → 合法。"""
        node = _make_node(node_id="parent", status="active", summary="x", parent_id="p-1")
        child1 = _make_node(node_id="c-1", status="done")
        child2 = _make_node(node_id="c-2", status="dropped")
        warnings = validate_status_transition("active", "done", node, [child1, child2])
        assert warnings == []

    def test_active_to_dropped_with_active_children_allow_with_warning(self):
        """active→dropped: 有活跃子节点 → allow + warning。"""
        node = _make_node(node_id="parent", status="active", summary="x", parent_id="p-1")
        child1 = _make_node(node_id="c-1", status="active")
        warnings = validate_status_transition("active", "dropped", node, [child1])
        assert len(warnings) == 1
        assert "c-1" in warnings[0]

    def test_done_to_active_missing_reason_reject(self):
        """done→active: 缺少 reason → reject。"""
        node = _make_node(status="done", summary="x", parent_id="p-1")
        with pytest.raises(ValidationError) as exc_info:
            validate_status_transition("done", "active", node, [], reason=None)
        err = exc_info.value
        assert err.code == "MISSING_REASON"
        assert "reason" in err.suggestion

    def test_done_to_active_with_reason_legal(self):
        """done→active: 有 reason → 合法。"""
        node = _make_node(status="done", summary="x", parent_id="p-1")
        warnings = validate_status_transition(
            "done", "active", node, [], reason="need to fix a bug"
        )
        assert warnings == []

    def test_dropped_to_inbox_missing_reason_reject(self):
        """dropped→inbox: 缺少 reason → reject。"""
        node = _make_node(status="dropped", summary="x", parent_id="p-1")
        with pytest.raises(ValidationError) as exc_info:
            validate_status_transition("dropped", "inbox", node, [], reason=None)
        err = exc_info.value
        assert err.code == "MISSING_REASON"

    def test_dropped_to_inbox_with_reason_legal(self):
        """dropped→inbox: 有 reason → 合法。"""
        node = _make_node(status="dropped", summary="x", parent_id="p-1")
        warnings = validate_status_transition(
            "dropped", "inbox", node, [], reason="re-evaluate"
        )
        assert warnings == []

    def test_done_to_waiting_illegal(self):
        """done→waiting: 非法迁移 → reject。"""
        node = _make_node(status="done", summary="x", parent_id="p-1")
        with pytest.raises(ValidationError) as exc_info:
            validate_status_transition("done", "waiting", node, [])
        err = exc_info.value
        assert err.code == "ILLEGAL_TRANSITION"

    def test_inbox_to_done_illegal(self):
        """inbox→done: 非法迁移 → reject。"""
        node = _make_node(summary="x", parent_id="p-1")
        with pytest.raises(ValidationError) as exc_info:
            validate_status_transition("inbox", "done", node, [])
        assert exc_info.value.code == "ILLEGAL_TRANSITION"


# ===========================================================================
# DAG Safety Tests
# ===========================================================================

class TestDAGSafety:
    """validate_dag_safety 测试 — 使用真实 SQLite 数据库。"""

    def test_parent_cycle_reject(self, store):
        """DAG parent cycle → reject。A→B→C, adding C→A creates cycle。"""
        a = _make_node(node_id="a", is_root=True, summary="a")
        b = _make_node(node_id="b", parent_id="a", summary="b")
        c = _make_node(node_id="c", parent_id="b", summary="c")
        store.insert_node(a)
        store.insert_node(b)
        store.insert_node(c)
        store.insert_edge("a", "b", "parent")
        store.insert_edge("b", "c", "parent")

        with pytest.raises(ValidationError) as exc_info:
            validate_dag_safety(store, "c", "a", "parent")
        assert exc_info.value.code == "CYCLE_DETECTED"

    def test_depends_on_cycle_reject(self, store):
        """DAG depends_on cycle → reject。A depends B, B depends C, adding C depends A。"""
        a = _make_node(node_id="a", is_root=True, summary="a")
        b = _make_node(node_id="b", is_root=True, summary="b")
        c = _make_node(node_id="c", is_root=True, summary="c")
        store.insert_node(a)
        store.insert_node(b)
        store.insert_node(c)
        store.insert_edge("a", "b", "depends_on")
        store.insert_edge("b", "c", "depends_on")

        with pytest.raises(ValidationError) as exc_info:
            validate_dag_safety(store, "c", "a", "depends_on")
        assert exc_info.value.code == "CYCLE_DETECTED"

    def test_cross_dimension_deadlock_reject(self, store):
        """跨维度死锁: child depends_on ancestor → reject。
        A is parent of B (A→B parent edge). B depends_on A = deadlock.
        """
        a = _make_node(node_id="a", is_root=True, summary="a")
        b = _make_node(node_id="b", parent_id="a", summary="b")
        store.insert_node(a)
        store.insert_node(b)
        store.insert_edge("a", "b", "parent")

        with pytest.raises(ValidationError) as exc_info:
            validate_dag_safety(store, "b", "a", "depends_on")
        assert exc_info.value.code == "CYCLE_DETECTED"

    def test_self_reference_reject(self, store):
        """自引用 → reject。"""
        a = _make_node(node_id="a", is_root=True, summary="a")
        store.insert_node(a)

        with pytest.raises(ValidationError) as exc_info:
            validate_dag_safety(store, "a", "a", "parent")
        assert exc_info.value.code == "CYCLE_DETECTED"

    def test_valid_edge_no_cycle(self, store):
        """合法边: 不形成环 → 不抛异常。"""
        a = _make_node(node_id="a", is_root=True, summary="a")
        b = _make_node(node_id="b", is_root=True, summary="b")
        store.insert_node(a)
        store.insert_node(b)

        # Should not raise
        validate_dag_safety(store, "a", "b", "depends_on")


# ===========================================================================
# XOR Constraint Tests
# ===========================================================================

class TestXORConstraint:
    """validate_xor_constraint 测试。"""

    def test_root_with_parent_reject(self):
        """is_root=True + parent_id≠None → reject。"""
        with pytest.raises(ValidationError) as exc_info:
            validate_xor_constraint(is_root=True, parent_id="p-1")
        assert exc_info.value.code == "XOR_VIOLATION"

    def test_root_without_parent_ok(self):
        """is_root=True + parent_id=None → ok。"""
        validate_xor_constraint(is_root=True, parent_id=None)

    def test_non_root_with_parent_ok(self):
        """is_root=False + parent_id≠None → ok。"""
        validate_xor_constraint(is_root=False, parent_id="p-1")

    def test_non_root_without_parent_ok(self):
        """is_root=False + parent_id=None → ok (orphan allowed at creation)。"""
        validate_xor_constraint(is_root=False, parent_id=None)


# ===========================================================================
# Active Domain Tests
# ===========================================================================

class TestActiveDomain:
    """validate_active_domain 测试。"""

    def test_archived_node_reject(self):
        """归档节点 → reject。"""
        node = _make_node(archived_at="2026-01-01T00:00:00Z")
        with pytest.raises(ValidationError) as exc_info:
            validate_active_domain(node)
        assert exc_info.value.code == "ARCHIVED_TARGET"

    def test_active_node_ok(self):
        """未归档节点 → ok。"""
        node = _make_node(archived_at=None)
        validate_active_domain(node)  # should not raise


# ===========================================================================
# validate_attach Tests
# ===========================================================================

class TestValidateAttach:
    """validate_attach 综合校验。"""

    def test_attach_to_archived_reject(self, store):
        """attach 到归档节点 → reject。"""
        parent = _make_node(node_id="p-1", is_root=True, summary="p", archived_at="2026-01-01T00:00:00Z")
        child = _make_node(node_id="c-1", summary="c")
        store.insert_node(parent)
        store.insert_node(child)

        with pytest.raises(ValidationError) as exc_info:
            validate_attach(store, "c-1", "p-1")
        assert exc_info.value.code == "ARCHIVED_TARGET"

    def test_attach_creates_cycle_reject(self, store):
        """attach 创建环 → reject。"""
        a = _make_node(node_id="a", is_root=True, summary="a")
        b = _make_node(node_id="b", parent_id="a", summary="b")
        store.insert_node(a)
        store.insert_node(b)
        store.insert_edge("b", "a", "parent")  # child -> parent convention

        with pytest.raises(ValidationError) as exc_info:
            validate_attach(store, "a", "b")
        assert exc_info.value.code == "CYCLE_DETECTED"

    def test_attach_valid(self, store):
        """合法 attach → 不抛异常。"""
        a = _make_node(node_id="a", is_root=True, summary="a")
        b = _make_node(node_id="b", is_root=True, summary="b")
        store.insert_node(a)
        store.insert_node(b)

        validate_attach(store, "b", "a")  # should not raise


# ===========================================================================
# validate_dependency Tests
# ===========================================================================

class TestValidateDependency:
    """validate_dependency 综合校验。"""

    def test_self_dependency_reject(self, store):
        """节点依赖自身 → reject。"""
        a = _make_node(node_id="a", is_root=True, summary="a")
        store.insert_node(a)

        with pytest.raises(ValidationError) as exc_info:
            validate_dependency(store, "a", "a")
        assert exc_info.value.code == "SELF_DEPENDENCY"

    def test_dependency_on_archived_reject(self, store):
        """依赖归档节点 → reject。"""
        a = _make_node(node_id="a", is_root=True, summary="a")
        b = _make_node(node_id="b", is_root=True, summary="b", archived_at="2026-01-01T00:00:00Z")
        store.insert_node(a)
        store.insert_node(b)

        with pytest.raises(ValidationError) as exc_info:
            validate_dependency(store, "a", "b")
        assert exc_info.value.code == "ARCHIVED_TARGET"

    def test_dependency_cycle_reject(self, store):
        """依赖环 → reject。"""
        a = _make_node(node_id="a", is_root=True, summary="a")
        b = _make_node(node_id="b", is_root=True, summary="b")
        store.insert_node(a)
        store.insert_node(b)
        store.insert_edge("a", "b", "depends_on")

        with pytest.raises(ValidationError) as exc_info:
            validate_dependency(store, "b", "a")
        assert exc_info.value.code == "CYCLE_DETECTED"

    def test_dependency_valid(self, store):
        """合法依赖 → 不抛异常。"""
        a = _make_node(node_id="a", is_root=True, summary="a")
        b = _make_node(node_id="b", is_root=True, summary="b")
        store.insert_node(a)
        store.insert_node(b)

        validate_dependency(store, "a", "b")  # should not raise


# ===========================================================================
# All ValidationError include code + message + suggestion
# ===========================================================================

class TestValidationErrorAttributes:
    """所有 ValidationError 必须有 code, message, suggestion。"""

    def _collect_errors(self) -> List[ValidationError]:
        """Trigger various validation errors and collect them."""
        errors: List[ValidationError] = []

        # ILLEGAL_TRANSITION
        try:
            node = _make_node(summary="x", parent_id="p-1")
            validate_status_transition("done", "waiting", node, [])
        except ValidationError as e:
            errors.append(e)

        # MISSING_SUMMARY
        try:
            node = _make_node(parent_id="p-1")
            validate_status_transition("inbox", "active", node, [])
        except ValidationError as e:
            errors.append(e)

        # XOR_VIOLATION
        try:
            validate_xor_constraint(True, "p-1")
        except ValidationError as e:
            errors.append(e)

        # ARCHIVED_TARGET
        try:
            validate_active_domain(_make_node(archived_at="2026-01-01"))
        except ValidationError as e:
            errors.append(e)

        return errors

    def test_all_errors_have_required_attributes(self):
        """每个 ValidationError 都有 code, message, suggestion。"""
        errors = self._collect_errors()
        assert len(errors) >= 4, "Expected at least 4 different errors"
        for err in errors:
            assert err.code, f"Missing code: {err}"
            assert err.message, f"Missing message: {err}"
            assert err.suggestion, f"Missing suggestion: {err}"
