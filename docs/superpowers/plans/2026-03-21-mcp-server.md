# FPMS MCP Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wrap SpineEngine's 15 tools + heartbeat + bootstrap + get_context_bundle as a standard MCP server for Claude Desktop / Claude Code / OpenClaw.

**Architecture:** Single file `mcp_server.py` using FastMCP decorator pattern. Each SpineEngine tool becomes an `@mcp.tool()` function. Engine initialized once at module level. stdio transport for universal compatibility.

**Tech Stack:** Python 3.11+, `mcp[cli]` (FastMCP), existing `fpms.spine.SpineEngine`

---

## File Structure

| Action | Path | Responsibility |
|--------|------|---------------|
| Create | `fpms/mcp_server.py` | MCP server: tool definitions, engine init, entry point |
| Create | `tests/test_mcp_server.py` | Unit tests: tool registration, parameter mapping, error handling |
| Modify | `pyproject.toml` or `requirements.txt` | Add `mcp[cli]` dependency |

---

### Task 1: Project Setup + Dependency

**Files:**
- Modify: `/Users/ontanetwork/Documents/Onta Network/Founder OS/MemoryFPMS/V4/requirements.txt` (create if not exists)

- [ ] **Step 1: Add mcp dependency**

Check if `pyproject.toml` or `requirements.txt` exists. Add `mcp[cli]>=1.2.0` to dependencies.

```
# requirements.txt
pydantic>=2.0
httpx>=0.24
mcp[cli]>=1.2.0
```

- [ ] **Step 2: Install dependency**

Run: `pip install "mcp[cli]>=1.2.0"`

- [ ] **Step 3: Verify import works**

Run: `python -c "from mcp.server.fastmcp import FastMCP; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "chore: add mcp[cli] dependency for MCP server"
```

---

### Task 2: MCP Server — Write Tools (10)

**Files:**
- Create: `/Users/ontanetwork/Documents/Onta Network/Founder OS/MemoryFPMS/V4/fpms/mcp_server.py`
- Test: `/Users/ontanetwork/Documents/Onta Network/Founder OS/MemoryFPMS/V4/tests/test_mcp_server.py`

- [ ] **Step 1: Write failing test for tool registration**

```python
# tests/test_mcp_server.py
"""MCP Server tool registration and execution tests."""

import json
import pytest


def test_server_has_all_tools():
    """Verify all 18 tools (15 spine + 3 system) are registered."""
    from fpms.mcp_server import mcp

    tools = mcp._tool_manager._tools  # FastMCP internal registry
    tool_names = set(tools.keys())

    # 15 SpineEngine tools
    spine_tools = {
        "create_node", "update_status", "update_field",
        "attach_node", "detach_node",
        "add_dependency", "remove_dependency",
        "append_log", "unarchive", "set_persistent",
        "shift_focus", "expand_context",
        "get_node", "search_nodes", "get_assembly_trace",
    }
    # 3 system tools
    system_tools = {"heartbeat", "bootstrap", "get_context_bundle"}

    expected = spine_tools | system_tools
    assert expected.issubset(tool_names), f"Missing tools: {expected - tool_names}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/ontanetwork/Documents/Onta\ Network/Founder\ OS/MemoryFPMS/V4 && python -m pytest tests/test_mcp_server.py::test_server_has_all_tools -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Write mcp_server.py — engine init + 10 write tools**

```python
# fpms/mcp_server.py
"""FPMS MCP Server — 将 SpineEngine 暴露为 MCP tools。

Usage:
  python -m fpms.mcp_server                     # stdio transport (default)
  FPMS_DB_PATH=./data/fpms.db python -m fpms.mcp_server  # custom DB path

Environment variables:
  FPMS_DB_PATH       — SQLite path (default: fpms/db/fpms.db)
  FPMS_EVENTS_PATH   — Events JSONL path (default: fpms/events.jsonl)
  FPMS_NARRATIVES_DIR — Narratives directory (default: fpms/narratives)
"""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import asdict
from typing import Optional

from mcp.server.fastmcp import FastMCP

from fpms.spine import SpineEngine

# --- Logging (stderr only for stdio transport) ---
logging.basicConfig(stream=sys.stderr, level=logging.INFO)
logger = logging.getLogger("fpms.mcp")

# --- Engine singleton ---
_engine: SpineEngine | None = None


