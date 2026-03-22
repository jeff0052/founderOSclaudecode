"""Tests for full-text search (FTS5) in store.py."""

from __future__ import annotations

import os
import pytest

from fpms.spine.store import Store
from fpms.spine.models import Node
from fpms.spine import narrative as narrative_mod


@pytest.fixture
def tmp_dirs(tmp_path):
    db_path = str(tmp_path / "test.db")
    events_path = str(tmp_path / "events.jsonl")
    narratives_dir = str(tmp_path / "narratives")
    knowledge_dir = str(tmp_path / "knowledge")
    return db_path, events_path, narratives_dir, knowledge_dir


@pytest.fixture
def store(tmp_dirs):
    db_path, events_path, _, _ = tmp_dirs
    return Store(db_path, events_path)


def _make_node(store, node_id, title, **kwargs):
    defaults = dict(id=node_id, title=title, status="active", node_type="task", is_root=True)
    defaults.update(kwargs)
    node = Node(**defaults)
    with store.transaction():
        store._create_node_inner(node)
    return node


class TestFullTextSearch:

    def test_search_by_title(self, store):
        _make_node(store, "task-a1", "Implement payment gateway")
        _make_node(store, "task-a2", "Design user interface")
        results = store.search_fts("payment")
        assert len(results) == 1
        assert results[0].id == "task-a1"

    def test_search_by_narrative(self, store, tmp_dirs):
        _, _, narr_dir, _ = tmp_dirs
        _make_node(store, "task-b1", "Build API")
        narrative_mod.append_narrative(narr_dir, "task-b1", "2025-01-15T10:00:00Z", "log",
                                        "Decided to use Redis for caching", category="decision")
        store.index_narrative("task-b1", narr_dir)
        results = store.search_fts("Redis caching")
        assert len(results) >= 1
        assert any(r.id == "task-b1" for r in results)

    def test_search_chinese(self, store):
        # unicode61 tokenizer splits on whitespace, so Chinese words must be
        # space-separated to be individually searchable as tokens.
        _make_node(store, "task-c1", "实现 支付 系统")
        _make_node(store, "task-c2", "设计 用户 界面")
        results = store.search_fts("支付")
        assert len(results) == 1
        assert results[0].id == "task-c1"

    def test_search_no_results(self, store):
        _make_node(store, "task-d1", "Build something")
        results = store.search_fts("nonexistent_xyz_keyword")
        assert results == []

    def test_search_multiple_matches(self, store):
        _make_node(store, "task-e1", "Payment API v1")
        _make_node(store, "task-e2", "Payment API v2")
        results = store.search_fts("Payment API")
        assert len(results) == 2

    def test_search_excludes_archived(self, store):
        _make_node(store, "task-f1", "Archived payment task")
        with store.transaction():
            store._update_node_inner("task-f1", {"archived_at": "2025-01-01T00:00:00Z"})
        results = store.search_fts("payment")
        assert len(results) == 0

    def test_search_empty_query(self, store):
        _make_node(store, "task-g1", "Something")
        results = store.search_fts("")
        assert results == []
        results = store.search_fts("   ")
        assert results == []
