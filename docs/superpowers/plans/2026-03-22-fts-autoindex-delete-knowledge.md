# FTS Auto-Index + delete_knowledge MCP Tool — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix two v0.3 gaps: (1) FTS index auto-updates when narrative/knowledge changes, (2) expose delete_knowledge as MCP tool.

**Architecture:** First fix `index_narrative` to preserve existing `knowledge_text` (same pattern as `index_knowledge`). Then hook FTS re-indexing into `append_log` (tools.py) and `set_knowledge` / `delete_knowledge` (mcp_server.py) post-commit paths. Add `delete_knowledge` MCP tool mirroring existing `set_knowledge` pattern.

**Tech Stack:** Python 3.11, SQLite FTS5, pytest

**Python:** `/opt/homebrew/opt/python@3.11/bin/python3.11`
**Test command:** `/opt/homebrew/opt/python@3.11/bin/python3.11 -m pytest tests/ -v`
**Project root:** `/Users/ontanetwork/Documents/Onta Network/Founder OS/MemoryFPMS/V4`

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `fpms/spine/store.py` | Modify | Fix `index_narrative` to preserve `knowledge_text` |
| `fpms/spine/tools.py` | Modify | Hook `index_narrative` after `append_log` |
| `fpms/mcp_server.py` | Modify | Hook `index_knowledge` after `set_knowledge`, add `delete_knowledge` tool |
| `tests/test_fts_autoindex.py` | Create | Tests for auto-indexing + delete_knowledge + coexistence |

---

### Task 1: Fix index_narrative to preserve knowledge_text + auto-index on append_log

**Files:**
- Modify: `fpms/spine/store.py` — `index_narrative` method (line 510-520)
- Modify: `fpms/spine/tools.py` — `handle_append_log` method (line 505-557)
- Create: `tests/test_fts_autoindex.py`

**Context for worker:**
- `store.index_narrative(node_id, narratives_dir)` exists at `store.py:510-520`. It deletes the FTS row and re-inserts with `knowledge_text=""`. This is a bug — it wipes any existing knowledge from the index.
- Compare with `index_knowledge` at `store.py:522-537` which correctly preserves `narrative_text` by reading the existing row first.
- Fix `index_narrative` to preserve existing `knowledge_text` using the same pattern.
- Then hook `index_narrative` into `handle_append_log` in `tools.py`.
- `handle_append_log` is at `tools.py:505-557`. The `ok = self.narrative.append_narrative(...)` call is around line 540-547. The return statement is at line 550.
- The ToolHandler has `self.store` and `self.narratives_dir` already available.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_fts_autoindex.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/opt/homebrew/opt/python@3.11/bin/python3.11 -m pytest tests/test_fts_autoindex.py::TestFTSAutoIndexNarrative -v`
Expected: FAIL — narrative content not indexed, and `test_append_log_preserves_knowledge_in_fts` will fail because `index_narrative` wipes `knowledge_text`.

- [ ] **Step 3: Fix index_narrative in store.py**

In `fpms/spine/store.py`, replace the `index_narrative` method (lines 510-520) with:

```python
    def index_narrative(self, node_id: str, narratives_dir: str) -> None:
        """Index (or re-index) a node's narrative content into FTS."""
        from . import narrative as narrative_mod
        text = narrative_mod.read_narrative(narratives_dir, node_id)
        node = self.get_node(node_id)
        title = node.title if node else ""
        # Preserve existing knowledge_text
        existing = self._conn.execute(
            "SELECT knowledge_text FROM fts_index WHERE node_id=?", (node_id,)
        ).fetchone()
        knowledge_text = existing[0] if existing else ""
        self._conn.execute("DELETE FROM fts_index WHERE node_id=?", (node_id,))
        self._conn.execute(
            "INSERT INTO fts_index (node_id, title, narrative_text, knowledge_text) VALUES (?,?,?,?)",
            (node_id, title, text or "", knowledge_text),
        )
```

- [ ] **Step 4: Hook index_narrative into append_log in tools.py**

In `fpms/spine/tools.py`, in the `handle_append_log` method, find the line:

```python
        ok = self.narrative.append_narrative(
            self.narratives_dir,
            node_id,
            now,
            event_type,
            content,
        )
```

Right after that block (after `ok = ...`) and before the `return ToolResult(...)`, add:

```python
        # Post-commit: update FTS index
        if ok:
            try:
                self.store.index_narrative(node_id, self.narratives_dir)
            except Exception:
                pass  # FTS update failure is non-fatal
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `/opt/homebrew/opt/python@3.11/bin/python3.11 -m pytest tests/test_fts_autoindex.py::TestFTSAutoIndexNarrative -v`
Expected: All 3 tests PASS

- [ ] **Step 6: Run full test suite for regression**

Run: `/opt/homebrew/opt/python@3.11/bin/python3.11 -m pytest tests/ -v`
Expected: All 657+ tests pass

- [ ] **Step 7: Commit**

```bash
git add fpms/spine/store.py fpms/spine/tools.py tests/test_fts_autoindex.py
git commit -m "fix: auto-index narrative into FTS on append_log, preserve knowledge_text"
```

---

### Task 2: FTS auto-index on set_knowledge + delete_knowledge MCP tool

**Files:**
- Modify: `fpms/mcp_server.py` — `set_knowledge` function (line 444-460), add `delete_knowledge` function after `get_knowledge`
- Modify: `tests/test_fts_autoindex.py` (append new test classes)

