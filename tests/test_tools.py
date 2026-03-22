"""tools.py + command_executor.py 测试 — 15 Tool handlers + idempotency。"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import pytest

from fpms.spine.models import Edge, Node, ToolResult
from fpms.spine.store import Store
from fpms.spine.tools import ToolHandler
from fpms.spine.command_executor import CommandExecutor
from fpms.spine import validator as validator_mod
from fpms.spine import narrative as narrative_mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_dirs(tmp_path):
    """Return paths for db, events, and narratives."""
    db_path = str(tmp_path / "test.db")
    events_path = str(tmp_path / "events.jsonl")
    narratives_dir = str(tmp_path / "narratives")
    return db_path, events_path, narratives_dir


@pytest.fixture
def store(tmp_dirs):
    db_path, events_path, _ = tmp_dirs
    return Store(db_path, events_path)


@pytest.fixture
def handler(store, tmp_dirs):
    _, _, narratives_dir = tmp_dirs
    h = ToolHandler(store)
    h.narratives_dir = narratives_dir
    return h


@pytest.fixture
def executor(store, handler):
    ex = CommandExecutor(store, tool_handler=handler)
    return ex


def _make_node(store, **overrides) -> Node:
    """Helper: create a node in the store and return it."""
    defaults = dict(
        id="",
        title="Test Node",
        status="inbox",
        node_type="task",
    )
    defaults.update(overrides)
    node = Node(**defaults)
    with store.transaction():
        created = store.create_node(node)
    return created


def _make_active_node(store, handler, **overrides) -> Node:
    """Helper: create a node and move it to active status (needs summary + is_root)."""
    defaults = dict(
        title="Active Node",
        summary="Has a summary",
        is_root=True,
    )
    defaults.update(overrides)
    node = _make_node(store, **defaults)
    # Transition to active
    result = handler.handle("update_status", {
        "node_id": node.id,
        "new_status": "active",
        "command_id": "setup-active",
    })
    assert result.success, f"Failed to activate node: {result.error}"
    return store.get_node(node.id)


# ===========================================================================
# 1. create_node
# ===========================================================================

class TestCreateNode:
    def test_normal_create_with_source(self, handler):
        result = handler.handle("create_node", {
            "title": "My Task",
            "node_type": "task",
            "source": "github",
            "source_id": "GH-42",
            "source_url": "https://github.com/issue/42",
            "command_id": "cmd-1",
        })
        assert result.success is True
        assert result.data["title"] == "My Task"
        assert result.data["source"] == "github"
        assert result.data["source_id"] == "GH-42"
        assert result.data["source_url"] == "https://github.com/issue/42"
        assert result.data["status"] == "inbox"
        assert result.event_id is not None
        assert result.command_id == "cmd-1"

    def test_missing_required_field(self, handler):
        result = handler.handle("create_node", {
            "command_id": "cmd-2",
        })
        assert result.success is False
        assert result.error is not None
        assert result.suggestion is not None

    def test_pydantic_validation_reject(self, handler):
        result = handler.handle("create_node", {
            "title": "Bad Type",
            "node_type": "invalid_type",
            "command_id": "cmd-3",
        })
        assert result.success is False
        assert "node_type" in result.error

    def test_xor_violation(self, handler, store):
        # Create a parent node first
        parent = _make_node(store, title="Parent")
        result = handler.handle("create_node", {
            "title": "XOR Fail",
            "is_root": True,
            "parent_id": parent.id,
            "command_id": "cmd-4",
        })
        assert result.success is False
        assert "XOR" in result.error or "is_root" in result.error

    def test_create_with_parent_creates_edge(self, handler, store):
        parent = _make_node(store, title="Parent")
        result = handler.handle("create_node", {
            "title": "Child",
            "parent_id": parent.id,
            "command_id": "cmd-5",
        })
        assert result.success is True
        child_id = result.data["id"]
        edges = store.get_edges(parent.id, edge_type="parent", direction="incoming")
        assert any(e.source_id == child_id for e in edges)


# ===========================================================================
# 2. update_status
# ===========================================================================

class TestUpdateStatus:
    def test_legal_transition(self, handler, store):
        node = _make_node(store, title="Status Test", summary="Has summary", is_root=True)
        result = handler.handle("update_status", {
            "node_id": node.id,
            "new_status": "active",
            "command_id": "cmd-10",
        })
        assert result.success is True
        assert result.data["status"] == "active"
        assert result.data["status_changed_at"] != node.status_changed_at

    def test_illegal_transition_rejected(self, handler, store):
        node = _make_node(store, title="Illegal", summary="s", is_root=True)
        result = handler.handle("update_status", {
            "node_id": node.id,
            "new_status": "done",
            "command_id": "cmd-11",
        })
        # inbox→done is illegal
        assert result.success is False
        assert "ILLEGAL_TRANSITION" in result.error or "不合法" in result.error

    def test_is_root_auto_clears_parent(self, handler, store):
        parent = _make_node(store, title="Parent")
        child = _make_node(store, title="Child", parent_id=parent.id, summary="s")
        # Parent edge is auto-added by create_node (child -> parent convention)

        result = handler.handle("update_status", {
            "node_id": child.id,
            "new_status": "active",
            "is_root": True,
            "command_id": "cmd-12",
        })
        assert result.success is True
        updated = store.get_node(child.id)
        assert updated.parent_id is None
        assert updated.is_root is True

    def test_done_requires_children_terminal(self, handler, store):
        parent = _make_node(store, title="Parent", summary="s", is_root=True)
        # Activate parent first
        handler.handle("update_status", {
            "node_id": parent.id, "new_status": "active", "command_id": "s1"
        })
        # Create active child
        child = _make_node(store, title="Child", parent_id=parent.id, summary="s")
        handler.handle("update_status", {
            "node_id": child.id, "new_status": "active", "command_id": "s2"
        })
        # Try done on parent
        result = handler.handle("update_status", {
            "node_id": parent.id,
            "new_status": "done",
            "command_id": "cmd-13",
        })
        assert result.success is False
        assert "ACTIVE_CHILDREN" in result.error or "非终态" in result.error

    def test_node_not_found(self, handler):
        result = handler.handle("update_status", {
            "node_id": "nonexistent",
            "new_status": "active",
            "command_id": "cmd-14",
        })
        assert result.success is False
        assert "not found" in result.error


# ===========================================================================
# 3. update_field
# ===========================================================================

class TestUpdateField:
    def test_normal_update(self, handler, store):
        node = _make_node(store, title="Old Title")
        result = handler.handle("update_field", {
            "node_id": node.id,
            "field": "title",
            "value": "New Title",
            "command_id": "cmd-20",
        })
        assert result.success is True
        assert result.data["title"] == "New Title"

    def test_forbidden_field_rejected(self, handler, store):
        node = _make_node(store, title="T")
        result = handler.handle("update_field", {
            "node_id": node.id,
            "field": "status",
            "value": "active",
            "command_id": "cmd-21",
        })
        assert result.success is False
        assert result.suggestion is not None

    def test_summary_update(self, handler, store):
        node = _make_node(store, title="T")
        result = handler.handle("update_field", {
            "node_id": node.id,
            "field": "summary",
            "value": "This is a summary",
            "command_id": "cmd-22",
        })
        assert result.success is True
        assert result.data["summary"] == "This is a summary"


# ===========================================================================
# 4. attach_node
# ===========================================================================

class TestAttachNode:
    def test_normal_attach(self, handler, store):
        parent = _make_node(store, title="Parent")
        child = _make_node(store, title="Child")
        result = handler.handle("attach_node", {
            "node_id": child.id,
            "parent_id": parent.id,
            "command_id": "cmd-30",
        })
        assert result.success is True
        updated = store.get_node(child.id)
        assert updated.parent_id == parent.id
        assert updated.is_root is False

    def test_atomic_replace_parent(self, handler, store):
        old_parent = _make_node(store, title="OldParent")
        new_parent = _make_node(store, title="NewParent")
        child = _make_node(store, title="Child", parent_id=old_parent.id)
        # Parent edge is auto-added by create_node (child -> parent convention)

        result = handler.handle("attach_node", {
            "node_id": child.id,
            "parent_id": new_parent.id,
            "command_id": "cmd-31",
        })
        assert result.success is True
        updated = store.get_node(child.id)
        assert updated.parent_id == new_parent.id
        # Old edge should be gone (child -> old_parent convention)
        old_edges = store.get_edges(child.id, edge_type="parent", direction="outgoing")
        assert not any(e.target_id == old_parent.id for e in old_edges)

    def test_archived_target_reject(self, handler, store):
        parent = _make_node(store, title="ArchivedParent")
        with store.transaction():
            store.update_node(parent.id, {"archived_at": datetime.now(timezone.utc).isoformat()})
        child = _make_node(store, title="Child")

        result = handler.handle("attach_node", {
            "node_id": child.id,
            "parent_id": parent.id,
            "command_id": "cmd-32",
        })
        assert result.success is False
        assert "ARCHIVED" in result.error or "归档" in result.error

    def test_dag_cycle_reject(self, handler, store):
        a = _make_node(store, title="A")
        b = _make_node(store, title="B")
        # Attach B to A
        handler.handle("attach_node", {
            "node_id": b.id, "parent_id": a.id, "command_id": "s1"
        })
        # Try to attach A to B (cycle)
        result = handler.handle("attach_node", {
            "node_id": a.id,
            "parent_id": b.id,
            "command_id": "cmd-33",
        })
        assert result.success is False
        assert "CYCLE" in result.error or "环路" in result.error


# ===========================================================================
# 5. detach_node
# ===========================================================================

class TestDetachNode:
    def test_normal_detach(self, handler, store):
        parent = _make_node(store, title="Parent")
        child = _make_node(store, title="Child", parent_id=parent.id)
        # Parent edge is auto-added by create_node (child -> parent convention)

        result = handler.handle("detach_node", {
            "node_id": child.id,
            "command_id": "cmd-40",
        })
        assert result.success is True
        updated = store.get_node(child.id)
        assert updated.parent_id is None

    def test_no_parent_behavior(self, handler, store):
        node = _make_node(store, title="Orphan")
        result = handler.handle("detach_node", {
            "node_id": node.id,
            "command_id": "cmd-41",
        })
        assert result.success is True
        assert len(result.warnings) > 0  # warning about no parent


# ===========================================================================
# 6. add_dependency
# ===========================================================================

class TestAddDependency:
    def test_normal(self, handler, store):
        a = _make_node(store, title="A")
        b = _make_node(store, title="B")
        result = handler.handle("add_dependency", {
            "source_id": a.id,
            "target_id": b.id,
            "command_id": "cmd-50",
        })
        assert result.success is True
        deps = store.get_dependencies(a.id)
        assert any(d.id == b.id for d in deps)

    def test_self_dependency_reject(self, handler, store):
        a = _make_node(store, title="A")
        result = handler.handle("add_dependency", {
            "source_id": a.id,
            "target_id": a.id,
            "command_id": "cmd-51",
        })
        assert result.success is False
        assert "SELF" in result.error or "自身" in result.error

    def test_cycle_reject(self, handler, store):
        a = _make_node(store, title="A")
        b = _make_node(store, title="B")
        # A depends_on B
        handler.handle("add_dependency", {
            "source_id": a.id, "target_id": b.id, "command_id": "s1"
        })
        # B depends_on A should fail (cycle)
        result = handler.handle("add_dependency", {
            "source_id": b.id,
            "target_id": a.id,
            "command_id": "cmd-52",
        })
        assert result.success is False
        assert "CYCLE" in result.error or "环路" in result.error

    def test_archived_target_reject(self, handler, store):
        a = _make_node(store, title="A")
        b = _make_node(store, title="B")
        with store.transaction():
            store.update_node(b.id, {"archived_at": datetime.now(timezone.utc).isoformat()})
        result = handler.handle("add_dependency", {
            "source_id": a.id,
            "target_id": b.id,
            "command_id": "cmd-53",
        })
        assert result.success is False
        assert "ARCHIVED" in result.error or "归档" in result.error


# ===========================================================================
# 7. remove_dependency
# ===========================================================================

class TestRemoveDependency:
    def test_normal(self, handler, store):
        a = _make_node(store, title="A")
        b = _make_node(store, title="B")
        with store.transaction():
            store.add_edge(Edge(source_id=a.id, target_id=b.id, edge_type="depends_on"))
        result = handler.handle("remove_dependency", {
            "source_id": a.id,
            "target_id": b.id,
            "command_id": "cmd-60",
        })
        assert result.success is True
        assert result.data["removed"] is True

    def test_non_existent_dependency(self, handler, store):
        a = _make_node(store, title="A")
        b = _make_node(store, title="B")
        result = handler.handle("remove_dependency", {
            "source_id": a.id,
            "target_id": b.id,
            "command_id": "cmd-61",
        })
        assert result.success is True
        assert result.data["removed"] is False
        assert len(result.warnings) > 0


# ===========================================================================
# 8. append_log
# ===========================================================================

class TestAppendLog:
    def test_normal_append(self, handler, store, tmp_dirs):
        node = _make_node(store, title="LogNode")
        result = handler.handle("append_log", {
            "node_id": node.id,
            "content": "Something happened",
            "event_type": "note",
            "command_id": "cmd-70",
        })
        assert result.success is True
        # Check narrative file was written
        _, _, narratives_dir = tmp_dirs
        filepath = os.path.join(narratives_dir, f"{node.id}.md")
        assert os.path.exists(filepath)
        with open(filepath) as f:
            text = f.read()
        assert "Something happened" in text

    def test_does_not_reset_anti_amnesia_timer(self, handler, store):
        node = _make_node(store, title="TimerNode")
        # Set a fake anti-amnesia timer
        with store.transaction():
            store.set_session("anti_amnesia_last", {"ts": "2025-01-01T00:00:00Z"})

        handler.handle("append_log", {
            "node_id": node.id,
            "content": "Log entry",
            "event_type": "log",
            "command_id": "cmd-71",
        })

        # Timer should NOT be reset
        timer = store.get_session("anti_amnesia_last")
        assert timer == {"ts": "2025-01-01T00:00:00Z"}


# ===========================================================================
# 8b. append_log — category field
# ===========================================================================

class TestAppendLogCategory:
    def test_append_log_with_category(self, handler, store, tmp_dirs):
        node = _make_node(store, title="CatNode")
        result = handler.handle("append_log", {
            "node_id": node.id,
            "content": "Made a decision",
            "event_type": "log",
            "category": "decision",
            "command_id": "cmd-cat-1",
        })
        assert result.success is True
        assert result.data["category"] == "decision"
        _, _, narratives_dir = tmp_dirs
        filepath = os.path.join(narratives_dir, f"{node.id}.md")
        text = open(filepath).read()
        assert "[decision]" in text

    def test_append_log_default_category_general(self, handler, store, tmp_dirs):
        node = _make_node(store, title="DefaultCatNode")
        result = handler.handle("append_log", {
            "node_id": node.id,
            "content": "No category specified",
            "event_type": "log",
            "command_id": "cmd-cat-2",
        })
        assert result.success is True
        assert result.data["category"] == "general"
        _, _, narratives_dir = tmp_dirs
        filepath = os.path.join(narratives_dir, f"{node.id}.md")
        text = open(filepath).read()
        assert "[general]" in text

    def test_append_log_invalid_category_rejected(self, handler, store):
        node = _make_node(store, title="BadCatNode")
        result = handler.handle("append_log", {
            "node_id": node.id,
            "content": "Some content",
            "event_type": "log",
            "category": "invalid_cat",
            "command_id": "cmd-cat-3",
        })
        assert result.success is False
        assert "Invalid category" in result.error
        assert "invalid_cat" in result.error


# ===========================================================================
# 9. unarchive
# ===========================================================================

class TestUnarchive:
    def test_normal_unarchive(self, handler, store):
        node = _make_node(store, title="Archived")
        with store.transaction():
            store.update_node(node.id, {"archived_at": "2025-01-01T00:00:00Z"})

        result = handler.handle("unarchive", {
            "node_id": node.id,
            "command_id": "cmd-80",
        })
        assert result.success is True
        updated = store.get_node(node.id)
        assert updated.archived_at is None
        # status_changed_at should be refreshed to NOW
        assert updated.status_changed_at > node.status_changed_at

    def test_unarchive_with_new_status(self, handler, store):
        node = _make_node(store, title="Archived", summary="s", is_root=True)
        with store.transaction():
            store.update_node(node.id, {"archived_at": "2025-01-01T00:00:00Z"})

        result = handler.handle("unarchive", {
            "node_id": node.id,
            "new_status": "active",
            "command_id": "cmd-81",
        })
        assert result.success is True
        updated = store.get_node(node.id)
        assert updated.archived_at is None
        assert updated.status == "active"

    def test_non_archived_node_rejected(self, handler, store):
        node = _make_node(store, title="NotArchived")
        result = handler.handle("unarchive", {
            "node_id": node.id,
            "command_id": "cmd-82",
        })
        assert result.success is False
        assert "not archived" in result.error


# ===========================================================================
# 10. set_persistent
# ===========================================================================

class TestSetPersistent:
    def test_set_persistent(self, handler, store):
        node = _make_node(store, title="Persist")
        result = handler.handle("set_persistent", {
            "node_id": node.id,
            "is_persistent": True,
            "command_id": "cmd-90",
        })
        assert result.success is True
        updated = store.get_node(node.id)
        assert updated.is_persistent is True

    def test_unset_persistent(self, handler, store):
        node = _make_node(store, title="Persist", is_persistent=True)
        result = handler.handle("set_persistent", {
            "node_id": node.id,
            "is_persistent": False,
            "command_id": "cmd-91",
        })
        assert result.success is True
        updated = store.get_node(node.id)
        assert updated.is_persistent is False


# ===========================================================================
# 11. shift_focus
# ===========================================================================

class TestShiftFocus:
    def test_switches_focus(self, handler, store):
        node = _make_node(store, title="Focus")
        result = handler.handle("shift_focus", {
            "node_id": node.id,
            "command_id": "cmd-100",
        })
        assert result.success is True
        focus = store.get_session("focus_list")
        assert focus == [node.id]

    def test_node_not_found(self, handler):
        result = handler.handle("shift_focus", {
            "node_id": "nonexistent",
            "command_id": "cmd-101",
        })
        assert result.success is False


# ===========================================================================
# 12. expand_context
# ===========================================================================

class TestExpandContext:
    def test_returns_context(self, handler, store):
        parent = _make_node(store, title="Parent")
        child = _make_node(store, title="Child", parent_id=parent.id)
        result = handler.handle("expand_context", {
            "node_id": child.id,
            "command_id": "cmd-110",
        })
        assert result.success is True
        assert result.data["node"]["id"] == child.id
        assert result.data["parent"]["id"] == parent.id

    def test_node_not_found(self, handler):
        result = handler.handle("expand_context", {
            "node_id": "nonexistent",
            "command_id": "cmd-111",
        })
        assert result.success is False


# ===========================================================================
# 13. get_node
# ===========================================================================

class TestGetNode:
    def test_exists(self, handler, store):
        node = _make_node(store, title="FindMe")
        result = handler.handle("get_node", {
            "node_id": node.id,
            "command_id": "cmd-120",
        })
        assert result.success is True
        assert result.data["title"] == "FindMe"

    def test_not_exists(self, handler):
        result = handler.handle("get_node", {
            "node_id": "no-such-id",
            "command_id": "cmd-121",
        })
        assert result.success is False
        assert "not found" in result.error


# ===========================================================================
# 14. search_nodes
# ===========================================================================

class TestSearchNodes:
    def test_by_status_filter(self, handler, store):
        _make_node(store, title="A", summary="s", is_root=True)
        n2 = _make_node(store, title="B", summary="s", is_root=True)
        # Activate B
        handler.handle("update_status", {
            "node_id": n2.id, "new_status": "active", "command_id": "s1"
        })

        result = handler.handle("search_nodes", {
            "filters": {"status": "active"},
            "command_id": "cmd-130",
        })
        assert result.success is True
        nodes = result.data["nodes"]
        assert len(nodes) == 1
        assert nodes[0]["id"] == n2.id

    def test_by_parent_id_filter(self, handler, store):
        parent = _make_node(store, title="P")
        child = _make_node(store, title="C", parent_id=parent.id)
        _make_node(store, title="Other")

        result = handler.handle("search_nodes", {
            "filters": {"parent_id": parent.id},
            "command_id": "cmd-131",
        })
        assert result.success is True
        assert result.data["count"] == 1
        assert result.data["nodes"][0]["id"] == child.id

    def test_by_source_filter(self, handler, store):
        _make_node(store, title="GH", source="github")
        _make_node(store, title="Int", source="internal")

        result = handler.handle("search_nodes", {
            "filters": {"source": "github"},
            "command_id": "cmd-132",
        })
        assert result.success is True
        assert result.data["count"] == 1

    def test_pagination(self, handler, store):
        for i in range(5):
            _make_node(store, title=f"N{i}")

        result = handler.handle("search_nodes", {
            "limit": 2,
            "offset": 0,
            "command_id": "cmd-133",
        })
        assert result.success is True
        assert result.data["count"] == 2

    def test_summary_default_not_included(self, handler, store):
        _make_node(store, title="WithSummary", summary="My summary")

        result = handler.handle("search_nodes", {
            "command_id": "cmd-134",
        })
        assert result.success is True
        nodes = result.data["nodes"]
        assert len(nodes) == 1
        assert "summary" not in nodes[0]

    def test_summary_included_when_requested(self, handler, store):
        _make_node(store, title="WithSummary", summary="My summary")

        result = handler.handle("search_nodes", {
            "include_summary": True,
            "command_id": "cmd-135",
        })
        assert result.success is True
        nodes = result.data["nodes"]
        assert nodes[0]["summary"] == "My summary"


# ===========================================================================
# 15. get_assembly_trace
# ===========================================================================

class TestGetAssemblyTrace:
    def test_returns_empty_for_v0(self, handler):
        result = handler.handle("get_assembly_trace", {
            "command_id": "cmd-140",
        })
        assert result.success is True
        assert result.data["traces"] == []


# ===========================================================================
# Idempotency via CommandExecutor
# ===========================================================================

class TestIdempotencyWithTools:
    def test_same_command_id_returns_same_result(self, executor, store):
        result1 = executor.execute("cmd-idem-1", "create_node", {
            "title": "Idempotent Node",
            "node_type": "task",
        })
        assert result1.success is True
        node_id = result1.data["id"]

        # Same command_id → cached result
        result2 = executor.execute("cmd-idem-1", "create_node", {
            "title": "Should Not Create",
        })
        assert result2.success is True
        assert result2.data["id"] == node_id

        # Only one node created
        all_nodes = store.list_nodes()
        assert len(all_nodes) == 1

    def test_different_command_id_creates_new(self, executor, store):
        result1 = executor.execute("cmd-idem-2a", "create_node", {
            "title": "First",
            "node_type": "task",
        })
        result2 = executor.execute("cmd-idem-2b", "create_node", {
            "title": "Second",
            "node_type": "task",
        })
        assert result1.data["id"] != result2.data["id"]
        assert len(store.list_nodes()) == 2


# ===========================================================================
# Unknown tool
# ===========================================================================

class TestUnknownTool:
    def test_unknown_tool_returns_error(self, handler):
        result = handler.handle("nonexistent_tool", {"command_id": "cmd-999"})
        assert result.success is False
        assert "Unknown tool" in result.error
        assert result.suggestion is not None
