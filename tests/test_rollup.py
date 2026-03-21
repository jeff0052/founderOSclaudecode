"""rollup.py 测试 — 递归自底向上的状态汇总。

TDD: 先写测试，再实现。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional

import pytest

from fpms.spine.models import Node, RiskMarks, RollupResult
from fpms.spine.store import Store
from fpms.spine.rollup import compute_rollup


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _make_node(
    node_id: str,
    status: str = "active",
    parent_id: Optional[str] = None,
    is_root: bool = False,
    archived_at: Optional[str] = None,
) -> Node:
    now = _iso(_now())
    return Node(
        id=node_id,
        title=f"Node {node_id}",
        status=status,
        node_type="task",
        is_root=is_root,
        parent_id=parent_id,
        created_at=now,
        updated_at=now,
        status_changed_at=now,
        archived_at=archived_at,
    )


@pytest.fixture
def store(tmp_path):
    """Provide a real Store backed by a temp SQLite DB."""
    db_path = str(tmp_path / "test.db")
    events_path = str(tmp_path / "events.jsonl")
    s = Store(db_path=db_path, events_path=events_path)
    yield s
    s._conn.close()


def _insert_node(store: Store, node: Node) -> None:
    """Insert a Node directly into DB."""
    now = _iso(_now())
    store._conn.execute(
        """INSERT INTO nodes (
            id, title, status, node_type, is_root, parent_id,
            summary, why, next_step, owner, deadline, is_persistent,
            created_at, updated_at, status_changed_at, archived_at,
            source, source_id, source_url, source_synced_at, source_deleted,
            needs_compression, compression_in_progress, no_llm_compression, tags
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            node.id, node.title, node.status, node.node_type,
            int(node.is_root), node.parent_id,
            None, None, None, None,
            None, 0,
            node.created_at, node.updated_at,
            node.status_changed_at or now,
            node.archived_at,
            "internal", None, None, None, 0,
            0, 0, 0, "[]",
        ),
    )
    store._conn.commit()


# ===========================================================================
# TestRollupBasic
# ===========================================================================

class TestRollupBasic:
    """基本 rollup 规则测试。"""

    def test_leaf_returns_own_status(self, store):
        """叶节点无子节点 → rollup_status = 自身 status。"""
        leaf = _make_node("leaf-001", status="active")
        _insert_node(store, leaf)

        result = compute_rollup("leaf-001", store)
        assert result.node_id == "leaf-001"
        assert result.rollup_status == "active"

    def test_leaf_waiting_returns_waiting(self, store):
        """waiting 叶节点 → rollup_status = waiting。"""
        leaf = _make_node("leaf-001", status="waiting")
        _insert_node(store, leaf)

        result = compute_rollup("leaf-001", store)
        assert result.rollup_status == "waiting"

    def test_active_child_makes_parent_active(self, store):
        """有 active 子节点 → parent rollup_status = active。"""
        parent = _make_node("parent-001", status="waiting", is_root=True)
        child = _make_node("child-001", status="active", parent_id="parent-001")
        _insert_node(store, parent)
        _insert_node(store, child)

        result = compute_rollup("parent-001", store)
        assert result.rollup_status == "active"

    def test_waiting_child_makes_parent_waiting(self, store):
        """只有 waiting 子节点 → parent rollup_status = waiting。"""
        parent = _make_node("parent-001", status="active", is_root=True)
        child = _make_node("child-001", status="waiting", parent_id="parent-001")
        _insert_node(store, parent)
        _insert_node(store, child)

        result = compute_rollup("parent-001", store)
        assert result.rollup_status == "waiting"

    def test_all_done_children_returns_done(self, store):
        """所有子节点 done → rollup_status = done。"""
        parent = _make_node("parent-001", status="active", is_root=True)
        child1 = _make_node("child-001", status="done", parent_id="parent-001")
        child2 = _make_node("child-002", status="done", parent_id="parent-001")
        _insert_node(store, parent)
        _insert_node(store, child1)
        _insert_node(store, child2)

        result = compute_rollup("parent-001", store)
        assert result.rollup_status == "done"

    def test_all_dropped_children_returns_dropped(self, store):
        """所有子节点 dropped → rollup_status = dropped。"""
        parent = _make_node("parent-001", status="active", is_root=True)
        child1 = _make_node("child-001", status="dropped", parent_id="parent-001")
        child2 = _make_node("child-002", status="dropped", parent_id="parent-001")
        _insert_node(store, parent)
        _insert_node(store, child1)
        _insert_node(store, child2)

        result = compute_rollup("parent-001", store)
        assert result.rollup_status == "dropped"

    def test_mixed_done_and_dropped_returns_done(self, store):
        """done + dropped 混合（任意一个 done）→ rollup_status = done。"""
        parent = _make_node("parent-001", status="active", is_root=True)
        child1 = _make_node("child-001", status="done", parent_id="parent-001")
        child2 = _make_node("child-002", status="dropped", parent_id="parent-001")
        _insert_node(store, parent)
        _insert_node(store, child1)
        _insert_node(store, child2)

        result = compute_rollup("parent-001", store)
        assert result.rollup_status == "done"

    def test_active_beats_waiting(self, store):
        """active 优先级高于 waiting → rollup_status = active。"""
        parent = _make_node("parent-001", status="inbox", is_root=True)
        child1 = _make_node("child-001", status="active", parent_id="parent-001")
        child2 = _make_node("child-002", status="waiting", parent_id="parent-001")
        _insert_node(store, parent)
        _insert_node(store, child1)
        _insert_node(store, child2)

        result = compute_rollup("parent-001", store)
        assert result.rollup_status == "active"


