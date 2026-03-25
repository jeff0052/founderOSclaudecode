"""Tests for activate_workbench — AI task preparation workspace."""

from __future__ import annotations

import os
import pytest
from fpms.spine import SpineEngine


@pytest.fixture
def engine(tmp_path):
    return SpineEngine(
        db_path=str(tmp_path / "test.db"),
        events_path=str(tmp_path / "events.jsonl"),
        narratives_dir=str(tmp_path / "narratives"),
    )


def _create(engine, title, parent_id=None, is_root=False, summary=None, why=None, **kw):
    params = {"title": title, "is_root": is_root}
    if parent_id: params["parent_id"] = parent_id
    if summary: params["summary"] = summary
    if why: params["why"] = why
    params.update(kw)
    return engine.execute_tool("create_node", params).data["id"]


class TestActivateWorkbench:

    def test_returns_required_keys(self, engine):
        nid = _create(engine, "Payment", is_root=True, summary="Add Stripe")
        engine.execute_tool("update_status", {"node_id": nid, "new_status": "active"})
        wb = engine.activate_workbench(nid, role="execution")
        for key in ("goal", "knowledge", "context", "subtasks", "suggested_next", "role_prompt", "token_budget"):
            assert key in wb
        assert wb["goal"] == "Payment"

    def test_subtasks_sorted_by_dependency(self, engine):
        pid = _create(engine, "Parent", is_root=True, summary="P")
        engine.execute_tool("update_status", {"node_id": pid, "new_status": "active"})
        a = _create(engine, "Step A", parent_id=pid, summary="A")
        b = _create(engine, "Step B", parent_id=pid, summary="B")
        engine.execute_tool("add_dependency", {"source_id": b, "target_id": a})
        wb = engine.activate_workbench(pid, role="execution")
        ids = [s["id"] for s in wb["subtasks"]]
        assert ids.index(a) < ids.index(b)

    def test_suggested_next_skips_done(self, engine):
        pid = _create(engine, "Big", is_root=True, summary="B")
        engine.execute_tool("update_status", {"node_id": pid, "new_status": "active"})
        a = _create(engine, "Done Step", parent_id=pid, summary="done")
        engine.execute_tool("update_status", {"node_id": a, "new_status": "active"})
        engine.execute_tool("update_status", {"node_id": a, "new_status": "done"})
        b = _create(engine, "Next Step", parent_id=pid, summary="next")
        wb = engine.activate_workbench(pid, role="execution")
        assert wb["suggested_next"]["id"] == b

    def test_no_subtasks(self, engine):
        nid = _create(engine, "Leaf", is_root=True, summary="L")
        engine.execute_tool("update_status", {"node_id": nid, "new_status": "active"})
        wb = engine.activate_workbench(nid, role="execution")
        assert wb["subtasks"] == []
        assert wb["suggested_next"] is None

    def test_invalid_node_raises(self, engine):
        with pytest.raises(ValueError, match="not found"):
            engine.activate_workbench("nonexistent-9999", role="execution")

    def test_strategy_returns_decisions(self, engine):
        nid = _create(engine, "Dec", is_root=True, summary="D")
        engine.execute_tool("update_status", {"node_id": nid, "new_status": "active"})
        engine.execute_tool("append_log", {
            "node_id": nid, "content": "Chose Stripe", "category": "decision",
        })
        wb = engine.activate_workbench(nid, role="strategy")
        assert "decisions" in wb
        assert len(wb["decisions"]) > 0
        assert "Chose Stripe" in wb["decisions"][0]["content"]

    def test_review_returns_risks(self, engine):
        nid = _create(engine, "Risk", is_root=True, summary="R")
        engine.execute_tool("update_status", {"node_id": nid, "new_status": "active"})
        engine.execute_tool("append_log", {
            "node_id": nid, "content": "PCI compliance required", "category": "risk",
        })
        wb = engine.activate_workbench(nid, role="review")
        assert "risks" in wb
        assert "PCI compliance" in wb["risks"][0]["content"]

    def test_execution_token_budget(self, engine):
        nid = _create(engine, "Exec", is_root=True, summary="E")
        engine.execute_tool("update_status", {"node_id": nid, "new_status": "active"})
        wb = engine.activate_workbench(nid, role="execution")
        assert wb["token_budget"]["total"] == 8000
        assert wb["token_budget"]["l0"] == 0

    def test_role_prompt_loaded(self, engine):
        nid = _create(engine, "Prompt", is_root=True, summary="P")
        engine.execute_tool("update_status", {"node_id": nid, "new_status": "active"})
        wb = engine.activate_workbench(nid, role="strategy")
        assert "中书省" in wb["role_prompt"]

    def test_knowledge_included(self, engine):
        """Workbench includes knowledge docs."""
        from fpms.spine import knowledge as knowledge_mod
        nid = _create(engine, "WithKnowledge", is_root=True, summary="K")
        engine.execute_tool("update_status", {"node_id": nid, "new_status": "active"})
        knowledge_mod.set_knowledge(engine._knowledge_dir, nid, "overview", "Project overview content")
        wb = engine.activate_workbench(nid, role="execution")
        assert wb["knowledge"]["overview"] == "Project overview content"
