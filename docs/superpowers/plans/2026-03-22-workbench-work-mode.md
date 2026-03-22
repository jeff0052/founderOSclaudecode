# FocalPoint v0.3 — Work Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add knowledge layer, role-based context filtering, workbench, full-text search, and 三省 Protocol to FocalPoint so AI agents can prepare context before execution.

**Architecture:** 5 new capabilities layered on existing Spine engine: (1) knowledge.py for per-node Markdown docs with parent inheritance, (2) narrative category field for log classification, (3) FTS5 virtual table for full-text search across titles/narratives/knowledge, (4) role-based filtering in BundleAssembler, (5) activate_workbench as stateless context assembler. 三省 Protocol uses role prompts from `fpms/prompts/` with parallel review + rejection loop.

**Tech Stack:** Python 3.11, pytest, SQLite FTS5, FastMCP

**Python:** `/opt/homebrew/opt/python@3.11/bin/python3.11`
**Test command:** `/opt/homebrew/opt/python@3.11/bin/python3.11 -m pytest tests/ -v`
**Project root:** `/Users/ontanetwork/Documents/Onta Network/Founder OS/MemoryFPMS/V4/`

**Design decisions (confirmed, do not re-discuss):**
1. Roles filter data by narrative category (per acceptance tests)
2. Workbench is stateless — one call, one response
3. Knowledge docs are extensible — base 3 + custom names
4. Narrative records process, knowledge records conclusions
5. No soft links between nodes — FTS5 search replaces them
6. 三省 reviews in parallel, not serial
7. Max 3 rejections before escalating to human
8. One role focuses on one thing only

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `fpms/spine/knowledge.py` | **Create** | Knowledge doc CRUD + parent inheritance |
| `fpms/spine/narrative.py` | Modify | Add `category` param to append/read |
| `fpms/spine/models.py` | Modify | Add constants (NARRATIVE_CATEGORIES, ROLES) |
| `fpms/spine/store.py` | Modify | Add FTS5 virtual table + `search_fts()` method |
| `fpms/spine/schema.py` | Modify | Add FTS5 table to schema |
| `fpms/spine/bundle.py` | Modify | Add `role` param, category filtering, role budgets |
| `fpms/spine/tools.py` | Modify | Add `category` to append_log, `query` to search_nodes, knowledge + workbench handlers |
| `fpms/spine/__init__.py` | Modify | Add knowledge/workbench/search methods, wire knowledge module |
| `fpms/mcp_server.py` | Modify | 3 new tools (activate_workbench, set_knowledge, get_knowledge) + 2 updated (append_log, get_context_bundle, search_nodes) |
| `fpms/prompts/strategy.md` | **Create** | 中书省 role prompt |
| `fpms/prompts/review.md` | **Create** | 门下省 role prompt |
| `fpms/prompts/execution.md` | **Create** | 尚书省 role prompt |
| `tests/test_knowledge.py` | **Create** | Knowledge layer tests |
| `tests/test_narrative.py` | Modify | Category tests |
| `tests/test_bundle.py` | Modify | Role filtering tests |
| `tests/test_tools.py` | Modify | Category + search tool tests |
| `tests/test_workbench.py` | **Create** | Workbench tests |
| `tests/test_fts.py` | **Create** | Full-text search tests |

---

## Dependency Graph

```
Task 1: knowledge.py           ← no deps
Task 2: narrative category      ← no deps
Task 3: FTS5 full-text search   ← no deps
   ↑ Tasks 1-3 can run in parallel

Task 4: role prompt files        ← no deps (just .md files)
Task 5: bundle role filtering    ← depends on Task 2
Task 6: workbench.py             ← depends on Tasks 1, 4, 5
Task 7: MCP tools                ← depends on Tasks 1-6
Task 8: 三省 Protocol            ← depends on Task 6
Task 9: final verification       ← depends on all
```

---

### Task 1: Knowledge document layer (knowledge.py)

**Files:**
- Create: `fpms/spine/knowledge.py`
- Create: `tests/test_knowledge.py`

- [ ] **Step 1: Write failing tests for knowledge CRUD + inheritance**

Create `tests/test_knowledge.py`:

```python
"""Tests for fpms.spine.knowledge — per-node Markdown knowledge docs with inheritance."""

from __future__ import annotations

import os

import pytest

from fpms.spine.knowledge import (
    set_knowledge,
    get_knowledge,
    delete_knowledge,
    list_knowledge,
)


@pytest.fixture
def kdir(tmp_path):
    """Return a temporary knowledge base directory."""
    return str(tmp_path / "knowledge")


class TestSetKnowledge:

    def test_write_creates_file(self, kdir):
        set_knowledge(kdir, "proj-1234", "overview", "# Project Overview\nThis is the overview.")
        path = os.path.join(kdir, "proj-1234", "overview.md")
        assert os.path.exists(path)
        assert "# Project Overview" in open(path).read()

    def test_overwrite_replaces_content(self, kdir):
        set_knowledge(kdir, "proj-1234", "overview", "Version 1")
        set_knowledge(kdir, "proj-1234", "overview", "Version 2")
        content = open(os.path.join(kdir, "proj-1234", "overview.md")).read()
        assert "Version 2" in content
        assert "Version 1" not in content

    def test_custom_doc_type(self, kdir):
        set_knowledge(kdir, "proj-1234", "competitive_analysis", "Competitor X is strong.")
        path = os.path.join(kdir, "proj-1234", "competitive_analysis.md")
        assert os.path.exists(path)


class TestGetKnowledge:

    def test_get_single_doc(self, kdir):
        set_knowledge(kdir, "proj-1234", "overview", "The overview content.")
        result = get_knowledge(kdir, "proj-1234", doc_type="overview")
        assert result == "The overview content."

    def test_get_all_docs(self, kdir):
        set_knowledge(kdir, "proj-1234", "overview", "OV")
        set_knowledge(kdir, "proj-1234", "requirements", "REQ")
        set_knowledge(kdir, "proj-1234", "architecture", "ARCH")
        result = get_knowledge(kdir, "proj-1234")
        assert isinstance(result, dict)
        assert result["overview"] == "OV"
        assert result["requirements"] == "REQ"
        assert result["architecture"] == "ARCH"

    def test_get_nonexistent_returns_none(self, kdir):
        result = get_knowledge(kdir, "proj-1234", doc_type="overview")
        assert result is None

    def test_get_all_empty_returns_empty_dict(self, kdir):
        result = get_knowledge(kdir, "proj-1234")
        assert result == {}


class TestKnowledgeInheritance:
    """Child inherits parent knowledge, own docs override parent's."""

    def _make_store_with_tree(self, tmp_path):
        """Create a store with project -> milestone -> task tree."""
        from fpms.spine.store import Store
        from fpms.spine.models import Node, Edge

        db_path = str(tmp_path / "test.db")
        events_path = str(tmp_path / "events.jsonl")
        store = Store(db_path, events_path)

        # project (root)
        with store.transaction():
            store._create_node_inner(Node(
                id="proj-aa", title="Project", status="active",
                node_type="project", is_root=True,
            ))
        # milestone (child of project)
        with store.transaction():
            store._create_node_inner(Node(
                id="mile-bb", title="Milestone", status="active",
                node_type="milestone", parent_id="proj-aa",
            ))
        # task (child of milestone)
        with store.transaction():
            store._create_node_inner(Node(
                id="task-cc", title="Task", status="active",
                node_type="task", parent_id="mile-bb",
            ))
        return store

    def test_child_inherits_parent_knowledge(self, tmp_path):
        kdir = str(tmp_path / "knowledge")
        store = self._make_store_with_tree(tmp_path)

        set_knowledge(kdir, "proj-aa", "overview", "Project overview")
        set_knowledge(kdir, "proj-aa", "requirements", "Project requirements")

        # milestone has no knowledge — inherits from project
        result = get_knowledge(kdir, "mile-bb", store=store, inherit=True)
        assert result["overview"] == "Project overview"
        assert result["requirements"] == "Project requirements"

    def test_child_overrides_parent_knowledge(self, tmp_path):
        kdir = str(tmp_path / "knowledge")
        store = self._make_store_with_tree(tmp_path)

        set_knowledge(kdir, "proj-aa", "overview", "Project overview")
        set_knowledge(kdir, "proj-aa", "requirements", "Project requirements")
        set_knowledge(kdir, "mile-bb", "requirements", "Milestone requirements")

        result = get_knowledge(kdir, "mile-bb", store=store, inherit=True)
        assert result["overview"] == "Project overview"  # inherited
        assert result["requirements"] == "Milestone requirements"  # overridden

    def test_deep_inheritance_task_from_grandparent(self, tmp_path):
        kdir = str(tmp_path / "knowledge")
        store = self._make_store_with_tree(tmp_path)

        set_knowledge(kdir, "proj-aa", "overview", "Project overview")

        result = get_knowledge(kdir, "task-cc", store=store, inherit=True)
        assert result["overview"] == "Project overview"

    def test_no_inherit_returns_only_own(self, tmp_path):
        kdir = str(tmp_path / "knowledge")
        store = self._make_store_with_tree(tmp_path)

        set_knowledge(kdir, "proj-aa", "overview", "Project overview")
        # milestone has no own knowledge
        result = get_knowledge(kdir, "mile-bb", store=store, inherit=False)
        assert result == {}


class TestDeleteKnowledge:

    def test_delete_removes_file(self, kdir):
        set_knowledge(kdir, "proj-1234", "overview", "Content")
        delete_knowledge(kdir, "proj-1234", "overview")
        assert not os.path.exists(os.path.join(kdir, "proj-1234", "overview.md"))

    def test_delete_nonexistent_no_error(self, kdir):
        # Should not raise
        delete_knowledge(kdir, "proj-1234", "overview")


class TestListKnowledge:

    def test_list_returns_doc_types(self, kdir):
        set_knowledge(kdir, "proj-1234", "overview", "OV")
        set_knowledge(kdir, "proj-1234", "requirements", "REQ")
        result = list_knowledge(kdir, "proj-1234")
        assert set(result) == {"overview", "requirements"}

    def test_list_empty_node(self, kdir):
        result = list_knowledge(kdir, "proj-1234")
        assert result == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/opt/homebrew/opt/python@3.11/bin/python3.11 -m pytest tests/test_knowledge.py -v`