# ===========================================================================
# TestRollupInbox
# ===========================================================================

class TestRollupInbox:
    """inbox 子节点应从 rollup 中排除（FR-7）。"""

    def test_inbox_children_excluded(self, store):
        """inbox 子节点不参与 rollup，只有 active 子节点决定结果。"""
        parent = _make_node("parent-001", status="inbox", is_root=True)
        inbox_child = _make_node("inbox-child", status="inbox", parent_id="parent-001")
        active_child = _make_node("active-child", status="active", parent_id="parent-001")
        _insert_node(store, parent)
        _insert_node(store, inbox_child)
        _insert_node(store, active_child)

        result = compute_rollup("parent-001", store)
        # inbox child excluded, active child wins
        assert result.rollup_status == "active"

    def test_only_inbox_children_falls_back_to_own_status(self, store):
        """只有 inbox 子节点时，fallback 到节点自身 status。"""
        parent = _make_node("parent-001", status="waiting", is_root=True)
        inbox_child = _make_node("inbox-child", status="inbox", parent_id="parent-001")
        _insert_node(store, parent)
        _insert_node(store, inbox_child)

        result = compute_rollup("parent-001", store)
        # No non-inbox children → use own status
        assert result.rollup_status == "waiting"

    def test_no_children_at_all_falls_back_to_own_status(self, store):
        """无子节点时，fallback 到节点自身 status。"""
        parent = _make_node("parent-001", status="done", is_root=True)
        _insert_node(store, parent)

        result = compute_rollup("parent-001", store)
        assert result.rollup_status == "done"


# ===========================================================================
# TestRollupArchived
# ===========================================================================

class TestRollupArchived:
    """已归档子节点应纳入 rollup 计算（分母保留）。"""

    def test_archived_children_included_in_rollup(self, store):
        """归档子节点参与 rollup（不过滤归档）。"""
        parent = _make_node("parent-001", status="active", is_root=True)
        # Archived done child
        archived_child = _make_node(
            "archived-child", status="done", parent_id="parent-001",
            archived_at=_iso(_now() - timedelta(days=1))
        )
        _insert_node(store, parent)
        _insert_node(store, archived_child)

        result = compute_rollup("parent-001", store)
        # archived child counts: status=done, rollup should be done
        assert result.rollup_status == "done"

    def test_archived_active_child_still_counts(self, store):
        """归档的 active 子节点也计入 rollup（保留分母）。"""
        parent = _make_node("parent-001", status="done", is_root=True)
        archived_active = _make_node(
            "archived-active", status="active", parent_id="parent-001",
            archived_at=_iso(_now() - timedelta(days=1))
        )
        _insert_node(store, parent)
        _insert_node(store, archived_active)

        result = compute_rollup("parent-001", store)
        # archived active child counts → parent active
        assert result.rollup_status == "active"


# ===========================================================================
# TestRollupRecursive
# ===========================================================================

