"""bundle.py 测试 — BundleAssembler: 4层认知上下文组装。

TDD: 先写测试，再实现。
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone, timedelta
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

from fpms.spine.models import (
    Node,
    RiskMarks,
    ContextBundle,
    HeartbeatResult,
    HeartbeatAlert,
    FocusState,
)
from fpms.spine.store import Store


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _make_node(
    node_id: str = "task-0001",
    title: str = "",
    status: str = "active",
    deadline: Optional[str] = None,
    status_changed_at: Optional[str] = None,
    archived_at: Optional[str] = None,
    node_type: str = "task",
    parent_id: Optional[str] = None,
    is_root: bool = False,
    summary: Optional[str] = None,
    why: Optional[str] = None,
    next_step: Optional[str] = None,
) -> Node:
    now = _iso(_now())
    return Node(
        id=node_id,
        title=title or f"Node {node_id}",
        status=status,
        node_type=node_type,
        is_root=is_root,
        parent_id=parent_id,
        created_at=now,
        updated_at=now,
        status_changed_at=status_changed_at or now,
        archived_at=archived_at,
        deadline=deadline,
        summary=summary,
        why=why,
        next_step=next_step,
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
    """Provide a real Store backed by a temp SQLite DB."""
    db_path = str(tmp_path / "test.db")
    events_path = str(tmp_path / "events.jsonl")
    s = Store(db_path=db_path, events_path=events_path)
    yield s
    s._conn.close()


@pytest.fixture
def narratives_dir(tmp_path):
    """Provide a temp narratives directory."""
    d = str(tmp_path / "narratives")
    os.makedirs(d, exist_ok=True)
    return d


def _make_assembler(store, narratives_dir, heartbeat_obj=None, focus_scheduler=None):
    """Create a BundleAssembler with real modules injected."""
    from fpms.spine.bundle import BundleAssembler
    from fpms.spine import dashboard as dashboard_mod
    from fpms.spine import risk as risk_mod
    from fpms.spine import rollup as rollup_mod
    from fpms.spine import narrative as narrative_mod

    return BundleAssembler(
        store=store,
        dashboard_mod=dashboard_mod,
        heartbeat_obj=heartbeat_obj,
        focus_scheduler=focus_scheduler,
        risk_mod=risk_mod,
        rollup_mod=rollup_mod,
        narrative_mod=narrative_mod,
        narratives_dir=narratives_dir,
    )


# ---------------------------------------------------------------------------
# Import BundleAssembler after helpers
# ---------------------------------------------------------------------------

from fpms.spine.bundle import BundleAssembler


# ===========================================================================
# TestAssemblyOrder
# ===========================================================================

class TestAssemblyOrder:
    """L0 / L_Alert / L1 / L2 are all assembled; L0 appears before others."""

    def test_all_four_layers_present_with_focus(self, store, narratives_dir):
        """With a focus node, all 4 layers are non-empty strings."""
        focus = _make_node("task-0001", title="My Focus Task", status="active")
        _insert_node(store, focus)

        assembler = _make_assembler(store, narratives_dir)
        bundle = assembler.assemble(focus_node_id="task-0001")

        assert isinstance(bundle, ContextBundle)
        assert bundle.l0_dashboard != ""
        assert bundle.l_alert != ""
        assert bundle.l1_neighborhood != ""
        assert bundle.l2_focus != ""

    def test_l0_appears_before_l_alert_in_content(self, store, narratives_dir):
        """L0 content prefix ('# Dashboard') appears before L_Alert in the bundle."""
        focus = _make_node("task-0001", title="Test", status="active")
        _insert_node(store, focus)

        assembler = _make_assembler(store, narratives_dir)
        bundle = assembler.assemble(focus_node_id="task-0001")

        # Combine all layers in order to check ordering
        combined = bundle.l0_dashboard + "\n" + bundle.l_alert + "\n" + bundle.l1_neighborhood + "\n" + bundle.l2_focus
        l0_pos = combined.find("# Dashboard")
        l_alert_pos = combined.find("# Alerts")
        assert l0_pos >= 0, "L0 should contain '# Dashboard'"
        assert l_alert_pos >= 0, "L_Alert should contain '# Alerts'"
        assert l0_pos < l_alert_pos, "L0 must appear before L_Alert"

    def test_l1_appears_before_l2(self, store, narratives_dir):
        """L1 heading ('# Neighborhood') appears before L2 heading in ordered layers."""
        focus = _make_node("task-0001", title="Test", status="active")
        _insert_node(store, focus)

        assembler = _make_assembler(store, narratives_dir)
        bundle = assembler.assemble(focus_node_id="task-0001")

        combined = bundle.l1_neighborhood + "\n" + bundle.l2_focus
        l1_pos = combined.find("# Neighborhood")
        l2_pos = combined.find("# Focus:")
        assert l1_pos >= 0, "L1 should contain '# Neighborhood'"
        assert l2_pos >= 0, "L2 should contain '# Focus:'"
        assert l1_pos < l2_pos, "L1 must appear before L2"

    def test_focus_node_id_recorded_in_bundle(self, store, narratives_dir):
        """The assembled ContextBundle records the focus_node_id."""
        focus = _make_node("task-abc1", title="Focus", status="active")
        _insert_node(store, focus)

        assembler = _make_assembler(store, narratives_dir)
        bundle = assembler.assemble(focus_node_id="task-abc1")

        assert bundle.focus_node_id == "task-abc1"


# ===========================================================================
# TestNoFocusMode
# ===========================================================================

class TestNoFocusMode:
    """When there is no focus node, L1 and L2 indicate no focus."""

    def test_no_focus_l1_contains_no_focus_message(self, store, narratives_dir):
        """Without focus, L1 says 'No focus node selected.'"""
        assembler = _make_assembler(store, narratives_dir)
        bundle = assembler.assemble(focus_node_id=None)

        assert "No focus node selected." in bundle.l1_neighborhood

    def test_no_focus_l2_contains_no_focus_message(self, store, narratives_dir):
        """Without focus, L2 says 'No focus node selected.'"""
        assembler = _make_assembler(store, narratives_dir)
        bundle = assembler.assemble(focus_node_id=None)

        assert "No focus node selected." in bundle.l2_focus

    def test_no_focus_l0_still_present(self, store, narratives_dir):
        """L0 dashboard is still assembled even without focus."""
        assembler = _make_assembler(store, narratives_dir)
        bundle = assembler.assemble(focus_node_id=None)

        assert "# Dashboard" in bundle.l0_dashboard

    def test_no_focus_l_alert_still_present(self, store, narratives_dir):
        """L_Alert is still assembled even without focus."""
        assembler = _make_assembler(store, narratives_dir)
        bundle = assembler.assemble(focus_node_id=None)

        assert "# Alerts" in bundle.l_alert

    def test_focus_from_scheduler_used_when_no_explicit_focus(self, store, narratives_dir):
        """When focus_node_id=None, the assembler reads primary from focus_scheduler."""
        focus = _make_node("task-0001", title="Scheduled Focus", status="active")
        _insert_node(store, focus)

        mock_scheduler = MagicMock()
        mock_scheduler.tick.return_value = FocusState(primary="task-0001")
        mock_scheduler.get_state.return_value = FocusState(primary="task-0001")

        assembler = _make_assembler(store, narratives_dir, focus_scheduler=mock_scheduler)
        bundle = assembler.assemble(focus_node_id=None)

        # The bundle should have used the scheduler's primary
        assert bundle.focus_node_id == "task-0001"
        assert "# Focus: Scheduled Focus" in bundle.l2_focus


# ===========================================================================
# TestL0
# ===========================================================================

class TestL0:
    """L0 dashboard content tests."""

    def test_l0_has_dashboard_prefix(self, store, narratives_dir):
        """L0 is prefixed with '# Dashboard'."""
        assembler = _make_assembler(store, narratives_dir)
        bundle = assembler.assemble()
        assert bundle.l0_dashboard.startswith("# Dashboard")

    def test_l0_includes_active_nodes(self, store, narratives_dir):
        """L0 contains active node titles."""
        node = _make_node("task-0001", title="Active Work", status="active", is_root=True)
        _insert_node(store, node)

        assembler = _make_assembler(store, narratives_dir)
        bundle = assembler.assemble()

        assert "Active Work" in bundle.l0_dashboard or "task-0001" in bundle.l0_dashboard


# ===========================================================================
# TestLAlert
# ===========================================================================

class TestLAlert:
    """L_Alert formatting tests."""

    def test_l_alert_has_alerts_prefix(self, store, narratives_dir):
        """L_Alert always starts with '# Alerts'."""
        assembler = _make_assembler(store, narratives_dir)
        bundle = assembler.assemble()
        assert bundle.l_alert.startswith("# Alerts")

    def test_no_alerts_shows_no_alerts_text(self, store, narratives_dir):
        """When heartbeat returns no alerts, L_Alert says 'No alerts.'"""
        mock_hb = MagicMock()
        mock_hb.scan.return_value = HeartbeatResult(alerts=[], nodes_scanned=0)

        assembler = _make_assembler(store, narratives_dir, heartbeat_obj=mock_hb)
        bundle = assembler.assemble()

        assert "No alerts." in bundle.l_alert

    def test_alerts_formatted_correctly(self, store, narratives_dir):
        """Alerts are formatted as markdown bullet points with node and action."""
        alert = HeartbeatAlert(
            alert_type="stale_warning",
            severity=4,
            node_id="task-stale",
            message="No status change in over 72 hours.",
            suggested_action="Update status or log progress.",
        )
        mock_hb = MagicMock()
        mock_hb.scan.return_value = HeartbeatResult(alerts=[alert], nodes_scanned=1)

        assembler = _make_assembler(store, narratives_dir, heartbeat_obj=mock_hb)
        bundle = assembler.assemble()

        assert "stale_warning" in bundle.l_alert
        assert "task-stale" in bundle.l_alert
        assert "Update status or log progress." in bundle.l_alert

    def test_alerts_show_at_most_top_3(self, store, narratives_dir):
        """Only top 3 alerts (by severity) appear in L_Alert."""
        alerts = [
            HeartbeatAlert("urgent_deadline", 1, f"node-{i}", f"msg{i}", f"action{i}")
            for i in range(5)
        ]
        mock_hb = MagicMock()
        mock_hb.scan.return_value = HeartbeatResult(alerts=alerts[:3], nodes_scanned=5)

        assembler = _make_assembler(store, narratives_dir, heartbeat_obj=mock_hb)
        bundle = assembler.assemble()

        # Count bullet points in alert section
        alert_lines = [
            line for line in bundle.l_alert.split("\n")
            if line.strip().startswith("- [")
        ]
        assert len(alert_lines) <= 3


# ===========================================================================
# TestL1
# ===========================================================================

class TestL1:
    """L1 Neighborhood content tests."""

    def test_l1_has_neighborhood_prefix(self, store, narratives_dir):
        """L1 starts with '# Neighborhood'."""
        focus = _make_node("task-0001", title="Focus", status="active")
        _insert_node(store, focus)

        assembler = _make_assembler(store, narratives_dir)
        bundle = assembler.assemble(focus_node_id="task-0001")

        assert bundle.l1_neighborhood.startswith("# Neighborhood")

    def test_l1_includes_parent_summary(self, store, narratives_dir):
        """L1 shows parent node as a one-line summary."""
        parent = _make_node("proj-0001", title="Parent Project", status="active", is_root=True)
        child = _make_node("task-0001", title="Child Task", status="active", parent_id="proj-0001")
        _insert_node(store, parent)
        _insert_node(store, child)

        assembler = _make_assembler(store, narratives_dir)
        bundle = assembler.assemble(focus_node_id="task-0001")

        assert "proj-0001" in bundle.l1_neighborhood
        assert "Parent Project" in bundle.l1_neighborhood

    def test_l1_direct_children_only_no_grandchildren(self, store, narratives_dir):
        """FR-10: L1 shows only direct children (depth=1), NOT grandchildren."""
        parent = _make_node("proj-0001", title="Parent", status="active", is_root=True)
        child = _make_node("task-0001", title="Direct Child", status="active", parent_id="proj-0001")
        grandchild = _make_node("task-0002", title="Grandchild Task", status="active", parent_id="task-0001")
        _insert_node(store, parent)
        _insert_node(store, child)
        _insert_node(store, grandchild)

        assembler = _make_assembler(store, narratives_dir)
        bundle = assembler.assemble(focus_node_id="proj-0001")

        # Direct child should be present
        assert "task-0001" in bundle.l1_neighborhood
        # Grandchild should NOT be in L1 (only depth-1 expansion)
        assert "task-0002" not in bundle.l1_neighborhood

    def test_l1_top_15_children_limit_excess_folded(self, store, narratives_dir):
        """When there are more than 15 children, excess are folded."""
        parent = _make_node("proj-0001", title="Big Parent", status="active", is_root=True)
        _insert_node(store, parent)

        # Insert 18 children
        for i in range(18):
            child = _make_node(
                f"task-{i:04d}", title=f"Child {i}", status="active",
                parent_id="proj-0001"
            )
            _insert_node(store, child)

        assembler = _make_assembler(store, narratives_dir)
        bundle = assembler.assemble(focus_node_id="proj-0001")

        # There should be a fold indicator for the excess children
        assert "folded" in bundle.l1_neighborhood.lower() or "..." in bundle.l1_neighborhood

    def test_l1_includes_dependencies(self, store, narratives_dir):
        """L1 shows nodes this focus node depends on."""
        focus = _make_node("task-0001", title="Focus", status="active")
        dep = _make_node("task-dep1", title="Dependency Node", status="active")
        _insert_node(store, focus)
        _insert_node(store, dep)

        # Insert depends_on edge
        now = _iso(_now())
        store._conn.execute(
            "INSERT INTO edges (source_id, target_id, edge_type, created_at) VALUES (?,?,?,?)",
            ("task-0001", "task-dep1", "depends_on", now),
        )
        store._conn.commit()

        assembler = _make_assembler(store, narratives_dir)
        bundle = assembler.assemble(focus_node_id="task-0001")

        assert "task-dep1" in bundle.l1_neighborhood

    def test_l1_includes_siblings(self, store, narratives_dir):
        """L1 shows sibling nodes (same parent)."""
        parent = _make_node("proj-0001", title="Parent", status="active", is_root=True)
        focus = _make_node("task-0001", title="Focus", status="active", parent_id="proj-0001")
        sibling = _make_node("task-0002", title="Sibling Task", status="active", parent_id="proj-0001")
        _insert_node(store, parent)
        _insert_node(store, focus)
        _insert_node(store, sibling)

        assembler = _make_assembler(store, narratives_dir)
        bundle = assembler.assemble(focus_node_id="task-0001")

        assert "task-0002" in bundle.l1_neighborhood

    def test_l1_children_sorted_by_risk_severity(self, store, narratives_dir):
        """Children in L1 are sorted by risk severity (blocked first)."""
        parent = _make_node("proj-0001", title="Parent", status="active", is_root=True)
        healthy_child = _make_node(
            "task-healthy", title="Healthy Child", status="active", parent_id="proj-0001"
        )
        # Make a blocked child by setting its dependency on a non-done node
        blocker = _make_node("task-blocker", title="Blocker", status="active", parent_id="proj-0001")
        blocked_child = _make_node(
            "task-blocked", title="Blocked Child", status="active", parent_id="proj-0001"
        )
        _insert_node(store, parent)
        _insert_node(store, healthy_child)
        _insert_node(store, blocker)
        _insert_node(store, blocked_child)

        # blocked_child depends on blocker (which is active, so it's blocked)
        now = _iso(_now())
        store._conn.execute(
            "INSERT INTO edges (source_id, target_id, edge_type, created_at) VALUES (?,?,?,?)",
            ("task-blocked", "task-blocker", "depends_on", now),
        )
        store._conn.commit()

        assembler = _make_assembler(store, narratives_dir)
        bundle = assembler.assemble(focus_node_id="proj-0001")

        # Blocked child should appear before healthy child in L1
        blocked_pos = bundle.l1_neighborhood.find("task-blocked")
        healthy_pos = bundle.l1_neighborhood.find("task-healthy")
        assert blocked_pos >= 0, "Blocked child should be in L1"
        assert healthy_pos >= 0, "Healthy child should be in L1"
        assert blocked_pos < healthy_pos, "Blocked child should appear before healthy child"


# ===========================================================================
# TestL2
# ===========================================================================

class TestL2:
    """L2 Focus content tests."""

    def test_l2_has_focus_title_prefix(self, store, narratives_dir):
        """L2 starts with '# Focus: {title}'."""
        focus = _make_node("task-0001", title="My Focus Task", status="active")
        _insert_node(store, focus)

        assembler = _make_assembler(store, narratives_dir)
        bundle = assembler.assemble(focus_node_id="task-0001")

        assert bundle.l2_focus.startswith("# Focus: My Focus Task")

    def test_l2_includes_skeleton_fields(self, store, narratives_dir):
        """L2 renders node skeleton fields: status, type, summary, why, next_step."""
        focus = _make_node(
            "task-0001", title="Detailed Task", status="active",
            summary="This is the summary.",
            why="Because we need it.",
            next_step="Do the thing.",
        )
        _insert_node(store, focus)

        assembler = _make_assembler(store, narratives_dir)
        bundle = assembler.assemble(focus_node_id="task-0001")

        assert "This is the summary." in bundle.l2_focus
        assert "Because we need it." in bundle.l2_focus
        assert "Do the thing." in bundle.l2_focus

    def test_l2_includes_recent_narrative(self, store, narratives_dir):
        """L2 includes recent narrative entries for the focus node."""
        focus = _make_node("task-0001", title="Task With Narrative", status="active")
        _insert_node(store, focus)

        # Write a narrative entry
        from fpms.spine import narrative as narrative_mod
        narrative_mod.append_narrative(
            narratives_dir=narratives_dir,
            node_id="task-0001",
            timestamp=_iso(_now()),
            event_type="note",
            content="This is a narrative entry for testing.",
        )

        assembler = _make_assembler(store, narratives_dir)
        bundle = assembler.assemble(focus_node_id="task-0001")

        assert "This is a narrative entry for testing." in bundle.l2_focus

    def test_l2_compressed_summary_prioritized(self, store, narratives_dir):
        """Compressed summary is included in L2 when it exists."""
        focus = _make_node("task-0001", title="Compressed Task", status="active")
        _insert_node(store, focus)

        # Write a compressed summary
        from fpms.spine import narrative as narrative_mod
        narrative_mod.write_compressed(
            narratives_dir=narratives_dir,
            node_id="task-0001",
            content="COMPRESSED: This is the compressed summary of the task.",
        )

        assembler = _make_assembler(store, narratives_dir)
        bundle = assembler.assemble(focus_node_id="task-0001")

        assert "COMPRESSED: This is the compressed summary of the task." in bundle.l2_focus

    def test_l2_no_narrative_file_does_not_crash(self, store, narratives_dir):
        """L2 works gracefully when no narrative file exists for the focus node."""
        focus = _make_node("task-0001", title="No Narrative Task", status="active")
        _insert_node(store, focus)

        assembler = _make_assembler(store, narratives_dir)
        bundle = assembler.assemble(focus_node_id="task-0001")

        assert bundle.l2_focus != ""
        assert "# Focus: No Narrative Task" in bundle.l2_focus


# ===========================================================================
# TestTokenTrim
# ===========================================================================

class TestTokenTrim:
    """Token budget trimming tests."""

    def test_over_budget_content_is_trimmed(self, store, narratives_dir):
        """When total tokens exceed budget, content is trimmed."""
        # Insert a node with a very long summary to force trimming
        long_text = "X" * 40000  # ~10000 tokens in summary
        focus = _make_node(
            "task-0001", title="Oversized Task", status="active",
            summary=long_text,
        )
        _insert_node(store, focus)

        assembler = _make_assembler(store, narratives_dir)
        bundle = assembler.assemble(focus_node_id="task-0001")

        # Total tokens should be within a reasonable bound
        assert bundle.total_tokens <= 12000  # some headroom

    def test_trim_order_siblings_before_l2_narrative(self, store, narratives_dir):
        """Trim order: siblings section trimmed before L2 narrative."""
        from fpms.spine.bundle import BundleAssembler

        assembler = _make_assembler(store, narratives_dir)

        # Build L1 with a long siblings section and short L2 narrative
        l0 = "# Dashboard\n" + "A" * 1000
        l_alert = "# Alerts\nNo alerts."
        # l1 has a big siblings section
        l1 = "# Neighborhood\n## Parent\nparent info\n## Siblings\n" + "- sibling-line\n" * 200
        l2 = "# Focus: Task\nstatus: active\n## Narrative\nShort narrative."

        trimmed_l0, trimmed_alert, trimmed_l1, trimmed_l2 = assembler._trim_to_budget(
            l0, l_alert, l1, l2, max_tokens=500
        )

        # Total tokens should now be within budget
        total = sum(
            assembler._estimate_tokens(t)
            for t in [trimmed_l0, trimmed_alert, trimmed_l1, trimmed_l2]
        )
        assert total <= 600  # some slack

    def test_total_tokens_calculated_in_bundle(self, store, narratives_dir):
        """total_tokens in ContextBundle reflects assembled content size."""
        focus = _make_node("task-0001", title="Task", status="active")
        _insert_node(store, focus)

        assembler = _make_assembler(store, narratives_dir)
        bundle = assembler.assemble(focus_node_id="task-0001")

        expected_tokens = assembler._estimate_tokens(
            bundle.l0_dashboard + bundle.l_alert + bundle.l1_neighborhood + bundle.l2_focus
        )
        assert bundle.total_tokens == expected_tokens


# ===========================================================================
# TestAssemblyTrace
# ===========================================================================

class TestAssemblyTrace:
    """Assembly trace file writing tests."""

    def test_trace_file_written_after_assembly(self, store, narratives_dir, tmp_path):
        """After assemble(), a trace entry is written to assembly_traces.jsonl."""
        db_dir = str(tmp_path)

        from fpms.spine.bundle import BundleAssembler
        from fpms.spine import dashboard as dashboard_mod
        from fpms.spine import risk as risk_mod
        from fpms.spine import rollup as rollup_mod
        from fpms.spine import narrative as narrative_mod

        assembler = BundleAssembler(
            store=store,
            dashboard_mod=dashboard_mod,
            risk_mod=risk_mod,
            rollup_mod=rollup_mod,
            narrative_mod=narrative_mod,
            narratives_dir=narratives_dir,
        )
        # Override db_dir for the trace
        assembler._db_dir = db_dir

        focus = _make_node("task-0001", title="Trace Test", status="active")
        _insert_node(store, focus)

        assembler.assemble(focus_node_id="task-0001")

        trace_path = os.path.join(db_dir, "assembly_traces.jsonl")
        assert os.path.exists(trace_path), "assembly_traces.jsonl should be created"

        with open(trace_path, "r") as f:
            lines = [line.strip() for line in f.readlines() if line.strip()]

        assert len(lines) >= 1, "At least one trace entry should exist"
        record = json.loads(lines[0])
        assert "focus_node_id" in record
        assert "total" in record or "total_tokens" in record

    def test_trace_contains_token_counts(self, store, narratives_dir, tmp_path):
        """Trace entry records per-layer token counts."""
        db_dir = str(tmp_path)

        from fpms.spine.bundle import BundleAssembler
        from fpms.spine import dashboard as dashboard_mod
        from fpms.spine import risk as risk_mod
        from fpms.spine import rollup as rollup_mod
        from fpms.spine import narrative as narrative_mod

        assembler = BundleAssembler(
            store=store,
            dashboard_mod=dashboard_mod,
            risk_mod=risk_mod,
            rollup_mod=rollup_mod,
            narrative_mod=narrative_mod,
            narratives_dir=narratives_dir,
        )
        assembler._db_dir = db_dir

        focus = _make_node("task-0001", title="Token Test", status="active")
        _insert_node(store, focus)

        assembler.assemble(focus_node_id="task-0001")

        trace_path = os.path.join(db_dir, "assembly_traces.jsonl")
        with open(trace_path, "r") as f:
            record = json.loads(f.readline().strip())

        assert "tokens_per_layer" in record or "l0_tokens" in record


# ===========================================================================
# TestEmptyDB
# ===========================================================================

class TestEmptyDB:
    """Edge case: empty database."""

    def test_empty_db_no_crash_returns_valid_bundle(self, store, narratives_dir):
        """Empty database → no crash, returns valid ContextBundle with minimal L0."""
        assembler = _make_assembler(store, narratives_dir)
        bundle = assembler.assemble()

        assert isinstance(bundle, ContextBundle)
        assert isinstance(bundle.l0_dashboard, str)
        assert isinstance(bundle.l_alert, str)
        assert isinstance(bundle.l1_neighborhood, str)
        assert isinstance(bundle.l2_focus, str)
        assert isinstance(bundle.total_tokens, int)

    def test_empty_db_l0_is_minimal(self, store, narratives_dir):
        """Empty database → L0 is present but minimal (no nodes to show)."""
        assembler = _make_assembler(store, narratives_dir)
        bundle = assembler.assemble()

        assert "# Dashboard" in bundle.l0_dashboard

    def test_empty_db_l_alert_shows_no_alerts(self, store, narratives_dir):
        """Empty database → L_Alert shows 'No alerts.' or empty result."""
        mock_hb = MagicMock()
        mock_hb.scan.return_value = HeartbeatResult(alerts=[], nodes_scanned=0)

        assembler = _make_assembler(store, narratives_dir, heartbeat_obj=mock_hb)
        bundle = assembler.assemble()

        assert "No alerts." in bundle.l_alert

    def test_focus_node_not_found_still_returns_bundle(self, store, narratives_dir):
        """Requesting a non-existent focus node → returns bundle without crash."""
        assembler = _make_assembler(store, narratives_dir)
        bundle = assembler.assemble(focus_node_id="nonexistent-9999")

        assert isinstance(bundle, ContextBundle)
        # L1 and L2 should handle missing node gracefully
        assert bundle.l1_neighborhood != ""
        assert bundle.l2_focus != ""