Expected: FAIL — module `fpms.spine.knowledge` does not exist.

- [ ] **Step 3: Implement knowledge.py**

Create `fpms/spine/knowledge.py`:

```python
"""知识文档层 — 每个节点挂载 Markdown 知识文档，支持继承。

存储结构:
    data/knowledge/{node_id}/
    ├── overview.md
    ├── requirements.md
    ├── architecture.md
    └── {custom_name}.md
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .store import Store


def set_knowledge(
    knowledge_dir: str,
    node_id: str,
    doc_type: str,
    content: str,
) -> None:
    """写入或覆盖知识文档。"""
    node_dir = os.path.join(knowledge_dir, node_id)
    os.makedirs(node_dir, exist_ok=True)
    filepath = os.path.join(node_dir, f"{doc_type}.md")
    with open(filepath, "w") as f:
        f.write(content)


def get_knowledge(
    knowledge_dir: str,
    node_id: str,
    doc_type: Optional[str] = None,
    store: Optional["Store"] = None,
    inherit: bool = False,
) -> Optional[str] | Dict[str, str]:
    """读取知识文档。

    Args:
        knowledge_dir: 知识文档根目录
        node_id: 节点 ID
        doc_type: 指定文档类型（None = 返回全部）
        store: Store 实例（继承需要）
        inherit: 是否沿 parent_id 向上继承

    Returns:
        doc_type 指定时返回 str|None；否则返回 dict[doc_type, content]
    """
    if doc_type is not None:
        return _get_single(knowledge_dir, node_id, doc_type, store, inherit)

    # Get all docs (with optional inheritance)
    result: Dict[str, str] = {}

    if inherit and store is not None:
        # Collect ancestor chain (bottom-up), then resolve top-down
        chain = _get_ancestor_chain(store, node_id)
        for ancestor_id in chain:
            ancestor_docs = _list_own_docs(knowledge_dir, ancestor_id)
            for dt in ancestor_docs:
                if dt not in result:  # child overrides parent
                    result[dt] = _read_doc(knowledge_dir, ancestor_id, dt)

        # Own docs override everything
        own_docs = _list_own_docs(knowledge_dir, node_id)
        for dt in own_docs:
            result[dt] = _read_doc(knowledge_dir, node_id, dt)
    else:
        own_docs = _list_own_docs(knowledge_dir, node_id)
        for dt in own_docs:
            result[dt] = _read_doc(knowledge_dir, node_id, dt)

    return result


def _get_single(
    knowledge_dir: str,
    node_id: str,
    doc_type: str,
    store: Optional["Store"],
    inherit: bool,
) -> Optional[str]:
    """Get a single doc, optionally walking up the parent chain."""
    content = _read_doc(knowledge_dir, node_id, doc_type)
    if content is not None:
        return content

    if not inherit or store is None:
        return None

    # Walk up parent chain
    chain = _get_ancestor_chain(store, node_id)
    for ancestor_id in chain:
        content = _read_doc(knowledge_dir, ancestor_id, doc_type)
        if content is not None:
            return content

    return None


def _get_ancestor_chain(store: "Store", node_id: str) -> List[str]:
    """Return ancestor IDs from immediate parent to root (bottom-up)."""
    chain: List[str] = []
    current = store.get_node(node_id)
    if current is None:
        return chain
    while current and current.parent_id:
        chain.append(current.parent_id)
        current = store.get_node(current.parent_id)
    return chain


def _read_doc(knowledge_dir: str, node_id: str, doc_type: str) -> Optional[str]:
    """Read a single knowledge doc file. Returns None if not found."""
    filepath = os.path.join(knowledge_dir, node_id, f"{doc_type}.md")
    if not os.path.exists(filepath):
        return None
    with open(filepath, "r") as f:
        return f.read()


def _list_own_docs(knowledge_dir: str, node_id: str) -> List[str]:
    """List doc types that this node has (own, not inherited)."""
    node_dir = os.path.join(knowledge_dir, node_id)
    if not os.path.isdir(node_dir):
        return []
    return [
        f[:-3]  # strip .md
        for f in os.listdir(node_dir)
        if f.endswith(".md")
    ]


def delete_knowledge(
    knowledge_dir: str,
    node_id: str,
    doc_type: str,
) -> None:
    """删除知识文档。"""
    filepath = os.path.join(knowledge_dir, node_id, f"{doc_type}.md")
    if os.path.exists(filepath):
        os.remove(filepath)


def list_knowledge(knowledge_dir: str, node_id: str) -> List[str]:
    """列出节点拥有的文档类型（不含继承）。"""
    return _list_own_docs(knowledge_dir, node_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/opt/homebrew/opt/python@3.11/bin/python3.11 -m pytest tests/test_knowledge.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
cd "/Users/ontanetwork/Documents/Onta Network/Founder OS/MemoryFPMS/V4"
git add fpms/spine/knowledge.py tests/test_knowledge.py
git commit -m "feat(v0.3): add knowledge document layer with parent inheritance

Per-node Markdown docs stored in data/knowledge/{node_id}/.
Supports set/get/delete/list + inheritance up parent chain."
```

---

### Task 2: Narrative category field

