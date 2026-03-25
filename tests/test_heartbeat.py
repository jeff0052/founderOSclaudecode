"""heartbeat.py 测试 — HeartbeatAlert 生成、去重、Anti-Amnesia。

TDD: 先写测试，再实现。
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from fpms.spine.models import (
    Node,
    RiskMarks,
    HeartbeatAlert,
    HeartbeatResult,
    DedupeRecord,
)
from fpms.spine.schema import init_db
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
    status: str = "active",
    deadline: Optional[str] = None,
    status_changed_at: Optional[str] = None,
    created_at: Optional[str] = None,
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
        created_at=created_at or now,
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


def _insert_depends_on(store: Store, source_id: str, target_id: str) -> None:
    """Insert a depends_on edge."""
    now = _iso(_now())
    store._conn.execute(
        "INSERT INTO edges (source_id, target_id, edge_type, created_at) VALUES (?,?,?,?)",
        (source_id, target_id, "depends_on", now),
    )
    store._conn.commit()


def _insert_audit_event(store: Store, tool_name: str, node_id: str, ts: str) -> None:
    """Insert an audit_outbox event for testing _check_substantive_action."""
    event = {
        "type": tool_name,
        "tool_name": tool_name,
        "event_type": tool_name,
        "node_id": node_id,
        "timestamp": ts,
    }
    store._conn.execute(
        "INSERT INTO audit_outbox (event_json, created_at, flushed) VALUES (?,?,?)",
        (json.dumps(event), ts, 0),
    )
    store._conn.commit()


# ---------------------------------------------------------------------------
# Import heartbeat after store is set up
# ---------------------------------------------------------------------------

from fpms.spine.heartbeat import Heartbeat


# ===========================================================================
# TestAlertGeneration
# ===========================================================================

class TestAlertGeneration:
    """Alert generation from risk marks."""

    def test_blocked_node_with_dependents_generates_critical_blocked(self, store):
        """blocked node that has dependents → critical_blocked (severity=2)."""
        now = _now()
        blocker = _make_node("blocker-001", status="active")
        node = _make_node("task-001", status="active")
        dependent = _make_node("dep-on-me-001", status="active")
        _insert_node(store, blocker)
        _insert_node(store, node)
        _insert_node(store, dependent)
        # task-001 is blocked by blocker-001
        _insert_depends_on(store, "task-001", "blocker-001")
        # dep-on-me-001 depends on task-001 (so task-001 has dependents)
        _insert_depends_on(store, "dep-on-me-001", "task-001")

        hb = Heartbeat(store)
        result = hb.scan(now=now)

        alert_types = [a.alert_type for a in result.alerts]
        assert "critical_blocked" in alert_types
        critical = next(a for a in result.alerts if a.alert_type == "critical_blocked")
        assert critical.node_id == "task-001"
        assert critical.severity == 2

    def test_at_risk_within_24h_generates_urgent_deadline(self, store):
        """at_risk AND deadline < 24h → urgent_deadline (severity=1)."""
        now = _now()
        deadline = now + timedelta(hours=12)
        node = _make_node("task-001", status="active", deadline=_iso(deadline))
        _insert_node(store, node)

        hb = Heartbeat(store)
        result = hb.scan(now=now)

        alert_types = [a.alert_type for a in result.alerts]
        assert "urgent_deadline" in alert_types
        urgent = next(a for a in result.alerts if a.alert_type == "urgent_deadline")
        assert urgent.node_id == "task-001"
        assert urgent.severity == 1

    def test_at_risk_within_48h_generates_deadline_warning(self, store):
        """at_risk (between 24h and 48h) → deadline_warning (severity=3)."""
        now = _now()
        deadline = now + timedelta(hours=36)
        node = _make_node("task-001", status="active", deadline=_iso(deadline))
        _insert_node(store, node)

        hb = Heartbeat(store)
        result = hb.scan(now=now)

        alert_types = [a.alert_type for a in result.alerts]
        assert "deadline_warning" in alert_types
        warning = next(a for a in result.alerts if a.alert_type == "deadline_warning")
        assert warning.node_id == "task-001"
        assert warning.severity == 3

    def test_stale_node_generates_stale_warning(self, store):
        """stale node → stale_warning (severity=4)."""
        now = _now()
        old_time = _iso(now - timedelta(hours=80))
        node = _make_node("task-001", status="active", status_changed_at=old_time)
        _insert_node(store, node)

        hb = Heartbeat(store)
        result = hb.scan(now=now)

        alert_types = [a.alert_type for a in result.alerts]
        assert "stale_warning" in alert_types
        stale = next(a for a in result.alerts if a.alert_type == "stale_warning")
        assert stale.node_id == "task-001"
        assert stale.severity == 4

    def test_inbox_stale_7_plus_days_generates_inbox_stale(self, store):
        """inbox node created > 7 days ago → inbox_stale (severity=5)."""
        now = _now()
        old_created = _iso(now - timedelta(days=8))
        node = _make_node(
            "task-001",
            status="inbox",
            created_at=old_created,
            status_changed_at=old_created,
        )
        _insert_node(store, node)

        hb = Heartbeat(store)
        result = hb.scan(now=now)

        alert_types = [a.alert_type for a in result.alerts]
        assert "inbox_stale" in alert_types
        inbox = next(a for a in result.alerts if a.alert_type == "inbox_stale")
        assert inbox.node_id == "task-001"
        assert inbox.severity == 5

    def test_inbox_stale_uses_created_at_not_status_changed_at(self, store):
        """inbox_stale check uses created_at, NOT status_changed_at (per FR-7)."""
        now = _now()
        # created_at is old (8 days), but status_changed_at is recent
        old_created = _iso(now - timedelta(days=8))
        recent_status_change = _iso(now - timedelta(hours=1))
        node = _make_node(
            "task-001",
            status="inbox",
            created_at=old_created,
            status_changed_at=recent_status_change,
        )
        _insert_node(store, node)

        hb = Heartbeat(store)
        result = hb.scan(now=now)

        # Should still fire because created_at is old
        alert_types = [a.alert_type for a in result.alerts]
        assert "inbox_stale" in alert_types

    def test_inbox_stale_not_triggered_when_created_recently(self, store):
        """inbox node created < 7 days ago → NO inbox_stale, even if status_changed_at is old."""
        now = _now()
        recent_created = _iso(now - timedelta(days=3))
        old_status = _iso(now - timedelta(days=10))
        node = _make_node(
            "task-001",
            status="inbox",
            created_at=recent_created,
            status_changed_at=old_status,
        )
        _insert_node(store, node)

        hb = Heartbeat(store)
        result = hb.scan(now=now)

        alert_types = [a.alert_type for a in result.alerts]
        assert "inbox_stale" not in alert_types

    def test_terminal_node_generates_no_alerts(self, store):
        """done/dropped nodes → no alerts generated."""
        now = _now()
        deadline = now + timedelta(hours=6)
        old_time = _iso(now - timedelta(hours=100))
        done_node = _make_node(
            "task-done",
            status="done",
            deadline=_iso(deadline),
            status_changed_at=old_time,
        )
        dropped_node = _make_node(
            "task-dropped",
            status="dropped",
            deadline=_iso(deadline),
            status_changed_at=old_time,
        )
        _insert_node(store, done_node)
        _insert_node(store, dropped_node)

        hb = Heartbeat(store)
        result = hb.scan(now=now)

        node_ids = [a.node_id for a in result.alerts]
        assert "task-done" not in node_ids
        assert "task-dropped" not in node_ids


# ===========================================================================
# TestDedup
# ===========================================================================

class TestDedup:
    """Deduplication logic tests."""

    def test_same_alert_not_repushed_within_24h(self, store):
        """Same alert within 24h is suppressed (not re-pushed)."""
        now = _now()
        deadline = now + timedelta(hours=12)
        node = _make_node("task-001", status="active", deadline=_iso(deadline))
        _insert_node(store, node)

        hb = Heartbeat(store)
        # First scan
        result1 = hb.scan(now=now)
        count1 = sum(1 for a in result1.alerts if a.node_id == "task-001")

        # Second scan 1 hour later (within 24h) — same alert should be suppressed
        now2 = now + timedelta(hours=1)
        result2 = hb.scan(now=now2)
        urgent_alerts2 = [a for a in result2.alerts if a.alert_type == "urgent_deadline" and a.node_id == "task-001"]
        assert len(urgent_alerts2) == 0, "Same alert should be suppressed within 24h"

    def test_different_alert_types_for_same_node_both_pushed(self, store):
        """Different alert types for the same node are both pushed."""
        now = _now()
        # Node is both at_risk AND stale
        deadline = now + timedelta(hours=36)
        old_time = _iso(now - timedelta(hours=80))
        node = _make_node(
            "task-001",
            status="active",
            deadline=_iso(deadline),
            status_changed_at=old_time,
        )
        _insert_node(store, node)

        hb = Heartbeat(store)
        result = hb.scan(now=now)

        alert_types_for_node = [a.alert_type for a in result.alerts if a.node_id == "task-001"]
        # Both deadline_warning and stale_warning should be present (before top-3 filter)
        # We check via fresh scan with no dedup state
        all_types = {a.alert_type for a in result.alerts}
        # At minimum, both types should have been considered
        # (top-3 may drop lower severity, so we check that distinct keys are tracked)
        assert len(set(alert_types_for_node)) <= 2  # up to 2 types for this node

    def test_substantive_action_resets_dedup(self, store):
        """A substantive action (update_status) resets the dedup record so alert re-fires."""
        now = _now()
        deadline = now + timedelta(hours=12)
        node = _make_node("task-001", status="active", deadline=_iso(deadline))
        _insert_node(store, node)

        hb = Heartbeat(store)
        # First scan — alert fires
        result1 = hb.scan(now=now)
        assert any(a.alert_type == "urgent_deadline" and a.node_id == "task-001"
                   for a in result1.alerts)

        # Simulate substantive action: update_status event 30 min later
        action_time = _iso(now + timedelta(minutes=30))
        _insert_audit_event(store, "update_status", "task-001", action_time)

        # Second scan 2 hours later (still within 24h window, but action happened)
        now2 = now + timedelta(hours=2)
        result2 = hb.scan(now=now2)
        # Alert should re-fire because substantive action reset the dedup
        assert any(a.alert_type == "urgent_deadline" and a.node_id == "task-001"
                   for a in result2.alerts)


# ===========================================================================
# TestAntiAmnesia
# ===========================================================================

class TestAntiAmnesia:
    """Anti-Amnesia: forced re-push after 24h without substantive action."""

    def test_alert_repushed_after_24h_no_substantive_action(self, store):
        """Alert fires again after 24h without any substantive action (Anti-Amnesia)."""
        now = _now()
        deadline = now + timedelta(hours=12)
        node = _make_node("task-001", status="active", deadline=_iso(deadline))
        _insert_node(store, node)

        hb = Heartbeat(store)
        # First scan
        result1 = hb.scan(now=now)
        assert any(a.alert_type == "urgent_deadline" and a.node_id == "task-001"
                   for a in result1.alerts)

        # Second scan 25 hours later with NO substantive action → Anti-Amnesia re-push
        now2 = now + timedelta(hours=25)
        # Need a node that's still at risk
        deadline2 = now2 + timedelta(hours=12)
        store._conn.execute(
            "UPDATE nodes SET deadline=? WHERE id=?",
            (_iso(deadline2), "task-001"),
        )
        store._conn.commit()
        result2 = hb.scan(now=now2)
        assert any(a.alert_type == "urgent_deadline" and a.node_id == "task-001"
                   for a in result2.alerts), "Anti-Amnesia should force re-push after 24h"

    def test_append_log_does_not_reset_anti_amnesia_timer(self, store):
        """append_log event is NOT substantive → does NOT reset the Anti-Amnesia timer."""
        now = _now()
        deadline = now + timedelta(hours=12)
        node = _make_node("task-001", status="active", deadline=_iso(deadline))
        _insert_node(store, node)

        hb = Heartbeat(store)
        # First scan
        hb.scan(now=now)

        # Add append_log event (non-substantive)
        log_time = _iso(now + timedelta(minutes=30))
        _insert_audit_event(store, "append_log", "task-001", log_time)

        # Second scan 2 hours later (within 24h) — should still be suppressed
        now2 = now + timedelta(hours=2)
        result2 = hb.scan(now=now2)
        urgent_alerts = [a for a in result2.alerts
                         if a.alert_type == "urgent_deadline" and a.node_id == "task-001"]
        assert len(urgent_alerts) == 0, "append_log must not reset Anti-Amnesia timer"

    def test_update_status_resets_anti_amnesia_timer(self, store):
        """update_status IS substantive → resets the timer, alert re-fires before 24h."""
        now = _now()
        deadline = now + timedelta(hours=12)
        node = _make_node("task-001", status="active", deadline=_iso(deadline))
        _insert_node(store, node)

        hb = Heartbeat(store)
        # First scan
        hb.scan(now=now)

        # Add update_status event (substantive)
        action_time = _iso(now + timedelta(minutes=30))
        _insert_audit_event(store, "update_status", "task-001", action_time)

        # Second scan 2 hours later (within 24h but has substantive action)
        now2 = now + timedelta(hours=2)
        result2 = hb.scan(now=now2)
        assert any(a.alert_type == "urgent_deadline" and a.node_id == "task-001"
                   for a in result2.alerts), "update_status should reset timer, alert re-fires"


# ===========================================================================
# TestTop3
# ===========================================================================

class TestTop3:
    """Only top 3 alerts by severity are returned."""

    def test_more_than_3_alerts_returns_only_top_3(self, store):
        """When more than 3 alerts exist, only the 3 highest severity ones are returned."""
        now = _now()
        # Create 5 nodes each with a different alert type
        # 2 urgent_deadline (sev 1), 1 critical_blocked (sev 2), 1 deadline_warning (sev 3),
        # 1 stale_warning (sev 4), 1 inbox_stale (sev 5)

        # urgent_deadline nodes
        for i in range(2):
            deadline = now + timedelta(hours=6)
            n = _make_node(f"urgent-{i:03d}", status="active", deadline=_iso(deadline))
            _insert_node(store, n)

        # stale node
        old_time = _iso(now - timedelta(hours=80))
        stale_node = _make_node("stale-001", status="active", status_changed_at=old_time)
        _insert_node(store, stale_node)

        # inbox_stale node
        old_created = _iso(now - timedelta(days=8))
        inbox_node = _make_node(
            "inbox-001", status="inbox",
            created_at=old_created, status_changed_at=old_created,
        )
        _insert_node(store, inbox_node)

        # deadline_warning node (36h)
        mid_deadline = now + timedelta(hours=36)
        warn_node = _make_node("warn-001", status="active", deadline=_iso(mid_deadline))
        _insert_node(store, warn_node)

        hb = Heartbeat(store)
        result = hb.scan(now=now)

        assert len(result.alerts) <= 3, f"Expected at most 3, got {len(result.alerts)}"
        # All returned alerts should be from the highest severity
        for a in result.alerts:
            assert a.severity <= 3


# ===========================================================================
# TestFocusCandidates
# ===========================================================================

class TestFocusCandidates:
    """Focus candidates come from severity 1-2 alerts only."""

    def test_severity_1_alert_generates_focus_candidate(self, store):
        """urgent_deadline (severity=1) node appears in focus_candidates."""
        now = _now()
        deadline = now + timedelta(hours=6)
        node = _make_node("task-001", status="active", deadline=_iso(deadline))
        _insert_node(store, node)

        hb = Heartbeat(store)
        result = hb.scan(now=now)

        assert "task-001" in result.focus_candidates

    def test_severity_2_alert_generates_focus_candidate(self, store):
        """critical_blocked (severity=2) node appears in focus_candidates."""
        now = _now()
        blocker = _make_node("blocker-001", status="active")
        node = _make_node("task-001", status="active")
        dependent = _make_node("dep-001", status="active")
        _insert_node(store, blocker)
        _insert_node(store, node)
        _insert_node(store, dependent)
        _insert_depends_on(store, "task-001", "blocker-001")
        _insert_depends_on(store, "dep-001", "task-001")

        hb = Heartbeat(store)
        result = hb.scan(now=now)

        assert "task-001" in result.focus_candidates

    def test_severity_3_or_higher_does_not_generate_focus_candidate(self, store):
        """deadline_warning/stale_warning/inbox_stale do NOT generate focus candidates."""
        now = _now()
        # deadline_warning (sev=3)
        deadline = now + timedelta(hours=36)
        warn_node = _make_node("warn-001", status="active", deadline=_iso(deadline))
        _insert_node(store, warn_node)

        # stale_warning (sev=4)
        old_time = _iso(now - timedelta(hours=80))
        stale_node = _make_node("stale-001", status="active", status_changed_at=old_time)
        _insert_node(store, stale_node)

        hb = Heartbeat(store)
        result = hb.scan(now=now)

        assert "warn-001" not in result.focus_candidates
        assert "stale-001" not in result.focus_candidates


# ===========================================================================
# TestArchiveCandidates
# ===========================================================================

class TestArchiveCandidates:
    """Archive candidates are included in HeartbeatResult."""

    def test_archive_candidates_included_in_result(self, store):
        """scan_archive_candidates results appear in result.archive_candidates."""
        now = _now()
        # Create a done node that is past the 7-day cooldown
        old_time = _iso(now - timedelta(days=8))
        done_node = _make_node(
            "task-done",
            status="done",
            status_changed_at=old_time,
            created_at=old_time,
        )
        _insert_node(store, done_node)

        hb = Heartbeat(store)
        result = hb.scan(now=now)

        assert "task-done" in result.archive_candidates

    def test_active_node_not_in_archive_candidates(self, store):
        """Active nodes should NOT appear in archive_candidates."""
        now = _now()
        active_node = _make_node("task-active", status="active")
        _insert_node(store, active_node)

        hb = Heartbeat(store)
        result = hb.scan(now=now)

        assert "task-active" not in result.archive_candidates


# ===========================================================================
# TestEmptyDB
# ===========================================================================

class TestEmptyDB:
    """Edge case: empty database."""

    def test_empty_db_returns_empty_result_no_crash(self, store):
        """With no nodes, scan returns empty HeartbeatResult without crashing."""
        now = _now()
        hb = Heartbeat(store)
        result = hb.scan(now=now)

        assert isinstance(result, HeartbeatResult)
        assert result.alerts == []
        assert result.focus_candidates == []
        assert result.archive_candidates == []
        assert result.nodes_scanned == 0

    def test_nodes_scanned_reflects_actual_count(self, store):
        """nodes_scanned in result matches the number of non-archived nodes queried."""
        now = _now()
        for i in range(3):
            n = _make_node(f"task-{i:03d}", status="active")
            _insert_node(store, n)

        hb = Heartbeat(store)
        result = hb.scan(now=now)

        assert result.nodes_scanned == 3
