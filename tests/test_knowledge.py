"""Tests for fpms.spine.knowledge — per-node Markdown doc storage with inheritance."""

from __future__ import annotations

import os

import pytest

from fpms.spine.knowledge import (
    delete_knowledge,
    get_knowledge,
    list_knowledge,
    set_knowledge,
)


@pytest.fixture
def kdir(tmp_path):
    """Return a temporary knowledge directory path (not yet created)."""
    return str(tmp_path / "knowledge")


def _make_store_with_tree(tmp_path):
    from fpms.spine.models import Node
    from fpms.spine.store import Store

    store = Store(str(tmp_path / "test.db"), str(tmp_path / "events.jsonl"))
    # Create: proj-aa (root) -> mile-bb -> task-cc
    with store.transaction():
        store._create_node_inner(
            Node(id="proj-aa", title="Project", status="active", node_type="project", is_root=True)
        )
    with store.transaction():
        store._create_node_inner(
            Node(id="mile-bb", title="Milestone", status="active", node_type="milestone", parent_id="proj-aa")
        )
    with store.transaction():
        store._create_node_inner(
            Node(id="task-cc", title="Task", status="active", node_type="task", parent_id="mile-bb")
        )
    return store


# ── set_knowledge ─────────────────────────────────────────────────────────


class TestSetKnowledge:
    def test_write_creates_file(self, kdir):
        set_knowledge(kdir, "node-1", "overview", "# Overview\nHello world")
        filepath = os.path.join(kdir, "node-1", "overview.md")
        assert os.path.isfile(filepath)
        assert "Hello world" in open(filepath).read()

    def test_overwrite_replaces_content(self, kdir):
        set_knowledge(kdir, "node-1", "overview", "Version 1")
        set_knowledge(kdir, "node-1", "overview", "Version 2")
        filepath = os.path.join(kdir, "node-1", "overview.md")
        content = open(filepath).read()
        assert "Version 2" in content
        assert "Version 1" not in content

    def test_custom_doc_type(self, kdir):
        set_knowledge(kdir, "node-2", "competitive_analysis", "Competitors: A, B, C")
        filepath = os.path.join(kdir, "node-2", "competitive_analysis.md")
        assert os.path.isfile(filepath)
        assert "Competitors" in open(filepath).read()


# ── get_knowledge ─────────────────────────────────────────────────────────


class TestGetKnowledge:
    def test_get_single_doc(self, kdir):
        set_knowledge(kdir, "node-1", "requirements", "# Requirements\nMust do X")
        result = get_knowledge(kdir, "node-1", doc_type="requirements")
        assert isinstance(result, str)
        assert "Must do X" in result

    def test_get_all_docs(self, kdir):
        set_knowledge(kdir, "node-1", "overview", "Overview content")
        set_knowledge(kdir, "node-1", "architecture", "Architecture content")
        result = get_knowledge(kdir, "node-1")
        assert isinstance(result, dict)
        assert "overview" in result
        assert "architecture" in result
        assert "Overview content" in result["overview"]
        assert "Architecture content" in result["architecture"]

    def test_get_nonexistent_returns_none(self, kdir):
        result = get_knowledge(kdir, "node-missing", doc_type="overview")
        assert result is None

    def test_get_all_empty_returns_empty_dict(self, kdir):
        result = get_knowledge(kdir, "node-empty")
        assert result == {}


# ── inheritance ────────────────────────────────────────────────────────────


class TestKnowledgeInheritance:
    def test_child_inherits_parent_knowledge(self, tmp_path):
        store = _make_store_with_tree(tmp_path)
        kdir = str(tmp_path / "knowledge")

        # Set doc on project (grandparent of task-cc, parent of mile-bb)
        set_knowledge(kdir, "proj-aa", "overview", "Project overview")

        # milestone has no own overview — should inherit from proj-aa
        result = get_knowledge(kdir, "mile-bb", doc_type="overview", store=store, inherit=True)
        assert result == "Project overview"

    def test_child_overrides_parent_knowledge(self, tmp_path):
        store = _make_store_with_tree(tmp_path)
        kdir = str(tmp_path / "knowledge")

        set_knowledge(kdir, "proj-aa", "overview", "Project overview")
        set_knowledge(kdir, "mile-bb", "overview", "Milestone overview")

        result = get_knowledge(kdir, "mile-bb", doc_type="overview", store=store, inherit=True)
        assert result == "Milestone overview"

    def test_deep_inheritance_task_from_grandparent(self, tmp_path):
        store = _make_store_with_tree(tmp_path)
        kdir = str(tmp_path / "knowledge")

        # Only project has the doc — task should find it 2 levels up
        set_knowledge(kdir, "proj-aa", "architecture", "Arch from root")

        result = get_knowledge(kdir, "task-cc", doc_type="architecture", store=store, inherit=True)
        assert result == "Arch from root"

    def test_no_inherit_returns_only_own(self, tmp_path):
        store = _make_store_with_tree(tmp_path)
        kdir = str(tmp_path / "knowledge")

        set_knowledge(kdir, "proj-aa", "overview", "Project overview")

        # inherit=False — milestone has no own doc, should return None
        result = get_knowledge(kdir, "mile-bb", doc_type="overview", store=store, inherit=False)
        assert result is None

    def test_inherit_get_all_merges_parent_docs(self, tmp_path):
        store = _make_store_with_tree(tmp_path)
        kdir = str(tmp_path / "knowledge")

        set_knowledge(kdir, "proj-aa", "overview", "Parent overview")
        set_knowledge(kdir, "proj-aa", "requirements", "Parent requirements")
        set_knowledge(kdir, "mile-bb", "overview", "Child overview")  # overrides parent

        result = get_knowledge(kdir, "mile-bb", store=store, inherit=True)
        assert isinstance(result, dict)
        # own overview overrides parent
        assert result["overview"] == "Child overview"
        # requirements inherited from parent
        assert result["requirements"] == "Parent requirements"


# ── delete_knowledge ──────────────────────────────────────────────────────


class TestDeleteKnowledge:
    def test_delete_removes_file(self, kdir):
        set_knowledge(kdir, "node-1", "overview", "To be deleted")
        filepath = os.path.join(kdir, "node-1", "overview.md")
        assert os.path.isfile(filepath)

        delete_knowledge(kdir, "node-1", "overview")
        assert not os.path.isfile(filepath)

    def test_delete_nonexistent_no_error(self, kdir):
        # Should not raise even if file doesn't exist
        delete_knowledge(kdir, "node-ghost", "overview")


# ── list_knowledge ────────────────────────────────────────────────────────


class TestListKnowledge:
    def test_list_returns_doc_types(self, kdir):
        set_knowledge(kdir, "node-1", "overview", "Overview")
        set_knowledge(kdir, "node-1", "requirements", "Requirements")
        set_knowledge(kdir, "node-1", "competitive_analysis", "Competitive")

        result = list_knowledge(kdir, "node-1")
        assert isinstance(result, list)
        assert set(result) == {"overview", "requirements", "competitive_analysis"}

    def test_list_empty_node(self, kdir):
        result = list_knowledge(kdir, "node-empty")
        assert result == []