**Files:**
- Modify: `fpms/spine/models.py` (add constant)
- Modify: `fpms/spine/narrative.py:12-40` (append_narrative) + `fpms/spine/narrative.py:43-95` (read_narrative)
- Modify: `fpms/spine/tools.py:505-546` (handle_append_log)
- Test: `tests/test_narrative.py`
- Test: `tests/test_tools.py`

- [ ] **Step 1: Add NARRATIVE_CATEGORIES constant to models.py**

In `fpms/spine/models.py`, add after the imports:

```python
# Narrative categories for log classification
NARRATIVE_CATEGORIES = {"decision", "feedback", "risk", "technical", "progress", "general"}
```

- [ ] **Step 2: Write failing tests for category in narrative**

Append to `tests/test_narrative.py`:

```python
class TestNarrativeCategory:
    """Tests for category field in narrative entries."""

    def test_append_with_category_in_header(self, narr_dir):
        """Category appears in the header line: ## {ts} [{event_type}] [{category}]"""
        ok = append_narrative(
            narr_dir, "node-cat", "2025-01-15T10:00:00Z", "log", "Chose Stripe",
            category="decision",
        )
        assert ok is True
        content = open(os.path.join(narr_dir, "node-cat.md")).read()
        assert "## 2025-01-15T10:00:00Z [log] [decision]" in content

    def test_append_default_category_is_general(self, narr_dir):
        """Without category param, default is 'general'."""
        append_narrative(narr_dir, "node-def", "2025-01-15T10:00:00Z", "log", "Default entry")
        content = open(os.path.join(narr_dir, "node-def.md")).read()
        assert "[general]" in content

    def test_append_all_valid_categories(self, narr_dir):
        """All 6 category values are accepted."""
        from fpms.spine.models import NARRATIVE_CATEGORIES
        for cat in sorted(NARRATIVE_CATEGORIES):
            ok = append_narrative(
                narr_dir, f"node-{cat}", "2025-01-15T10:00:00Z", "log", f"Entry {cat}",
                category=cat,
            )
            assert ok is True

    def test_read_narrative_filter_by_category(self, narr_dir):
        """read_narrative with category filter returns only matching entries."""
        append_narrative(narr_dir, "node-f", "2025-01-15T10:00:00Z", "log", "Decision made", category="decision")
        append_narrative(narr_dir, "node-f", "2025-01-15T11:00:00Z", "log", "Code written", category="technical")
        append_narrative(narr_dir, "node-f", "2025-01-15T12:00:00Z", "log", "Risk found", category="risk")

        result = read_narrative(narr_dir, "node-f", categories=["decision"])
        assert "Decision made" in result
        assert "Code written" not in result
        assert "Risk found" not in result

    def test_read_narrative_filter_multiple_categories(self, narr_dir):
        """read_narrative with multiple categories returns union."""
        append_narrative(narr_dir, "node-m", "2025-01-15T10:00:00Z", "log", "Decision", category="decision")
        append_narrative(narr_dir, "node-m", "2025-01-15T11:00:00Z", "log", "Feedback", category="feedback")
        append_narrative(narr_dir, "node-m", "2025-01-15T12:00:00Z", "log", "Technical", category="technical")

        result = read_narrative(narr_dir, "node-m", categories=["decision", "feedback"])
        assert "Decision" in result
        assert "Feedback" in result
        assert "Technical" not in result

    def test_read_narrative_no_category_filter_returns_all(self, narr_dir):
        """read_narrative without categories returns all entries (backward compat)."""
        append_narrative(narr_dir, "node-a", "2025-01-15T10:00:00Z", "log", "Entry A", category="decision")
        append_narrative(narr_dir, "node-a", "2025-01-15T11:00:00Z", "log", "Entry B", category="technical")

        result = read_narrative(narr_dir, "node-a")
        assert "Entry A" in result
        assert "Entry B" in result

    def test_backward_compat_old_entries_without_category(self, narr_dir):
        """Old entries without category tag are still readable."""
        filepath = os.path.join(narr_dir, "node-old.md")
        os.makedirs(narr_dir, exist_ok=True)
        with open(filepath, "w") as f:
            f.write("## 2025-01-15T10:00:00Z [log]\nOld entry without category\n\n")

        result = read_narrative(narr_dir, "node-old")
        assert "Old entry without category" in result

        # With filter — old entry without category is included (matches all)
        result = read_narrative(narr_dir, "node-old", categories=["decision"])
        assert "Old entry without category" in result
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `/opt/homebrew/opt/python@3.11/bin/python3.11 -m pytest tests/test_narrative.py::TestNarrativeCategory -v`
Expected: FAIL — `append_narrative` doesn't accept `category`, `read_narrative` doesn't accept `categories`.

- [ ] **Step 4: Implement category in append_narrative**

In `fpms/spine/narrative.py`, update `append_narrative`:

```python
def append_narrative(
    narratives_dir: str,
    node_id: str,
    timestamp: str,
    event_type: str,
    content: str,
    mentions: Optional[List[str]] = None,
    category: str = "general",
) -> bool:
    """追加一条叙事到 narratives/{node_id}.md。
    格式: ## {timestamp} [{event_type}] [{category}]\\n{content}
    返回是否写入成功。失败时不抛异常，返回 False。"""
    try:
        os.makedirs(narratives_dir, exist_ok=True)
        filepath = os.path.join(narratives_dir, f"{node_id}.md")

        block = f"## {timestamp} [{event_type}] [{category}]\n{content}\n"
        if mentions:
            block += f"Mentions: {', '.join(mentions)}\n"
        block += "\n"

        with open(filepath, "a") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                f.write(block)
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        return True
    except Exception:
        return False
```

- [ ] **Step 5: Implement category filtering in read_narrative**

Add `_extract_category` helper and update `read_narrative` to accept `categories` param:

```python
def _extract_category(entry: str) -> Optional[str]:
    """Extract category from entry header like '## 2025-01-15T10:00:00Z [log] [decision]'."""
    if not entry.startswith("## "):
        return None
    header_line = entry.split("\n", 1)[0]
    import re
    brackets = re.findall(r'\[([^\]]+)\]', header_line)
    if len(brackets) >= 2:
        return brackets[-1]  # last bracket is category
    return None  # old format without category


def read_narrative(
    narratives_dir: str,
    node_id: str,
    last_n_entries: Optional[int] = None,
    since_days: Optional[int] = None,
    categories: Optional[List[str]] = None,
) -> str:
```

After the `since_days` filter block, add before the `last_n_entries` filter:

```python
    # Filter by categories
    if categories is not None:
        cat_set = set(categories)
        filtered_cat: List[str] = []
        for entry in entries:
            cat = _extract_category(entry)
            if cat is None or cat in cat_set:
                # None = old format without category → include always
                filtered_cat.append(entry)
        entries = filtered_cat
```

- [ ] **Step 6: Update ALL existing test assertions for new header format**

The header format changes from `## {ts} [{event_type}]` to `## {ts} [{event_type}] [{category}]`.

**IMPORTANT:** Search ALL test files for assertions on narrative header format and update them.
Run: `grep -rn '\[created\]\|header.*format\|\[log\].*in content\|\[status_change\]' tests/`

At minimum, update in `tests/test_narrative.py`:
- `TestAppendNarrative.test_basic_format`: `"## 2025-01-15T10:00:00Z [created]"` → `"## 2025-01-15T10:00:00Z [created] [general]"`

Run the FULL test suite after this step to catch any other broken assertions:
`/opt/homebrew/opt/python@3.11/bin/python3.11 -m pytest tests/ -v`
Fix any additional failures caused by the new header format.

- [ ] **Step 7: Implement category in handle_append_log (tools.py)**

