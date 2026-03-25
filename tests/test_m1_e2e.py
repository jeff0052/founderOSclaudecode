"""M1 Integration Tests — end-to-end GitHub adapter flow."""

import pytest
import os
from datetime import datetime, timezone
from unittest.mock import MagicMock

from fpms.spine import SpineEngine
from fpms.spine.models import NodeSnapshot, SourceEvent
from fpms.spine.adapters.registry import AdapterRegistry
from fpms.spine.adapters.base import BaseAdapter


class _MockGitHubAdapter(BaseAdapter):
    def __init__(self, snapshots=None, events=None):
        self._snapshots = snapshots or {}
        self._events = events or []
        self.sync_called = []

    @property
    def source_name(self):
        return "github"

    def sync_node(self, source_id):
        self.sync_called.append(source_id)
        return self._snapshots.get(source_id)

    def list_updates(self, since=None):
        if since:
            return [e for e in self._events if e.timestamp > since.isoformat()]
        return self._events


@pytest.fixture
def engine_with_adapter(tmp_path):
    db_path = str(tmp_path / "test.db")
    events_path = str(tmp_path / "events.jsonl")
    narratives_dir = str(tmp_path / "narratives")

    engine = SpineEngine(
        db_path=db_path,
        events_path=events_path,
        narratives_dir=narratives_dir,
    )

    adapter = _MockGitHubAdapter(snapshots={
        "octocat/repo#42": NodeSnapshot(
            source="github",
            source_id="octocat/repo#42",
            title="Fix login from GitHub",
            status="active",
            assignee="jeff",
        ),
    })

    registry = AdapterRegistry()
    registry.register(adapter)
    engine.set_adapter_registry(registry)

    return engine, adapter


class TestM1CreateAndSync:
    def test_create_github_node_and_get_context(self, engine_with_adapter):
        engine, adapter = engine_with_adapter

        result = engine.execute_tool("create_node", {
            "title": "Fix login bug",
            "node_type": "task",
            "is_root": True,
            "source": "github",
            "source_id": "octocat/repo#42",
            "source_url": "https://github.com/octocat/repo/issues/42",
        })
        assert result.success
        node_id = result.data["id"]

        bundle = engine.get_context_bundle(user_focus=node_id)
        assert "Fix login from GitHub" in bundle.l2_focus

    def test_sync_source_updates_node(self, engine_with_adapter):
        engine, adapter = engine_with_adapter

        result = engine.execute_tool("create_node", {
            "title": "Old title",
            "node_type": "task",
            "is_root": True,
            "source": "github",
            "source_id": "octocat/repo#42",
        })
        node_id = result.data["id"]

        updated = engine.sync_source(node_id)
        assert updated.title == "Fix login from GitHub"
        assert updated.source_synced_at is not None


class TestM1MixedTree:
    def test_mixed_local_and_github_rollup(self, engine_with_adapter):
        engine, adapter = engine_with_adapter

        root_result = engine.execute_tool("create_node", {
            "title": "Q1 Launch",
            "node_type": "goal",
            "is_root": True,
            "summary": "Launch by end of Q1",
        })
        root_id = root_result.data["id"]

        engine.execute_tool("update_status", {
            "node_id": root_id,
            "new_status": "active",
        })

        gh_result = engine.execute_tool("create_node", {
            "title": "Fix login bug (from GH)",
            "node_type": "task",
            "parent_id": root_id,
            "source": "github",
            "source_id": "octocat/repo#42",
            "summary": "Linked to GitHub issue",
        })
        gh_id = gh_result.data["id"]

        engine.execute_tool("update_status", {
            "node_id": gh_id,
            "new_status": "active",
        })

        local_result = engine.execute_tool("create_node", {
            "title": "Write tests",
            "node_type": "task",
            "parent_id": root_id,
            "summary": "Unit tests for all modules",
        })
        local_id = local_result.data["id"]

        engine.execute_tool("update_status", {
            "node_id": local_id,
            "new_status": "active",
        })

        bundle = engine.get_context_bundle(user_focus=root_id)
        assert root_id in (bundle.focus_node_id or "")


class TestM1SyncAll:
    def test_sync_all_updates_multiple_nodes(self, engine_with_adapter):
        engine, adapter = engine_with_adapter

        r1 = engine.execute_tool("create_node", {
            "title": "Issue 42", "node_type": "task", "is_root": True,
            "source": "github", "source_id": "octocat/repo#42",
        })
        r2 = engine.execute_tool("create_node", {
            "title": "Issue 99", "node_type": "task", "is_root": True,
            "source": "github", "source_id": "octocat/repo#99",
        })

        adapter._snapshots["octocat/repo#99"] = NodeSnapshot(
            source="github", source_id="octocat/repo#99",
            title="Updated 99", status="done",
        )

        count = engine.sync_all()
        assert count >= 1

    def test_sync_all_no_registry_returns_zero(self, tmp_path):
        engine = SpineEngine(
            db_path=str(tmp_path / "test.db"),
            events_path=str(tmp_path / "events.jsonl"),
            narratives_dir=str(tmp_path / "narratives"),
        )
        assert engine.sync_all() == 0


class TestM1SourceDeleted:
    def test_deleted_node_marked_in_db(self, engine_with_adapter):
        engine, adapter = engine_with_adapter
        adapter._snapshots.clear()

        result = engine.execute_tool("create_node", {
            "title": "Will be deleted", "node_type": "task", "is_root": True,
            "source": "github", "source_id": "octocat/repo#deleted",
        })
        node_id = result.data["id"]

        updated = engine.sync_source(node_id)
        assert updated.source_deleted is True

    def test_deleted_node_still_renders_in_l2(self, engine_with_adapter):
        engine, adapter = engine_with_adapter
        adapter._snapshots.clear()

        result = engine.execute_tool("create_node", {
            "title": "Deleted externally", "node_type": "task", "is_root": True,
            "source": "github", "source_id": "octocat/repo#gone",
        })
        node_id = result.data["id"]

        bundle = engine.get_context_bundle(user_focus=node_id)
        assert "Deleted externally" in bundle.l2_focus


class TestM1SourceIdGuard:
    def test_sync_source_without_source_id_raises(self, engine_with_adapter):
        engine, adapter = engine_with_adapter

        result = engine.execute_tool("create_node", {
            "title": "No source_id", "node_type": "task", "is_root": True,
            "source": "github",
        })
        node_id = result.data["id"]

        with pytest.raises(ValueError, match="no source_id"):
            engine.sync_source(node_id)


class TestM1OfflineDegradation:
    def test_adapter_failure_uses_cache(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        events_path = str(tmp_path / "events.jsonl")
        narratives_dir = str(tmp_path / "narratives")

        engine = SpineEngine(
            db_path=db_path,
            events_path=events_path,
            narratives_dir=narratives_dir,
        )

        failing_adapter = _MockGitHubAdapter()
        failing_adapter.sync_node = MagicMock(side_effect=ConnectionError("offline"))

        registry = AdapterRegistry()
        registry.register(failing_adapter)
        engine.set_adapter_registry(registry)

        result = engine.execute_tool("create_node", {
            "title": "Cached title",
            "node_type": "task",
            "is_root": True,
            "source": "github",
            "source_id": "octocat/repo#99",
        })
        node_id = result.data["id"]

        bundle = engine.get_context_bundle(user_focus=node_id)
        assert bundle.l2_focus is not None
        assert "Cached title" in bundle.l2_focus