def _get_engine() -> SpineEngine:
    global _engine
    if _engine is None:
        _engine = SpineEngine(
            db_path=os.environ.get("FPMS_DB_PATH", "fpms/db/fpms.db"),
            events_path=os.environ.get("FPMS_EVENTS_PATH", "fpms/events.jsonl"),
            narratives_dir=os.environ.get("FPMS_NARRATIVES_DIR", "fpms/narratives"),
        )
    return _engine


# --- FastMCP instance ---
mcp = FastMCP(
    "fpms",
    instructions=(
        "FPMS (Focal Point Memory System) is a cognitive memory engine. "
        "Use these tools to create/manage work items, track status, "
        "get context bundles for conversation injection, and run heartbeat scans."
    ),
)


def _result_to_str(result) -> str:
    """Convert ToolResult dataclass to JSON string."""
    return json.dumps(asdict(result), ensure_ascii=False, default=str)


def _safe_tool(fn):
    """Decorator: catch exceptions and return structured error JSON instead of crashing."""
    import functools

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            logger.exception("Tool %s failed", fn.__name__)
            return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)

    return wrapper


# =====================================================================
# Write Tools (10)
# =====================================================================


@mcp.tool()
@_safe_tool
def create_node(
    title: str,
    node_type: str = "unknown",
    parent_id: Optional[str] = None,
    is_root: bool = False,
    summary: Optional[str] = None,
    why: Optional[str] = None,
    next_step: Optional[str] = None,
    owner: Optional[str] = None,
    deadline: Optional[str] = None,
    source: str = "internal",
    source_id: Optional[str] = None,
    source_url: Optional[str] = None,
) -> str:
    """Create a new work item (node).

    Args:
        title: Node title (required)
        node_type: goal|project|milestone|task|unknown
        parent_id: Parent node ID (mutually exclusive with is_root=True)
        is_root: Mark as root node (no parent)
        summary: Brief description
        why: Reason / context for this node
        next_step: Suggested next action
        owner: Assignee
        deadline: ISO 8601 deadline (e.g. 2026-03-25T18:00:00+08:00)
        source: Data source (internal|github|notion)
        source_id: External source object ID
        source_url: External source URL
    """
    params = {"title": title, "node_type": node_type, "is_root": is_root, "source": source}
    if parent_id is not None:
        params["parent_id"] = parent_id
    if summary is not None:
        params["summary"] = summary
    if why is not None:
        params["why"] = why
    if next_step is not None:
        params["next_step"] = next_step
    if owner is not None:
        params["owner"] = owner
    if deadline is not None:
        params["deadline"] = deadline
    if source_id is not None:
        params["source_id"] = source_id
    if source_url is not None:
        params["source_url"] = source_url
    return _result_to_str(_get_engine().execute_tool("create_node", params))


@mcp.tool()
@_safe_tool
def update_status(
    node_id: str,
    new_status: str,
    reason: Optional[str] = None,
    is_root: Optional[bool] = None,
) -> str:
    """Change a node's status.

    Args:
        node_id: Target node ID
        new_status: inbox|active|waiting|done|dropped
        reason: Why this transition is happening
        is_root: If True, auto-clear parent_id
    """
    params = {"node_id": node_id, "new_status": new_status}
    if reason is not None:
        params["reason"] = reason
    if is_root is not None:
        params["is_root"] = is_root
    return _result_to_str(_get_engine().execute_tool("update_status", params))


@mcp.tool()
@_safe_tool
def update_field(
    node_id: str,
    field: str,
    value: Optional[str] = None,
) -> str:
    """Update a specific field on a node.

    Args:
        node_id: Target node ID
        field: Field name — one of: title, summary, why, next_step, owner, deadline, node_type
        value: New value for the field
    """
    return _result_to_str(_get_engine().execute_tool("update_field", {
        "node_id": node_id, "field": field, "value": value,
    }))


@mcp.tool()
@_safe_tool
def attach_node(node_id: str, parent_id: str) -> str:
    """Attach a node to a parent. If already has a parent, atomically reparent.

    Args:
        node_id: Node to attach
        parent_id: New parent node ID
    """
    return _result_to_str(_get_engine().execute_tool("attach_node", {
        "node_id": node_id, "parent_id": parent_id,
    }))


@mcp.tool()
@_safe_tool
def detach_node(node_id: str) -> str:
    """Detach a node from its parent (make it an orphan).

    Args:
        node_id: Node to detach
    """
    return _result_to_str(_get_engine().execute_tool("detach_node", {"node_id": node_id}))


