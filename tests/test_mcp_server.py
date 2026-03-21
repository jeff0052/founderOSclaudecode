"""MCP Server — tool registration, unit tests, and E2E workflow."""

from __future__ import annotations

import json
import os
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _setup_env(tmp_path):
    """Set env vars to point engine at tmp_path. Returns cleanup function."""
    os.environ["FPMS_DB_PATH"] = str(tmp_path / "test.db")
    os.environ["FPMS_EVENTS_PATH"] = str(tmp_path / "events.jsonl")
    os.environ["FPMS_NARRATIVES_DIR"] = str(tmp_path / "narratives")

    import fpms.mcp_server as mod
    mod._engine = None  # reset singleton
    return mod


def _teardown(mod):
    """Reset engine singleton and clean env vars."""
    mod._engine = None
    for key in ["FPMS_DB_PATH", "FPMS_EVENTS_PATH", "FPMS_NARRATIVES_DIR"]:
        os.environ.pop(key, None)


@pytest.fixture
def mcp_env(tmp_path):
    """Fixture: yields mcp_server module with isolated tmp engine."""
    mod = _setup_env(tmp_path)
    yield mod
    _teardown(mod)


# ---------------------------------------------------------------------------
# Task 2+3: Tool Registration
# ---------------------------------------------------------------------------


def test_server_has_all_tools():
    """Verify all 18 tools (15 spine + 3 system) are registered."""
    from fpms.mcp_server import mcp as mcp_instance

    # FastMCP stores tools in _tool_manager._tools dict
    tools = mcp_instance._tool_manager._tools
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
    missing = expected - tool_names
    assert not missing, f"Missing tools: {missing}"
    assert len(expected) == 18


# ---------------------------------------------------------------------------
# Task 3: System Tools
# ---------------------------------------------------------------------------


def test_bootstrap_returns_context_bundle(mcp_env):
    """bootstrap() should return a ContextBundle-shaped JSON."""
    result = json.loads(mcp_env.bootstrap())
    assert "l0_dashboard" in result
    assert "l_alert" in result
    assert "total_tokens" in result


def test_heartbeat_returns_alerts(mcp_env):
    """heartbeat() should return alerts dict."""
    result = json.loads(mcp_env.heartbeat())
    assert "alerts" in result
    assert "active_count" in result


def test_get_context_bundle_empty(mcp_env):
    """get_context_bundle() on empty DB should succeed."""
    result = json.loads(mcp_env.get_context_bundle())
    assert "l0_dashboard" in result
    assert "total_tokens" in result


# ---------------------------------------------------------------------------
# Error Handling
# ---------------------------------------------------------------------------


def test_safe_tool_catches_exceptions(mcp_env):
    """Calling get_node with invalid ID should return error JSON, not crash."""
    result = json.loads(mcp_env.get_node(node_id="nonexistent-id-12345"))
    # Should be a ToolResult with success=False or similar error
    assert isinstance(result, dict)


def test_search_nodes_invalid_json(mcp_env):
    """search_nodes with malformed JSON filters should return error."""
    result = json.loads(mcp_env.search_nodes(filters="not valid json"))
    assert result["success"] is False
    assert "Invalid filters JSON" in result["error"]


# ---------------------------------------------------------------------------
# Task 4: E2E Workflow
# ---------------------------------------------------------------------------


def test_e2e_workflow(mcp_env):
    """Full workflow: bootstrap → create → activate → heartbeat → bundle → done."""
    mod = mcp_env

    # 1. Bootstrap
    bundle = json.loads(mod.bootstrap())
    assert bundle["total_tokens"] >= 0

    # 2. Create root project
    result = json.loads(mod.create_node(
        title="Test Project", is_root=True, node_type="project",
    ))
    assert result["success"] is True
    project_id = result["data"]["id"]

    # 3. Create child task
    result = json.loads(mod.create_node(
        title="Test Task", parent_id=project_id, node_type="task",
    ))
    assert result["success"] is True
    task_id = result["data"]["id"]

    # 4a. Add summary (required before inbox → active)
    result = json.loads(mod.update_field(
        node_id=task_id, field="summary", value="A test task",
    ))
    assert result["success"] is True

    # 4b. Activate task
    result = json.loads(mod.update_status(
        node_id=task_id, new_status="active", reason="starting work",
    ))
    assert result["success"] is True

    # 5. Append log
    result = json.loads(mod.append_log(
        node_id=task_id, content="Making progress",
    ))
    assert result["success"] is True

    # 6. Search active nodes
    result = json.loads(mod.search_nodes(filters='{"status": "active"}'))
    assert result["success"] is True
    assert result["data"]["count"] >= 1

    # 7. Get node detail
    result = json.loads(mod.get_node(node_id=task_id))
    assert result["success"] is True
    assert result["data"]["status"] == "active"

    # 8. Heartbeat
    hb = json.loads(mod.heartbeat())
    assert "alerts" in hb

    # 9. Get context bundle with focus
    bundle = json.loads(mod.get_context_bundle(focus_node_id=task_id))
    assert bundle["focus_node_id"] == task_id

    # 10. Complete task
    result = json.loads(mod.update_status(node_id=task_id, new_status="done"))
    assert result["success"] is True

    # 11. Update field
    result = json.loads(mod.update_field(
        node_id=project_id, field="summary", value="A test project",
    ))
    assert result["success"] is True

    # 12. Attach / Detach
    result = json.loads(mod.detach_node(node_id=task_id))
    assert result["success"] is True
    result = json.loads(mod.attach_node(node_id=task_id, parent_id=project_id))
    assert result["success"] is True

    # 13. Set persistent
    result = json.loads(mod.set_persistent(node_id=project_id, is_persistent=True))
    assert result["success"] is True

    # 14. Expand context
    result = json.loads(mod.expand_context(node_id=project_id))
    assert result["success"] is True

    # 15. Shift focus
    result = json.loads(mod.shift_focus(node_id=project_id))
    assert result["success"] is True

    # 16. Get assembly trace
    result = json.loads(mod.get_assembly_trace())
    # Should return something (may be empty on first call)
    assert isinstance(result, dict)