In `fpms/spine/tools.py`, update `handle_append_log` to extract `category`, validate against `NARRATIVE_CATEGORIES`, pass to `append_narrative`, and include in result data. See `tools.py:505-546`. Add:

```python
    category = params.get("category", "general")
    # ... after node existence check ...
    from .models import NARRATIVE_CATEGORIES
    if category not in NARRATIVE_CATEGORIES:
        return ToolResult(
            success=False,
            command_id=command_id,
            error=f"Invalid category '{category}'. Must be one of: {sorted(NARRATIVE_CATEGORIES)}",
            suggestion=f"Valid categories: {sorted(NARRATIVE_CATEGORIES)}",
        )
    # ... pass category=category to append_narrative ...
    # ... include "category": category in result.data ...
```

- [ ] **Step 8: Write failing tests for category in tools**

Append to `tests/test_tools.py`:

```python
class TestAppendLogCategory:
    def test_append_log_with_category(self, store, handler, tmp_dirs):
        node = _make_node(store, title="Cat Node")
        result = handler.handle("append_log", {
            "node_id": node.id, "content": "Decision: use Stripe",
            "event_type": "log", "category": "decision",
        })
        assert result.success is True
        _, _, narr_dir = tmp_dirs
        content = open(os.path.join(narr_dir, f"{node.id}.md")).read()
        assert "[decision]" in content

    def test_append_log_default_category_general(self, store, handler, tmp_dirs):
        node = _make_node(store, title="Default Cat")
        result = handler.handle("append_log", {"node_id": node.id, "content": "Normal log"})
        assert result.success is True
        _, _, narr_dir = tmp_dirs
        content = open(os.path.join(narr_dir, f"{node.id}.md")).read()
        assert "[general]" in content

    def test_append_log_invalid_category_rejected(self, store, handler):
        node = _make_node(store, title="Invalid Cat")
        result = handler.handle("append_log", {
            "node_id": node.id, "content": "test", "category": "invalid_category",
        })
        assert result.success is False
        assert "category" in result.error.lower()
```

- [ ] **Step 9: Run all tests**

Run: `/opt/homebrew/opt/python@3.11/bin/python3.11 -m pytest tests/test_narrative.py tests/test_tools.py -v`
Expected: ALL PASS

- [ ] **Step 10: Commit**

```bash
cd "/Users/ontanetwork/Documents/Onta Network/Founder OS/MemoryFPMS/V4"
git add fpms/spine/models.py fpms/spine/narrative.py fpms/spine/tools.py tests/test_narrative.py tests/test_tools.py
git commit -m "feat(v0.3): add category field to narrative entries and append_log tool

Header format: ## {ts} [{event_type}] [{category}]
read_narrative gains categories filter param.
append_log validates category against allowed set.
Default: general. Backward compat with old entries preserved."
```

---

### Task 3: Full-text search (FTS5)

**Files:**
- Modify: `fpms/spine/schema.py` (add FTS5 table)
- Modify: `fpms/spine/store.py` (add search_fts + index maintenance)
- Modify: `fpms/spine/tools.py` (add `query` param to search_nodes)
- Create: `tests/test_fts.py`

- [ ] **Step 1: Write failing tests for full-text search**

Create `tests/test_fts.py`:

```python
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
        node = _make_node(store, "task-b1", "Build API")
        narrative_mod.append_narrative(narr_dir, "task-b1", "2025-01-15T10:00:00Z", "log",
                                        "Decided to use Redis for caching", category="decision")

        store.index_narrative("task-b1", narr_dir)
        results = store.search_fts("Redis caching")
        assert len(results) >= 1
        assert any(r.id == "task-b1" for r in results)

    def test_search_chinese(self, store):
        _make_node(store, "task-c1", "实现支付系统")
        _make_node(store, "task-c2", "设计用户界面")

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
        node = _make_node(store, "task-f1", "Archived payment task")
        with store.transaction():
            store._update_node_inner("task-f1", {"archived_at": "2025-01-01T00:00:00Z"})

        results = store.search_fts("payment")
        assert len(results) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/opt/homebrew/opt/python@3.11/bin/python3.11 -m pytest tests/test_fts.py -v`
Expected: FAIL — `store.search_fts` does not exist.

- [ ] **Step 3: Add FTS5 virtual table to schema.py**

In `fpms/spine/schema.py`, append to `_SCHEMA_SQL`:

```sql
-- Full-text search index (FTS5) — regular (not contentless) table
CREATE VIRTUAL TABLE IF NOT EXISTS fts_index USING fts5(
    node_id UNINDEXED,
    title,
    narrative_text,
    knowledge_text,
    tokenize='unicode61'
);
```

- [ ] **Step 4: Implement search_fts and index maintenance in store.py**

In `fpms/spine/store.py`, add methods:

```python
def search_fts(self, query: str, limit: int = 20) -> List[Node]:
    """Full-text search across titles, narratives, knowledge. Excludes archived."""
    if not query.strip():
        return []

    # Ensure all nodes are indexed (incremental — only missing ones)
    self._ensure_fts_indexed()

    cols = self._node_columns()
    sql = """
        SELECT n.* FROM nodes n
        JOIN fts_index f ON n.id = f.node_id
        WHERE fts_index MATCH ? AND n.archived_at IS NULL
        GROUP BY n.id
        ORDER BY rank
        LIMIT ?
    """
    try:
        rows = self._conn.execute(sql, (query, limit)).fetchall()
    except Exception:
        # FTS query syntax error — fall back to LIKE
        return self._search_like_fallback(query, limit)
    return [_row_to_node(r, cols) for r in rows]

def _ensure_fts_indexed(self) -> None:
    """Ensure all non-archived nodes have an FTS entry (incremental)."""
    # Find nodes missing from FTS index
    sql = """
        SELECT n.id, n.title FROM nodes n
        WHERE n.archived_at IS NULL
        AND n.id NOT IN (SELECT node_id FROM fts_index)
    """
    rows = self._conn.execute(sql).fetchall()
    for node_id, title in rows:
        self._conn.execute(
            "INSERT INTO fts_index (node_id, title, narrative_text, knowledge_text) VALUES (?,?,?,?)",
            (node_id, title or "", "", ""),
        )

def index_narrative(self, node_id: str, narratives_dir: str) -> None:
    """Index (or re-index) a node's narrative content into FTS."""
    from . import narrative as narrative_mod
    text = narrative_mod.read_narrative(narratives_dir, node_id)
    node = self.get_node(node_id)
    title = node.title if node else ""
    # Upsert: delete old entry, insert fresh
    self._conn.execute("DELETE FROM fts_index WHERE node_id=?", (node_id,))
    self._conn.execute(
        "INSERT INTO fts_index (node_id, title, narrative_text, knowledge_text) VALUES (?,?,?,?)",
        (node_id, title, text or "", ""),
    )

def index_knowledge(self, node_id: str, knowledge_dir: str) -> None:
    """Index (or re-index) a node's knowledge content into FTS."""
    from .knowledge import get_knowledge
    docs = get_knowledge(knowledge_dir, node_id)
    knowledge_text = "\n\n".join(docs.values()) if isinstance(docs, dict) else ""
    node = self.get_node(node_id)
    title = node.title if node else ""
    # Read existing narrative text to preserve it
    existing = self._conn.execute(
        "SELECT narrative_text FROM fts_index WHERE node_id=?", (node_id,)
    ).fetchone()
    narrative_text = existing[0] if existing else ""
    self._conn.execute("DELETE FROM fts_index WHERE node_id=?", (node_id,))
    self._conn.execute(
        "INSERT INTO fts_index (node_id, title, narrative_text, knowledge_text) VALUES (?,?,?,?)",
        (node_id, title, narrative_text, knowledge_text),
    )

def _search_like_fallback(self, query: str, limit: int) -> List[Node]:
    """Fallback LIKE search when FTS query fails."""
    cols = self._node_columns()
    pattern = f"%{query}%"
    sql = "SELECT * FROM nodes WHERE title LIKE ? AND archived_at IS NULL LIMIT ?"
    rows = self._conn.execute(sql, (pattern, limit)).fetchall()
    return [_row_to_node(r, cols) for r in rows]
```

