"""Tests for FTS auto-indexing when narrative/knowledge changes."""
import os
import tempfile
import pytest
from fpms.spine import SpineEngine


@pytest.fixture
def engine():
    tmp = tempfile.mkdtemp()
    e = SpineEngine(
        db_path=os.path.join(tmp, "test.db"),
        events_path=os.path.join(tmp, "events.jsonl"),
        narratives_dir=os.path.join(tmp, "narratives"),
    )
    return e


class TestFTSAutoIndexNarrative:
    def test_append_log_indexes_narrative_for_search(self, engine):
        """After append_log, the content should be findable via search_nodes query."""
        result = engine.execute_tool("create_node", {
            "title": "Payment System", "is_root": True, "node_type": "project",
        })
        node_id = result.data["id"]

        engine.execute_tool("append_log", {
            "node_id": node_id,
            "content": "决策：选择 Stripe 作为支付网关",
            "category": "decision",
        })

        result = engine.execute_tool("search_nodes", {"query": "Stripe 支付网关"})
        assert result.success
        found_ids = [n["id"] for n in result.data["nodes"]]
        assert node_id in found_ids

    def test_multiple_append_logs_all_searchable(self, engine):
        """Multiple append_log calls should all be searchable."""
        result = engine.execute_tool("create_node", {
            "title": "Backend API", "is_root": True,
        })
        node_id = result.data["id"]

        engine.execute_tool("append_log", {
            "node_id": node_id, "content": "使用 Redis 做缓存层",
            "category": "technical",
        })
        engine.execute_tool("append_log", {
            "node_id": node_id, "content": "性能测试显示延迟降低 40%",
            "category": "progress",
        })

        result = engine.execute_tool("search_nodes", {"query": "Redis 缓存"})
        assert node_id in [n["id"] for n in result.data["nodes"]]

        result = engine.execute_tool("search_nodes", {"query": "性能测试 延迟"})
        assert node_id in [n["id"] for n in result.data["nodes"]]

    def test_append_log_preserves_knowledge_in_fts(self, engine):
        """append_log must NOT wipe knowledge_text from FTS index."""
        result = engine.execute_tool("create_node", {
            "title": "Dual Content Node", "is_root": True,
        })
        node_id = result.data["id"]

        # First, set knowledge and index it
        from fpms.spine import knowledge as knowledge_mod
        knowledge_mod.set_knowledge(
            engine._knowledge_dir, node_id, "overview",
            "PostgreSQL with read replicas for scalability",
        )
        engine.store.index_knowledge(node_id, engine._knowledge_dir)

        # Verify knowledge is searchable
        result = engine.execute_tool("search_nodes", {"query": "PostgreSQL replicas"})
        assert node_id in [n["id"] for n in result.data["nodes"]]

        # Now append_log — this should NOT wipe the knowledge from FTS
        engine.execute_tool("append_log", {
            "node_id": node_id, "content": "Added connection pooling",
            "category": "technical",
        })

        # Knowledge should still be searchable
        result = engine.execute_tool("search_nodes", {"query": "PostgreSQL replicas"})
        assert node_id in [n["id"] for n in result.data["nodes"]], \
            "append_log wiped knowledge_text from FTS index!"

        # Narrative should also be searchable
        result = engine.execute_tool("search_nodes", {"query": "connection pooling"})
        assert node_id in [n["id"] for n in result.data["nodes"]]
