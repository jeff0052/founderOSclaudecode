"""store.py + command_executor.py 测试 — Node/Edge CRUD, Graph, Transaction, Audit, Idempotency."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta

import pytest

from fpms.spine.models import Edge, Node, ToolResult
from fpms.spine.store import Store
from fpms.spine.command_executor import CommandExecutor


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def store(tmp_path):
    """每个测试获得独立的 Store (临时 DB + events.jsonl)。"""
    db_path = str(tmp_path / "test.db")
    events_path = str(tmp_path / "events.jsonl")
    s = Store(db_path, events_path)
    return s


@pytest.fixture
def executor(store):
    """CommandExecutor wrapping the test store."""
    return CommandExecutor(store)


def _make_node(**overrides) -> Node:
    """Helper: build a minimal Node with overrides."""
    defaults = dict(
        id="",
        title="Test Node",
        status="inbox",
        node_type="task",
    )
    defaults.update(overrides)
    return Node(**defaults)


# ===========================================================================
# Node CRUD
# ===========================================================================

class TestCreateNode:
    def test_creates_and_returns_node(self, store):
        with store.transaction():
            node = store.create_node(_make_node(title="Alpha"))
        assert node.id  # id was generated
        assert node.id.startswith("task-")
        assert len(node.id) == 9  # "task-" + 4 hex chars
        assert node.title == "Alpha"
        assert node.created_at != ""
        assert node.updated_at != ""

    def test_writes_audit_outbox(self, store):
        with store.transaction():
            node = store.create_node(_make_node(title="Audit"))
        rows = store._conn.execute(
            "SELECT event_json FROM audit_outbox WHERE flushed=0"
        ).fetchall()
        assert len(rows) >= 1
        event = json.loads(rows[0][0])
        assert event["type"] == "node_created"
        assert event["node_id"] == node.id

    def test_source_fields_persisted(self, store):
        with store.transaction():
            node = store.create_node(_make_node(
                title="External",
                source="github",
                source_id="GH-123",
                source_url="https://github.com/issue/123",
            ))
        fetched = store.get_node(node.id)
        assert fetched is not None
        assert fetched.source == "github"
        assert fetched.source_id == "GH-123"
        assert fetched.source_url == "https://github.com/issue/123"

    def test_id_prefix_by_type(self, store):
        with store.transaction():
            goal = store.create_node(_make_node(node_type="goal", title="G"))
            proj = store.create_node(_make_node(node_type="project", title="P"))
            mile = store.create_node(_make_node(node_type="milestone", title="M"))
        assert goal.id.startswith("goal-")
        assert proj.id.startswith("proj-")
        assert mile.id.startswith("mile-")

    def test_tags_persisted(self, store):
        with store.transaction():
            node = store.create_node(_make_node(title="Tagged", tags=["urgent", "v2"]))
        fetched = store.get_node(node.id)
        assert fetched is not None
        assert fetched.tags == ["urgent", "v2"]


class TestGetNode:
    def test_existing(self, store):
        with store.transaction():
            created = store.create_node(_make_node(title="Find Me"))
        found = store.get_node(created.id)
        assert found is not None
        assert found.title == "Find Me"

    def test_non_existing(self, store):
        assert store.get_node("no-such-id") is None


class TestUpdateNode:
    def test_updates_fields_and_timestamp(self, store):
        with store.transaction():
            node = store.create_node(_make_node(title="Before"))
        old_updated = node.updated_at
        with store.transaction():
            updated = store.update_node(node.id, {"title": "After"})
        assert updated.title == "After"
        assert updated.updated_at >= old_updated

    def test_source_synced_at(self, store):
        with store.transaction():
            node = store.create_node(_make_node(title="Sync"))
        now = datetime.now(timezone.utc).isoformat()
        with store.transaction():
            updated = store.update_node(node.id, {"source_synced_at": now})
        assert updated.source_synced_at == now

    def test_source_deleted(self, store):
        with store.transaction():
            node = store.create_node(_make_node(title="Del"))
        with store.transaction():
            updated = store.update_node(node.id, {"source_deleted": True})
        assert updated.source_deleted is True

    def test_needs_compression(self, store):
        with store.transaction():
            node = store.create_node(_make_node(title="Compress"))
        with store.transaction():
            updated = store.update_node(node.id, {"needs_compression": True})
        assert updated.needs_compression is True

    def test_tags_update(self, store):
        with store.transaction():
            node = store.create_node(_make_node(title="Tags"))
        with store.transaction():
            updated = store.update_node(node.id, {"tags": ["alpha", "beta"]})
        assert updated.tags == ["alpha", "beta"]


class TestListNodes:
    def _seed(self, store):
        """Create several nodes for list testing."""
        nodes = []
        with store.transaction():
            nodes.append(store.create_node(_make_node(
                title="A", status="active", node_type="task", source="github")))
            nodes.append(store.create_node(_make_node(
                title="B", status="inbox", node_type="goal", source="internal")))
            nodes.append(store.create_node(_make_node(
                title="C", status="active", node_type="task", source="github")))
        return nodes

    def test_filter_by_status(self, store):
        self._seed(store)
        result = store.list_nodes(filters={"status": "active"})
        assert len(result) == 2
        assert all(n.status == "active" for n in result)

    def test_filter_by_node_type(self, store):
        self._seed(store)
        result = store.list_nodes(filters={"node_type": "goal"})
        assert len(result) == 1
        assert result[0].title == "B"

    def test_filter_by_parent_id(self, store):
        with store.transaction():
            parent = store.create_node(_make_node(title="Parent"))
            child = store.create_node(_make_node(title="Child", parent_id=parent.id))
            store.create_node(_make_node(title="Other"))
        result = store.list_nodes(filters={"parent_id": parent.id})
        assert len(result) == 1
        assert result[0].id == child.id

    def test_filter_by_source(self, store):
        self._seed(store)
        result = store.list_nodes(filters={"source": "github"})
        assert len(result) == 2

    def test_pagination(self, store):
        with store.transaction():
            for i in range(5):
                store.create_node(_make_node(title=f"N{i}"))
        page1 = store.list_nodes(limit=2, offset=0)
        page2 = store.list_nodes(limit=2, offset=2)
        assert len(page1) == 2
        assert len(page2) == 2
        ids1 = {n.id for n in page1}
        ids2 = {n.id for n in page2}
        assert ids1.isdisjoint(ids2)


# ===========================================================================
# Edge CRUD
# ===========================================================================

class TestEdgeCrud:
    def _two_nodes(self, store):
        with store.transaction():
            a = store.create_node(_make_node(title="A"))
            b = store.create_node(_make_node(title="B"))
        return a, b

    def test_add_and_remove_edge(self, store):
        a, b = self._two_nodes(store)
        with store.transaction():
            edge = store.add_edge(Edge(source_id=a.id, target_id=b.id, edge_type="depends_on"))
        assert edge.source_id == a.id
        assert edge.edge_type == "depends_on"

        removed = store.remove_edge(a.id, b.id, "depends_on")
        assert removed is True

        removed_again = store.remove_edge(a.id, b.id, "depends_on")
        assert removed_again is False

    def test_get_edges_outgoing(self, store):
        a, b = self._two_nodes(store)
        with store.transaction():
            store.add_edge(Edge(source_id=a.id, target_id=b.id, edge_type="depends_on"))
        edges = store.get_edges(a.id, direction="outgoing")
        assert len(edges) == 1
        assert edges[0].target_id == b.id

    def test_get_edges_incoming(self, store):
        a, b = self._two_nodes(store)
        with store.transaction():
            store.add_edge(Edge(source_id=a.id, target_id=b.id, edge_type="depends_on"))
        edges = store.get_edges(b.id, direction="incoming")
        assert len(edges) == 1
        assert edges[0].source_id == a.id

    def test_get_edges_both(self, store):
        a, b = self._two_nodes(store)
        with store.transaction():
            c = store.create_node(_make_node(title="C"))
            store.add_edge(Edge(source_id=a.id, target_id=b.id, edge_type="depends_on"))
            store.add_edge(Edge(source_id=c.id, target_id=a.id, edge_type="depends_on"))
        edges = store.get_edges(a.id, direction="both")
        assert len(edges) == 2


# ===========================================================================
# Graph Queries
# ===========================================================================

class TestGraphQueries:
    def test_get_children_and_parent(self, store):
        with store.transaction():
            parent = store.create_node(_make_node(title="Parent"))
            c1 = store.create_node(_make_node(title="C1", parent_id=parent.id))
            c2 = store.create_node(_make_node(title="C2", parent_id=parent.id))
        children = store.get_children(parent.id)
        assert len(children) == 2
        child_ids = {c.id for c in children}
        assert c1.id in child_ids
        assert c2.id in child_ids

        p = store.get_parent(c1.id)
        assert p is not None
        assert p.id == parent.id

    def test_get_children_excludes_archived(self, store):
        with store.transaction():
            parent = store.create_node(_make_node(title="P"))
            alive = store.create_node(_make_node(title="Alive", parent_id=parent.id))
            archived = store.create_node(_make_node(title="Archived", parent_id=parent.id))
        with store.transaction():
            store.update_node(archived.id, {"archived_at": datetime.now(timezone.utc).isoformat()})

        children = store.get_children(parent.id, include_archived=False)
        assert len(children) == 1
        assert children[0].id == alive.id

        children_all = store.get_children(parent.id, include_archived=True)
        assert len(children_all) == 2

    def test_get_dependencies_and_dependents(self, store):
        with store.transaction():
            a = store.create_node(_make_node(title="A"))
            b = store.create_node(_make_node(title="B"))
            store.add_edge(Edge(source_id=a.id, target_id=b.id, edge_type="depends_on"))

        deps = store.get_dependencies(a.id)
        assert len(deps) == 1
        assert deps[0].id == b.id

        dependents = store.get_dependents(b.id)
        assert len(dependents) == 1
        assert dependents[0].id == a.id

    def test_get_siblings(self, store):
        with store.transaction():
            parent = store.create_node(_make_node(title="P"))
            s1 = store.create_node(_make_node(title="S1", parent_id=parent.id))
            s2 = store.create_node(_make_node(title="S2", parent_id=parent.id))
            s3 = store.create_node(_make_node(title="S3", parent_id=parent.id))

        siblings = store.get_siblings(s1.id)
        sib_ids = {s.id for s in siblings}
        assert s1.id not in sib_ids
        assert s2.id in sib_ids
        assert s3.id in sib_ids

    def test_get_ancestors_recursive(self, store):
        with store.transaction():
            grandpa = store.create_node(_make_node(title="GP", is_root=True))
            dad = store.create_node(_make_node(title="Dad", parent_id=grandpa.id))
            kid = store.create_node(_make_node(title="Kid", parent_id=dad.id))

        ancestors = store.get_ancestors(kid.id)
        assert dad.id in ancestors
        assert grandpa.id in ancestors
        assert kid.id not in ancestors

    def test_get_descendants_recursive(self, store):
        with store.transaction():
            root = store.create_node(_make_node(title="Root", is_root=True))
            child = store.create_node(_make_node(title="Child", parent_id=root.id))
            grandchild = store.create_node(_make_node(title="GC", parent_id=child.id))

        descendants = store.get_descendants(root.id)
        assert child.id in descendants
        assert grandchild.id in descendants
        assert root.id not in descendants


# ===========================================================================
# Transaction
# ===========================================================================

class TestTransaction:
    def test_commit_on_success(self, store):
        with store.transaction():
            store.create_node(_make_node(title="Committed"))
        nodes = store.list_nodes()
        assert len(nodes) == 1
        assert nodes[0].title == "Committed"

    def test_rollback_on_exception(self, store):
        with pytest.raises(ValueError):
            with store.transaction():
                store.create_node(_make_node(title="Doomed"))
                raise ValueError("boom")
        # Node should NOT be persisted
        nodes = store.list_nodes()
        assert len(nodes) == 0


# ===========================================================================
# Audit & Events
# ===========================================================================

class TestAudit:
    def test_write_event_to_outbox(self, store):
        with store.transaction():
            store.write_event({"type": "test", "data": 42})
        rows = store._conn.execute(
            "SELECT event_json, flushed FROM audit_outbox"
        ).fetchall()
        assert len(rows) == 1
        assert json.loads(rows[0][0])["type"] == "test"
        assert rows[0][1] == 0

    def test_flush_events_to_jsonl(self, store):
        with store.transaction():
            store.write_event({"type": "evt1"})
            store.write_event({"type": "evt2"})
        count = store.flush_events()
        assert count == 2

        # events.jsonl should have 2 lines
        with open(store._events_path) as f:
            lines = f.readlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["type"] == "evt1"

        # outbox marked flushed
        unflushed = store._conn.execute(
            "SELECT COUNT(*) FROM audit_outbox WHERE flushed=0"
        ).fetchone()[0]
        assert unflushed == 0

    def test_flush_idempotent(self, store):
        with store.transaction():
            store.write_event({"type": "once"})
        assert store.flush_events() == 1
        assert store.flush_events() == 0  # nothing new


# ===========================================================================
# Session State
# ===========================================================================

class TestSessionState:
    def test_set_and_get(self, store):
        with store.transaction():
            store.set_session("focus", {"node_id": "task-abc1"})
        result = store.get_session("focus")
        assert result == {"node_id": "task-abc1"}

    def test_get_missing(self, store):
        assert store.get_session("nope") is None

    def test_overwrite(self, store):
        with store.transaction():
            store.set_session("k", {"v": 1})
        with store.transaction():
            store.set_session("k", {"v": 2})
        assert store.get_session("k") == {"v": 2}


# ===========================================================================
# Idempotency (CommandExecutor)
# ===========================================================================

class TestIdempotency:
    def test_cached_result_returned(self, store, executor):
        """Same command_id returns cached ToolResult."""
        result = ToolResult(
            success=True,
            command_id="cmd-001",
            data={"node_id": "task-abcd"},
            affected_nodes=["task-abcd"],
        )
        # Manually insert into recent_commands
        with store.transaction():
            executor.save_command_result("cmd-001", "create_node", result)

        # Execute should return cached result
        cached = executor.execute("cmd-001", "create_node", {})
        assert cached.success is True
        assert cached.command_id == "cmd-001"
        assert cached.data == {"node_id": "task-abcd"}

    def test_unknown_command_raises(self, executor):
        """Non-cached command_id raises NotImplementedError (no tool routing yet)."""
        with pytest.raises(NotImplementedError):
            executor.execute("cmd-new", "create_node", {})