- [ ] **Step 5: Add `query` param to handle_search_nodes in tools.py**

In `fpms/spine/tools.py`, update `handle_search_nodes`:

```python
def handle_search_nodes(self, params: dict) -> ToolResult:
    command_id = params.get("command_id", "")
    query = params.get("query")  # NEW: full-text search query
    filters = params.get("filters", {})
    limit = params.get("limit", 50)
    offset = params.get("offset", 0)
    include_summary = params.get("include_summary", False)

    # If query is provided, use FTS
    if query:
        nodes = self.store.search_fts(query, limit=limit)
    else:
        nodes = self.store.list_nodes(filters=filters, limit=limit, offset=offset)

    results = []
    for n in nodes:
        d = _node_to_dict(n)
        if not include_summary:
            d.pop("summary", None)
        results.append(d)

    return ToolResult(
        success=True,
        command_id=command_id,
        data={"nodes": results, "count": len(results)},
    )
```

- [ ] **Step 6: Run tests**

Run: `/opt/homebrew/opt/python@3.11/bin/python3.11 -m pytest tests/test_fts.py -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
cd "/Users/ontanetwork/Documents/Onta Network/Founder OS/MemoryFPMS/V4"
git add fpms/spine/schema.py fpms/spine/store.py fpms/spine/tools.py tests/test_fts.py
git commit -m "feat(v0.3): add FTS5 full-text search for titles and narratives

SQLite FTS5 virtual table with unicode61 tokenizer.
search_nodes gains query param for full-text search.
Replaces soft-link concept — search finds related nodes on demand."
```

---

### Task 4: Role prompt files

**Files:**
- Create: `fpms/prompts/strategy.md`
- Create: `fpms/prompts/review.md`
- Create: `fpms/prompts/execution.md`

- [ ] **Step 1: Create strategy.md (中书省)**

Create `fpms/prompts/strategy.md`:

```markdown
# 中书省 — Strategy Role

你是需求决策者。你的职责是判断该不该做、做什么、优先级如何。

## 关注点

- 用户痛点是什么？这个需求解决什么问题？
- 投入产出比：值不值得做？
- 优先级：和其他工作比，这个排第几？
- 范围：做多少？MVP 是什么？

## 思维方式

- 从用户视角出发，不从技术视角出发
- 先问"为什么做"，再问"做什么"
- 量化收益：影响多少用户？节省多少时间？
- 识别隐性成本：维护成本、机会成本、认知负担

## 产出

- 需求文档（存入 knowledge）
- 优先级判断 + 理由
- 范围定义（做什么 + 不做什么）

## 不做什么

- 不评估技术可行性（尚书省的事）
- 不翻历史教训（门下省的事）
- 不写代码
```

- [ ] **Step 2: Create review.md (门下省)**

Create `fpms/prompts/review.md`:

```markdown
# 门下省 — Review Role

你是经验审查者。你的职责是翻历史教训、检查风险、防止踩坑。

## 关注点

- 历史上类似的事情怎么做的？结果如何？
- 有什么风险？不可逆操作？
- 会不会影响现有功能？
- 有没有遗漏的边界情况？

## 思维方式

- 悲观主义：假设会出错，找出出错的路径
- 基于证据：引用具体的历史记录，不凭感觉
- 量化风险：影响范围、发生概率、恢复成本
- 关注不可逆操作：数据删除、API 发布、合同签署

## 产出

- 通过 / 打回 + 理由
- 风险标注（存入 narrative，category=risk）
- 改进建议

## 不做什么

- 不做需求决策（中书省的事）
- 不写代码（尚书省的事）
- 不优化方案（只审查风险）
```

- [ ] **Step 3: Create execution.md (尚书省)**

Create `fpms/prompts/execution.md`:

```markdown
# 尚书省 — Execution Role

你是工程执行者。你的职责是评估工程可行性、设计方案、执行实现。

## 关注点

- 技术可行性：现有代码能支持吗？
- 方案设计：怎么做最优？有几种方案？
- 成本估算：多长时间？多复杂？
- 验收标准：怎么验证做完了？

## 思维方式

- 从代码出发，不从愿景出发
- 先看现有架构，再决定改动方式
- 最小改动原则：改最少的代码达到目标
- 测试驱动：先定验收标准，再写代码

## 产出

- 工程评审：通过 / 打回 + 理由
- 验收文档（存入 knowledge）
- 任务拆解 + 执行
- 技术记录（存入 narrative，category=technical）

## 不做什么

- 不做需求决策（中书省的事）
- 不翻历史教训（门下省的事）
- 不质疑需求本身（只评估可行性）
```

- [ ] **Step 4: Commit**

```bash
cd "/Users/ontanetwork/Documents/Onta Network/Founder OS/MemoryFPMS/V4"
mkdir -p fpms/prompts
git add fpms/prompts/strategy.md fpms/prompts/review.md fpms/prompts/execution.md
git commit -m "feat(v0.3): add role prompt files for 三省 Protocol

strategy.md (中书省), review.md (门下省), execution.md (尚书省).
Each role focuses on one responsibility only."
```

---

### Task 5: BundleAssembler role-based filtering + token budgets

**Files:**
- Modify: `fpms/spine/bundle.py` (add `role` param, category filtering, budgets)
- Modify: `tests/test_bundle.py`

- [ ] **Step 1: Write failing tests for role-based filtering**

Append to `tests/test_bundle.py` (adapt to existing test fixture patterns in that file):