@mcp.tool()
@_safe_tool
def add_dependency(source_id: str, target_id: str) -> str:
    """Add a depends_on edge: source depends on target.

    Args:
        source_id: The node that depends on another
        target_id: The node being depended on
    """
    return _result_to_str(_get_engine().execute_tool("add_dependency", {
        "source_id": source_id, "target_id": target_id,
    }))


@mcp.tool()
@_safe_tool
def remove_dependency(source_id: str, target_id: str) -> str:
    """Remove a depends_on edge.

    Args:
        source_id: The node that had the dependency
        target_id: The node that was depended on
    """
    return _result_to_str(_get_engine().execute_tool("remove_dependency", {
        "source_id": source_id, "target_id": target_id,
    }))


@mcp.tool()
@_safe_tool
def append_log(
    node_id: str,
    content: str = "",
    event_type: str = "log",
) -> str:
    """Append a log entry to a node's narrative. Does NOT reset Anti-Amnesia timer.

    Args:
        node_id: Target node ID
        content: Log content text
        event_type: Event type label (default: "log")
    """
    return _result_to_str(_get_engine().execute_tool("append_log", {
        "node_id": node_id, "content": content, "event_type": event_type,
    }))


@mcp.tool()
@_safe_tool
def unarchive(
    node_id: str,
    new_status: Optional[str] = None,
) -> str:
    """Restore an archived node. Optionally set a new status atomically.

    Args:
        node_id: Archived node ID
        new_status: Optional status to transition to (inbox|active|waiting)
    """
    params = {"node_id": node_id}
    if new_status is not None:
        params["new_status"] = new_status
    return _result_to_str(_get_engine().execute_tool("unarchive", params))


@mcp.tool()
@_safe_tool
def set_persistent(node_id: str, is_persistent: bool) -> str:
    """Mark a node as persistent (exempt from auto-archive) or remove the mark.

    Args:
        node_id: Target node ID
        is_persistent: True to protect from archiving, False to allow
    """
    return _result_to_str(_get_engine().execute_tool("set_persistent", {
        "node_id": node_id, "is_persistent": is_persistent,
    }))
```

- [ ] **Step 4: Run test to verify registration (partial — write tools only so far)**

Run: `cd /Users/ontanetwork/Documents/Onta\ Network/Founder\ OS/MemoryFPMS/V4 && python -m pytest tests/test_mcp_server.py::test_server_has_all_tools -v`
Expected: FAIL (missing runtime + read + system tools — that's expected, we'll add them in Task 3)

- [ ] **Step 5: Commit**

```bash
git add fpms/mcp_server.py tests/test_mcp_server.py
git commit -m "feat(mcp): add MCP server with 10 write tools"
```

---

### Task 3: MCP Server — Runtime + Read + System Tools (8)

**Files:**
- Modify: `/Users/ontanetwork/Documents/Onta Network/Founder OS/MemoryFPMS/V4/fpms/mcp_server.py`

- [ ] **Step 1: Write test for system tools (heartbeat/bootstrap/get_context_bundle)**

Add to `tests/test_mcp_server.py`:

```python
import asyncio


def test_bootstrap_returns_context_bundle(tmp_path):
    """bootstrap() should return a ContextBundle as JSON."""
    import os
    os.environ["FPMS_DB_PATH"] = str(tmp_path / "test.db")
    os.environ["FPMS_EVENTS_PATH"] = str(tmp_path / "events.jsonl")
    os.environ["FPMS_NARRATIVES_DIR"] = str(tmp_path / "narratives")

    # Reset engine singleton
    import fpms.mcp_server as mod
    mod._engine = None

    result = json.loads(mod.bootstrap())
    assert "l0_dashboard" in result
    assert "l_alert" in result
    assert "total_tokens" in result

    # Cleanup
    mod._engine = None
    for key in ["FPMS_DB_PATH", "FPMS_EVENTS_PATH", "FPMS_NARRATIVES_DIR"]:
        os.environ.pop(key, None)


def test_heartbeat_returns_alerts(tmp_path):
    """heartbeat() should return alerts dict."""
    import os
    os.environ["FPMS_DB_PATH"] = str(tmp_path / "test.db")
    os.environ["FPMS_EVENTS_PATH"] = str(tmp_path / "events.jsonl")
    os.environ["FPMS_NARRATIVES_DIR"] = str(tmp_path / "narratives")

    import fpms.mcp_server as mod
    mod._engine = None

    result = json.loads(mod.heartbeat())
    assert "alerts" in result
    assert "active_count" in result

    mod._engine = None
    for key in ["FPMS_DB_PATH", "FPMS_EVENTS_PATH", "FPMS_NARRATIVES_DIR"]:
        os.environ.pop(key, None)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_mcp_server.py -v`
Expected: FAIL (functions not defined yet)

- [ ] **Step 3: Add runtime + read + system tools to mcp_server.py**

Append to `fpms/mcp_server.py`:

```python
# =====================================================================
# Runtime Tools (2)
# =====================================================================


