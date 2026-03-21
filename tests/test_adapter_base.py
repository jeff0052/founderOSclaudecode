# tests/test_adapter_base.py
"""Tests for Adapter data structures: NodeSnapshot, SourceEvent."""

import pytest
from fpms.spine.models import NodeSnapshot, SourceEvent


class TestNodeSnapshot:
    def test_create_minimal(self):
        snap = NodeSnapshot(
            source="github",
            source_id="octocat/repo#42",
            title="Fix login bug",
            status="active",
        )
        assert snap.source == "github"
        assert snap.source_id == "octocat/repo#42"
        assert snap.title == "Fix login bug"
        assert snap.status == "active"
        assert snap.source_url is None
        assert snap.assignee is None
        assert snap.updated_at is None
        assert snap.labels == []
        assert snap.raw == {}

    def test_create_full(self):
        snap = NodeSnapshot(
            source="github",
            source_id="octocat/repo#42",
            title="Fix login bug",
            status="active",
            source_url="https://github.com/octocat/repo/issues/42",
            assignee="jeff",
            updated_at="2026-03-20T10:00:00+08:00",
            labels=["bug", "urgent"],
            raw={"number": 42},
        )
        assert snap.assignee == "jeff"
        assert snap.labels == ["bug", "urgent"]
        assert snap.raw == {"number": 42}

    def test_snapshot_is_dataclass(self):
        from dataclasses import is_dataclass
        assert is_dataclass(NodeSnapshot)


class TestSourceEvent:
    def test_create_status_change(self):
        evt = SourceEvent(
            source="github",
            source_id="octocat/repo#42",
            event_type="status_change",
            timestamp="2026-03-20T10:00:00Z",
            data={"old": "open", "new": "closed"},
        )
        assert evt.event_type == "status_change"
        assert evt.data["old"] == "open"

    def test_create_comment(self):
        evt = SourceEvent(
            source="github",
            source_id="octocat/repo#42",
            event_type="comment",
            timestamp="2026-03-20T10:00:00Z",
            data={"body": "Working on this"},
        )
        assert evt.event_type == "comment"

    def test_event_is_dataclass(self):
        from dataclasses import is_dataclass
        assert is_dataclass(SourceEvent)


from fpms.spine.adapters.base import BaseAdapter


class TestBaseAdapter:
    def test_cannot_instantiate(self):
        with pytest.raises(TypeError):
            BaseAdapter()

    def test_has_required_methods(self):
        import inspect
        methods = {name for name, _ in inspect.getmembers(BaseAdapter, predicate=inspect.isfunction)}
        assert "sync_node" in methods
        assert "list_updates" in methods
        assert "write_comment" in methods
        assert "search" in methods

    def test_concrete_subclass_must_implement_required(self):
        class Incomplete(BaseAdapter):
            pass
        with pytest.raises(TypeError):
            Incomplete()

    def test_concrete_subclass_with_required_methods(self):
        class Complete(BaseAdapter):
            @property
            def source_name(self) -> str:
                return "test"
            def sync_node(self, source_id):
                return None
            def list_updates(self, since=None):
                return []

        adapter = Complete()
        assert adapter.source_name == "test"
        assert adapter.sync_node("x") is None
        assert adapter.list_updates() == []

    def test_write_comment_default_not_implemented(self):
        class Minimal(BaseAdapter):
            @property
            def source_name(self) -> str:
                return "test"
            def sync_node(self, source_id):
                return None
            def list_updates(self, since=None):
                return []

        adapter = Minimal()
        with pytest.raises(NotImplementedError):
            adapter.write_comment("id", "text")
        with pytest.raises(NotImplementedError):
            adapter.search("query")
