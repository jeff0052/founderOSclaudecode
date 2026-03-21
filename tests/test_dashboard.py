"""dashboard.py 测试 — L0 全局看板树渲染。

TDD: 先写测试，再实现。
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone, timedelta
from typing import Optional

import pytest

from fpms.spine.models import Node, RiskMarks
from fpms.spine.store import Store
from fpms.spine.dashboard import render_dashboard, _estimate_tokens, _render_node_line, _get_root_nodes


# ---------------------------------------------------------------------------
# Helpers (mirrors test_risk.py pattern)
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
    now = _iso(_now())
    store._conn.execute(
        "INSERT INTO edges (source_id, target_id, edge_type, created_at) VALUES (?,?,?,?)",
        (source_id, target_id, "depends_on", now),
    )
    store._conn.commit()


# ---------------------------------------------------------------------------
# Helper: stub risk_module that returns pre-configured RiskMarks
# ---------------------------------------------------------------------------

class _StubRiskModule:
    """A callable risk_module stub that returns predetermined RiskMarks."""

    def __init__(self, marks_map: dict[str, RiskMarks] | None = None):
        self._map = marks_map or {}

    def compute_risk_marks_batch(self, nodes, store, now=None):
        result = {}
        for node in nodes:
            result[node.id] = self._map.get(node.id, RiskMarks())
        return result


# ===========================================================================
# TestEstimateTokens
# ===========================================================================

class TestEstimateTokens:
    def test_empty_string(self):
        assert _estimate_tokens("") == 0

    def test_four_chars_one_token(self):
        assert _estimate_tokens("abcd") == 1

    def test_rough_ratio(self):
        text = "a" * 400
        assert _estimate_tokens(text) == 100

    def test_non_divisible(self):
        # 5 chars → 5 // 4 = 1
        assert _estimate_tokens("hello") == 1


# ===========================================================================
# TestRenderNodeLine
# ===========================================================================

class TestRenderNodeLine:
    def test_active_icon(self):
        node = _make_node("task-001", title="My Task", status="active")
        line = _render_node_line(node, depth=0, risk_marks=RiskMarks(), is_last=True)
        assert "▶" in line
        assert "task-001" in line
        assert "My Task" in line

    def test_inbox_icon(self):
        node = _make_node("task-002", title="Inbox Task", status="inbox")
        line = _render_node_line(node, depth=0, risk_marks=RiskMarks(), is_last=True)
        assert "📥" in line

    def test_done_icon(self):
        node = _make_node("task-003", title="Done Task", status="done")
        line = _render_node_line(node, depth=0, risk_marks=RiskMarks(), is_last=True)
        assert "✅" in line

    def test_waiting_icon(self):
        node = _make_node("task-004", title="Wait Task", status="waiting")
        line = _render_node_line(node, depth=0, risk_marks=RiskMarks(), is_last=True)
        assert "⏳" in line

    def test_dropped_icon(self):
        node = _make_node("task-005", title="Drop Task", status="dropped")
        line = _render_node_line(node, depth=0, risk_marks=RiskMarks(), is_last=True)
        assert "❌" in line

    def test_blocked_decoration(self):
        node = _make_node("task-006", title="Blocked Task", status="active")
        marks = RiskMarks(blocked=True, blocked_by=["dep-001"])
        line = _render_node_line(node, depth=0, risk_marks=marks, is_last=True)
        assert "🚨" in line
        assert "blocked" in line

    def test_at_risk_decoration(self):
        node = _make_node("task-007", title="At Risk Task", status="active")
        marks = RiskMarks(at_risk=True, deadline_hours=10.0)
        line = _render_node_line(node, depth=0, risk_marks=marks, is_last=True)
        assert "🚨" in line
        assert "at-risk" in line

    def test_stale_decoration(self):
        node = _make_node("task-008", title="Stale Task", status="active")
        marks = RiskMarks(stale=True)
        line = _render_node_line(node, depth=0, risk_marks=marks, is_last=True)
        assert "⚠️" in line
        assert "stale" in line

    def test_depth_indentation(self):
        node = _make_node("task-009", title="Deep Task", status="active")
        line_d0 = _render_node_line(node, depth=0, risk_marks=RiskMarks(), is_last=False)
        line_d1 = _render_node_line(node, depth=1, risk_marks=RiskMarks(), is_last=False)
        line_d2 = _render_node_line(node, depth=2, risk_marks=RiskMarks(), is_last=False)
        # Deeper lines should be longer (more indentation)
        assert len(line_d1) > len(line_d0)
        assert len(line_d2) > len(line_d1)

    def test_is_last_uses_corner(self):
        node = _make_node("task-010", title="Last Node", status="active")
        line_last = _render_node_line(node, depth=1, risk_marks=RiskMarks(), is_last=True)
        line_not_last = _render_node_line(node, depth=1, risk_marks=RiskMarks(), is_last=False)
        assert "└─" in line_last
        assert "├─" in line_not_last

    def test_deadline_info_shown(self):
        now = _now()
        deadline = now + timedelta(hours=10)
        node = _make_node("task-011", title="Deadline Task", status="active", deadline=_iso(deadline))
        marks = RiskMarks(at_risk=True, deadline_hours=10.0)
        line = _render_node_line(node, depth=0, risk_marks=marks, is_last=True)
        # Should show something about the deadline hours
        assert "10h" in line or "deadline" in line.lower() or "🚨" in line


# ===========================================================================
# TestGetRootNodes
# ===========================================================================

class TestGetRootNodes:
    def test_is_root_true_returned(self, store):
        node = _make_node("goal-001", status="active", is_root=True)
        _insert_node(store, node)
        roots = _get_root_nodes(store)
        ids = [n.id for n in roots]
        assert "goal-001" in ids

    def test_no_parent_non_inbox_returned(self, store):
        node = _make_node("task-001", status="active", parent_id=None, is_root=False)
        _insert_node(store, node)
        roots = _get_root_nodes(store)
        ids = [n.id for n in roots]
        assert "task-001" in ids

    def test_inbox_no_parent_excluded_from_roots(self, store):
        """Inbox nodes with no parent go to Zone 0, not zone 1 roots."""
        node = _make_node("task-002", status="inbox", parent_id=None, is_root=False)
        _insert_node(store, node)
        roots = _get_root_nodes(store)
        ids = [n.id for n in roots]
        assert "task-002" not in ids

    def test_child_node_not_root(self, store):
        parent = _make_node("goal-001", status="active", is_root=True)
        child = _make_node("task-001", status="active", parent_id="goal-001", is_root=False)
        _insert_node(store, parent)
        _insert_node(store, child)
        roots = _get_root_nodes(store)
        ids = [n.id for n in roots]
        assert "task-001" not in ids
        assert "goal-001" in ids

    def test_archived_excluded(self, store):
        now = _iso(_now())
        node = _make_node("goal-001", status="active", is_root=True, archived_at=now)
        _insert_node(store, node)
        roots = _get_root_nodes(store)
        ids = [n.id for n in roots]
        assert "goal-001" not in ids


# ===========================================================================
# TestZone0
# ===========================================================================

class TestZone0:
    """Inbox nodes appear in Zone 0 at top, max 5, overflow as count."""

    def test_inbox_node_appears_in_zone0(self, store):
        node = _make_node("task-001", title="New Email", status="inbox")
        _insert_node(store, node)
        output = render_dashboard(store)
        assert "[收件箱]" in output
        assert "New Email" in output

    def test_zone0_at_top(self, store):
        inbox = _make_node("task-inbox", title="Inbox Item", status="inbox")
        active = _make_node("goal-001", title="Active Goal", status="active", is_root=True)
        _insert_node(store, inbox)
        _insert_node(store, active)
        output = render_dashboard(store)
        inbox_pos = output.find("[收件箱]")
        active_pos = output.find("goal-001")
        assert inbox_pos < active_pos, "Zone 0 inbox should appear before Zone 1 tree"

    def test_max_5_inbox_shown(self, store):
        for i in range(7):
            node = _make_node(f"task-{i:03d}", title=f"Inbox {i}", status="inbox")
            _insert_node(store, node)
        output = render_dashboard(store)
        # Count occurrences of [收件箱]
        count = output.count("[收件箱]")
        assert count <= 5

    def test_overflow_count_shown(self, store):
        for i in range(7):
            node = _make_node(f"task-{i:03d}", title=f"Inbox {i}", status="inbox")
            _insert_node(store, node)
        output = render_dashboard(store)
        # Should mention the remaining 2 items somehow
        assert "2" in output or "+2" in output or "更多" in output or "more" in output.lower()

    def test_no_inbox_nodes_no_zone0_header(self, store):
        node = _make_node("goal-001", title="Active Goal", status="active", is_root=True)
        _insert_node(store, node)
        output = render_dashboard(store)
        # Zone 0 section either absent or empty — shouldn't show inbox items
        assert "Inbox Item" not in output

    def test_inbox_format(self, store):
        node = _make_node("task-001", title="Review PR", status="inbox")
        _insert_node(store, node)
        output = render_dashboard(store)
        # Each inbox line should have [收件箱] prefix
        lines = output.splitlines()
        inbox_lines = [l for l in lines if "Review PR" in l]
        assert len(inbox_lines) == 1
        assert "[收件箱]" in inbox_lines[0]


# ===========================================================================
# TestZone1Tree
# ===========================================================================

class TestZone1Tree:
    """Tree indentation correct for parent→child→grandchild."""

    def test_root_node_appears(self, store):
        root = _make_node("goal-001", title="My Goal", status="active", is_root=True)
        _insert_node(store, root)
        output = render_dashboard(store)
        assert "goal-001" in output
        assert "My Goal" in output

    def test_child_indented_under_parent(self, store):
        root = _make_node("goal-001", title="Parent Goal", status="active", is_root=True)
        child = _make_node("task-001", title="Child Task", status="active", parent_id="goal-001")
        _insert_node(store, root)
        _insert_node(store, child)
        output = render_dashboard(store)
        lines = output.splitlines()
        root_line_idx = next(i for i, l in enumerate(lines) if "goal-001" in l)
        child_line_idx = next(i for i, l in enumerate(lines) if "task-001" in l)
        # Child must appear after root
        assert child_line_idx > root_line_idx
        # Child line must have more leading whitespace than root
        root_line = lines[root_line_idx]
        child_line = lines[child_line_idx]
        root_indent = len(root_line) - len(root_line.lstrip())
        child_indent = len(child_line) - len(child_line.lstrip())
        assert child_indent > root_indent

    def test_grandchild_deeper_indent(self, store):
        root = _make_node("goal-001", title="Root", status="active", is_root=True)
        child = _make_node("proj-001", title="Child", status="active", parent_id="goal-001")
        grandchild = _make_node("task-001", title="Grandchild", status="active", parent_id="proj-001")
        _insert_node(store, root)
        _insert_node(store, child)
        _insert_node(store, grandchild)
        output = render_dashboard(store)
        lines = output.splitlines()
        root_line = next(l for l in lines if "goal-001" in l)
        child_line = next(l for l in lines if "proj-001" in l)
        grandchild_line = next(l for l in lines if "task-001" in l)
        root_indent = len(root_line) - len(root_line.lstrip())
        child_indent = len(child_line) - len(child_line.lstrip())
        grandchild_indent = len(grandchild_line) - len(grandchild_line.lstrip())
        assert child_indent > root_indent
        assert grandchild_indent > child_indent

    def test_tree_connectors_present(self, store):
        root = _make_node("goal-001", title="Root Goal", status="active", is_root=True)
        child = _make_node("task-001", title="Child Task", status="active", parent_id="goal-001")
        _insert_node(store, root)
        _insert_node(store, child)
        output = render_dashboard(store)
        # Should have tree connector characters
        assert "├─" in output or "└─" in output

    def test_multiple_children_all_shown(self, store):
        root = _make_node("goal-001", title="Root", status="active", is_root=True)
        child1 = _make_node("task-001", title="Child One", status="active", parent_id="goal-001")
        child2 = _make_node("task-002", title="Child Two", status="active", parent_id="goal-001")
        _insert_node(store, root)
        _insert_node(store, child1)
        _insert_node(store, child2)
        output = render_dashboard(store)
        assert "task-001" in output
        assert "task-002" in output


# ===========================================================================
# TestRiskSorting
# ===========================================================================

class TestRiskSorting:
    """Blocked nodes sort first, then at-risk, then stale, then healthy."""

    def test_blocked_sorts_before_healthy(self, store):
        root = _make_node("goal-001", title="Root", status="active", is_root=True)
        healthy = _make_node("task-healthy", title="Healthy Task", status="active", parent_id="goal-001")
        blocker_dep = _make_node("dep-001", title="Dep", status="active")
        blocked = _make_node("task-blocked", title="Blocked Task", status="active", parent_id="goal-001")

        _insert_node(store, root)
        _insert_node(store, healthy)
        _insert_node(store, blocker_dep)
        _insert_node(store, blocked)
        _insert_depends_on(store, "task-blocked", "dep-001")

        output = render_dashboard(store)
        blocked_pos = output.find("task-blocked")
        healthy_pos = output.find("task-healthy")
        assert blocked_pos < healthy_pos, "Blocked node should appear before healthy node"

    def test_stale_sorts_before_healthy(self, store):
        now = _now()
        old_time = _iso(now - timedelta(hours=80))
        root = _make_node("goal-001", title="Root", status="active", is_root=True)
        stale = _make_node("task-stale", title="Stale Task", status="active",
                           parent_id="goal-001", status_changed_at=old_time)
        healthy = _make_node("task-healthy", title="Healthy Task", status="active", parent_id="goal-001")

        _insert_node(store, root)
        _insert_node(store, stale)
        _insert_node(store, healthy)

        output = render_dashboard(store)
        stale_pos = output.find("task-stale")
        healthy_pos = output.find("task-healthy")
        assert stale_pos < healthy_pos, "Stale node should appear before healthy node"

    def test_at_risk_sorts_before_stale(self, store):
        now = _now()
        old_time = _iso(now - timedelta(hours=80))
        near_deadline = _iso(now + timedelta(hours=10))
        root = _make_node("goal-001", title="Root", status="active", is_root=True)
        stale = _make_node("task-stale", title="Stale Task", status="active",
                           parent_id="goal-001", status_changed_at=old_time)
        at_risk = _make_node("task-atrisk", title="At Risk Task", status="active",
                             parent_id="goal-001", deadline=near_deadline)

        _insert_node(store, root)
        _insert_node(store, stale)
        _insert_node(store, at_risk)

        output = render_dashboard(store)
        atrisk_pos = output.find("task-atrisk")
        stale_pos = output.find("task-stale")
        assert atrisk_pos < stale_pos, "At-risk node should appear before stale node"


# ===========================================================================
# TestArchivedExcluded
# ===========================================================================

class TestArchivedExcluded:
    """Archived nodes must not appear in dashboard output."""

    def test_archived_root_excluded(self, store):
        now_str = _iso(_now())
        node = _make_node("goal-archived", title="Archived Goal", status="active",
                          is_root=True, archived_at=now_str)
        _insert_node(store, node)
        output = render_dashboard(store)
        assert "goal-archived" not in output
        assert "Archived Goal" not in output

    def test_archived_child_excluded(self, store):
        now_str = _iso(_now())
        root = _make_node("goal-001", title="Root", status="active", is_root=True)
        archived_child = _make_node("task-archived", title="Archived Child", status="active",
                                    parent_id="goal-001", archived_at=now_str)
        _insert_node(store, root)
        _insert_node(store, archived_child)
        output = render_dashboard(store)
        assert "task-archived" not in output
        assert "Archived Child" not in output

    def test_non_archived_still_shown(self, store):
        now_str = _iso(_now())
        archived = _make_node("task-archived", title="Archived", status="active",
                              is_root=True, archived_at=now_str)
        active = _make_node("task-active", title="Active Node", status="active", is_root=True)
        _insert_node(store, archived)
        _insert_node(store, active)
        output = render_dashboard(store)
        assert "task-active" in output
        assert "task-archived" not in output


# ===========================================================================
# TestTokenTruncation
# ===========================================================================

class TestTokenTruncation:
    """Large trees fold healthy branches when over token budget."""

    def test_healthy_branches_folded_under_budget(self, store):
        """With very low max_tokens, healthy children should be folded."""
        root = _make_node("goal-001", title="Root", status="active", is_root=True)
        _insert_node(store, root)
        # Add many children (all healthy)
        for i in range(10):
            child = _make_node(f"task-{i:03d}", title=f"Healthy Child {i}",
                               status="active", parent_id="goal-001")
            _insert_node(store, child)

        # Very small budget forces folding
        output = render_dashboard(store, max_tokens=20)
        # Should have fold indicator
        assert "折叠" in output or "..." in output

    def test_risky_nodes_always_shown(self, store):
        """Blocked/at-risk/stale nodes must appear even under tiny budget."""
        now = _now()
        old_time = _iso(now - timedelta(hours=80))

        root = _make_node("goal-001", title="Root", status="active", is_root=True)
        blocker = _make_node("dep-001", title="Blocker Dep", status="active")
        blocked = _make_node("task-blocked", title="Blocked Task", status="active",
                             parent_id="goal-001")
        # Also add many healthy nodes to push us over budget
        _insert_node(store, root)
        _insert_node(store, blocker)
        _insert_node(store, blocked)
        _insert_depends_on(store, "task-blocked", "dep-001")

        for i in range(20):
            child = _make_node(f"healthy-{i:03d}", title=f"Healthy {i}",
                               status="active", parent_id="goal-001")
            _insert_node(store, child)

        output = render_dashboard(store, max_tokens=50)
        # Blocked node must always be visible
        assert "task-blocked" in output

    def test_normal_budget_shows_everything(self, store):
        """Default budget of 1000 tokens shows all nodes in a small tree."""
        root = _make_node("goal-001", title="Root", status="active", is_root=True)
        child1 = _make_node("task-001", title="Child One", status="active", parent_id="goal-001")
        child2 = _make_node("task-002", title="Child Two", status="active", parent_id="goal-001")
        _insert_node(store, root)
        _insert_node(store, child1)
        _insert_node(store, child2)

        output = render_dashboard(store, max_tokens=1000)
        assert "task-001" in output
        assert "task-002" in output


# ===========================================================================
# TestEmptyDashboard
# ===========================================================================

class TestEmptyDashboard:
    """Empty DB returns minimal output without errors."""

    def test_empty_db_no_crash(self, store):
        output = render_dashboard(store)
        assert isinstance(output, str)

    def test_empty_db_returns_string(self, store):
        output = render_dashboard(store)
        assert len(output) >= 0  # At minimum, empty or short string

    def test_empty_db_no_node_ids(self, store):
        output = render_dashboard(store)
        # No random node IDs should appear
        assert "goal-" not in output
        assert "task-" not in output


# ===========================================================================
# TestRiskDecorations
# ===========================================================================

class TestRiskDecorations:
    """Risk marks appear correctly in output lines."""

    def test_blocked_mark_in_output(self, store):
        root = _make_node("goal-001", title="Root", status="active", is_root=True)
        blocker = _make_node("dep-001", title="Dep", status="active")
        blocked = _make_node("task-blocked", title="Blocked Task", status="active",
                             parent_id="goal-001")
        _insert_node(store, root)
        _insert_node(store, blocker)
        _insert_node(store, blocked)
        _insert_depends_on(store, "task-blocked", "dep-001")

        output = render_dashboard(store)
        lines = output.splitlines()
        blocked_lines = [l for l in lines if "task-blocked" in l]
        assert len(blocked_lines) >= 1
        assert "🚨" in blocked_lines[0]
        assert "blocked" in blocked_lines[0]

    def test_stale_mark_in_output(self, store):
        now = _now()
        old_time = _iso(now - timedelta(hours=80))
        root = _make_node("goal-001", title="Root", status="active", is_root=True)
        stale = _make_node("task-stale", title="Stale Task", status="active",
                           parent_id="goal-001", status_changed_at=old_time)
        _insert_node(store, root)
        _insert_node(store, stale)

        output = render_dashboard(store)
        lines = output.splitlines()
        stale_lines = [l for l in lines if "task-stale" in l]
        assert len(stale_lines) >= 1
        assert "⚠️" in stale_lines[0]
        assert "stale" in stale_lines[0]

    def test_at_risk_mark_in_output(self, store):
        now = _now()
        near_deadline = _iso(now + timedelta(hours=10))
        root = _make_node("goal-001", title="Root", status="active", is_root=True)
        at_risk = _make_node("task-atrisk", title="At Risk Task", status="active",
                             parent_id="goal-001", deadline=near_deadline)
        _insert_node(store, root)
        _insert_node(store, at_risk)

        output = render_dashboard(store)
        lines = output.splitlines()
        risk_lines = [l for l in lines if "task-atrisk" in l]
        assert len(risk_lines) >= 1
        assert "🚨" in risk_lines[0]
        assert "at-risk" in risk_lines[0]

    def test_healthy_node_no_risk_marks(self, store):
        root = _make_node("goal-001", title="Root", status="active", is_root=True)
        healthy = _make_node("task-healthy", title="Healthy Task", status="active",
                             parent_id="goal-001")
        _insert_node(store, root)
        _insert_node(store, healthy)

        output = render_dashboard(store)
        lines = output.splitlines()
        healthy_lines = [l for l in lines if "task-healthy" in l]
        assert len(healthy_lines) >= 1
        # Should not have risk decorations
        assert "🚨" not in healthy_lines[0]
        assert "⚠️" not in healthy_lines[0]


# ===========================================================================
# TestRootNodes
# ===========================================================================

class TestRootNodes:
    """is_root=True nodes shown as tree roots even if they have a parent_id."""

    def test_is_root_true_shown_as_root(self, store):
        node = _make_node("goal-001", title="Root Goal", status="active", is_root=True)
        _insert_node(store, node)
        output = render_dashboard(store)
        assert "goal-001" in output

    def test_multiple_roots_all_shown(self, store):
        root1 = _make_node("goal-001", title="Goal One", status="active", is_root=True)
        root2 = _make_node("goal-002", title="Goal Two", status="active", is_root=True)
        _insert_node(store, root1)
        _insert_node(store, root2)
        output = render_dashboard(store)
        assert "goal-001" in output
        assert "goal-002" in output

    def test_root_depth_zero_no_tree_connectors(self, store):
        """Root nodes at depth 0 should NOT have tree connector prefixes."""
        root = _make_node("goal-001", title="Root Goal", status="active", is_root=True)
        _insert_node(store, root)
        output = render_dashboard(store)
        lines = output.splitlines()
        root_line = next(l for l in lines if "goal-001" in l)
        # Root line should not start with tree branch characters
        stripped = root_line.lstrip()
        assert not stripped.startswith("├─")
        assert not stripped.startswith("└─")

    def test_inbox_nodes_not_in_zone1(self, store):
        """Pure inbox nodes (no parent, not is_root) go to Zone 0 only."""
        inbox = _make_node("task-inbox", title="Inbox Task", status="inbox")
        _insert_node(store, inbox)
        output = render_dashboard(store)
        # The node should appear (in zone 0) but should not also appear in zone 1 tree
        lines = output.splitlines()
        inbox_occurrences = [l for l in lines if "task-inbox" in l]
        # Should appear only once (in zone 0)
        assert len(inbox_occurrences) == 1
