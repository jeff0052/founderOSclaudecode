"""FPMS MCP Server — 将 SpineEngine 暴露为 MCP tools。

Usage:
  python -m fpms.mcp_server                                  # stdio transport
  FPMS_DB_PATH=./data/fpms.db python -m fpms.mcp_server      # custom DB path

Environment variables:
  FPMS_DB_PATH        — SQLite path (default: fpms/db/fpms.db)
  FPMS_EVENTS_PATH    — Events JSONL path (default: fpms/events.jsonl)
  FPMS_NARRATIVES_DIR — Narratives directory (default: fpms/narratives)
"""

from __future__ import annotations

import functools
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
    """Lazy-init engine singleton. Thread-safe not required for stdio."""
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
        "FocalPoint — AI 认知操作系统。记忆 + 注意力管理 + 工作流编排。\n\n"
        "## Work Mode Protocol\n\n"
        "开始任何非平凡任务前，按以下流程操作：\n\n"
        "1. **bootstrap** — 每次新对话开始时调用，获取全局状态\n"
        "2. **activate_workbench(node_id, role)** — 开始任务前调用，准备工作上下文\n"
        "   - role='strategy': 你是中书省，关注该不该做、做什么、优先级\n"
        "   - role='review': 你是门下省，关注风险、历史教训、边界情况\n"
        "   - role='execution': 你是尚书省，关注怎么做、验收标准、执行\n"
        "3. **读取返回的 role_prompt** — 进入角色思维模式\n"
        "4. **读取 knowledge + context** — 理解背景和当前状态\n"
        "5. **按 subtasks + suggested_next 执行** — 按依赖顺序推进\n\n"
        "## 三省 Protocol（重大决策时）\n\n"
        "新功能/重大变更需要三省审查：\n"
        "- 中书省产出需求 → sansei_review 提交审查\n"
        "- 门下省 + 尚书省并行审查 → 两个都通过才执行\n"
        "- 打回 ≤ 3 次，超过通知人类\n\n"
        "## 日常操作\n\n"
        "- 决策记录: append_log(category='decision')\n"
        "- 风险标注: append_log(category='risk')\n"
        "- 技术笔记: append_log(category='technical')\n"
        "- 进度更新: append_log(category='progress')\n"
        "- 结论存档: set_knowledge(doc_type, content)\n"
    ),
)


def _result_to_str(result) -> str:
    """Convert ToolResult dataclass to JSON string."""
    return json.dumps(asdict(result), ensure_ascii=False, default=str)


