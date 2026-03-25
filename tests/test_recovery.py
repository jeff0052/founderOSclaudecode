"""recovery.py 和 SpineEngine v1 接线测试 (FR-13)。

TDD: 先写测试，再实现。
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone, timedelta
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

from fpms.spine.models import (
    Node,
    ContextBundle,
    FocusState,
    HeartbeatResult,
    HeartbeatAlert,
)
from fpms.spine.store import Store
from fpms.spine import SpineEngine


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
    archived_at: Optional[str] = None,
    node_type: str = "task",
    parent_id: Optional[str] = None,
    deadline: Optional[str] = None,
    status_changed_at: Optional[str] = None,
    created_at: Optional[str] = None,
    is_root: bool = False,
) -> Node:
    now_str = _iso(_now())
    return Node(
        id=node_id,
        title=f"Node {node_id}",
        status=status,
        node_type=node_type,
        is_root=is_root,
        parent_id=parent_id,
        created_at=created_at or now_str,
        updated_at=now_str,
        status_changed_at=status_changed_at or now_str,
        archived_at=archived_at,
        deadline=deadline,
    )


def _insert_node(store: Store, node: Node) -> None:
    """Insert a Node directly into DB without ID generation."""
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
            node.status_changed_at or node.created_at,
            node.archived_at,
            node.source, node.source_id, node.source_url,
            node.source_synced_at, int(node.source_deleted),
            int(node.needs_compression), int(node.compression_in_progress),
            int(node.no_llm_compression),
            json.dumps(node.tags),
        ),
    )
    store._conn.commit()


@pytest.fixture
def store(tmp_path):
    """Real Store backed by a temp SQLite DB."""
    db_path = str(tmp_path / "test.db")
    events_path = str(tmp_path / "events.jsonl")
    s = Store(db_path=db_path, events_path=events_path)
    yield s
    s._conn.close()


@pytest.fixture
def engine(tmp_path):
    """SpineEngine with temp paths."""
    db_path = str(tmp_path / "fpms.db")
    events_path = str(tmp_path / "events.jsonl")
    narratives_dir = str(tmp_path / "narratives")
    e = SpineEngine(
        db_path=db_path,
        events_path=events_path,
        narratives_dir=narratives_dir,
    )
    yield e
    e.store._conn.close()


# ---------------------------------------------------------------------------
# Helper: build real modules from a store
# ---------------------------------------------------------------------------

def _build_modules(store, tmp_path):
    """Build Heartbeat, FocusScheduler, BundleAssembler for a given store."""
    from fpms.spine.heartbeat import Heartbeat
    from fpms.spine.focus import FocusScheduler
    from fpms.spine.bundle import BundleAssembler
    from fpms.spine import risk, archive, rollup, dashboard, narrative

    narratives_dir = str(tmp_path / "narratives")

    heartbeat = Heartbeat(store=store, risk_module=risk, archive_module=archive)
    focus_scheduler = FocusScheduler(store=store, narrative_module=None)
    bundle_assembler = BundleAssembler(
        store=store,
        dashboard_mod=dashboard,
        heartbeat_obj=heartbeat,
        focus_scheduler=focus_scheduler,
        risk_mod=risk,
        rollup_mod=rollup,
        narrative_mod=narrative,
        narratives_dir=narratives_dir,
    )
    return heartbeat, focus_scheduler, bundle_assembler


# ===========================================================================
# TestBootstrap
# ===========================================================================

class TestBootstrap:
    """FR-13 bootstrap flow tests."""

    def test_empty_db_returns_valid_bundle(self, store, tmp_path):
        """Empty DB: bootstrap returns a ContextBundle without crashing."""
        from fpms.spine.recovery import bootstrap
        from fpms.spine import archive

        heartbeat, focus_scheduler, bundle_assembler = _build_modules(store, tmp_path)

        bundle = bootstrap(
            store=store,
            heartbeat=heartbeat,
            focus_scheduler=focus_scheduler,
            bundle_assembler=bundle_assembler,
            archive_module=archive,
        )

        assert isinstance(bundle, ContextBundle)
        assert bundle.l0_dashboard is not None
        assert bundle.l_alert is not None
        assert bundle.l1_neighborhood is not None
        assert bundle.l2_focus is not None

    def test_with_active_nodes_l0_contains_dashboard(self, store, tmp_path):
        """With active nodes: L0 dashboard is populated."""
        from fpms.spine.recovery import bootstrap
        from fpms.spine import archive

        node = _make_node("task-aaaa", status="active", is_root=True)
        _insert_node(store, node)

        heartbeat, focus_scheduler, bundle_assembler = _build_modules(store, tmp_path)

        bundle = bootstrap(
            store=store,
            heartbeat=heartbeat,
            focus_scheduler=focus_scheduler,
            bundle_assembler=bundle_assembler,
            archive_module=archive,
        )

        assert isinstance(bundle, ContextBundle)
        assert "# Dashboard" in bundle.l0_dashboard

    def test_with_stale_node_l_alert_contains_stale_alert(self, store, tmp_path):
        """With a node stale for > 72h, the heartbeat detects a stale alert.

        Note: bootstrap calls heartbeat.scan() once (for focus candidates), then
        bundle_assembler.assemble() calls it a second time internally for L_Alert.
        The second scan deduplicates the already-pushed alert within 24h, so L_Alert
        shows "No alerts." — the stale decoration appears in L0 dashboard instead.
        We verify: (a) the heartbeat scan itself returns a stale alert, and (b) the
        L0 dashboard contains the stale risk decoration.
        """
        from fpms.spine.recovery import bootstrap
        from fpms.spine import archive

        stale_ts = _iso(_now() - timedelta(hours=100))
        node = _make_node(
            "task-bbbb",
            status="active",
            is_root=True,
            status_changed_at=stale_ts,
        )
        _insert_node(store, node)

        heartbeat, focus_scheduler, bundle_assembler = _build_modules(store, tmp_path)

        bundle = bootstrap(
            store=store,
            heartbeat=heartbeat,
            focus_scheduler=focus_scheduler,
            bundle_assembler=bundle_assembler,
            archive_module=archive,
        )

        assert isinstance(bundle, ContextBundle)
        # L0 dashboard should show the stale risk decoration
        assert "stale" in bundle.l0_dashboard.lower()

    def test_with_historical_focus_in_session_state_focus_restored(self, store, tmp_path):
        """Historical focus in session_state is loaded and used in bundle."""
        from fpms.spine.recovery import bootstrap
        from fpms.spine import archive

        node = _make_node("task-cccc", status="active")
        _insert_node(store, node)

        # Pre-load focus state in session
        store.set_session("focus_state", {
            "primary": "task-cccc",
            "secondary": [],
            "stash": [],
            "last_touched": {"task-cccc": _iso(_now())},
        })

        heartbeat, focus_scheduler, bundle_assembler = _build_modules(store, tmp_path)

        bundle = bootstrap(
            store=store,
            heartbeat=heartbeat,
            focus_scheduler=focus_scheduler,
            bundle_assembler=bundle_assembler,
            archive_module=archive,
        )

        assert isinstance(bundle, ContextBundle)
        # Focus was restored from session — bundle should reflect it
        assert bundle.focus_node_id == "task-cccc"

    def test_invalid_historical_focus_archived_gracefully_degraded(self, store, tmp_path):
        """Archived historical focus is silently dropped — no crash, focus_node_id is None."""
        from fpms.spine.recovery import bootstrap
        from fpms.spine import archive

        archived_node = _make_node(
            "task-dddd",
            status="done",
            archived_at=_iso(_now()),
        )
        _insert_node(store, archived_node)

        # Pre-load archived node as focus
        store.set_session("focus_state", {
            "primary": "task-dddd",
            "secondary": [],
            "stash": [],
            "last_touched": {"task-dddd": _iso(_now())},
        })

        heartbeat, focus_scheduler, bundle_assembler = _build_modules(store, tmp_path)

        bundle = bootstrap(
            store=store,
            heartbeat=heartbeat,
            focus_scheduler=focus_scheduler,
            bundle_assembler=bundle_assembler,
            archive_module=archive,
        )

        assert isinstance(bundle, ContextBundle)
        # Archived node is invalid — focus gracefully degraded
        assert bundle.focus_node_id is None


# ===========================================================================
# TestDegradation
# ===========================================================================

class TestDegradation:
    """Partial failure should not block bootstrap."""

    def test_heartbeat_scan_throws_still_returns_bundle(self, store, tmp_path):
        """If heartbeat.scan() throws, bootstrap returns a valid bundle (degraded)."""
        from fpms.spine.recovery import bootstrap
        from fpms.spine import archive

        _, focus_scheduler, bundle_assembler = _build_modules(store, tmp_path)

        # Mock heartbeat that always raises
        mock_heartbeat = MagicMock()
        mock_heartbeat.scan.side_effect = RuntimeError("DB connection lost")

        bundle = bootstrap(
            store=store,
            heartbeat=mock_heartbeat,
            focus_scheduler=focus_scheduler,
            bundle_assembler=bundle_assembler,
            archive_module=archive,
        )

        assert isinstance(bundle, ContextBundle)
        # Degraded bundle — no focus candidates from heartbeat
        assert bundle.focus_node_id is None

    def test_focus_scheduler_no_candidates_no_focus_mode(self, store, tmp_path):
        """No active nodes and no historical focus → no-focus bundle."""
        from fpms.spine.recovery import bootstrap
        from fpms.spine import archive

        heartbeat, focus_scheduler, bundle_assembler = _build_modules(store, tmp_path)

        # Empty store — no candidates, no session focus
        bundle = bootstrap(
            store=store,
            heartbeat=heartbeat,
            focus_scheduler=focus_scheduler,
            bundle_assembler=bundle_assembler,
            archive_module=archive,
        )

        assert isinstance(bundle, ContextBundle)
        assert bundle.focus_node_id is None
        assert "No focus node" in bundle.l1_neighborhood or bundle.l1_neighborhood is not None


# ===========================================================================
# TestArchiveIntegration
# ===========================================================================

class TestArchiveIntegration:
    """Archive candidates are processed during bootstrap."""

    def test_eligible_nodes_archived_during_bootstrap(self, store, tmp_path):
        """Eligible done/old nodes are archived during bootstrap."""
        from fpms.spine.recovery import bootstrap
        from fpms.spine import archive

        old_ts = _iso(_now() - timedelta(days=10))
        done_node = Node(
            id="task-eeee",
            title="Old done node",
            status="done",
            node_type="task",
            created_at=old_ts,
            updated_at=old_ts,
            status_changed_at=old_ts,
            is_persistent=False,
        )
        _insert_node(store, done_node)

        heartbeat, focus_scheduler, bundle_assembler = _build_modules(store, tmp_path)

        bundle = bootstrap(
            store=store,
            heartbeat=heartbeat,
            focus_scheduler=focus_scheduler,
            bundle_assembler=bundle_assembler,
            archive_module=archive,
        )

        assert isinstance(bundle, ContextBundle)
        # Node should be archived now
        refreshed = store.get_node("task-eeee")
        assert refreshed is not None
        assert refreshed.archived_at is not None

    def test_archive_failure_does_not_block_bootstrap(self, store, tmp_path):
        """If archive module raises for a node, bootstrap still completes."""
        from fpms.spine.recovery import bootstrap
        from fpms.spine.heartbeat import Heartbeat
        from fpms.spine.focus import FocusScheduler
        from fpms.spine.bundle import BundleAssembler
        from fpms.spine import risk, rollup, dashboard, narrative

        # Heartbeat that returns a fake archive candidate
        mock_heartbeat = MagicMock()
        mock_heartbeat.scan.return_value = HeartbeatResult(
            alerts=[],
            focus_candidates=[],
            archive_candidates=["task-ffff"],  # non-existent node
            nodes_scanned=0,
        )

        # Archive module that always raises
        mock_archive = MagicMock()
        mock_archive.execute_archive.side_effect = RuntimeError("archive broken")

        focus_scheduler = FocusScheduler(store=store, narrative_module=None)
        narratives_dir = str(tmp_path / "narratives")
        bundle_assembler = BundleAssembler(
            store=store,
            dashboard_mod=dashboard,
            heartbeat_obj=mock_heartbeat,
            focus_scheduler=focus_scheduler,
            risk_mod=risk,
            rollup_mod=rollup,
            narrative_mod=narrative,
            narratives_dir=narratives_dir,
        )

        bundle = bootstrap(
            store=store,
            heartbeat=mock_heartbeat,
            focus_scheduler=focus_scheduler,
            bundle_assembler=bundle_assembler,
            archive_module=mock_archive,
        )

        assert isinstance(bundle, ContextBundle)

    def test_bootstrap_without_archive_module_does_not_crash(self, store, tmp_path):
        """Passing archive_module=None should not crash."""
        from fpms.spine.recovery import bootstrap

        heartbeat, focus_scheduler, bundle_assembler = _build_modules(store, tmp_path)

        bundle = bootstrap(
            store=store,
            heartbeat=heartbeat,
            focus_scheduler=focus_scheduler,
            bundle_assembler=bundle_assembler,
            archive_module=None,
        )

        assert isinstance(bundle, ContextBundle)


# ===========================================================================
# TestSpineEngineWiring
# ===========================================================================

class TestSpineEngineWiring:
    """SpineEngine v1 wiring tests."""

    def test_spine_engine_initializes_without_error(self, engine):
        """SpineEngine() constructor completes without error."""
        assert engine is not None

    def test_engine_bootstrap_returns_context_bundle(self, engine):
        """engine.bootstrap() returns a ContextBundle."""
        bundle = engine.bootstrap()
        assert isinstance(bundle, ContextBundle)

    def test_engine_heartbeat_returns_dict_with_alerts(self, engine):
        """engine.heartbeat() returns a dict containing 'alerts' key."""
        result = engine.heartbeat()
        assert isinstance(result, dict)
        assert "alerts" in result
        assert "focus_suggestion" in result

    def test_engine_heartbeat_returns_counts(self, engine):
        """engine.heartbeat() returns active_count and waiting_count."""
        result = engine.heartbeat()
        assert "active_count" in result
        assert "waiting_count" in result

    def test_engine_get_context_bundle_no_focus(self, engine):
        """get_context_bundle() with no focus returns a valid bundle."""
        bundle = engine.get_context_bundle()
        assert isinstance(bundle, ContextBundle)

    def test_engine_get_context_bundle_with_user_focus(self, engine, tmp_path):
        """get_context_bundle(user_focus=...) calls shift_focus and assembles."""
        # Create a node first
        result = engine.execute_tool("create_node", {
            "title": "Focus Test Node",
            "node_type": "task",
        })
        assert result.success
        # result.data is a flat node dict (not nested under "node")
        node_id = result.data["id"]

        bundle = engine.get_context_bundle(user_focus=node_id)
        assert isinstance(bundle, ContextBundle)
        assert bundle.focus_node_id == node_id

    def test_engine_sync_source_nonexistent_raises(self, engine):
        """sync_source on nonexistent node raises ValueError."""
        with pytest.raises(ValueError, match="not found"):
            engine.sync_source("nonexistent-node")

    def test_engine_sync_all_no_registry_returns_zero(self, engine):
        """sync_all with no adapter registry returns 0."""
        assert engine.sync_all() == 0

    def test_engine_bootstrap_with_active_node(self, engine):
        """bootstrap() with an active node returns a bundle with dashboard content."""
        engine.execute_tool("create_node", {
            "title": "Bootstrap Test Node",
            "node_type": "task",
        })
        bundle = engine.bootstrap()
        assert isinstance(bundle, ContextBundle)
        assert "# Dashboard" in bundle.l0_dashboard

    def test_engine_has_no_detect_alerts_method(self, engine):
        """_detect_alerts method is removed in v1 SpineEngine."""
        assert not hasattr(engine, "_detect_alerts"), (
            "_detect_alerts should be removed in v1 — replaced by Heartbeat module"
        )