**Context for worker:**
- `store.index_knowledge(node_id, knowledge_dir)` exists in `store.py:522-537`. It reads knowledge docs and upserts the FTS index, preserving existing `narrative_text`.
- The `set_knowledge` MCP tool in `mcp_server.py` (around line 444-460) writes knowledge via `knowledge_mod.set_knowledge(...)` but does NOT call `index_knowledge` afterward.
- The fix: after `knowledge_mod.set_knowledge(...)`, also call `engine.store.index_knowledge(node_id, engine._knowledge_dir)`.
- For `delete_knowledge`: the function `knowledge.delete_knowledge(knowledge_dir, node_id, doc_type)` already exists in `fpms/spine/knowledge.py:105-111`. Create an MCP tool that calls it and then re-indexes. Follow the exact pattern of `set_knowledge` MCP tool.
- Access engine via `_get_engine()`. The engine has `._knowledge_dir` and `.store`.
- **Important**: MCP tool tests that call functions like `delete_knowledge(...)` directly will use `_get_engine()` which returns a global singleton. The test must either (a) test via `engine.execute_tool` instead, or (b) test that the function exists as a valid import. For full integration, test through the engine directly.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_fts_autoindex.py`:

```python
import json
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
```

- [ ] **Step 2: Run tests to verify failures**

Run: `/opt/homebrew/opt/python@3.11/bin/python3.11 -m pytest tests/test_fts_autoindex.py::TestDeleteKnowledgeMCPTool::test_delete_knowledge_function_importable -v`
Expected: FAIL — `delete_knowledge` not found in mcp_server.

- [ ] **Step 3: Implement — add FTS hook to set_knowledge + add delete_knowledge MCP tool**

In `fpms/mcp_server.py`:

**3a.** In the existing `set_knowledge` function, find the line:

```python
    knowledge_mod.set_knowledge(engine._knowledge_dir, node_id, doc_type, content)
    return json.dumps({"success": True, "node_id": node_id, "doc_type": doc_type})
```

Replace with:

```python
    knowledge_mod.set_knowledge(engine._knowledge_dir, node_id, doc_type, content)
    # Update FTS index
    try:
        engine.store.index_knowledge(node_id, engine._knowledge_dir)
    except Exception:
        pass  # FTS update failure is non-fatal
    return json.dumps({"success": True, "node_id": node_id, "doc_type": doc_type})
```

**3b.** Add new `delete_knowledge` MCP tool right after `get_knowledge`:

```python
@mcp.tool()
@_safe_tool
def delete_knowledge(node_id: str, doc_type: str) -> str:
    """Delete a knowledge document from a node.

    Args:
        node_id: Target node ID
        doc_type: Document type to delete (e.g. overview, requirements, architecture)
    """
    from fpms.spine import knowledge as knowledge_mod
    engine = _get_engine()
    node = engine.store.get_node(node_id)
    if node is None:
        return json.dumps({"success": False, "error": f"Node '{node_id}' not found"})
    knowledge_mod.delete_knowledge(engine._knowledge_dir, node_id, doc_type)
    # Update FTS index
    try:
        engine.store.index_knowledge(node_id, engine._knowledge_dir)
    except Exception:
        pass  # FTS update failure is non-fatal
    return json.dumps({"success": True, "node_id": node_id, "doc_type": doc_type, "deleted": True})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/opt/homebrew/opt/python@3.11/bin/python3.11 -m pytest tests/test_fts_autoindex.py -v`
Expected: All tests PASS

- [ ] **Step 5: Run full test suite for regression**

Run: `/opt/homebrew/opt/python@3.11/bin/python3.11 -m pytest tests/ -v`
Expected: All 657+ tests pass

- [ ] **Step 6: Commit**

```bash
git add fpms/mcp_server.py tests/test_fts_autoindex.py
git commit -m "fix: auto-index knowledge into FTS, add delete_knowledge MCP tool"
```

---

### Task 3: Final verification

**Files:** None (verification only)

- [ ] **Step 1: Run full test suite**

Run: `/opt/homebrew/opt/python@3.11/bin/python3.11 -m pytest tests/ -v`
Expected: All tests pass (657 existing + ~8 new)

- [ ] **Step 2: Verify FTS end-to-end — narrative + knowledge coexistence**

```bash
/opt/homebrew/opt/python@3.11/bin/python3.11 -c "
import tempfile, os
from fpms.spine import SpineEngine
from fpms.spine import knowledge as km

tmp = tempfile.mkdtemp()
e = SpineEngine(
    db_path=os.path.join(tmp, 'test.db'),
    events_path=os.path.join(tmp, 'ev.jsonl'),
    narratives_dir=os.path.join(tmp, 'narratives'),
)

r = e.execute_tool('create_node', {'title': 'Test', 'is_root': True})
nid = r.data['id']

# Set knowledge first
km.set_knowledge(e._knowledge_dir, nid, 'arch', 'PostgreSQL with read replicas')
e.store.index_knowledge(nid, e._knowledge_dir)

# Then append log (must NOT wipe knowledge)
e.execute_tool('append_log', {'node_id': nid, 'content': 'Redis caching strategy', 'category': 'technical'})

# Search narrative
r1 = e.execute_tool('search_nodes', {'query': 'Redis'})
# Search knowledge (should still work after append_log)
r2 = e.execute_tool('search_nodes', {'query': 'PostgreSQL replicas'})

ids1 = [n['id'] for n in r1.data['nodes']]
ids2 = [n['id'] for n in r2.data['nodes']]
print(f'Narrative search: {\"PASS\" if nid in ids1 else \"FAIL\"}')
print(f'Knowledge search after append_log: {\"PASS\" if nid in ids2 else \"FAIL\"}')
"
```
Expected: Both print PASS.

- [ ] **Step 3: Commit (if any fixes needed)**