class TestRollupRecursive:
    """递归三层树测试。"""

    def test_three_level_tree_propagates_correctly(self, store):
        """三层树: grandchild active → parent active → root active。"""
        root = _make_node("root-001", status="done", is_root=True)
        mid = _make_node("mid-001", status="done", parent_id="root-001")
        leaf = _make_node("leaf-001", status="active", parent_id="mid-001")

        _insert_node(store, root)
        _insert_node(store, mid)
        _insert_node(store, leaf)

        result_root = compute_rollup("root-001", store)
        result_mid = compute_rollup("mid-001", store)

        assert result_mid.rollup_status == "active"
        assert result_root.rollup_status == "active"

    def test_three_level_all_done_propagates_done(self, store):
        """三层树: 所有叶都 done → 全树 done。"""
        root = _make_node("root-001", status="active", is_root=True)
        mid = _make_node("mid-001", status="active", parent_id="root-001")
        leaf1 = _make_node("leaf-001", status="done", parent_id="mid-001")
        leaf2 = _make_node("leaf-002", status="done", parent_id="mid-001")

        _insert_node(store, root)
        _insert_node(store, mid)
        _insert_node(store, leaf1)
        _insert_node(store, leaf2)

        result_mid = compute_rollup("mid-001", store)
        result_root = compute_rollup("root-001", store)

        assert result_mid.rollup_status == "done"
        assert result_root.rollup_status == "done"

    def test_cache_reuse_within_computation(self, store):
        """同一节点 id 使用同一 _cache 时不重复计算（幂等结果）。"""
        parent = _make_node("parent-001", status="active", is_root=True)
        child = _make_node("child-001", status="done", parent_id="parent-001")
        _insert_node(store, parent)
        _insert_node(store, child)

        cache: dict = {}
        result1 = compute_rollup("parent-001", store, _cache=cache)
        result2 = compute_rollup("parent-001", store, _cache=cache)

        assert result1.rollup_status == result2.rollup_status
        assert "parent-001" in cache


# ===========================================================================
# TestRollupRiskExposure
# ===========================================================================

class TestRollupRiskExposure:
    """风险传播测试：子节点有风险 → parent has_risk_children=True。"""

    def test_child_with_risk_sets_has_risk_children(self, store):
        """子节点有风险标记 → parent.has_risk_children=True。"""
        parent = _make_node("parent-001", status="active", is_root=True)
        child = _make_node("child-001", status="active", parent_id="parent-001")
        _insert_node(store, parent)
        _insert_node(store, child)

        # child is blocked
        child_marks = RiskMarks(blocked=True, blocked_by=["dep-x"])
        risk_map = {"child-001": child_marks}

        result = compute_rollup("parent-001", store, risk_marks_map=risk_map)
        assert result.has_risk_children is True

    def test_no_risk_children_false(self, store):
        """子节点无风险 → parent.has_risk_children=False。"""
        parent = _make_node("parent-001", status="active", is_root=True)
        child = _make_node("child-001", status="active", parent_id="parent-001")
        _insert_node(store, parent)
        _insert_node(store, child)

        child_marks = RiskMarks()  # all False
        risk_map = {"child-001": child_marks}

        result = compute_rollup("parent-001", store, risk_marks_map=risk_map)
        assert result.has_risk_children is False

    def test_risk_summary_populated_for_at_risk_child(self, store):
        """at_risk 子节点 → risk_summary 包含描述信息。"""
        parent = _make_node("parent-001", status="active", is_root=True)
        child = _make_node("child-001", status="active", parent_id="parent-001")
        _insert_node(store, parent)
        _insert_node(store, child)

        child_marks = RiskMarks(at_risk=True, deadline_hours=10.0)
        risk_map = {"child-001": child_marks}

        result = compute_rollup("parent-001", store, risk_marks_map=risk_map)
        assert result.has_risk_children is True
        assert len(result.risk_summary) > 0

    def test_no_risk_map_defaults_false(self, store):
        """不传 risk_marks_map → has_risk_children=False（默认安全）。"""
        parent = _make_node("parent-001", status="active", is_root=True)
        child = _make_node("child-001", status="active", parent_id="parent-001")
        _insert_node(store, parent)
        _insert_node(store, child)

        result = compute_rollup("parent-001", store, risk_marks_map=None)
        assert result.has_risk_children is False
