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


from fpms.spine import knowledge as knowledge_mod


class TestFTSAutoIndexKnowledge:
    def test_knowledge_searchable_after_index(self, engine):
        """After set_knowledge + index, content should be findable via search."""
        result = engine.execute_tool("create_node", {
            "title": "Auth System", "is_root": True, "node_type": "project",
        })
        node_id = result.data["id"]

        knowledge_mod.set_knowledge(
            engine._knowledge_dir, node_id, "architecture",
            "## Architecture\n\nUse JWT tokens with RSA256 signing.",
        )
        engine.store.index_knowledge(node_id, engine._knowledge_dir)

        result = engine.execute_tool("search_nodes", {"query": "JWT RSA256"})
        assert result.success
        found_ids = [n["id"] for n in result.data["nodes"]]
        assert node_id in found_ids

    def test_delete_knowledge_removes_from_search_index(self, engine):
        """After delete_knowledge + re-index, content should no longer be findable."""
        result = engine.execute_tool("create_node", {
            "title": "Cache Layer", "is_root": True,
        })
        node_id = result.data["id"]

        knowledge_mod.set_knowledge(
            engine._knowledge_dir, node_id, "overview",
            "Memcached cluster with consistent hashing",
        )
        engine.store.index_knowledge(node_id, engine._knowledge_dir)

        # Verify searchable
        result = engine.execute_tool("search_nodes", {"query": "Memcached"})
        assert node_id in [n["id"] for n in result.data["nodes"]]

        # Delete and re-index
        knowledge_mod.delete_knowledge(engine._knowledge_dir, node_id, "overview")
        engine.store.index_knowledge(node_id, engine._knowledge_dir)

        # Should no longer be findable
        result = engine.execute_tool("search_nodes", {"query": "Memcached"})
        found_ids = [n["id"] for n in result.data["nodes"]]
        assert node_id not in found_ids

    def test_knowledge_index_preserves_narrative(self, engine):
        """index_knowledge must NOT wipe narrative_text from FTS index."""
        result = engine.execute_tool("create_node", {
            "title": "Mixed Node", "is_root": True,
        })
        node_id = result.data["id"]

        # Add narrative first
        engine.execute_tool("append_log", {
            "node_id": node_id, "content": "Elasticsearch cluster setup",
            "category": "technical",
        })

        # Now add knowledge — should not wipe narrative
        knowledge_mod.set_knowledge(
            engine._knowledge_dir, node_id, "arch", "GraphQL API gateway",
        )
        engine.store.index_knowledge(node_id, engine._knowledge_dir)

        # Both should be searchable
        r1 = engine.execute_tool("search_nodes", {"query": "Elasticsearch"})
        assert node_id in [n["id"] for n in r1.data["nodes"]]

        r2 = engine.execute_tool("search_nodes", {"query": "GraphQL"})
        assert node_id in [n["id"] for n in r2.data["nodes"]]


class TestDeleteKnowledgeMCPTool:
    def test_delete_knowledge_function_importable(self):
        """The delete_knowledge MCP tool function should be importable."""
        from fpms.mcp_server import delete_knowledge
        assert callable(delete_knowledge)

    def test_delete_knowledge_removes_file(self, engine):
        """delete_knowledge should remove the knowledge file."""
        result = engine.execute_tool("create_node", {
            "title": "Test Project", "is_root": True,
        })
        node_id = result.data["id"]

        knowledge_mod.set_knowledge(
            engine._knowledge_dir, node_id, "overview", "Test content",
        )

        # Verify file exists
        import os
        filepath = os.path.join(engine._knowledge_dir, node_id, "overview.md")
        assert os.path.exists(filepath)

        # Delete via knowledge module directly
        knowledge_mod.delete_knowledge(engine._knowledge_dir, node_id, "overview")
        assert not os.path.exists(filepath)