@mcp.tool()
def shift_focus(node_id: str) -> str:
    """Switch primary focus to a node. Triggers context assembly.

    Args:
        node_id: Node to focus on
    """
    return _result_to_str(_get_engine().execute_tool("shift_focus", {"node_id": node_id}))


@mcp.tool()
def expand_context(node_id: str) -> str:
    """Get expanded context for a node (parent, children, dependencies).

    Args:
        node_id: Node to expand
    """
    return _result_to_str(_get_engine().execute_tool("expand_context", {"node_id": node_id}))


# =====================================================================
# Read Tools (3)
# =====================================================================


@mcp.tool()
def get_node(node_id: str) -> str:
    """Query a single node's full details.

    Args:
        node_id: Node ID to look up
    """
    return _result_to_str(_get_engine().execute_tool("get_node", {"node_id": node_id}))


@mcp.tool()
def search_nodes(
    filters: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    include_summary: bool = False,
) -> str:
    """Search nodes with filters.

    Args:
        filters: JSON string of filters, e.g. '{"status": "active"}'. Keys: status, parent_id, source, archived
        limit: Max results (default 50)
        offset: Pagination offset
        include_summary: Include summary field in results
    """
    parsed_filters = json.loads(filters) if filters else {}
    return _result_to_str(_get_engine().execute_tool("search_nodes", {
        "filters": parsed_filters, "limit": limit, "offset": offset,
        "include_summary": include_summary,
    }))


@mcp.tool()
def get_assembly_trace() -> str:
    """Query the most recent context assembly trace (observability)."""
    return _result_to_str(_get_engine().execute_tool("get_assembly_trace", {}))


# =====================================================================
# System Tools (3) — not part of SpineEngine.execute_tool()
# =====================================================================


@mcp.tool()
def heartbeat() -> str:
    """Run a heartbeat scan. Detects risks (blocked, at-risk, stale) and
    Anti-Amnesia alerts. Returns alerts + focus suggestion + node counts.

    Call this periodically (e.g. every conversation start or every few minutes).
    """
    result = _get_engine().heartbeat()
    return json.dumps(result, ensure_ascii=False, default=str)


@mcp.tool()
def bootstrap() -> str:
    """Cold start the memory engine. Run this at the start of a new session.

    Returns a full context bundle (L0 dashboard + alerts + neighborhood + focus).
    Inject the result into your system prompt for memory continuity.
    """
    bundle = _get_engine().bootstrap()
    return json.dumps(asdict(bundle), ensure_ascii=False, default=str)


@mcp.tool()
def get_context_bundle(focus_node_id: Optional[str] = None) -> str:
    """Assemble the current cognitive context bundle (4 layers).

    Returns L0 (global dashboard), L_Alert (top 3 alerts),
    L1 (focus neighborhood), L2 (focus detail + history).

    Args:
        focus_node_id: Optional node ID to shift focus to before assembly
    """
    bundle = _get_engine().get_context_bundle(user_focus=focus_node_id)
    return json.dumps(asdict(bundle), ensure_ascii=False, default=str)


# =====================================================================
# Entry point
# =====================================================================


def main():
    """Run FPMS MCP server with stdio transport."""
    logger.info("Starting FPMS MCP server...")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run all tests**

Run: `python -m pytest tests/test_mcp_server.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add fpms/mcp_server.py tests/test_mcp_server.py
git commit -m "feat(mcp): add runtime, read, and system tools — 18 tools total"
```

---

### Task 4: Integration Test + Manual Verification

**Files:**
- Modify: `/Users/ontanetwork/Documents/Onta Network/Founder OS/MemoryFPMS/V4/tests/test_mcp_server.py`

- [ ] **Step 1: Write E2E test — full workflow through MCP tools**