```python
class TestRoleBasedFiltering:
    """Role-based context filtering (v0.3 Work Mode)."""

    def _setup_categorized_narrative(self, store, narratives_dir):
        """Create a node with narrative entries of different categories."""
        from fpms.spine import narrative as narrative_mod
        # Create node using existing test patterns
        focus = _make_node("task-role", title="Role Test", status="active",
                           summary="Test summary", why="Test reason")
        _insert_node(store, focus)

        narrative_mod.append_narrative(narratives_dir, "task-role", "2025-01-15T10:00:00Z",
                                       "log", "Strategic decision made", category="decision")
        narrative_mod.append_narrative(narratives_dir, "task-role", "2025-01-15T11:00:00Z",
                                       "log", "User feedback received", category="feedback")
        narrative_mod.append_narrative(narratives_dir, "task-role", "2025-01-15T12:00:00Z",
                                       "log", "Risk identified", category="risk")
        narrative_mod.append_narrative(narratives_dir, "task-role", "2025-01-15T13:00:00Z",
                                       "log", "Code implemented", category="technical")
        narrative_mod.append_narrative(narratives_dir, "task-role", "2025-01-15T14:00:00Z",
                                       "log", "Task 50% done", category="progress")

    def test_role_all_returns_all(self, store, narratives_dir):
        self._setup_categorized_narrative(store, narratives_dir)
        assembler = _make_assembler(store, narratives_dir)
        bundle = assembler.assemble(focus_node_id="task-role", role="all")
        assert "Strategic decision made" in bundle.l2_focus
        assert "Code implemented" in bundle.l2_focus

    def test_role_execution_excludes_decision_feedback(self, store, narratives_dir):
        self._setup_categorized_narrative(store, narratives_dir)
        assembler = _make_assembler(store, narratives_dir)
        bundle = assembler.assemble(focus_node_id="task-role", role="execution")
        assert "Code implemented" in bundle.l2_focus
        assert "Task 50% done" in bundle.l2_focus
        assert "Strategic decision made" not in bundle.l2_focus
        assert "User feedback received" not in bundle.l2_focus

    def test_role_strategy_excludes_technical_progress(self, store, narratives_dir):
        self._setup_categorized_narrative(store, narratives_dir)
        assembler = _make_assembler(store, narratives_dir)
        bundle = assembler.assemble(focus_node_id="task-role", role="strategy")
        assert "Strategic decision made" in bundle.l2_focus
        assert "User feedback received" in bundle.l2_focus
        assert "Code implemented" not in bundle.l2_focus
        assert "Task 50% done" not in bundle.l2_focus

    def test_role_review_includes_risk_excludes_decision_technical(self, store, narratives_dir):
        self._setup_categorized_narrative(store, narratives_dir)
        assembler = _make_assembler(store, narratives_dir)
        bundle = assembler.assemble(focus_node_id="task-role", role="review")
        assert "Risk identified" in bundle.l2_focus
        assert "Strategic decision made" not in bundle.l2_focus
        assert "Code implemented" not in bundle.l2_focus

    def test_default_role_is_all(self, store, narratives_dir):
        self._setup_categorized_narrative(store, narratives_dir)
        assembler = _make_assembler(store, narratives_dir)
        bundle = assembler.assemble(focus_node_id="task-role")
        assert "Strategic decision made" in bundle.l2_focus
        assert "Code implemented" in bundle.l2_focus

    def test_execution_role_no_l0(self, store, narratives_dir):
        focus = _make_node("task-exec", title="Exec", status="active", summary="s")
        _insert_node(store, focus)
        assembler = _make_assembler(store, narratives_dir)
        bundle = assembler.assemble(focus_node_id="task-exec", role="execution")
        assert assembler._estimate_tokens(bundle.l0_dashboard) <= 50

    def test_strategy_role_has_l0(self, store, narratives_dir):
        focus = _make_node("task-strat", title="Strat", status="active", summary="s", is_root=True)
        _insert_node(store, focus)
        assembler = _make_assembler(store, narratives_dir)
        bundle = assembler.assemble(focus_node_id="task-strat", role="strategy")
        assert "# Dashboard" in bundle.l0_dashboard
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/opt/homebrew/opt/python@3.11/bin/python3.11 -m pytest tests/test_bundle.py::TestRoleBasedFiltering -v`
Expected: FAIL — `assemble()` doesn't accept `role`.

- [ ] **Step 3: Add role constants to bundle.py**

At top of `fpms/spine/bundle.py`, after existing constants:

```python
# Role → narrative categories to include (None = no filtering)
_ROLE_CATEGORIES = {
    "strategy":  {"decision", "feedback"},
    "review":    {"risk", "progress"},
    "execution": {"technical", "progress"},
    "all":       None,
}

# Role → token budget allocation
_ROLE_BUDGETS = {
    "execution": {"total": 8000, "l0": 0,    "l1": 3000, "l2": 5000},
    "strategy":  {"total": 8000, "l0": 2000, "l1": 3000, "l2": 3000},
    "review":    {"total": 8000, "l0": 1000, "l1": 2000, "l2": 5000},
    "all":       {"total": 10000, "l0": None, "l1": None, "l2": None},
}
```

- [ ] **Step 4: Update assemble() signature and body**

Add `role: str = "all"` param. Inside body:
1. Look up budget from `_ROLE_BUDGETS[role]`, override `max_tokens`
2. When `l0` budget is 0, set `l0 = ""`
3. Pass `categories=_ROLE_CATEGORIES.get(role)` to `_build_l2`

- [ ] **Step 5: Update _build_l2 to accept categories**

Add `categories: Optional[set] = None` param. Pass to `read_narrative`:

```python
narrative = self._narrative_mod.read_narrative(
    self._narratives_dir, focus_node_id, last_n_entries=5,
    categories=list(categories) if categories else None,
)
```

- [ ] **Step 6: Run tests**

Run: `/opt/homebrew/opt/python@3.11/bin/python3.11 -m pytest tests/test_bundle.py -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
cd "/Users/ontanetwork/Documents/Onta Network/Founder OS/MemoryFPMS/V4"
git add fpms/spine/bundle.py tests/test_bundle.py
git commit -m "feat(v0.3): role-based context filtering and token budgets in BundleAssembler

Roles: strategy(decision+feedback), review(risk+progress), execution(technical+progress), all(default).
Each role has different token budget. execution skips L0 dashboard."
```

---

### Task 6: Workbench + SpineEngine wiring

**Files:**
- Modify: `fpms/spine/__init__.py` (add activate_workbench, get_context_bundle role param, wire knowledge)
- Create: `tests/test_workbench.py`

- [ ] **Step 1: Write failing tests for activate_workbench**

Create `tests/test_workbench.py`:

```python
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
        assert isinstance(wb, dict)
        for key in ("goal", "context", "subtasks", "suggested_next", "token_budget"):
            assert key in wb

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/opt/homebrew/opt/python@3.11/bin/python3.11 -m pytest tests/test_workbench.py -v`
Expected: FAIL — no `activate_workbench` method.

- [ ] **Step 3: Implement activate_workbench in SpineEngine**

In `fpms/spine/__init__.py`, add:
1. `activate_workbench(node_id, role)` — assembles workbench dict
2. `_sort_subtasks_by_deps(children)` — topological sort via Kahn's algorithm
3. `_extract_narrative_by_category(node_id, category)` — extracts structured entries
4. Update `get_context_bundle` to accept `role` param and pass through
5. Wire `knowledge_dir` in `__init__`

Full implementation code:

```python
def activate_workbench(self, node_id: str, role: str = "execution") -> dict:
    """Activate the workbench — prepare AI working context. Stateless."""
    from .bundle import _ROLE_BUDGETS
    from . import knowledge as knowledge_mod

    node = self._store.get_node(node_id)
    if node is None:
        raise ValueError(f"Node '{node_id}' not found")

    # Role-filtered context bundle
    bundle = self._bundle_assembler.assemble(focus_node_id=node_id, role=role)

    # Assemble context text
    context_parts = []
    if bundle.l0_dashboard.strip():
        context_parts.append(bundle.l0_dashboard)
    if bundle.l_alert.strip() and "No alerts" not in bundle.l_alert:
        context_parts.append(bundle.l_alert)
    context_parts.append(bundle.l1_neighborhood)
    context_parts.append(bundle.l2_focus)
    context_text = "\n\n".join(context_parts)

    # Knowledge docs (with inheritance)
    knowledge = knowledge_mod.get_knowledge(
        self._knowledge_dir, node_id, store=self._store, inherit=True,
    )

    # Subtasks sorted by dependency
    children = self._store.get_children(node_id, include_archived=False)
    subtasks = self._sort_subtasks_by_deps(children)

    # Suggested next: first non-terminal subtask
    suggested_next = None
    for st in subtasks:
        if st["status"] not in ("done", "dropped"):
            suggested_next = {"id": st["id"], "title": st["title"]}
            break

    # Role-specific narrative extractions
    decisions = self._extract_narrative_by_category(node_id, "decision")
    risks = self._extract_narrative_by_category(node_id, "risk")

    # Role prompt
    role_prompt = self._load_role_prompt(role)

    # Token budget
    budget = _ROLE_BUDGETS.get(role, _ROLE_BUDGETS["all"])

    result = {
        "goal": node.title,
        "knowledge": knowledge if isinstance(knowledge, dict) else {},
        "context": context_text,
        "subtasks": subtasks,
        "suggested_next": suggested_next,
        "role_prompt": role_prompt,
        "token_budget": {
            "total": budget["total"],
            "l0": budget.get("l0") or 0,
            "l1": budget.get("l1") or 0,
            "l2": budget.get("l2") or 0,
        },
    }

    # Add role-specific fields
    if role == "strategy":
        result["decisions"] = decisions
    elif role == "review":
        result["risks"] = risks

    return result


def _sort_subtasks_by_deps(self, children: list) -> list:
    """Topological sort of subtasks by dependency order (Kahn's algorithm)."""
    from dataclasses import asdict
    if not children:
        return []

    child_ids = {c.id for c in children}
    child_map = {c.id: c for c in children}

    # Build adjacency: which children depend on which other children
    deps = {}
    for c in children:
        child_deps = self._store.get_dependencies(c.id)
        deps[c.id] = {d.id for d in child_deps if d.id in child_ids}

    # Kahn's algorithm
    in_degree = {cid: len(deps.get(cid, set())) for cid in child_ids}
    queue = sorted(cid for cid in child_ids if in_degree[cid] == 0)
    sorted_ids = []

    while queue:
        current = queue.pop(0)
        sorted_ids.append(current)
        for cid in child_ids:
            if current in deps.get(cid, set()):
                in_degree[cid] -= 1
                if in_degree[cid] == 0:
                    queue.append(cid)
        queue.sort()

    # Add any remaining (cycle — shouldn't happen with DAG safety)
    for cid in child_ids:
        if cid not in sorted_ids:
            sorted_ids.append(cid)

    return [
        {"id": child_map[cid].id, "title": child_map[cid].title,
         "status": child_map[cid].status, "summary": child_map[cid].summary}
        for cid in sorted_ids
    ]


def _extract_narrative_by_category(self, node_id: str, category: str) -> list:
    """Extract narrative entries of a specific category as structured list."""
    raw = self._narrative_mod.read_narrative(
        self._narratives_dir, node_id, categories=[category]
    )
    if not raw.strip():
        return []
    entries = []
    for block in raw.split("\n## "):
        block = block.strip()
        if not block:
            continue
        if not block.startswith("## "):
            block = "## " + block
        lines = block.split("\n", 1)
        content = lines[1].strip() if len(lines) > 1 else ""
        if content:
            entries.append({"content": content})
    return entries


def _load_role_prompt(self, role: str) -> str:
    """Load role prompt from fpms/prompts/{role}.md."""
    prompt_map = {"strategy": "strategy", "review": "review", "execution": "execution"}
    filename = prompt_map.get(role)
    if not filename:
        return ""
    import fpms
    pkg_dir = os.path.dirname(fpms.__file__)
    prompt_path = os.path.join(pkg_dir, "prompts", f"{filename}.md")
    if os.path.exists(prompt_path):
        with open(prompt_path) as f:
            return f.read()
    return ""
```

- [ ] **Step 4: Run tests**

Run: `/opt/homebrew/opt/python@3.11/bin/python3.11 -m pytest tests/test_workbench.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
cd "/Users/ontanetwork/Documents/Onta Network/Founder OS/MemoryFPMS/V4"
git add fpms/spine/__init__.py tests/test_workbench.py
git commit -m "feat(v0.3): add activate_workbench with role prompts and dep-sorted subtasks

Stateless workbench: one call returns goal, context, subtasks, suggested_next,
role_prompt, token_budget. Subtasks topologically sorted by dependencies."
```

---

### Task 7: MCP tools (3 new + 3 updated)

**Files:**
- Modify: `fpms/mcp_server.py`
- Modify: `tests/test_mcp_server.py`

- [ ] **Step 1: Update existing MCP tools**

In `fpms/mcp_server.py`:

1. **append_log** — add `category: str = "general"` param, pass to execute_tool
2. **get_context_bundle** — add `role: str = "all"` param, pass to `engine.get_context_bundle`
3. **search_nodes** — add `query: Optional[str] = None` param, pass to execute_tool

- [ ] **Step 2: Add new MCP tools**

```python
@mcp.tool()
@_safe_tool
def activate_workbench(node_id: str, role: str = "execution") -> str:
    """Activate the AI workbench for a task — prepare the working context.

    Returns goal, role-filtered context, subtasks (dependency-sorted),
    suggested next step, role prompt, and token budget.

    Args:
        node_id: The task/node to prepare the workbench for
        role: Context role — strategy|review|execution (default: execution)
    """
    wb = _get_engine().activate_workbench(node_id, role=role)
    return json.dumps(wb, ensure_ascii=False, default=str)


@mcp.tool()
@_safe_tool
def set_knowledge(node_id: str, doc_type: str, content: str) -> str:
    """Set a knowledge document for a node.

    Args:
        node_id: Target node ID
        doc_type: Document type (overview|requirements|architecture|custom)
        content: Markdown content
    """
    from fpms.spine import knowledge as knowledge_mod
    engine = _get_engine()
    node = engine.store.get_node(node_id)
    if node is None:
        return json.dumps({"success": False, "error": f"Node '{node_id}' not found"})
    knowledge_mod.set_knowledge(engine._knowledge_dir, node_id, doc_type, content)
    return json.dumps({"success": True, "node_id": node_id, "doc_type": doc_type})


@mcp.tool()
@_safe_tool
def get_knowledge(
    node_id: str,
    doc_type: Optional[str] = None,
    inherit: bool = True,
) -> str:
    """Get knowledge documents for a node (with optional parent inheritance).

    Args:
        node_id: Target node ID
        doc_type: Specific doc type (None = return all)
        inherit: Walk up parent chain for missing docs (default: True)
    """
    from fpms.spine import knowledge as knowledge_mod
    engine = _get_engine()
    result = knowledge_mod.get_knowledge(
        engine._knowledge_dir, node_id, doc_type=doc_type,
        store=engine.store, inherit=inherit,
    )
    return json.dumps({"success": True, "knowledge": result}, ensure_ascii=False)
```

- [ ] **Step 3: Wire knowledge_dir in SpineEngine.__init__**

In `fpms/spine/__init__.py`, add to `__init__`:

```python
self._knowledge_dir = os.path.join(os.path.dirname(narratives_dir), "knowledge")
```

- [ ] **Step 4: Run full test suite**

Run: `/opt/homebrew/opt/python@3.11/bin/python3.11 -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
cd "/Users/ontanetwork/Documents/Onta Network/Founder OS/MemoryFPMS/V4"
git add fpms/mcp_server.py fpms/spine/__init__.py tests/test_mcp_server.py
git commit -m "feat(v0.3): add MCP tools — activate_workbench, set/get_knowledge, update append_log/search_nodes/get_context_bundle"
```

---

### Task 8: 三省 Protocol logic

**Files:**
- Modify: `fpms/spine/__init__.py` (add sansei_review method)
- Create: `tests/test_sansei.py`

- [ ] **Step 1: Write failing tests for 三省 Protocol**

Create `tests/test_sansei.py`:

