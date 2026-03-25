"""risk.py 测试 — blocked, at_risk, stale 风险标记的纯函数计算。

TDD: 先写测试，再实现。
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional

import pytest

from fpms.spine.models import Node, RiskMarks
from fpms.spine.schema import init_db
from fpms.spine.store import Store
from fpms.spine.risk import compute_risk_marks, compute_risk_marks_batch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _make_node(
    node_id: str = "task-0001",
    status: str = "active",
    deadline: Optional[str] = None,
    status_changed_at: Optional[str] = None,
    archived_at: Optional[str] = None,
    node_type: str = "task",
    parent_id: Optional[str] = None,
    is_root: bool = False,
) -> Node:
    now = _iso(_now())
    return Node(
        id=node_id,
        title=f"Node {node_id}",
        status=status,
        node_type=node_type,
        is_root=is_root,
        parent_id=parent_id,
        created_at=now,
        updated_at=now,
        status_changed_at=status_changed_at or now,
        archived_at=archived_at,
        deadline=deadline,
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
    """Insert a Node directly into DB without ID generation."""
    import json
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
            node.summary, node.why, node.next_step, node.owner,
            node.deadline, int(node.is_persistent),
            node.created_at, node.updated_at,
            node.status_changed_at or now,
            node.archived_at,
            node.source, node.source_id, node.source_url,
            node.source_synced_at, int(node.source_deleted),
            int(node.needs_compression), int(node.compression_in_progress),
            int(node.no_llm_compression),
            json.dumps(node.tags),
        ),
    )
    store._conn.commit()


def _insert_depends_on(store: Store, source_id: str, target_id: str) -> None:
    """Insert a depends_on edge."""
    now = _iso(_now())
    store._conn.execute(
        "INSERT INTO edges (source_id, target_id, edge_type, created_at) VALUES (?,?,?,?)",
        (source_id, target_id, "depends_on", now),
    )
    store._conn.commit()


# ===========================================================================
# TestBlocked
# ===========================================================================

class TestBlocked:
    """blocked 标记测试。"""

    def test_dependency_not_done_is_blocked(self, store):
        """依赖节点非 done → blocked=True。"""
        dep = _make_node("dep-001", status="active")
        node = _make_node("task-001", status="active")
        _insert_node(store, dep)
        _insert_node(store, node)
        _insert_depends_on(store, "task-001", "dep-001")

        now = _now()
        marks = compute_risk_marks(node, store, now=now)
        assert marks.blocked is True
        assert "dep-001" in marks.blocked_by

    def test_dependency_done_is_not_blocked(self, store):
        """依赖节点 done → blocked=False。"""
        dep = _make_node("dep-001", status="done")
        node = _make_node("task-001", status="active")
        _insert_node(store, dep)
        _insert_node(store, node)
        _insert_depends_on(store, "task-001", "dep-001")

        now = _now()
        marks = compute_risk_marks(node, store, now=now)
        assert marks.blocked is False
        assert marks.blocked_by == []

    def test_dependency_dropped_still_blocked(self, store):
        """依赖节点 dropped → 仍然 blocked=True（dropped 不解锁）。"""
        dep = _make_node("dep-001", status="dropped")
        node = _make_node("task-001", status="active")
        _insert_node(store, dep)
        _insert_node(store, node)
        _insert_depends_on(store, "task-001", "dep-001")

        now = _now()
        marks = compute_risk_marks(node, store, now=now)
        assert marks.blocked is True
        assert "dep-001" in marks.blocked_by

    def test_terminal_node_never_blocked(self, store):
        """终态节点（done/dropped）永远不 blocked。"""
        dep = _make_node("dep-001", status="active")
        done_node = _make_node("task-done", status="done")
        dropped_node = _make_node("task-dropped", status="dropped")

        _insert_node(store, dep)
        _insert_node(store, done_node)
        _insert_node(store, dropped_node)
        _insert_depends_on(store, "task-done", "dep-001")
        _insert_depends_on(store, "task-dropped", "dep-001")

        now = _now()
        marks_done = compute_risk_marks(done_node, store, now=now)
        marks_dropped = compute_risk_marks(dropped_node, store, now=now)

        assert marks_done.blocked is False
        assert marks_dropped.blocked is False

    def test_no_dependencies_not_blocked(self, store):
        """无依赖 → blocked=False。"""
        node = _make_node("task-001", status="active")
        _insert_node(store, node)

        now = _now()
        marks = compute_risk_marks(node, store, now=now)
        assert marks.blocked is False
        assert marks.blocked_by == []

    def test_multiple_deps_one_not_done_blocked(self, store):
        """多个依赖，其中一个非 done → blocked，blocked_by 包含该依赖。"""
        dep_done = _make_node("dep-done", status="done")
        dep_active = _make_node("dep-active", status="active")
        node = _make_node("task-001", status="active")

        _insert_node(store, dep_done)
        _insert_node(store, dep_active)
        _insert_node(store, node)
        _insert_depends_on(store, "task-001", "dep-done")
        _insert_depends_on(store, "task-001", "dep-active")

        now = _now()
        marks = compute_risk_marks(node, store, now=now)
        assert marks.blocked is True
        assert "dep-active" in marks.blocked_by
        assert "dep-done" not in marks.blocked_by

    def test_all_deps_done_not_blocked(self, store):
        """所有依赖都 done → not blocked。"""
        dep1 = _make_node("dep-001", status="done")
        dep2 = _make_node("dep-002", status="done")
        node = _make_node("task-001", status="active")

        _insert_node(store, dep1)
        _insert_node(store, dep2)
        _insert_node(store, node)
        _insert_depends_on(store, "task-001", "dep-001")
        _insert_depends_on(store, "task-001", "dep-002")

        now = _now()
        marks = compute_risk_marks(node, store, now=now)
        assert marks.blocked is False


# ===========================================================================
# TestAtRisk
# ===========================================================================

class TestAtRisk:
    """at_risk 标记测试（deadline < NOW+48h）。"""

    def test_deadline_within_48h_is_at_risk(self, store):
        """deadline 在 48 小时内 → at_risk=True。"""
        now = _now()
        deadline = now + timedelta(hours=24)
        node = _make_node("task-001", status="active", deadline=_iso(deadline))
        _insert_node(store, node)

        marks = compute_risk_marks(node, store, now=now)
        assert marks.at_risk is True

    def test_deadline_exactly_48h_is_at_risk(self, store):
        """deadline 恰好在 48 小时内（47h59m）→ at_risk=True。"""
        now = _now()
        deadline = now + timedelta(hours=47, minutes=59)
        node = _make_node("task-001", status="active", deadline=_iso(deadline))
        _insert_node(store, node)

        marks = compute_risk_marks(node, store, now=now)
        assert marks.at_risk is True

    def test_deadline_far_away_not_at_risk(self, store):
        """deadline 在 72 小时后 → at_risk=False。"""
        now = _now()
        deadline = now + timedelta(hours=72)
        node = _make_node("task-001", status="active", deadline=_iso(deadline))
        _insert_node(store, node)

        marks = compute_risk_marks(node, store, now=now)
        assert marks.at_risk is False

    def test_terminal_node_not_at_risk(self, store):
        """终态节点不标记 at_risk，即使 deadline 已过。"""
        now = _now()
        deadline = now - timedelta(hours=1)  # 已过期
        done_node = _make_node("task-done", status="done", deadline=_iso(deadline))
        dropped_node = _make_node("task-dropped", status="dropped", deadline=_iso(deadline))

        _insert_node(store, done_node)
        _insert_node(store, dropped_node)

        marks_done = compute_risk_marks(done_node, store, now=now)
        marks_dropped = compute_risk_marks(dropped_node, store, now=now)

        assert marks_done.at_risk is False
        assert marks_dropped.at_risk is False

    def test_no_deadline_not_at_risk(self, store):
        """无 deadline → at_risk=False。"""
        node = _make_node("task-001", status="active", deadline=None)
        _insert_node(store, node)

        now = _now()
        marks = compute_risk_marks(node, store, now=now)
        assert marks.at_risk is False

    def test_deadline_hours_populated_when_at_risk(self, store):
        """at_risk 时 deadline_hours 应被填充。"""
        now = _now()
        deadline = now + timedelta(hours=10)
        node = _make_node("task-001", status="active", deadline=_iso(deadline))
        _insert_node(store, node)

        marks = compute_risk_marks(node, store, now=now)
        assert marks.at_risk is True
        assert marks.deadline_hours is not None
        assert abs(marks.deadline_hours - 10.0) < 0.1  # ~10 hours


# ===========================================================================
# TestStale
# ===========================================================================

class TestStale:
    """stale 标记测试（status_changed_at 超过 72 小时）。"""

    def test_active_after_72h_is_stale(self, store):
        """active 状态超过 72 小时 → stale=True。"""
        now = _now()
        old_time = _iso(now - timedelta(hours=73))
        node = _make_node("task-001", status="active", status_changed_at=old_time)
        _insert_node(store, node)

        marks = compute_risk_marks(node, store, now=now)
        assert marks.stale is True

    def test_waiting_after_72h_is_stale(self, store):
        """waiting 状态超过 72 小时 → stale=True。"""
        now = _now()
        old_time = _iso(now - timedelta(hours=80))
        node = _make_node("task-001", status="waiting", status_changed_at=old_time)
        _insert_node(store, node)

        marks = compute_risk_marks(node, store, now=now)
        assert marks.stale is True

    def test_active_within_72h_not_stale(self, store):
        """active 状态在 72 小时内 → stale=False。"""
        now = _now()
        recent_time = _iso(now - timedelta(hours=48))
        node = _make_node("task-001", status="active", status_changed_at=recent_time)
        _insert_node(store, node)

        marks = compute_risk_marks(node, store, now=now)
        assert marks.stale is False

    def test_inbox_not_stale(self, store):
        """inbox 状态（非 active/waiting）即使超过 72h → stale=False。"""
        now = _now()
        old_time = _iso(now - timedelta(hours=100))
        node = _make_node("task-001", status="inbox", status_changed_at=old_time)
        _insert_node(store, node)

        marks = compute_risk_marks(node, store, now=now)
        assert marks.stale is False

    def test_terminal_not_stale(self, store):
        """终态节点（done/dropped）不标记 stale。"""
        now = _now()
        old_time = _iso(now - timedelta(hours=200))
        done_node = _make_node("task-done", status="done", status_changed_at=old_time)
        dropped_node = _make_node("task-dropped", status="dropped", status_changed_at=old_time)

        _insert_node(store, done_node)
        _insert_node(store, dropped_node)

        marks_done = compute_risk_marks(done_node, store, now=now)
        marks_dropped = compute_risk_marks(dropped_node, store, now=now)

        assert marks_done.stale is False
        assert marks_dropped.stale is False

    def test_exactly_72h_not_stale(self, store):
        """恰好 72 小时（不超过）→ stale=False（边界：strictly older than 72h）。"""
        now = _now()
        exactly_72h = _iso(now - timedelta(hours=72))
        node = _make_node("task-001", status="active", status_changed_at=exactly_72h)
        _insert_node(store, node)

        marks = compute_risk_marks(node, store, now=now)
        # Exactly 72h is NOT stale; must be strictly greater than 72h
        assert marks.stale is False


# ===========================================================================
# TestBatch
# ===========================================================================

class TestBatch:
    """compute_risk_marks_batch 测试。"""

    def test_batch_returns_all_ids(self, store):
        """batch 应为每个传入节点返回结果。"""
        now = _now()
        node1 = _make_node("task-001", status="active")
        node2 = _make_node("task-002", status="done")
        _insert_node(store, node1)
        _insert_node(store, node2)

        result = compute_risk_marks_batch([node1, node2], store, now=now)
        assert "task-001" in result
        assert "task-002" in result

    def test_batch_terminal_no_marks(self, store):
        """batch: 终态节点无风险标记。"""
        now = _now()
        deadline = now + timedelta(hours=1)
        old_time = _iso(now - timedelta(hours=100))
        node = _make_node("task-done", status="done",
                          deadline=_iso(deadline), status_changed_at=old_time)
        _insert_node(store, node)

        result = compute_risk_marks_batch([node], store, now=now)
        marks = result["task-done"]
        assert marks.blocked is False
        assert marks.at_risk is False
        assert marks.stale is False

    def test_batch_empty_list(self, store):
        """batch: 空列表 → 空字典。"""
        result = compute_risk_marks_batch([], store, now=_now())
        assert result == {}