```python
def test_e2e_workflow(tmp_path):
    """Full workflow: bootstrap → create → activate → heartbeat → bundle."""
    import os
    os.environ["FPMS_DB_PATH"] = str(tmp_path / "test.db")
    os.environ["FPMS_EVENTS_PATH"] = str(tmp_path / "events.jsonl")
    os.environ["FPMS_NARRATIVES_DIR"] = str(tmp_path / "narratives")

    import fpms.mcp_server as mod
    mod._engine = None

    # 1. Bootstrap
    bundle = json.loads(mod.bootstrap())
    assert bundle["total_tokens"] >= 0

    # 2. Create root project
    result = json.loads(mod.create_node(title="Test Project", is_root=True, node_type="project"))
    assert result["success"] is True
    project_id = result["data"]["id"]

    # 3. Create child task
    result = json.loads(mod.create_node(title="Test Task", parent_id=project_id, node_type="task"))
    assert result["success"] is True
    task_id = result["data"]["id"]

    # 4. Activate task
    result = json.loads(mod.update_status(node_id=task_id, new_status="active", reason="starting work"))
    assert result["success"] is True

    # 5. Append log
    result = json.loads(mod.append_log(node_id=task_id, content="Making progress"))
    assert result["success"] is True

    # 6. Search
    result = json.loads(mod.search_nodes(filters='{"status": "active"}'))
    assert result["success"] is True
    assert result["data"]["count"] >= 1

    # 7. Get node
    result = json.loads(mod.get_node(node_id=task_id))
    assert result["success"] is True
    assert result["data"]["status"] == "active"

    # 8. Heartbeat
    hb = json.loads(mod.heartbeat())
    assert "alerts" in hb

    # 9. Get context bundle
    bundle = json.loads(mod.get_context_bundle(focus_node_id=task_id))
    assert bundle["focus_node_id"] == task_id

    # 10. Complete task
    result = json.loads(mod.update_status(node_id=task_id, new_status="done"))
    assert result["success"] is True

    # Cleanup
    mod._engine = None
    for key in ["FPMS_DB_PATH", "FPMS_EVENTS_PATH", "FPMS_NARRATIVES_DIR"]:
        os.environ.pop(key, None)
```

- [ ] **Step 2: Run full test suite**

Run: `python -m pytest tests/test_mcp_server.py -v`
Expected: ALL PASS

- [ ] **Step 3: Manual smoke test — verify MCP server starts**

Run: `cd /Users/ontanetwork/Documents/Onta\ Network/Founder\ OS/MemoryFPMS/V4 && timeout 3 python -m fpms.mcp_server 2>&1 || true`
Expected: Server starts, logs to stderr, exits on timeout (no crash)

- [ ] **Step 4: Commit**

```bash
git add tests/test_mcp_server.py
git commit -m "test(mcp): add E2E workflow test for MCP server"
```

---

### Task 5: Documentation + Client Config

**Files:**
- Modify: `/Users/ontanetwork/Documents/Onta Network/Founder OS/MemoryFPMS/V4/docs/USAGE-GUIDE.md`
- Modify: `/Users/ontanetwork/Documents/Onta Network/Founder OS/MemoryFPMS/V4/CHANGELOG.md`

- [ ] **Step 1: Add MCP server section to USAGE-GUIDE.md**

Add section "4.2 MCP Server 启动" with:
- How to run: `python -m fpms.mcp_server`
- Environment variables: FPMS_DB_PATH, FPMS_EVENTS_PATH, FPMS_NARRATIVES_DIR
- Claude Desktop config example:

```json
{
  "mcpServers": {
    "fpms": {
      "command": "python",
      "args": ["-m", "fpms.mcp_server"],
      "cwd": "/path/to/MemoryFPMS/V4",
      "env": {
        "FPMS_DB_PATH": "./data/fpms.db"
      }
    }
  }
}
```

- Claude Code config example (`.claude/settings.json`)
- OpenClaw config example

- [ ] **Step 2: Update CHANGELOG.md**

Add entry for MCP Server implementation.

- [ ] **Step 3: Commit**

```bash
git add docs/USAGE-GUIDE.md CHANGELOG.md
git commit -m "docs: add MCP server usage instructions and client config examples"
```

---

### Task 6: Run Full Test Suite

- [ ] **Step 1: Run all 560+ existing tests to ensure no regression**

Run: `cd /Users/ontanetwork/Documents/Onta\ Network/Founder\ OS/MemoryFPMS/V4 && python -m pytest tests/ -v --tb=short`
Expected: ALL PASS (560 existing + new MCP tests)

- [ ] **Step 2: Verify MCP tool count**

Run: `python -c "from fpms.mcp_server import mcp; print(len(mcp._tool_manager._tools), 'tools registered')"`
Expected: `18 tools registered`