def _safe_tool(fn):
    """Decorator: catch exceptions and return structured error JSON."""

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
    params: dict = {"title": title, "node_type": node_type, "is_root": is_root, "source": source}
    for key, val in [
        ("parent_id", parent_id), ("summary", summary), ("why", why),
        ("next_step", next_step), ("owner", owner), ("deadline", deadline),
        ("source_id", source_id), ("source_url", source_url),
    ]:
        if val is not None:
            params[key] = val
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
    params: dict = {"node_id": node_id, "new_status": new_status}
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
    category: str = "general",
) -> str:
    """Append a log entry to a node's narrative. Does NOT reset Anti-Amnesia timer.

    Args:
        node_id: Target node ID
        content: Log content text
        event_type: Event type label (default: "log")
        category: Log category — decision|feedback|risk|technical|progress|general (default: "general")
    """
    return _result_to_str(_get_engine().execute_tool("append_log", {
        "node_id": node_id, "content": content, "event_type": event_type,
        "category": category,
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
    params: dict = {"node_id": node_id}
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


# =====================================================================
# Runtime Tools (2)
# =====================================================================


@mcp.tool()
@_safe_tool
def shift_focus(node_id: str) -> str:
    """Switch primary focus to a node. Triggers context assembly.

    Args:
        node_id: Node to focus on
    """
    return _result_to_str(_get_engine().execute_tool("shift_focus", {"node_id": node_id}))


@mcp.tool()
@_safe_tool
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
@_safe_tool
def get_node(node_id: str) -> str:
    """Query a single node's full details.

    Args:
        node_id: Node ID to look up
    """
    return _result_to_str(_get_engine().execute_tool("get_node", {"node_id": node_id}))


@mcp.tool()
@_safe_tool
def search_nodes(
    filters: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    include_summary: bool = False,
    query: Optional[str] = None,
) -> str:
    """Search nodes with filters.

    Args:
        filters: JSON string of filters, e.g. '{"status": "active"}'. Keys: status, parent_id, source, archived
        limit: Max results (default 50)
        offset: Pagination offset
        include_summary: Include summary field in results
        query: Full-text search query (searches titles + narratives + knowledge)
    """
    try:
        parsed_filters = json.loads(filters) if filters else {}
    except json.JSONDecodeError as e:
        return json.dumps({"success": False, "error": f"Invalid filters JSON: {e}"}, ensure_ascii=False)
    params = {
        "filters": parsed_filters, "limit": limit, "offset": offset,
        "include_summary": include_summary,
    }
    if query:
        params["query"] = query
    return _result_to_str(_get_engine().execute_tool("search_nodes", params))


@mcp.tool()
@_safe_tool
def get_assembly_trace() -> str:
    """Query the most recent context assembly trace (observability)."""
    return _result_to_str(_get_engine().execute_tool("get_assembly_trace", {}))


# =====================================================================
# System Tools (3) — bypass execute_tool, call engine methods directly
# =====================================================================


@mcp.tool()
@_safe_tool
def heartbeat() -> str:
    """Run a heartbeat scan. Detects risks (blocked, at-risk, stale) and
    Anti-Amnesia alerts. Returns alerts + focus suggestion + node counts.

    Call this periodically (e.g. every conversation start or every few minutes).
    """
    result = _get_engine().heartbeat()
    return json.dumps(result, ensure_ascii=False, default=str)


@mcp.tool()
@_safe_tool
def bootstrap() -> str:
    """Cold start the memory engine. Run this at the start of a new session.

    Returns a full context bundle (L0 dashboard + alerts + neighborhood + focus).
    Inject the result into your system prompt for memory continuity.
    """
    bundle = _get_engine().bootstrap()
    return json.dumps(asdict(bundle), ensure_ascii=False, default=str)


@mcp.tool()
@_safe_tool
def get_context_bundle(focus_node_id: Optional[str] = None, role: str = "all") -> str:
    """Assemble the current cognitive context bundle (4 layers).

    Returns L0 (global dashboard), L_Alert (top 3 alerts),
    L1 (focus neighborhood), L2 (focus detail + history).

    Args:
        focus_node_id: Optional node ID to shift focus to before assembly
        role: Context role filter — strategy|review|execution|all (default: all)
    """
    bundle = _get_engine().get_context_bundle(user_focus=focus_node_id, role=role)
    return json.dumps(asdict(bundle), ensure_ascii=False, default=str)


# =====================================================================
# Workbench + Knowledge Tools (3)
# =====================================================================


@mcp.tool()
@_safe_tool
def activate_workbench(
    node_id: str,
    role: str = "execution",
) -> str:
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
    # Update FTS index
    try:
        engine.store.index_knowledge(node_id, engine._knowledge_dir)
    except Exception:
        pass  # FTS update failure is non-fatal
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


@mcp.tool()
@_safe_tool
def sansei_review(
    node_id: str,
    proposal: str,
    review_approved: bool = True,
    review_reason: str = "",
    engineer_approved: bool = True,
    engineer_reason: str = "",
) -> str:
    """三省 Protocol: submit parallel review verdicts from 门下省 + 尚书省.

    Both must approve for the proposal to pass. Rejections are logged to narrative.
    After 3 rejections on the same node, escalate_to_human=True.

    Args:
        node_id: Node being reviewed
        proposal: The proposal text from 中书省
        review_approved: 门下省 verdict (default: True)
        review_reason: 门下省 reason
        engineer_approved: 尚书省 verdict (default: True)
        engineer_reason: 尚书省 reason
    """
    result = _get_engine().sansei_review(
        node_id,
        proposal=proposal,
        review_verdict={"approved": review_approved, "reason": review_reason},
        engineer_verdict={"approved": engineer_approved, "reason": engineer_reason},
    )
    return json.dumps(result, ensure_ascii=False, default=str)


# =====================================================================
# Entry point
# =====================================================================


def main():
    """Run FPMS MCP server with stdio transport."""
    logger.info("Starting FPMS MCP server...")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
