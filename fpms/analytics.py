"""FocalPoint Analytics — 使用报告生成器。

读取 events.jsonl、assembly_traces.jsonl、SQLite DB，输出结构化使用报告。

CLI: focalpoint-stats
MCP: get_stats tool
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

def _load_jsonl(path: str) -> List[dict]:
    """Load a JSONL file, skipping malformed lines."""
    records = []
    if not os.path.exists(path):
        return records
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def _count_narrative_entries(narratives_dir: str) -> Dict[str, int]:
    """Count narrative entries and categories across all files."""
    stats: Dict[str, int] = {"total_files": 0, "total_entries": 0}
    categories: Counter = Counter()

    if not os.path.isdir(narratives_dir):
        stats["categories"] = dict(categories)
        return stats

    for fname in os.listdir(narratives_dir):
        if not fname.endswith(".md") or fname.endswith(".compressed.md"):
            continue
        if fname.startswith("_"):
            continue
        stats["total_files"] += 1
        filepath = os.path.join(narratives_dir, fname)
        with open(filepath, "r") as f:
            content = f.read()
        # Count entries by "## " headers
        entries = [e for e in content.split("\n## ") if e.strip()]
        stats["total_entries"] += len(entries)
        # Extract categories
        for entry in entries:
            header = entry.split("\n", 1)[0]
            brackets = re.findall(r'\[([^\]]+)\]', header)
            if len(brackets) >= 2:
                categories[brackets[-1]] += 1
            else:
                categories["general"] += 1

    stats["categories"] = dict(categories)
    return stats


def _count_knowledge_docs(knowledge_dir: str) -> Dict[str, int]:
    """Count knowledge documents and types."""
    stats: Dict[str, int] = {"nodes_with_knowledge": 0, "total_docs": 0}
    doc_types: Counter = Counter()

    if not os.path.isdir(knowledge_dir):
        stats["doc_types"] = dict(doc_types)
        return stats

    for node_dir in os.listdir(knowledge_dir):
        node_path = os.path.join(knowledge_dir, node_dir)
        if not os.path.isdir(node_path):
            continue
        docs = [f for f in os.listdir(node_path) if f.endswith(".md")]
        if docs:
            stats["nodes_with_knowledge"] += 1
            stats["total_docs"] += len(docs)
            for doc in docs:
                doc_type = doc.replace(".md", "")
                doc_types[doc_type] += 1

    stats["doc_types"] = dict(doc_types)
    return stats


# ---------------------------------------------------------------------------
# Report generator
# ---------------------------------------------------------------------------

def _resolve_paths(engine=None) -> dict:
    """Resolve all data paths from SpineEngine or environment variables.

    Single source of truth for path configuration.
    """
    if engine is not None:
        # Get paths from engine (same as MCP server uses)
        db_path = engine.store._conn.execute("PRAGMA database_list").fetchone()[2]
        events_path = engine.store._events_path
        narratives_dir = engine._narratives_dir
        knowledge_dir = engine._knowledge_dir
    else:
        # Fall back to environment variables (same defaults as SpineEngine)
        db_path = os.environ.get("FPMS_DB_PATH", "fpms/db/fpms.db")
        events_path = os.environ.get("FPMS_EVENTS_PATH", "fpms/events.jsonl")
        narratives_dir = os.environ.get("FPMS_NARRATIVES_DIR", "fpms/narratives")
        knowledge_dir = os.environ.get("FPMS_KNOWLEDGE_DIR",
                                        os.path.join(os.path.dirname(narratives_dir), "knowledge"))

    # Auto-detect traces path from db directory
    db_dir = os.path.dirname(db_path)
    traces_path = os.path.join(db_dir, "assembly_traces.jsonl") if db_dir else "assembly_traces.jsonl"
    if not os.path.exists(traces_path):
        traces_path = os.path.join(os.path.dirname(events_path), "assembly_traces.jsonl")

    return {
        "db_path": db_path,
        "events_path": events_path,
        "traces_path": traces_path,
        "narratives_dir": narratives_dir,
        "knowledge_dir": knowledge_dir,
    }


def generate_report(engine=None) -> dict:
    """Generate a complete usage report from all FPMS data sources.

    Args:
        engine: Optional SpineEngine instance. If provided, paths are read from it.
                If None, paths are resolved from environment variables.

    Returns a structured dict with sections: nodes, tools, tokens, narratives, knowledge, health.
    """
    paths = _resolve_paths(engine)

    report: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "nodes": {},
        "tools": {},
        "tokens": {},
        "narratives": {},
        "knowledge": {},
    }

    # --- Node Stats (from SQLite) ---
    report["nodes"] = _node_stats(paths["db_path"])

    # --- Tool Usage (from events.jsonl) ---
    events = _load_jsonl(paths["events_path"])
    report["tools"] = _tool_stats(events)

    # --- Token Efficiency (from assembly_traces.jsonl) ---
    traces = _load_jsonl(paths["traces_path"])
    report["tokens"] = _token_stats(traces)

    # --- Narrative Stats ---
    report["narratives"] = _count_narrative_entries(paths["narratives_dir"])

    # --- Knowledge Stats ---
    report["knowledge"] = _count_knowledge_docs(paths["knowledge_dir"])

    # --- Health Score ---
    report["health"] = compute_health_score(report)

    # --- Node Browser Data (for HTML) ---
    report["node_browser"] = _load_node_browser(
        paths["db_path"], paths["narratives_dir"], paths["knowledge_dir"]
    )

    return report


def _node_stats(db_path: str) -> dict:
    """Compute node statistics from SQLite."""
    stats: dict = {"total": 0, "by_status": {}, "by_type": {}, "archived": 0}

    if not os.path.exists(db_path):
        return stats

    try:
        conn = sqlite3.connect(db_path)
        # Total nodes
        row = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()
        stats["total"] = row[0] if row else 0

        # By status
        for row in conn.execute("SELECT status, COUNT(*) FROM nodes GROUP BY status"):
            stats["by_status"][row[0]] = row[1]

        # By type
        for row in conn.execute("SELECT node_type, COUNT(*) FROM nodes GROUP BY node_type"):
            stats["by_type"][row[0]] = row[1]

        # Archived
        row = conn.execute("SELECT COUNT(*) FROM nodes WHERE archived_at IS NOT NULL").fetchone()
        stats["archived"] = row[0] if row else 0

        conn.close()
    except Exception:
        pass

    return stats


def _load_node_browser(db_path: str, narratives_dir: str, knowledge_dir: str) -> List[dict]:
    """Load all nodes with their narratives and knowledge for the HTML browser."""
    nodes = []
    if not os.path.exists(db_path):
        return nodes

    try:
        conn = sqlite3.connect(db_path)
        cols = [row[1] for row in conn.execute("PRAGMA table_info(nodes)").fetchall()]
        rows = conn.execute("SELECT * FROM nodes ORDER BY created_at DESC").fetchall()

        # Load edges for parent-child relationships
        edges = {}
        try:
            for row in conn.execute("SELECT source_id, target_id, edge_type FROM edges"):
                src, tgt, etype = row
                if etype == "parent":
                    edges.setdefault("children", {}).setdefault(tgt, []).append(src)
                elif etype == "depends_on":
                    edges.setdefault("deps", {}).setdefault(src, []).append(tgt)
        except Exception:
            pass

        conn.close()

        for row in rows:
            d = dict(zip(cols, row))
            node_id = d["id"]

            # Load narrative
            narr_path = os.path.join(narratives_dir, f"{node_id}.md")
            narrative = ""
            if os.path.exists(narr_path):
                with open(narr_path, "r") as f:
                    narrative = f.read()

            # Load knowledge docs
            knowledge = {}
            know_dir = os.path.join(knowledge_dir, node_id)
            if os.path.isdir(know_dir):
                for fname in sorted(os.listdir(know_dir)):
                    if fname.endswith(".md"):
                        with open(os.path.join(know_dir, fname), "r") as f:
                            knowledge[fname.replace(".md", "")] = f.read()

            # Children and dependencies
            children_ids = edges.get("children", {}).get(node_id, [])
            dep_ids = edges.get("deps", {}).get(node_id, [])

            nodes.append({
                "id": node_id,
                "title": d.get("title", ""),
                "status": d.get("status", ""),
                "node_type": d.get("node_type", ""),
                "parent_id": d.get("parent_id"),
                "is_root": bool(d.get("is_root", 0)),
                "summary": d.get("summary") or "",
                "why": d.get("why") or "",
                "next_step": d.get("next_step") or "",
                "owner": d.get("owner") or "",
                "deadline": d.get("deadline") or "",
                "created_at": d.get("created_at", ""),
                "updated_at": d.get("updated_at", ""),
                "status_changed_at": d.get("status_changed_at", ""),
                "children": children_ids,
                "dependencies": dep_ids,
                "narrative": narrative,
                "knowledge": knowledge,
            })
    except Exception:
        pass

    return nodes


def _tool_stats(events: List[dict]) -> dict:
    """Compute tool usage statistics from events."""
    stats: dict = {
        "total_calls": 0,
        "by_tool": {},
        "calls_per_day": {},
        "success_rate": 0.0,
    }

    if not events:
        return stats

    tool_counter: Counter = Counter()
    daily_counter: Counter = Counter()
    success_count = 0
    total_commands = 0

    for ev in events:
        tool_name = ev.get("tool_name")
        if tool_name:
            tool_counter[tool_name] += 1

        # Count command executions for success rate
        if ev.get("event_type") == "command_executed":
            total_commands += 1
            if ev.get("success"):
                success_count += 1

        # Daily distribution
        ts = ev.get("timestamp", "")
        if ts:
            day = ts[:10]  # YYYY-MM-DD
            daily_counter[day] += 1

    stats["total_calls"] = sum(tool_counter.values())
    stats["by_tool"] = dict(tool_counter.most_common())
    stats["calls_per_day"] = dict(sorted(daily_counter.items()))
    stats["success_rate"] = (success_count / total_commands * 100) if total_commands > 0 else 100.0

    return stats


def _token_stats(traces: List[dict]) -> dict:
    """Compute token efficiency statistics from assembly traces."""
    stats: dict = {
        "total_assemblies": 0,
        "avg_tokens": 0,
        "avg_by_layer": {"l0": 0, "l_alert": 0, "l1": 0, "l2": 0},
        "max_tokens": 0,
        "min_tokens": 0,
        "over_budget_count": 0,
        "trimmed_count": 0,
    }

    if not traces:
        return stats

    stats["total_assemblies"] = len(traces)

    totals = [t.get("total", 0) for t in traces]
    stats["avg_tokens"] = round(sum(totals) / len(totals)) if totals else 0
    stats["max_tokens"] = max(totals) if totals else 0
    stats["min_tokens"] = min(totals) if totals else 0

    # Per-layer averages
    layer_sums: dict = {"l0": 0, "l_alert": 0, "l1": 0, "l2": 0}
    for t in traces:
        layers = t.get("tokens_per_layer", {})
        for k in layer_sums:
            layer_sums[k] += layers.get(k, 0)

    count = len(traces)
    stats["avg_by_layer"] = {k: round(v / count) for k, v in layer_sums.items()}

    # Over budget (assuming 10000 default)
    stats["over_budget_count"] = sum(1 for t in totals if t > 10000)

    # Trimmed
    stats["trimmed_count"] = sum(1 for t in traces if t.get("trimmed"))

    return stats


# ---------------------------------------------------------------------------
# Health Score
# ---------------------------------------------------------------------------

def compute_health_score(report: dict) -> dict:
    """Compute a health score (0-100) with per-dimension breakdown.

    Returns:
        {
            "total": 72,
            "dimensions": [
                {"name": "...", "score": 9, "max": 10, "icon": "✅", "detail": "..."},
                ...
            ]
        }
    """
    dimensions = []

    # 1. Node 管理 (10 pts)
    # Good: nodes exist, few stale inbox, most are active/done
    nodes = report.get("nodes", {})
    total_nodes = nodes.get("total", 0)
    by_status = nodes.get("by_status", {})
    inbox_count = by_status.get("inbox", 0)
    active_count = by_status.get("active", 0)
    done_count = by_status.get("done", 0)

    if total_nodes == 0:
        node_score = 0
        node_detail = "No nodes created yet"
    else:
        inbox_ratio = inbox_count / total_nodes
        if inbox_ratio > 0.5:
            node_score = 3
            node_detail = f"{inbox_count}/{total_nodes} nodes stuck in inbox"
        elif inbox_ratio > 0.3:
            node_score = 6
            node_detail = f"{inbox_count} inbox nodes need attention"
        elif active_count + done_count > 0:
            node_score = 9
            node_detail = f"{active_count} active, {done_count} done"
        else:
            node_score = 7
            node_detail = "Nodes exist but limited activity"
    dimensions.append({
        "name": "Node Management",
        "score": min(node_score, 10),
        "max": 10,
        "detail": node_detail,
    })

    # 2. 记录习惯 (10 pts)
    # Good: >50% logs have specific category (not "general")
    narr = report.get("narratives", {})
    total_entries = narr.get("total_entries", 0)
    cats = narr.get("categories", {})
    general_count = cats.get("general", 0)
    categorized = total_entries - general_count

    if total_entries == 0:
        record_score = 0
        record_detail = "No narrative entries yet"
    else:
        cat_ratio = categorized / total_entries
        if cat_ratio >= 0.5:
            record_score = 9
            record_detail = f"{cat_ratio:.0%} of logs have specific categories"
        elif cat_ratio >= 0.3:
            record_score = 7
            record_detail = f"{cat_ratio:.0%} categorized, {general_count} uncategorized"
        elif cat_ratio >= 0.1:
            record_score = 4
            record_detail = f"{general_count}/{total_entries} logs lack category — decisions not being tracked"
        else:
            record_score = 2
            record_detail = f"{general_count}/{total_entries} logs are 'general' — use category to track decisions/risks"
    dimensions.append({
        "name": "Recording Habits",
        "score": min(record_score, 10),
        "max": 10,
        "detail": record_detail,
    })

    # 3. 知识沉淀 (10 pts)
    # Good: project/goal nodes have knowledge docs
    know = report.get("knowledge", {})
    nodes_with_know = know.get("nodes_with_knowledge", 0)
    by_type = nodes.get("by_type", {})
    high_level_nodes = by_type.get("project", 0) + by_type.get("goal", 0)

    if total_nodes == 0:
        know_score = 0
        know_detail = "No nodes yet"
    elif high_level_nodes == 0:
        know_score = 5 if nodes_with_know > 0 else 3
        know_detail = f"{nodes_with_know} nodes have knowledge docs"
    else:
        know_ratio = min(nodes_with_know / max(high_level_nodes, 1), 1.0)
        if know_ratio >= 0.8:
            know_score = 10
            know_detail = f"{nodes_with_know}/{high_level_nodes} project/goal nodes have knowledge"
        elif know_ratio >= 0.5:
            know_score = 7
            know_detail = f"{nodes_with_know}/{high_level_nodes} have knowledge — add docs for the rest"
        elif know_ratio >= 0.2:
            know_score = 4
            know_detail = f"Only {nodes_with_know}/{high_level_nodes} project/goal nodes have knowledge"
        else:
            know_score = 2
            know_detail = f"{nodes_with_know}/{high_level_nodes} — most projects lack design docs"
    dimensions.append({
        "name": "Knowledge Docs",
        "score": min(know_score, 10),
        "max": 10,
        "detail": know_detail,
    })

    # 4. Token 效率 (10 pts)
    # Good: low over-budget, low trimmed
    tokens = report.get("tokens", {})
    total_asm = tokens.get("total_assemblies", 0)
    over_budget = tokens.get("over_budget_count", 0)
    trimmed = tokens.get("trimmed_count", 0)

    if total_asm == 0:
        token_score = 5
        token_detail = "No context assemblies yet"
    else:
        over_ratio = over_budget / total_asm
        trim_ratio = trimmed / total_asm
        if over_ratio > 0.2:
            token_score = 3
            token_detail = f"{over_ratio:.0%} assemblies over budget — context too large"
        elif trim_ratio > 0.3:
            token_score = 5
            token_detail = f"{trim_ratio:.0%} assemblies trimmed — some info being cut"
        elif over_ratio == 0 and trim_ratio <= 0.1:
            token_score = 10
            token_detail = f"0% over budget, {trim_ratio:.0%} trimmed — excellent"
        else:
            token_score = 7
            token_detail = f"{over_ratio:.0%} over, {trim_ratio:.0%} trimmed"
    dimensions.append({
        "name": "Token Efficiency",
        "score": min(token_score, 10),
        "max": 10,
        "detail": token_detail,
    })

    # 5. 工具利用 (10 pts)
    # Good: using advanced tools (workbench, sansei, search, knowledge)
    tools = report.get("tools", {})
    by_tool = tools.get("by_tool", {})
    advanced_tools = {"activate_workbench", "sansei_review", "search_nodes", "set_knowledge", "get_knowledge"}
    used_advanced = sum(1 for t in advanced_tools if by_tool.get(t, 0) > 0)

    if not by_tool:
        tool_score = 0
        tool_detail = "No tool usage recorded"
    elif used_advanced >= 4:
        tool_score = 10
        tool_detail = f"Using {used_advanced}/5 advanced tools"
    elif used_advanced >= 2:
        tool_score = 7
        tool_detail = f"Using {used_advanced}/5 advanced tools"
        missing = [t for t in advanced_tools if by_tool.get(t, 0) == 0]
        if missing:
            tool_detail += f" — try: {', '.join(list(missing)[:2])}"
    elif used_advanced >= 1:
        tool_score = 4
        tool_detail = f"Only {used_advanced}/5 advanced tools used"
    else:
        tool_score = 2
        tool_detail = "Only basic CRUD — try workbench, search, knowledge"
    dimensions.append({
        "name": "Tool Utilization",
        "score": min(tool_score, 10),
        "max": 10,
        "detail": tool_detail,
    })

    # Total score (weighted to 100)
    total = sum(d["score"] for d in dimensions) * 2  # 5 dimensions × 10 pts × 2 = 100

    # Add icons
    for d in dimensions:
        ratio = d["score"] / d["max"]
        if ratio >= 0.8:
            d["icon"] = "✅"
        elif ratio >= 0.5:
            d["icon"] = "⚠️"
        else:
            d["icon"] = "❌"

    return {"total": total, "dimensions": dimensions}


def format_health_score(health: dict) -> str:
    """Format health score into readable text."""
    lines = []
    total = health["total"]
    if total >= 80:
        grade = "Excellent"
    elif total >= 60:
        grade = "Good"
    elif total >= 40:
        grade = "Needs Work"
    else:
        grade = "Getting Started"

    lines.append(f"=== FocalPoint Health Score: {total}/100 ({grade}) ===")
    lines.append("")
    for d in health["dimensions"]:
        lines.append(f"  {d['icon']} {d['name']}: {d['score']}/{d['max']} — {d['detail']}")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Report formatter
# ---------------------------------------------------------------------------

def format_report(report: dict) -> str:
    """Format a report dict into readable text."""
    lines = []
    lines.append("=" * 50)
    lines.append("  FocalPoint Usage Report")
    lines.append("=" * 50)
    lines.append(f"  Generated: {report['generated_at'][:19]}")
    lines.append("")

    # --- Node Stats ---
    nodes = report.get("nodes", {})
    lines.append("--- Node Stats ---")
    lines.append(f"  Total nodes: {nodes.get('total', 0)}")
    lines.append(f"  Archived: {nodes.get('archived', 0)}")
    by_status = nodes.get("by_status", {})
    if by_status:
        parts = [f"{k}={v}" for k, v in sorted(by_status.items())]
        lines.append(f"  By status: {', '.join(parts)}")
    by_type = nodes.get("by_type", {})
    if by_type:
        parts = [f"{k}={v}" for k, v in sorted(by_type.items())]
        lines.append(f"  By type: {', '.join(parts)}")
    lines.append("")

    # --- Tool Usage ---
    tools = report.get("tools", {})
    lines.append("--- Tool Usage ---")
    lines.append(f"  Total calls: {tools.get('total_calls', 0)}")
    lines.append(f"  Success rate: {tools.get('success_rate', 0):.1f}%")
    by_tool = tools.get("by_tool", {})
    if by_tool:
        lines.append("  Top tools:")
        for tool, count in list(by_tool.items())[:10]:
            lines.append(f"    {tool}: {count}")
    daily = tools.get("calls_per_day", {})
    if daily:
        lines.append("  Recent activity:")
        for day, count in list(daily.items())[-7:]:
            bar = "█" * min(count // 2, 30)
            lines.append(f"    {day}: {bar} ({count})")
    lines.append("")

    # --- Token Efficiency ---
    tokens = report.get("tokens", {})
    lines.append("--- Token Efficiency ---")
    lines.append(f"  Total assemblies: {tokens.get('total_assemblies', 0)}")
    lines.append(f"  Avg tokens/assembly: {tokens.get('avg_tokens', 0):,}")
    lines.append(f"  Min: {tokens.get('min_tokens', 0):,}  Max: {tokens.get('max_tokens', 0):,}")
    avg_layer = tokens.get("avg_by_layer", {})
    if avg_layer:
        parts = [f"{k}={v:,}" for k, v in avg_layer.items()]
        lines.append(f"  Avg by layer: {', '.join(parts)}")
    total_asm = tokens.get("total_assemblies", 0)
    if total_asm > 0:
        over = tokens.get("over_budget_count", 0)
        trimmed = tokens.get("trimmed_count", 0)
        lines.append(f"  Over budget: {over} ({over/total_asm*100:.0f}%)")
        lines.append(f"  Trimmed: {trimmed} ({trimmed/total_asm*100:.0f}%)")
    lines.append("")

    # --- Narrative Stats ---
    narr = report.get("narratives", {})
    lines.append("--- Narrative Stats ---")
    lines.append(f"  Files: {narr.get('total_files', 0)}")
    lines.append(f"  Total entries: {narr.get('total_entries', 0)}")
    cats = narr.get("categories", {})
    if cats:
        parts = [f"{k}={v}" for k, v in sorted(cats.items(), key=lambda x: -x[1])]
        lines.append(f"  By category: {', '.join(parts)}")
    lines.append("")

    # --- Knowledge Stats ---
    know = report.get("knowledge", {})
    lines.append("--- Knowledge Stats ---")
    lines.append(f"  Nodes with knowledge: {know.get('nodes_with_knowledge', 0)}")
    lines.append(f"  Total docs: {know.get('total_docs', 0)}")
    doc_types = know.get("doc_types", {})
    if doc_types:
        parts = [f"{k}={v}" for k, v in sorted(doc_types.items(), key=lambda x: -x[1])]
        lines.append(f"  By type: {', '.join(parts)}")

    lines.append("")

    # --- Health Score ---
    health = report.get("health")
    if health:
        lines.append(format_health_score(health))

    lines.append("=" * 50)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# HTML Dashboard
# ---------------------------------------------------------------------------

def format_html(report: dict) -> str:
    """Generate a self-contained HTML dashboard from report data."""
    health = report.get("health", {})
    total_score = health.get("total", 0)
    dimensions = health.get("dimensions", [])
    nodes = report.get("nodes", {})
    tools = report.get("tools", {})
    tokens = report.get("tokens", {})
    narr = report.get("narratives", {})
    know = report.get("knowledge", {})

    # Build dimension cards HTML
    dim_cards = ""
    for d in dimensions:
        color = "#22c55e" if d["icon"] == "✅" else "#f59e0b" if d["icon"] == "⚠️" else "#ef4444"
        pct = d["score"] / d["max"] * 100
        dim_cards += f"""
        <div class="card">
          <div class="card-header">
            <span class="icon">{d['icon']}</span>
            <span class="card-title">{d['name']}</span>
            <span class="card-score" style="color:{color}">{d['score']}/{d['max']}</span>
          </div>
          <div class="bar-bg"><div class="bar-fill" style="width:{pct}%;background:{color}"></div></div>
          <div class="card-detail">{d['detail']}</div>
        </div>"""

    # Build tool usage rows
    tool_rows = ""
    by_tool = tools.get("by_tool", {})
    max_count = max(by_tool.values()) if by_tool else 1
    for tool, count in list(by_tool.items())[:10]:
        pct = count / max_count * 100
        tool_rows += f"""
        <div class="tool-row">
          <span class="tool-name">{tool}</span>
          <div class="tool-bar-bg"><div class="tool-bar" style="width:{pct}%"></div></div>
          <span class="tool-count">{count}</span>
        </div>"""

    # Build status distribution
    by_status = nodes.get("by_status", {})
    status_colors = {"active": "#3b82f6", "done": "#22c55e", "inbox": "#9ca3af", "waiting": "#f59e0b", "dropped": "#ef4444"}
    status_items = ""
    total_nodes = nodes.get("total", 1)
    for status, count in sorted(by_status.items()):
        pct = count / total_nodes * 100
        color = status_colors.get(status, "#6b7280")
        status_items += f'<div class="status-item"><div class="status-bar" style="width:{pct}%;background:{color}"></div><span>{status}: {count}</span></div>'

    # Build category distribution
    cats = narr.get("categories", {})
    cat_items = ""
    total_entries = narr.get("total_entries", 1)
    cat_colors = {"decision": "#8b5cf6", "risk": "#ef4444", "technical": "#3b82f6", "progress": "#22c55e", "feedback": "#f59e0b", "general": "#9ca3af"}
    for cat, count in sorted(cats.items(), key=lambda x: -x[1]):
        pct = count / total_entries * 100
        color = cat_colors.get(cat, "#6b7280")
        cat_items += f'<div class="status-item"><div class="status-bar" style="width:{pct}%;background:{color}"></div><span>{cat}: {count} ({pct:.0f}%)</span></div>'

    # Daily activity chart
    daily = tools.get("calls_per_day", {})
    daily_bars = ""
    max_daily = max(daily.values()) if daily else 1
    for day, count in list(daily.items())[-14:]:
        h = count / max_daily * 100
        daily_bars += f'<div class="daily-col"><div class="daily-bar" style="height:{h}%"></div><div class="daily-label">{day[-5:]}</div><div class="daily-count">{count}</div></div>'

    # Score ring color
    if total_score >= 80:
        ring_color = "#22c55e"
        grade = "Excellent"
    elif total_score >= 60:
        ring_color = "#3b82f6"
        grade = "Good"
    elif total_score >= 40:
        ring_color = "#f59e0b"
        grade = "Needs Work"
    else:
        ring_color = "#ef4444"
        grade = "Getting Started"

    # Serialize node browser data for JS
    node_browser = report.get("node_browser", [])
    nodes_json = json.dumps(node_browser, ensure_ascii=False, default=str)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>FocalPoint Dashboard</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f172a; color: #e2e8f0; min-height: 100vh; padding: 2rem; }}
  .container {{ max-width: 1200px; margin: 0 auto; }}
  h1 {{ font-size: 1.5rem; font-weight: 600; margin-bottom: 0.25rem; }}
  .subtitle {{ color: #94a3b8; font-size: 0.875rem; margin-bottom: 2rem; }}

  /* Score Ring */
  .score-section {{ display: flex; align-items: center; gap: 2rem; margin-bottom: 2rem; padding: 1.5rem; background: #1e293b; border-radius: 12px; }}
  .score-ring {{ position: relative; width: 120px; height: 120px; flex-shrink: 0; }}
  .score-ring svg {{ transform: rotate(-90deg); }}
  .score-ring circle {{ fill: none; stroke-width: 8; }}
  .score-ring .bg {{ stroke: #334155; }}
  .score-ring .fg {{ stroke: {ring_color}; stroke-linecap: round; stroke-dasharray: {total_score * 3.14}, 314; transition: stroke-dasharray 1s; }}
  .score-num {{ position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); font-size: 2rem; font-weight: 700; color: {ring_color}; }}
  .score-label {{ font-size: 0.75rem; color: #94a3b8; text-align: center; margin-top: 4px; }}
  .score-grade {{ font-size: 1.25rem; font-weight: 600; color: {ring_color}; }}
  .score-details {{ flex: 1; }}

  /* Cards */
  .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 1rem; margin-bottom: 2rem; }}
  .card {{ background: #1e293b; border-radius: 10px; padding: 1rem; }}
  .card-header {{ display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.5rem; }}
  .icon {{ font-size: 1.1rem; }}
  .card-title {{ flex: 1; font-size: 0.85rem; font-weight: 500; }}
  .card-score {{ font-size: 1.1rem; font-weight: 700; }}
  .bar-bg {{ height: 6px; background: #334155; border-radius: 3px; margin-bottom: 0.5rem; }}
  .bar-fill {{ height: 100%; border-radius: 3px; transition: width 0.5s; }}
  .card-detail {{ font-size: 0.75rem; color: #94a3b8; }}

  /* Panels */
  .panels {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin-bottom: 2rem; }}
  @media (max-width: 768px) {{ .panels {{ grid-template-columns: 1fr; }} }}
  .panel {{ background: #1e293b; border-radius: 10px; padding: 1.25rem; }}
  .panel-title {{ font-size: 0.9rem; font-weight: 600; margin-bottom: 1rem; color: #cbd5e1; }}

  /* Tool bars */
  .tool-row {{ display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.5rem; }}
  .tool-name {{ width: 140px; font-size: 0.8rem; color: #94a3b8; text-align: right; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
  .tool-bar-bg {{ flex: 1; height: 8px; background: #334155; border-radius: 4px; }}
  .tool-bar {{ height: 100%; background: #3b82f6; border-radius: 4px; }}
  .tool-count {{ width: 30px; font-size: 0.8rem; color: #94a3b8; }}

  /* Status bars */
  .status-item {{ margin-bottom: 0.4rem; }}
  .status-item span {{ font-size: 0.8rem; color: #94a3b8; }}
  .status-bar {{ height: 6px; border-radius: 3px; margin-bottom: 2px; min-width: 4px; }}

  /* Daily chart */
  .daily-chart {{ display: flex; align-items: flex-end; gap: 4px; height: 100px; }}
  .daily-col {{ flex: 1; display: flex; flex-direction: column; align-items: center; height: 100%; justify-content: flex-end; }}
  .daily-bar {{ width: 100%; background: #3b82f6; border-radius: 3px 3px 0 0; min-height: 2px; }}
  .daily-label {{ font-size: 0.6rem; color: #64748b; margin-top: 4px; }}
  .daily-count {{ font-size: 0.65rem; color: #94a3b8; }}

  /* Stats row */
  .stats-row {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 1rem; margin-bottom: 2rem; }}
  .stat {{ background: #1e293b; border-radius: 10px; padding: 1rem; text-align: center; }}
  .stat-num {{ font-size: 1.5rem; font-weight: 700; color: #e2e8f0; }}
  .stat-label {{ font-size: 0.75rem; color: #64748b; margin-top: 0.25rem; }}

  .footer {{ text-align: center; color: #475569; font-size: 0.75rem; margin-top: 2rem; }}
</style>
</head>
<body>
<div class="container">
  <h1>FocalPoint Dashboard</h1>
  <p class="subtitle">Generated {report['generated_at'][:19]} UTC</p>

  <!-- Health Score -->
  <div class="score-section">
    <div>
      <div class="score-ring">
        <svg viewBox="0 0 108 108"><circle class="bg" cx="54" cy="54" r="50"/><circle class="fg" cx="54" cy="54" r="50"/></svg>
        <div class="score-num">{total_score}</div>
      </div>
      <div class="score-label">/ 100</div>
    </div>
    <div class="score-details">
      <div class="score-grade">{grade}</div>
      {dim_cards}
    </div>
  </div>

  <!-- Quick Stats -->
  <div class="stats-row">
    <div class="stat"><div class="stat-num">{nodes.get('total', 0)}</div><div class="stat-label">Total Nodes</div></div>
    <div class="stat"><div class="stat-num">{tools.get('total_calls', 0)}</div><div class="stat-label">Tool Calls</div></div>
    <div class="stat"><div class="stat-num">{tokens.get('avg_tokens', 0):,}</div><div class="stat-label">Avg Tokens</div></div>
    <div class="stat"><div class="stat-num">{narr.get('total_entries', 0)}</div><div class="stat-label">Log Entries</div></div>
    <div class="stat"><div class="stat-num">{know.get('total_docs', 0)}</div><div class="stat-label">Knowledge Docs</div></div>
    <div class="stat"><div class="stat-num">{tools.get('success_rate', 0):.0f}%</div><div class="stat-label">Success Rate</div></div>
  </div>

  <!-- Detail Panels -->
  <div class="panels">
    <div class="panel">
      <div class="panel-title">Tool Usage</div>
      {tool_rows}
    </div>
    <div class="panel">
      <div class="panel-title">Node Status</div>
      {status_items}
    </div>
    <div class="panel">
      <div class="panel-title">Log Categories</div>
      {cat_items}
    </div>
    <div class="panel">
      <div class="panel-title">Daily Activity</div>
      <div class="daily-chart">{daily_bars}</div>
    </div>
  </div>

  <!-- Token Details -->
  <div class="panel" style="margin-bottom:2rem">
    <div class="panel-title">Token Efficiency</div>
    <div class="stats-row" style="margin-bottom:0">
      <div class="stat"><div class="stat-num">{tokens.get('total_assemblies', 0)}</div><div class="stat-label">Assemblies</div></div>
      <div class="stat"><div class="stat-num">{tokens.get('min_tokens', 0):,}</div><div class="stat-label">Min Tokens</div></div>
      <div class="stat"><div class="stat-num">{tokens.get('avg_tokens', 0):,}</div><div class="stat-label">Avg Tokens</div></div>
      <div class="stat"><div class="stat-num">{tokens.get('max_tokens', 0):,}</div><div class="stat-label">Max Tokens</div></div>
      <div class="stat"><div class="stat-num">{tokens.get('over_budget_count', 0)}</div><div class="stat-label">Over Budget</div></div>
      <div class="stat"><div class="stat-num">{tokens.get('trimmed_count', 0)}</div><div class="stat-label">Trimmed</div></div>
    </div>
  </div>

  <!-- Node Browser -->
  <div class="panel" style="margin-bottom:2rem">
    <div class="panel-title" style="display:flex;justify-content:space-between;align-items:center">
      <span>Node Browser</span>
      <input id="nodeSearch" type="text" placeholder="Search nodes..." style="background:#334155;border:1px solid #475569;border-radius:6px;padding:4px 10px;color:#e2e8f0;font-size:0.8rem;width:200px;outline:none">
    </div>
    <div id="nodeTree" style="margin-top:1rem"></div>
  </div>

  <!-- Node Detail Modal -->
  <div id="nodeModal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,0.7);z-index:100;overflow-y:auto">
    <div style="max-width:800px;margin:2rem auto;background:#1e293b;border-radius:12px;padding:2rem;position:relative">
      <button onclick="closeModal()" style="position:absolute;top:1rem;right:1rem;background:none;border:none;color:#94a3b8;font-size:1.5rem;cursor:pointer">&times;</button>
      <div id="modalContent"></div>
    </div>
  </div>

  <div class="footer">FocalPoint v0.3 — AI Cognitive Operating System</div>
</div>

<script>
const NODES = {nodes_json};

const STATUS_COLORS = {{"active":"#3b82f6","done":"#22c55e","inbox":"#9ca3af","waiting":"#f59e0b","dropped":"#ef4444"}};
const TYPE_ICONS = {{"goal":"🎯","project":"📁","milestone":"🏁","task":"📋","unknown":"📄"}};
const STATUS_ICONS = {{"inbox":"📥","active":"▶️","waiting":"⏳","done":"✅","dropped":"❌"}};

function buildTree() {{
  const byParent = {{}};
  const roots = [];
  NODES.forEach(n => {{
    if (n.parent_id) {{
      if (!byParent[n.parent_id]) byParent[n.parent_id] = [];
      byParent[n.parent_id].push(n);
    }} else {{
      roots.push(n);
    }}
  }});

  function renderNode(node, depth) {{
    const children = byParent[node.id] || [];
    const indent = depth * 20;
    const statusIcon = STATUS_ICONS[node.status] || "▶️";
    const typeIcon = TYPE_ICONS[node.node_type] || "📄";
    const color = STATUS_COLORS[node.status] || "#94a3b8";
    const hasChildren = children.length > 0;
    const arrow = hasChildren ? '<span class="tree-arrow" onclick="toggleChildren(this)">▼</span>' : '<span style="width:16px;display:inline-block"></span>';

    let html = `<div class="tree-node" data-id="${{node.id}}" data-title="${{node.title.toLowerCase()}}" style="padding-left:${{indent}}px">
      ${{arrow}}
      <span class="tree-type">${{typeIcon}}</span>
      <span class="tree-status" style="color:${{color}}">${{statusIcon}}</span>
      <span class="tree-title" onclick="showNode('${{node.id}}')">${{node.title}}</span>
      <span class="tree-id">${{node.id}}</span>
      <span class="tree-badge" style="background:${{color}}20;color:${{color}}">${{node.status}}</span>
    </div>`;

    if (hasChildren) {{
      html += `<div class="tree-children">`;
      children.sort((a, b) => (a.created_at || '').localeCompare(b.created_at || ''));
      children.forEach(c => {{ html += renderNode(c, depth + 1); }});
      html += `</div>`;
    }}
    return html;
  }}

  let html = '';
  roots.sort((a, b) => (a.created_at || '').localeCompare(b.created_at || ''));
  roots.forEach(r => {{ html += renderNode(r, 0); }});
  document.getElementById('nodeTree').innerHTML = html || '<div style="color:#64748b;padding:1rem">No nodes found</div>';
}}

function toggleChildren(el) {{
  const children = el.parentElement.nextElementSibling;
  if (children && children.classList.contains('tree-children')) {{
    const collapsed = children.style.display === 'none';
    children.style.display = collapsed ? 'block' : 'none';
    el.textContent = collapsed ? '▼' : '▶';
  }}
}}

function escapeHtml(str) {{
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}}

function showNode(nodeId) {{
  const node = NODES.find(n => n.id === nodeId);
  if (!node) return;

  const statusColor = STATUS_COLORS[node.status] || "#94a3b8";
  const typeIcon = TYPE_ICONS[node.node_type] || "📄";

  let html = `
    <div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:1rem">
      <span style="font-size:1.5rem">${{typeIcon}}</span>
      <h2 style="font-size:1.25rem;font-weight:600">${{escapeHtml(node.title)}}</h2>
      <span style="background:${{statusColor}}20;color:${{statusColor}};padding:2px 8px;border-radius:4px;font-size:0.8rem">${{node.status}}</span>
    </div>

    <div style="display:grid;grid-template-columns:1fr 1fr;gap:0.5rem;margin-bottom:1.5rem;font-size:0.85rem">
      <div><span style="color:#64748b">ID:</span> ${{node.id}}</div>
      <div><span style="color:#64748b">Type:</span> ${{node.node_type}}</div>
      <div><span style="color:#64748b">Created:</span> ${{(node.created_at||'').slice(0,19)}}</div>
      <div><span style="color:#64748b">Updated:</span> ${{(node.updated_at||'').slice(0,19)}}</div>
      ${{node.owner ? `<div><span style="color:#64748b">Owner:</span> ${{escapeHtml(node.owner)}}</div>` : ''}}
      ${{node.deadline ? `<div><span style="color:#64748b">Deadline:</span> ${{node.deadline}}</div>` : ''}}
      ${{node.parent_id ? `<div><span style="color:#64748b">Parent:</span> <a href="#" onclick="showNode('${{node.parent_id}}');return false" style="color:#3b82f6">${{node.parent_id}}</a></div>` : ''}}
    </div>`;

  if (node.summary) {{
    html += `<div style="margin-bottom:1rem"><div style="color:#94a3b8;font-size:0.75rem;margin-bottom:0.25rem">SUMMARY</div><div style="font-size:0.9rem">${{escapeHtml(node.summary)}}</div></div>`;
  }}
  if (node.why) {{
    html += `<div style="margin-bottom:1rem"><div style="color:#94a3b8;font-size:0.75rem;margin-bottom:0.25rem">WHY</div><div style="font-size:0.9rem">${{escapeHtml(node.why)}}</div></div>`;
  }}
  if (node.next_step) {{
    html += `<div style="margin-bottom:1rem"><div style="color:#94a3b8;font-size:0.75rem;margin-bottom:0.25rem">NEXT STEP</div><div style="font-size:0.9rem">${{escapeHtml(node.next_step)}}</div></div>`;
  }}

  // Children
  if (node.children && node.children.length > 0) {{
    html += `<div style="margin-bottom:1rem"><div style="color:#94a3b8;font-size:0.75rem;margin-bottom:0.5rem">CHILDREN (${{node.children.length}})</div>`;
    node.children.forEach(cid => {{
      const child = NODES.find(n => n.id === cid);
      if (child) {{
        const c = STATUS_COLORS[child.status] || "#94a3b8";
        html += `<div style="display:flex;align-items:center;gap:0.5rem;padding:4px 0"><span style="color:${{c}}">${{STATUS_ICONS[child.status]||'▶️'}}</span><a href="#" onclick="showNode('${{cid}}');return false" style="color:#3b82f6;font-size:0.85rem">${{escapeHtml(child.title)}}</a><span style="color:#64748b;font-size:0.75rem">${{cid}}</span></div>`;
      }}
    }});
    html += `</div>`;
  }}

  // Knowledge
  const knowKeys = Object.keys(node.knowledge || {{}});
  if (knowKeys.length > 0) {{
    html += `<div style="margin-bottom:1rem"><div style="color:#94a3b8;font-size:0.75rem;margin-bottom:0.5rem">KNOWLEDGE (${{knowKeys.length}} docs)</div>`;
    knowKeys.forEach(k => {{
      html += `<div style="margin-bottom:0.75rem">
        <div style="color:#8b5cf6;font-size:0.8rem;font-weight:600;margin-bottom:0.25rem">${{k}}</div>
        <pre style="background:#0f172a;padding:0.75rem;border-radius:6px;font-size:0.8rem;overflow-x:auto;white-space:pre-wrap;color:#cbd5e1;max-height:300px;overflow-y:auto">${{escapeHtml(node.knowledge[k])}}</pre>
      </div>`;
    }});
    html += `</div>`;
  }}

  // Narrative
  if (node.narrative && node.narrative.trim()) {{
    html += `<div><div style="color:#94a3b8;font-size:0.75rem;margin-bottom:0.5rem">NARRATIVE</div>
      <pre style="background:#0f172a;padding:0.75rem;border-radius:6px;font-size:0.78rem;overflow-x:auto;white-space:pre-wrap;color:#cbd5e1;max-height:400px;overflow-y:auto">${{escapeHtml(node.narrative)}}</pre>
    </div>`;
  }}

  document.getElementById('modalContent').innerHTML = html;
  document.getElementById('nodeModal').style.display = 'block';
}}

function closeModal() {{
  document.getElementById('nodeModal').style.display = 'none';
}}

document.getElementById('nodeModal').addEventListener('click', function(e) {{
  if (e.target === this) closeModal();
}});

document.getElementById('nodeSearch').addEventListener('input', function(e) {{
  const q = e.target.value.toLowerCase();
  document.querySelectorAll('.tree-node').forEach(el => {{
    const title = el.dataset.title || '';
    const id = el.dataset.id || '';
    const match = !q || title.includes(q) || id.includes(q);
    el.style.display = match ? 'flex' : 'none';
  }});
}});

document.addEventListener('keydown', function(e) {{
  if (e.key === 'Escape') closeModal();
}});

buildTree();
</script>

<style>
  .tree-node {{ display: flex; align-items: center; gap: 6px; padding: 4px 0; cursor: default; }}
  .tree-node:hover {{ background: #334155; border-radius: 4px; }}
  .tree-arrow {{ cursor: pointer; font-size: 0.7rem; width: 16px; text-align: center; color: #64748b; }}
  .tree-type {{ font-size: 0.9rem; }}
  .tree-status {{ font-size: 0.8rem; }}
  .tree-title {{ font-size: 0.85rem; cursor: pointer; color: #e2e8f0; }}
  .tree-title:hover {{ color: #3b82f6; text-decoration: underline; }}
  .tree-id {{ font-size: 0.7rem; color: #475569; }}
  .tree-badge {{ font-size: 0.65rem; padding: 1px 6px; border-radius: 3px; }}
  .tree-children {{ }}
  #nodeModal pre {{ scrollbar-width: thin; scrollbar-color: #475569 #0f172a; }}
</style>
</body>
</html>"""


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    """CLI entry point: focalpoint-stats

    Uses SpineEngine to resolve all data paths automatically.
    No manual path arguments needed — reads same data as MCP server.
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="focalpoint-stats",
        description="FocalPoint usage analytics report",
    )
    parser.add_argument("--json", action="store_true", help="Output raw JSON instead of formatted text")
    parser.add_argument("--html", nargs="?", const="focalpoint-dashboard.html",
                        help="Generate HTML dashboard (default: focalpoint-dashboard.html)")

    args = parser.parse_args()

    # Use SpineEngine as single source of truth for paths
    from fpms.spine import SpineEngine
    engine = SpineEngine(
        db_path=os.environ.get("FPMS_DB_PATH", "fpms/db/fpms.db"),
        events_path=os.environ.get("FPMS_EVENTS_PATH", "fpms/events.jsonl"),
        narratives_dir=os.environ.get("FPMS_NARRATIVES_DIR", "fpms/narratives"),
    )

    report = generate_report(engine=engine)

    if args.html:
        html_path = args.html
        with open(html_path, "w") as f:
            f.write(format_html(report))
        print(f"Dashboard saved to {html_path}")
        # Auto-open in browser
        import subprocess
        subprocess.run(["open", html_path], check=False)
    elif args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(format_report(report))


if __name__ == "__main__":
    main()
