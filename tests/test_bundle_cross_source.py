"""Tests for cross-source context loading in BundleAssembler."""

import pytest
import os
import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

from fpms.spine.store import Store
from fpms.spine.bundle import BundleAssembler
from fpms.spine.models import Node, NodeSnapshot
from fpms.spine.adapters.registry import AdapterRegistry
from fpms.spine.adapters.base import BaseAdapter


class _MockGitHubAdapter(BaseAdapter):
    def __init__(self, snapshots=None):
        self._snapshots = snapshots or {}

    @property
    def source_name(self) -> str:
        return "github"

    def sync_node(self, source_id):
        return self._snapshots.get(source_id)

    def list_updates(self, since=None):
        return []


@pytest.fixture
def tmp_env(tmp_path):
    db_path = str(tmp_path / "test.db")
    events_path = str(tmp_path / "events.jsonl")
    narratives_dir = str(tmp_path / "narratives")
    os.makedirs(narratives_dir, exist_ok=True)
    store = Store(db_path, events_path)
    return store, narratives_dir, tmp_path


def _create_github_node(store, node_id="task-gh01", source_id="octocat/repo#42"):
    node = Node(
        id=node_id,
        title="Old title from last sync",
        status="active",
        node_type="task",
        is_root=True,
        source="github",
        source_id=source_id,
        source_url="https://github.com/octocat/repo/issues/42",
    )
    store.create_node(node)
    return node


class TestCrossSourceL2:
    def test_l2_shows_synced_title_when_adapter_available(self, tmp_env):
        store, narratives_dir, tmp_path = tmp_env
        node = _create_github_node(store)

        adapter = _MockGitHubAdapter(snapshots={
            "octocat/repo#42": NodeSnapshot(
                source="github", source_id="octocat/repo#42",
                title="New title from GitHub", status="active", assignee="jeff",
            ),
        })

        registry = AdapterRegistry()
        registry.register(adapter)

        assembler = BundleAssembler(
            store=store, adapter_registry=registry, narratives_dir=narratives_dir,
        )

        bundle = assembler.assemble(focus_node_id=node.id)
        assert "New title from GitHub" in bundle.l2_focus
        assert "github" in bundle.l2_focus.lower() or "octocat/repo#42" in bundle.l2_focus

    def test_l2_uses_cache_when_adapter_fails(self, tmp_env):
        store, narratives_dir, tmp_path = tmp_env
        node = _create_github_node(store)

        adapter = _MockGitHubAdapter()
        adapter.sync_node = MagicMock(side_effect=ConnectionError("offline"))

        registry = AdapterRegistry()
        registry.register(adapter)

        assembler = BundleAssembler(
            store=store, adapter_registry=registry, narratives_dir=narratives_dir,
        )

        bundle = assembler.assemble(focus_node_id=node.id)
        assert bundle.l2_focus is not None
        assert "Old title from last sync" in bundle.l2_focus

    def test_l2_marks_stale_data(self, tmp_env):
        store, narratives_dir, tmp_path = tmp_env
        node = _create_github_node(store)

        adapter = _MockGitHubAdapter()
        adapter.sync_node = MagicMock(side_effect=ConnectionError("offline"))

        registry = AdapterRegistry()
        registry.register(adapter)

        assembler = BundleAssembler(
            store=store, adapter_registry=registry, narratives_dir=narratives_dir,
        )

        bundle = assembler.assemble(focus_node_id=node.id)
        assert "过时" in bundle.l2_focus or "stale" in bundle.l2_focus.lower()

    def test_l2_internal_node_unaffected(self, tmp_env):
        store, narratives_dir, tmp_path = tmp_env

        node = Node(
            id="task-int1", title="Local task",
            status="active", node_type="task", is_root=True,
            source="internal",
        )
        store.create_node(node)

        registry = AdapterRegistry()

        assembler = BundleAssembler(
            store=store, adapter_registry=registry, narratives_dir=narratives_dir,
        )

        bundle = assembler.assemble(focus_node_id=node.id)
        assert "Local task" in bundle.l2_focus

    def test_l2_no_registry_still_works(self, tmp_env):
        store, narratives_dir, tmp_path = tmp_env

        node = Node(
            id="task-int2", title="No registry task",
            status="active", node_type="task", is_root=True,
        )
        store.create_node(node)

        assembler = BundleAssembler(store=store, narratives_dir=narratives_dir)

        bundle = assembler.assemble(focus_node_id=node.id)
        assert "No registry task" in bundle.l2_focus

    def test_sync_updates_local_node_fields(self, tmp_env):
        store, narratives_dir, tmp_path = tmp_env
        node = _create_github_node(store)

        adapter = _MockGitHubAdapter(snapshots={
            "octocat/repo#42": NodeSnapshot(
                source="github", source_id="octocat/repo#42",
                title="Updated title", status="done", assignee="alice",
                updated_at="2026-03-21T10:00:00Z",
            ),
        })

        registry = AdapterRegistry()
        registry.register(adapter)

        assembler = BundleAssembler(
            store=store, adapter_registry=registry, narratives_dir=narratives_dir,
        )

        assembler.assemble(focus_node_id=node.id)

        updated = store.get_node(node.id)
        assert updated.title == "Updated title"
        assert updated.status == "done"


class TestAssemblyTraceSyncStatus:
    def test_trace_includes_sync_info(self, tmp_env):
        store, narratives_dir, tmp_path = tmp_env
        node = _create_github_node(store)

        adapter = _MockGitHubAdapter(snapshots={
            "octocat/repo#42": NodeSnapshot(
                source="github", source_id="octocat/repo#42",
                title="Synced", status="active",
            ),
        })

        registry = AdapterRegistry()
        registry.register(adapter)

        assembler = BundleAssembler(
            store=store, adapter_registry=registry, narratives_dir=narratives_dir,
        )

        assembler.assemble(focus_node_id=node.id)

        trace_path = os.path.join(assembler._db_dir, "assembly_traces.jsonl")
        assert os.path.exists(trace_path)
        with open(trace_path) as f:
            lines = f.readlines()
        last_trace = json.loads(lines[-1])
        assert "sync_status" in last_trace