```python
"""Tests for 三省 Protocol — parallel review with rejection loop."""

from __future__ import annotations

import pytest

from fpms.spine import SpineEngine


@pytest.fixture
def engine(tmp_path):
    return SpineEngine(
        db_path=str(tmp_path / "test.db"),
        events_path=str(tmp_path / "events.jsonl"),
        narratives_dir=str(tmp_path / "narratives"),
    )


def _create(engine, title, **kw):
    params = {"title": title, "is_root": True, **kw}
    return engine.execute_tool("create_node", params).data["id"]


class TestSanseiProtocol:

    def test_review_result_structure(self, engine):
        """sansei_review returns structured result with review/engineer verdicts."""
        nid = _create(engine, "Feature X", summary="New feature")
        engine.execute_tool("update_status", {"node_id": nid, "new_status": "active"})

        result = engine.sansei_review(nid, proposal="Build payment system with Stripe")
        assert "review_verdict" in result
        assert "engineer_verdict" in result
        assert "approved" in result
        assert "rejection_count" in result

    def test_both_approve_means_approved(self, engine):
        """When both review and engineer approve, result is approved."""
        nid = _create(engine, "Simple Task", summary="Easy")
        engine.execute_tool("update_status", {"node_id": nid, "new_status": "active"})

        result = engine.sansei_review(
            nid,
            proposal="Add a button",
            review_verdict={"approved": True, "reason": "No risk"},
            engineer_verdict={"approved": True, "reason": "Feasible"},
        )
        assert result["approved"] is True

    def test_review_rejects_means_not_approved(self, engine):
        nid = _create(engine, "Risky Task", summary="Risky")
        engine.execute_tool("update_status", {"node_id": nid, "new_status": "active"})

        result = engine.sansei_review(
            nid,
            proposal="Delete all user data",
            review_verdict={"approved": False, "reason": "Too risky"},
            engineer_verdict={"approved": True, "reason": "Feasible"},
        )
        assert result["approved"] is False

    def test_engineer_rejects_means_not_approved(self, engine):
        nid = _create(engine, "Impossible Task", summary="Hard")
        engine.execute_tool("update_status", {"node_id": nid, "new_status": "active"})

        result = engine.sansei_review(
            nid,
            proposal="Rewrite in Haskell overnight",
            review_verdict={"approved": True, "reason": "No risk"},
            engineer_verdict={"approved": False, "reason": "Not feasible"},
        )
        assert result["approved"] is False

    def test_rejection_count_tracked(self, engine):
        """Each rejection increments the count."""
        nid = _create(engine, "Iterating", summary="Will iterate")
        engine.execute_tool("update_status", {"node_id": nid, "new_status": "active"})

        r1 = engine.sansei_review(nid, proposal="v1",
            review_verdict={"approved": False, "reason": "Needs work"},
            engineer_verdict={"approved": True, "reason": "OK"})
        assert r1["rejection_count"] == 1

        r2 = engine.sansei_review(nid, proposal="v2",
            review_verdict={"approved": False, "reason": "Still not good"},
            engineer_verdict={"approved": True, "reason": "OK"})
        assert r2["rejection_count"] == 2

    def test_max_3_rejections_escalates(self, engine):
        """After 3 rejections, escalate_to_human is True."""
        nid = _create(engine, "Stuck", summary="Stuck task")
        engine.execute_tool("update_status", {"node_id": nid, "new_status": "active"})

        for i in range(3):
            engine.sansei_review(nid, proposal=f"attempt {i+1}",
                review_verdict={"approved": False, "reason": f"Nope {i+1}"},
                engineer_verdict={"approved": True, "reason": "OK"})

        r4 = engine.sansei_review(nid, proposal="attempt 4",
            review_verdict={"approved": False, "reason": "Nope 4"},
            engineer_verdict={"approved": True, "reason": "OK"})
        assert r4["escalate_to_human"] is True

    def test_rejection_reason_logged_to_narrative(self, engine):
        """Rejection reasons are appended to node narrative."""
        nid = _create(engine, "Logged", summary="With logs")
        engine.execute_tool("update_status", {"node_id": nid, "new_status": "active"})

        engine.sansei_review(nid, proposal="Bad idea",
            review_verdict={"approved": False, "reason": "Historical lesson: this failed before"},
            engineer_verdict={"approved": True, "reason": "OK"})

        from fpms.spine import narrative as narr
        text = narr.read_narrative(engine._narratives_dir, nid)
        assert "Historical lesson" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/opt/homebrew/opt/python@3.11/bin/python3.11 -m pytest tests/test_sansei.py -v`
Expected: FAIL — no `sansei_review` method.

- [ ] **Step 3: Implement sansei_review in SpineEngine**

In `fpms/spine/__init__.py`, add:

```python
def sansei_review(
    self,
    node_id: str,
    proposal: str,
    review_verdict: dict | None = None,
    engineer_verdict: dict | None = None,
) -> dict:
    """三省 Protocol: parallel review by 门下省 + 尚书省.

    Args:
        node_id: Node being reviewed
        proposal: The proposal text from 中书省
        review_verdict: {approved: bool, reason: str} from 门下省
        engineer_verdict: {approved: bool, reason: str} from 尚书省

    Returns dict with:
        approved, review_verdict, engineer_verdict, rejection_count, escalate_to_human
    """
    from datetime import datetime, timezone

    node = self._store.get_node(node_id)
    if node is None:
        raise ValueError(f"Node '{node_id}' not found")

    # Get/update rejection count from session state
    review_state = self._store.get_session(f"sansei_{node_id}") or {"rejection_count": 0}
    rejection_count = review_state["rejection_count"]

    # Default verdicts (for testing — in real use, AI agents provide these)
    if review_verdict is None:
        review_verdict = {"approved": True, "reason": "No issues found"}
    if engineer_verdict is None:
        engineer_verdict = {"approved": True, "reason": "Feasible"}

    approved = review_verdict["approved"] and engineer_verdict["approved"]

    now = datetime.now(timezone.utc).isoformat()

    if not approved:
        rejection_count += 1
        # Log rejection reasons to narrative
        if not review_verdict["approved"]:
            self._narrative_mod.append_narrative(
                self._narratives_dir, node_id, now, "review_rejected",
                f"门下省打回: {review_verdict['reason']}", category="risk",
            )
        if not engineer_verdict["approved"]:
            self._narrative_mod.append_narrative(
                self._narratives_dir, node_id, now, "engineer_rejected",
                f"尚书省打回: {engineer_verdict['reason']}", category="technical",
            )
    else:
        # Log approval
        self._narrative_mod.append_narrative(
            self._narratives_dir, node_id, now, "review_approved",
            f"三省审查通过: {proposal[:100]}", category="decision",
        )

    # Persist rejection count
    with self._store.transaction():
        self._store.set_session(f"sansei_{node_id}", {"rejection_count": rejection_count})

    escalate = rejection_count > 3

    return {
        "approved": approved,
        "review_verdict": review_verdict,
        "engineer_verdict": engineer_verdict,
        "rejection_count": rejection_count,
        "escalate_to_human": escalate,
        "proposal": proposal,
    }
```

- [ ] **Step 4: Run tests**

Run: `/opt/homebrew/opt/python@3.11/bin/python3.11 -m pytest tests/test_sansei.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
cd "/Users/ontanetwork/Documents/Onta Network/Founder OS/MemoryFPMS/V4"
git add fpms/spine/__init__.py tests/test_sansei.py
git commit -m "feat(v0.3): add 三省 Protocol — parallel review with max 3 rejections

sansei_review accepts parallel verdicts from 门下省 + 尚书省.
Both must approve. Rejections logged to narrative. >3 rejections escalates to human."
```

---

### Task 9: Final verification + docs

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `SYSTEM-CONFIG.md`

- [ ] **Step 1: Run full test suite**

Run: `/opt/homebrew/opt/python@3.11/bin/python3.11 -m pytest tests/ -v`
Expected: 584 existing tests + all new tests GREEN

- [ ] **Step 2: Run acceptance tests manually**

Verify key acceptance scenarios from `4-implementation/v03-acceptance.md`:
- append_log with category works
- role-based bundle filtering works
- activate_workbench returns correct structure
- 三省 rejection counting works

- [ ] **Step 3: Update CHANGELOG.md**

Add v0.3.0 entry with all new features.

- [ ] **Step 4: Update SYSTEM-CONFIG.md**

Add role token budget section.

- [ ] **Step 5: Commit**

```bash
cd "/Users/ontanetwork/Documents/Onta Network/Founder OS/MemoryFPMS/V4"
git add CHANGELOG.md SYSTEM-CONFIG.md
git commit -m "docs(v0.3): update CHANGELOG and SYSTEM-CONFIG for v0.3.0"
```
