"""v1 集成验证测试 — 5 个端到端场景。

覆盖 SpineEngine 所有主要认知层模块的协作流程。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from typing import Optional

import pytest

from fpms.spine import SpineEngine
from fpms.spine.models import ContextBundle, Node
from fpms.spine.store import Store
from fpms.spine.archive import scan_archive_candidates, execute_archive


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _ago(days: float = 0, hours: float = 0) -> str:
    """Return ISO timestamp N days/hours ago (UTC-aware)."""
    delta = timedelta(days=days, hours=hours)
    return _iso(_now() - delta)


def _in(hours: float = 0) -> str:
    """Return ISO timestamp N hours in the future (UTC-aware)."""
    return _iso(_now() + timedelta(hours=hours))


def _insert_node(store: Store, node: Node) -> None:
    """Insert a Node directly into DB bypassing ID generation."""
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
            node.created_at or _iso(_now()),
            node.updated_at or _iso(_now()),
            node.status_changed_at or _iso(_now()),
            node.archived_at,
            node.source, node.source_id, node.source_url,
            node.source_synced_at, int(node.source_deleted),
            int(node.needs_compression), int(node.compression_in_progress),
            int(node.no_llm_compression),
            json.dumps(node.tags),
        ),
    )
    store._conn.commit()


def _make_node(
    node_id: str,
    title: str = "",
    status: str = "active",
    node_type: str = "task",
    is_root: bool = False,
    parent_id: Optional[str] = None,
    summary: Optional[str] = None,
    deadline: Optional[str] = None,
    status_changed_at: Optional[str] = None,
    archived_at: Optional[str] = None,
    is_persistent: bool = False,
) -> Node:
    now = _iso(_now())
    return Node(
        id=node_id,
        title=title or f"Node {node_id}",
        status=status,
        node_type=node_type,
        is_root=is_root,
        parent_id=parent_id,
        summary=summary,
        created_at=now,
        updated_at=now,
        status_changed_at=status_changed_at or now,
        archived_at=archived_at,
        deadline=deadline,
        is_persistent=is_persistent,
    )


@pytest.fixture
def engine(tmp_path):
    """SpineEngine backed by a fresh temp SQLite DB."""
    db_path = str(tmp_path / "fpms.db")
    events_path = str(tmp_path / "events.jsonl")
    narratives_dir = str(tmp_path / "narratives")
    eng = SpineEngine(
        db_path=db_path,
        events_path=events_path,
        narratives_dir=narratives_dir,
    )
    yield eng
    eng.store._conn.close()


# ---------------------------------------------------------------------------
# Scenario 1: Cold start with empty DB
# ---------------------------------------------------------------------------

class TestColdStart:
    """Scenario 1: bootstrap() on an empty database returns a valid ContextBundle."""

    def test_bootstrap_returns_context_bundle(self, engine):
        bundle = engine.bootstrap()
        assert isinstance(bundle, ContextBundle)

    def test_bootstrap_l0_dashboard_present(self, engine):
        bundle = engine.bootstrap()
        assert bundle.l0_dashboard
        # Must be a non-empty string starting with the Dashboard header
        assert "Dashboard" in bundle.l0_dashboard

    def test_bootstrap_l_alert_present(self, engine):
        bundle = engine.bootstrap()
        assert bundle.l_alert
        assert isinstance(bundle.l_alert, str)

    def test_bootstrap_total_tokens_is_int(self, engine):
        bundle = engine.bootstrap()
        assert isinstance(bundle.total_tokens, int)
        assert bundle.total_tokens >= 0

    def test_bootstrap_does_not_crash_empty_db(self, engine):
        """No nodes exist — should gracefully return a bundle without raising."""
        try:
            bundle = engine.bootstrap()
        except Exception as exc:
            pytest.fail(f"bootstrap() raised unexpectedly: {exc}")


# ---------------------------------------------------------------------------
# Scenario 2: Multi-level rollup propagation
# ---------------------------------------------------------------------------

class TestRollupPropagation:
    """Scenario 2: rollup propagates through goal → project → task tree."""

    def test_all_done_tasks_rollup_project_done(self, engine):
        store = engine.store
        from fpms.spine import rollup as rollup_mod

        # Build goal → project → task1, task2
        goal = _make_node("goal-0001", "My Goal", status="active",
                          node_type="goal", is_root=True,
                          summary="Goal summary")
        proj = _make_node("proj-0001", "My Project", status="active",
                          node_type="project", parent_id="goal-0001",
                          summary="Project summary")
        task1 = _make_node("task-0001", "Task 1", status="done",
                           node_type="task", parent_id="proj-0001",
                           summary="Task 1 summary")
        task2 = _make_node("task-0002", "Task 2", status="done",
                           node_type="task", parent_id="proj-0001",
                           summary="Task 2 summary")

        for n in [goal, proj, task1, task2]:
            _insert_node(store, n)

        result = rollup_mod.compute_rollup("proj-0001", store)
        assert result.rollup_status == "done"

    def test_done_project_rollup_goal_done(self, engine):
        store = engine.store
        from fpms.spine import rollup as rollup_mod

        goal = _make_node("goal-0001", "Goal", status="active",
                          node_type="goal", is_root=True, summary="g")
        proj = _make_node("proj-0001", "Project", status="done",
                          node_type="project", parent_id="goal-0001",
                          summary="p")

        for n in [goal, proj]:
            _insert_node(store, n)

        result = rollup_mod.compute_rollup("goal-0001", store)
        assert result.rollup_status == "done"

    def test_archived_child_still_counted_in_rollup(self, engine):
        """Archived children are included via get_children_all (denominator preserved)."""
        store = engine.store
        from fpms.spine import rollup as rollup_mod

        proj = _make_node("proj-0001", "Project", status="active",
                          node_type="project", is_root=True, summary="p")
        # Archived done child
        archived_child = _make_node(
            "task-0001", "Archived Task", status="done",
            node_type="task", parent_id="proj-0001",
            summary="t", archived_at=_iso(_now()),
        )
        # Active sibling
        live_child = _make_node("task-0002", "Live Task", status="done",
                                node_type="task", parent_id="proj-0001",
                                summary="t2")

        for n in [proj, archived_child, live_child]:
            _insert_node(store, n)

        result = rollup_mod.compute_rollup("proj-0001", store)
        # Both children are done → rollup should be done
        assert result.rollup_status == "done"

    def test_active_child_makes_rollup_active(self, engine):
        store = engine.store
        from fpms.spine import rollup as rollup_mod

        proj = _make_node("proj-0001", "Project", status="active",
                          node_type="project", is_root=True, summary="p")
        done_child = _make_node("task-0001", "Done", status="done",
                                node_type="task", parent_id="proj-0001",
                                summary="t")
        active_child = _make_node("task-0002", "Active", status="active",
                                  node_type="task", parent_id="proj-0001",
                                  summary="t2")

        for n in [proj, done_child, active_child]:
            _insert_node(store, n)

        result = rollup_mod.compute_rollup("proj-0001", store)
        assert result.rollup_status == "active"


# ---------------------------------------------------------------------------
# Scenario 3: Heartbeat alerts and L_Alert layer
# ---------------------------------------------------------------------------

class TestHeartbeatAndAlerts:
    """Scenario 3: heartbeat.scan() detects stale nodes and urgent deadlines."""

    def test_stale_node_produces_stale_warning(self, engine):
        store = engine.store
        from fpms.spine.heartbeat import Heartbeat
        from fpms.spine import risk as risk_mod, archive as archive_mod

        stale_node = _make_node(
            "task-stale", "Stale Task", status="active",
            node_type="task", is_root=True, summary="stale",
            # status_changed_at more than 72h (3 days + buffer) ago
            status_changed_at=_ago(days=4),
        )
        _insert_node(store, stale_node)

        hb = Heartbeat(store=store, risk_module=risk_mod, archive_module=archive_mod)
        result = hb.scan()

        alert_types = [a.alert_type for a in result.alerts]
        assert "stale_warning" in alert_types

    def test_urgent_deadline_produces_urgent_alert(self, engine):
        store = engine.store
        from fpms.spine.heartbeat import Heartbeat
        from fpms.spine import risk as risk_mod, archive as archive_mod

        urgent_node = _make_node(
            "task-urgent", "Urgent Task", status="active",
            node_type="task", is_root=True, summary="urgent",
            deadline=_in(hours=12),  # deadline 12 hours from now (< 24h)
        )
        _insert_node(store, urgent_node)

        hb = Heartbeat(store=store, risk_module=risk_mod, archive_module=archive_mod)
        result = hb.scan()

        alert_types = [a.alert_type for a in result.alerts]
        assert "urgent_deadline" in alert_types

    def test_l_alert_contains_alert_info(self, engine):
        """ContextBundle.l_alert should reflect stale alerts when nodes are stale."""
        store = engine.store

        stale_node = _make_node(
            "task-stale", "Stale Task", status="active",
            node_type="task", is_root=True, summary="stale",
            status_changed_at=_ago(days=4),
        )
        _insert_node(store, stale_node)

        bundle = engine.get_context_bundle()
        # L_Alert must mention either the alert type or the node id
        assert "stale_warning" in bundle.l_alert or "task-stale" in bundle.l_alert

    def test_heartbeat_engine_method_returns_alerts(self, engine):
        """engine.heartbeat() returns dict with alerts list."""
        store = engine.store

        stale_node = _make_node(
            "task-stale", "Stale Task", status="active",
            node_type="task", is_root=True, summary="stale",
            status_changed_at=_ago(days=4),
        )
        _insert_node(store, stale_node)

        result = engine.heartbeat()
        assert "alerts" in result
        assert isinstance(result["alerts"], list)
        alert_types = [a["alert_type"] for a in result["alerts"]]
        assert "stale_warning" in alert_types

    def test_no_alerts_for_clean_nodes(self, engine):
        """Freshly-created active nodes with no deadline should produce no alerts."""
        store = engine.store

        fresh_node = _make_node(
            "task-fresh", "Fresh Task", status="active",
            node_type="task", is_root=True, summary="fresh",
        )
        _insert_node(store, fresh_node)

        result = engine.heartbeat()
        assert result["alerts"] == []


# ---------------------------------------------------------------------------
# Scenario 4: Focus lifecycle
# ---------------------------------------------------------------------------

class TestFocusLifecycle:
    """Scenario 4: shift_focus LRU eviction and ContextBundle L2."""

    def _create_active_node(self, engine, node_id: str, title: str) -> None:
        """Helper to create an active root node via the store."""
        node = _make_node(
            node_id, title, status="active",
            node_type="task", is_root=True, summary="summary",
        )
        _insert_node(engine.store, node)

    def test_shift_focus_sets_primary(self, engine):
        self._create_active_node(engine, "task-A", "Node A")
        state = engine._focus_scheduler.shift_focus("task-A")
        assert state.primary == "task-A"

    def test_shift_focus_moves_old_primary_to_secondary(self, engine):
        self._create_active_node(engine, "task-A", "Node A")
        self._create_active_node(engine, "task-B", "Node B")

        engine._focus_scheduler.shift_focus("task-A")
        state = engine._focus_scheduler.shift_focus("task-B")

        assert state.primary == "task-B"
        assert "task-A" in state.secondary

    def test_shift_focus_lru_eviction_max_2_secondary(self, engine):
        """Shifting to C when secondary is [B, A] should evict A (oldest)."""
        self._create_active_node(engine, "task-A", "Node A")
        self._create_active_node(engine, "task-B", "Node B")
        self._create_active_node(engine, "task-C", "Node C")

        engine._focus_scheduler.shift_focus("task-A")
        engine._focus_scheduler.shift_focus("task-B")
        # Secondary is now [A]; primary is B
        state = engine._focus_scheduler.shift_focus("task-C")
        # Primary = C, secondary = [B, A] → max 2 secondary, no eviction yet

        # Shift to a fourth node to trigger eviction
        self._create_active_node(engine, "task-D", "Node D")
        state = engine._focus_scheduler.shift_focus("task-D")
        # Primary = D, secondary should be [C, B], A evicted (LRU)
        assert state.primary == "task-D"
        assert len(state.secondary) <= 2
        assert "task-A" not in state.secondary

    def test_get_context_bundle_has_l2_for_focus_node(self, engine):
        """get_context_bundle returns L2 content for the current primary focus."""
        self._create_active_node(engine, "task-A", "Node A")
        engine._focus_scheduler.shift_focus("task-A")

        bundle = engine.get_context_bundle()
        # L2 should mention the focus node
        assert "task-A" in bundle.l2_focus or "Node A" in bundle.l2_focus
        assert bundle.focus_node_id == "task-A"

    def test_get_context_bundle_with_user_focus(self, engine):
        """Passing user_focus to get_context_bundle shifts focus and populates L2."""
        self._create_active_node(engine, "task-B", "Node B")

        bundle = engine.get_context_bundle(user_focus="task-B")
        assert bundle.focus_node_id == "task-B"
        assert "Node B" in bundle.l2_focus or "task-B" in bundle.l2_focus


# ---------------------------------------------------------------------------
# Scenario 5: Archive lifecycle
# ---------------------------------------------------------------------------

class TestArchiveLifecycle:
    """Scenario 5: archive scan, execute, unarchive, status refresh."""

    def test_old_done_node_eligible_for_archive(self, engine):
        store = engine.store

        node = _make_node(
            "task-old", "Old Task", status="done",
            node_type="task", is_root=True, summary="done",
            status_changed_at=_ago(days=8),  # > 7 day cooldown
        )
        _insert_node(store, node)

        candidates = scan_archive_candidates(store)
        assert "task-old" in candidates

    def test_execute_archive_sets_archived_at(self, engine):
        store = engine.store

        node = _make_node(
            "task-old", "Old Task", status="done",
            node_type="task", is_root=True, summary="done",
            status_changed_at=_ago(days=8),
        )
        _insert_node(store, node)

        result = execute_archive(store, "task-old")
        assert result is True

        archived_node = store.get_node("task-old")
        assert archived_node is not None
        assert archived_node.archived_at is not None

    def test_unarchive_via_engine_restores_node(self, engine):
        """Unarchiving a node via execute_tool should clear archived_at."""
        store = engine.store

        node = _make_node(
            "task-old", "Old Task", status="done",
            node_type="task", is_root=True, summary="done",
            status_changed_at=_ago(days=8),
        )
        _insert_node(store, node)

        # Archive it first
        execute_archive(store, "task-old")
        archived_node = store.get_node("task-old")
        assert archived_node.archived_at is not None

        # Unarchive via engine tool
        result = engine.execute_tool("unarchive", {"node_id": "task-old"})
        assert result.success, f"unarchive failed: {result.error}"

        restored = store.get_node("task-old")
        assert restored is not None
        assert restored.archived_at is None

    def test_unarchive_refreshes_status_changed_at(self, engine):
        """After unarchive, status_changed_at should be updated to now."""
        store = engine.store

        old_ts = _ago(days=8)
        node = _make_node(
            "task-old", "Old Task", status="done",
            node_type="task", is_root=True, summary="done",
            status_changed_at=old_ts,
        )
        _insert_node(store, node)

        execute_archive(store, "task-old")

        before_unarchive = _now()
        engine.execute_tool("unarchive", {"node_id": "task-old"})

        restored = store.get_node("task-old")
        # status_changed_at must have been refreshed — it must be >= before_unarchive
        # Use string comparison is unreliable; parse to datetime for comparison
        from datetime import datetime as _dt
        refreshed = _dt.fromisoformat(restored.status_changed_at)
        if refreshed.tzinfo is None:
            refreshed = refreshed.replace(tzinfo=timezone.utc)
        assert refreshed >= before_unarchive, (
            f"Expected refreshed status_changed_at ({refreshed}) >= "
            f"before_unarchive ({before_unarchive})"
        )

    def test_recent_done_node_not_eligible(self, engine):
        """Node done only 2 days ago should not be eligible for archive."""
        store = engine.store

        node = _make_node(
            "task-fresh", "Fresh Done", status="done",
            node_type="task", is_root=True, summary="done",
            status_changed_at=_ago(days=2),  # < 7 day cooldown
        )
        _insert_node(store, node)

        candidates = scan_archive_candidates(store)
        assert "task-fresh" not in candidates

    def test_archive_scan_via_heartbeat_finds_candidates(self, engine):
        """heartbeat.scan() archive_candidates list picks up eligible nodes."""
        store = engine.store
        from fpms.spine.heartbeat import Heartbeat
        from fpms.spine import risk as risk_mod, archive as archive_mod

        node = _make_node(
            "task-old", "Old Done", status="done",
            node_type="task", is_root=True, summary="done",
            status_changed_at=_ago(days=9),
        )
        _insert_node(store, node)

        hb = Heartbeat(store=store, risk_module=risk_mod, archive_module=archive_mod)
        result = hb.scan()
        assert "task-old" in result.archive_candidates
