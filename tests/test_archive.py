"""archive.py 测试 — 归档候选扫描与执行。

TDD: 先写测试，再实现。

覆盖 FR-6 归档条件：
1. status in (done, dropped)
2. status_changed_at < NOW() - 7 days
3. archived_at IS NULL
4. is_persistent = False
5. 无未归档的 depends_on 依赖者
6. 无未归档的后代节点
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone, timedelta
from typing import Optional

import pytest

from fpms.spine.models import Node
from fpms.spine.schema import init_db
from fpms.spine.store import Store
from fpms.spine.archive import (
    scan_archive_candidates,
    execute_archive,
    execute_archive_batch,
)


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
    status_changed_at: Optional[str] = None,
    archived_at: Optional[str] = None,
    is_persistent: bool = False,
    parent_id: Optional[str] = None,
    node_type: str = "task",
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
        is_persistent=is_persistent,
        created_at=now,
        updated_at=now,
        status_changed_at=status_changed_at or now,
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
    """Insert a Node directly into DB without ID generation."""
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
    """Insert a depends_on edge: source depends on target."""
    now = _iso(_now())
    store._conn.execute(
        "INSERT INTO edges (source_id, target_id, edge_type, created_at) VALUES (?,?,?,?)",
        (source_id, target_id, "depends_on", now),
    )
    store._conn.commit()


def _old_enough(days: int = 8) -> str:
    """Return ISO timestamp that is `days` days in the past."""
    return _iso(_now() - timedelta(days=days))


# ===========================================================================
# TestScanCandidates
# ===========================================================================

class TestScanCandidates:
    """scan_archive_candidates 测试。"""

    def test_done_old_no_deps_no_children_eligible(self, store):
        """done 7+ 天，无依赖者，无子节点 → 应被候选。"""
        now = _now()
        node = _make_node(
            "task-done",
            status="done",
            status_changed_at=_old_enough(8),
        )
        _insert_node(store, node)

        candidates = scan_archive_candidates(store, now=now)
        assert "task-done" in candidates

    def test_done_only_3_days_not_eligible(self, store):
        """done 但只有 3 天 → 冷却期未满，不应被候选。"""
        now = _now()
        node = _make_node(
            "task-recent",
            status="done",
            status_changed_at=_iso(now - timedelta(days=3)),
        )
        _insert_node(store, node)

        candidates = scan_archive_candidates(store, now=now)
        assert "task-recent" not in candidates

    def test_done_old_has_unarchived_dependent_not_eligible(self, store):
        """done 7+ 天，但有未归档的 depends_on 依赖者 → 不应被候选。"""
        now = _now()
        # node-a is done and old
        node_a = _make_node("task-aaaa", status="done", status_changed_at=_old_enough(8))
        # node-b depends on node-a and is still active (unarchived)
        node_b = _make_node("task-bbbb", status="active")
        _insert_node(store, node_a)
        _insert_node(store, node_b)
        # node_b depends_on node_a → node_a has a dependent
        _insert_depends_on(store, "task-bbbb", "task-aaaa")

        candidates = scan_archive_candidates(store, now=now)
        assert "task-aaaa" not in candidates

    def test_done_old_has_unarchived_child_not_eligible(self, store):
        """done 7+ 天，但有未归档的子节点 → 不应被候选。"""
        now = _now()
        parent = _make_node(
            "goal-pppp",
            status="done",
            status_changed_at=_old_enough(8),
            node_type="goal",
        )
        child = _make_node(
            "task-cccc",
            status="active",
            parent_id="goal-pppp",
        )
        _insert_node(store, parent)
        _insert_node(store, child)

        candidates = scan_archive_candidates(store, now=now)
        assert "goal-pppp" not in candidates

    def test_done_old_is_persistent_not_eligible(self, store):
        """done 7+ 天，但 is_persistent=True → 不应被候选。"""
        now = _now()
        node = _make_node(
            "task-perm",
            status="done",
            status_changed_at=_old_enough(8),
            is_persistent=True,
        )
        _insert_node(store, node)

        candidates = scan_archive_candidates(store, now=now)
        assert "task-perm" not in candidates

    def test_already_archived_not_eligible(self, store):
        """已归档节点 → 不应再次出现在候选列表。"""
        now = _now()
        node = _make_node(
            "task-arch",
            status="done",
            status_changed_at=_old_enough(8),
            archived_at=_old_enough(1),
        )
        _insert_node(store, node)

        candidates = scan_archive_candidates(store, now=now)
        assert "task-arch" not in candidates

    def test_active_node_not_eligible(self, store):
        """active 节点不满足终态条件 → 不应被候选。"""
        now = _now()
        node = _make_node(
            "task-actv",
            status="active",
            status_changed_at=_old_enough(10),
        )
        _insert_node(store, node)

        candidates = scan_archive_candidates(store, now=now)
        assert "task-actv" not in candidates

    def test_dropped_old_eligible(self, store):
        """dropped 7+ 天，无依赖者，无子节点 → 应被候选。"""
        now = _now()
        node = _make_node(
            "task-drop",
            status="dropped",
            status_changed_at=_old_enough(9),
        )
        _insert_node(store, node)

        candidates = scan_archive_candidates(store, now=now)
        assert "task-drop" in candidates

    def test_done_old_dependent_already_archived_eligible(self, store):
        """done 7+ 天，依赖者已归档 → 应被候选（已归档依赖者不阻止）。"""
        now = _now()
        node_a = _make_node("task-aaaa", status="done", status_changed_at=_old_enough(8))
        # node_b depends on node_a but is already archived
        node_b = _make_node(
            "task-bbbb",
            status="done",
            status_changed_at=_old_enough(10),
            archived_at=_old_enough(2),
        )
        _insert_node(store, node_a)
        _insert_node(store, node_b)
        _insert_depends_on(store, "task-bbbb", "task-aaaa")

        candidates = scan_archive_candidates(store, now=now)
        assert "task-aaaa" in candidates


# ===========================================================================
# TestExecuteArchive
# ===========================================================================

class TestExecuteArchive:
    """execute_archive 测试。"""

    def test_sets_archived_at_correctly(self, store):
        """执行归档后 archived_at 应被正确设置。"""
        now = _now()
        node = _make_node(
            "task-done",
            status="done",
            status_changed_at=_old_enough(8),
        )
        _insert_node(store, node)

        result = execute_archive(store, "task-done", now=now)
        assert result is True

        updated = store.get_node("task-done")
        assert updated is not None
        assert updated.archived_at is not None
        # Verify it's close to `now`
        archived_dt = datetime.fromisoformat(updated.archived_at)
        if archived_dt.tzinfo is None:
            archived_dt = archived_dt.replace(tzinfo=timezone.utc)
        diff = abs((archived_dt - now).total_seconds())
        assert diff < 5  # within 5 seconds

    def test_reverifies_conditions_before_archiving(self, store):
        """执行前再次校验条件；条件满足则返回 True。"""
        now = _now()
        node = _make_node(
            "task-done",
            status="done",
            status_changed_at=_old_enough(8),
        )
        _insert_node(store, node)

        # Should succeed
        result = execute_archive(store, "task-done", now=now)
        assert result is True

    def test_returns_false_if_conditions_changed(self, store):
        """条件改变后（如出现新的未归档依赖者）→ 返回 False，不执行归档。"""
        now = _now()
        node_a = _make_node("task-aaaa", status="done", status_changed_at=_old_enough(8))
        node_b = _make_node("task-bbbb", status="active")
        _insert_node(store, node_a)
        _insert_node(store, node_b)
        # node_b depends on node_a — blocks archiving node_a
        _insert_depends_on(store, "task-bbbb", "task-aaaa")

        result = execute_archive(store, "task-aaaa", now=now)
        assert result is False

        # archived_at must remain NULL
        node = store.get_node("task-aaaa")
        assert node is not None
        assert node.archived_at is None

    def test_returns_false_for_active_node(self, store):
        """active 节点不满足条件 → 返回 False。"""
        now = _now()
        node = _make_node(
            "task-actv",
            status="active",
            status_changed_at=_old_enough(10),
        )
        _insert_node(store, node)

        result = execute_archive(store, "task-actv", now=now)
        assert result is False

    def test_returns_false_for_recent_done(self, store):
        """done 但冷却期未满 → 返回 False。"""
        now = _now()
        node = _make_node(
            "task-new",
            status="done",
            status_changed_at=_iso(now - timedelta(days=3)),
        )
        _insert_node(store, node)

        result = execute_archive(store, "task-new", now=now)
        assert result is False


# ===========================================================================
# TestBottomUp
# ===========================================================================

class TestBottomUp:
    """底部优先（bottom-up）顺序测试。"""

    def test_parent_not_eligible_while_child_unarchived(self, store):
        """子节点未归档时父节点不应出现在候选列表中。"""
        now = _now()
        parent = _make_node(
            "goal-pppp",
            status="done",
            status_changed_at=_old_enough(8),
            node_type="goal",
        )
        child = _make_node(
            "task-cccc",
            status="done",
            status_changed_at=_old_enough(8),
            parent_id="goal-pppp",
        )
        _insert_node(store, parent)
        _insert_node(store, child)

        candidates = scan_archive_candidates(store, now=now)
        # child should be in candidates
        assert "task-cccc" in candidates
        # parent should NOT be in candidates until child is archived
        assert "goal-pppp" not in candidates

    def test_batch_archives_children_before_parents(self, store):
        """execute_archive_batch 应先归档子节点，再归档父节点。"""
        now = _now()
        parent = _make_node(
            "goal-pppp",
            status="done",
            status_changed_at=_old_enough(8),
            node_type="goal",
        )
        child = _make_node(
            "task-cccc",
            status="done",
            status_changed_at=_old_enough(8),
            parent_id="goal-pppp",
        )
        _insert_node(store, parent)
        _insert_node(store, child)

        # First pass: scan gets only child
        first_candidates = scan_archive_candidates(store, now=now)
        assert "task-cccc" in first_candidates
        assert "goal-pppp" not in first_candidates

        # Archive the child first
        count = execute_archive_batch(store, first_candidates, now=now)
        assert count == 1

        # Second pass: parent now eligible
        second_candidates = scan_archive_candidates(store, now=now)
        assert "goal-pppp" in second_candidates

        count2 = execute_archive_batch(store, second_candidates, now=now)
        assert count2 == 1

        # Both should be archived now
        parent_node = store.get_node("goal-pppp")
        child_node = store.get_node("task-cccc")
        assert parent_node.archived_at is not None
        assert child_node.archived_at is not None

    def test_batch_returns_count_of_archived(self, store):
        """execute_archive_batch 应返回成功归档的数量。"""
        now = _now()
        node1 = _make_node("task-1111", status="done", status_changed_at=_old_enough(8))
        node2 = _make_node("task-2222", status="done", status_changed_at=_old_enough(8))
        node3 = _make_node("task-3333", status="dropped", status_changed_at=_old_enough(8))
        _insert_node(store, node1)
        _insert_node(store, node2)
        _insert_node(store, node3)

        candidates = scan_archive_candidates(store, now=now)
        count = execute_archive_batch(store, candidates, now=now)
        assert count == 3

    def test_batch_skips_ineligible_nodes(self, store):
        """execute_archive_batch 中不满足条件的节点被跳过，不计入结果。"""
        now = _now()
        # eligible
        node_good = _make_node("task-good", status="done", status_changed_at=_old_enough(8))
        # ineligible: too recent
        node_bad = _make_node(
            "task-bad",
            status="done",
            status_changed_at=_iso(now - timedelta(days=2)),
        )
        _insert_node(store, node_good)
        _insert_node(store, node_bad)

        # Manually pass both IDs (simulating stale scan result)
        count = execute_archive_batch(store, ["task-good", "task-bad"], now=now)
        assert count == 1

        node_bad_after = store.get_node("task-bad")
        assert node_bad_after.archived_at is None

    def test_grandchild_archived_before_parent(self, store):
        """三层结构：grandchild 先归档，再 child，最后 parent。"""
        now = _now()
        grandparent = _make_node(
            "goal-gggg",
            status="done",
            status_changed_at=_old_enough(8),
            node_type="goal",
        )
        parent_node = _make_node(
            "mile-pppp",
            status="done",
            status_changed_at=_old_enough(8),
            parent_id="goal-gggg",
            node_type="milestone",
        )
        grandchild = _make_node(
            "task-cccc",
            status="done",
            status_changed_at=_old_enough(8),
            parent_id="mile-pppp",
        )
        _insert_node(store, grandparent)
        _insert_node(store, parent_node)
        _insert_node(store, grandchild)

        # Round 1: only grandchild eligible
        r1 = scan_archive_candidates(store, now=now)
        assert "task-cccc" in r1
        assert "mile-pppp" not in r1
        assert "goal-gggg" not in r1
        execute_archive_batch(store, r1, now=now)

        # Round 2: only parent_node eligible
        r2 = scan_archive_candidates(store, now=now)
        assert "mile-pppp" in r2
        assert "goal-gggg" not in r2
        execute_archive_batch(store, r2, now=now)

        # Round 3: grandparent eligible
        r3 = scan_archive_candidates(store, now=now)
        assert "goal-gggg" in r3
        execute_archive_batch(store, r3, now=now)

        # Verify all archived
        for nid in ["goal-gggg", "mile-pppp", "task-cccc"]:
            n = store.get_node(nid)
            assert n.archived_at is not None, f"{nid} should be archived"
