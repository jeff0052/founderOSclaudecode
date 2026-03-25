"""Tests for fpms.analytics — usage report generation."""

import json
import os
import sqlite3
import tempfile

import pytest

from fpms.analytics import (
    _count_knowledge_docs,
    _count_narrative_entries,
    _load_jsonl,
    _node_stats,
    _resolve_paths,
    _token_stats,
    _tool_stats,
    compute_health_score,
    format_health_score,
    format_report,
    generate_report,
)


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def sample_db(tmp_dir):
    """Create a minimal SQLite DB with test nodes."""
    db_path = os.path.join(tmp_dir, "fpms.db")
    conn = sqlite3.connect(db_path)
    conn.execute("""CREATE TABLE nodes (
        id TEXT PRIMARY KEY, title TEXT, status TEXT, node_type TEXT,
        is_root INTEGER DEFAULT 0, parent_id TEXT,
        summary TEXT, why TEXT, next_step TEXT, owner TEXT, deadline TEXT,
        is_persistent INTEGER DEFAULT 0,
        created_at TEXT, updated_at TEXT, status_changed_at TEXT,
        archived_at TEXT,
        source TEXT DEFAULT 'internal', source_id TEXT, source_url TEXT,
        source_synced_at TEXT, source_deleted INTEGER DEFAULT 0,
        needs_compression INTEGER DEFAULT 0,
        compression_in_progress INTEGER DEFAULT 0,
        no_llm_compression INTEGER DEFAULT 0,
        tags TEXT DEFAULT '[]'
    )""")
    conn.execute("INSERT INTO nodes (id, title, status, node_type, created_at, updated_at, status_changed_at) VALUES ('proj-1', 'Project A', 'active', 'project', '2026-01-01', '2026-01-01', '2026-01-01')")
    conn.execute("INSERT INTO nodes (id, title, status, node_type, created_at, updated_at, status_changed_at) VALUES ('task-1', 'Task 1', 'done', 'task', '2026-01-01', '2026-01-01', '2026-01-01')")
    conn.execute("INSERT INTO nodes (id, title, status, node_type, created_at, updated_at, status_changed_at) VALUES ('task-2', 'Task 2', 'active', 'task', '2026-01-01', '2026-01-01', '2026-01-01')")
    conn.execute("INSERT INTO nodes (id, title, status, node_type, created_at, updated_at, status_changed_at, archived_at) VALUES ('task-3', 'Task 3', 'done', 'task', '2026-01-01', '2026-01-01', '2026-01-01', '2026-01-10')")
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def sample_events(tmp_dir):
    """Create a sample events.jsonl."""
    path = os.path.join(tmp_dir, "events.jsonl")
    events = [
        {"event_type": "node_created", "tool_name": "create_node", "timestamp": "2026-03-20T10:00:00+00:00"},
        {"event_type": "node_created", "tool_name": "create_node", "timestamp": "2026-03-20T11:00:00+00:00"},
        {"event_type": "command_executed", "tool_name": "create_node", "command_id": "1", "success": True, "timestamp": "2026-03-20T10:00:00+00:00"},
        {"event_type": "command_executed", "tool_name": "update_status", "command_id": "2", "success": True, "timestamp": "2026-03-21T10:00:00+00:00"},
        {"event_type": "command_executed", "tool_name": "append_log", "command_id": "3", "success": False, "timestamp": "2026-03-21T11:00:00+00:00"},
        {"event_type": "node_updated", "tool_name": "update_status", "timestamp": "2026-03-21T10:00:00+00:00"},
    ]
    with open(path, "w") as f:
        for ev in events:
            f.write(json.dumps(ev) + "\n")
    return path


@pytest.fixture
def sample_traces(tmp_dir):
    """Create sample assembly traces."""
    path = os.path.join(tmp_dir, "assembly_traces.jsonl")
    traces = [
        {"timestamp": "2026-03-20T10:00:00", "focus_node_id": "proj-1", "tokens_per_layer": {"l0": 100, "l_alert": 50, "l1": 500, "l2": 350}, "total": 1000, "trimmed": []},
        {"timestamp": "2026-03-20T11:00:00", "focus_node_id": "task-1", "tokens_per_layer": {"l0": 200, "l_alert": 100, "l1": 800, "l2": 900}, "total": 2000, "trimmed": ["siblings"]},
        {"timestamp": "2026-03-21T10:00:00", "focus_node_id": "task-2", "tokens_per_layer": {"l0": 0, "l_alert": 50, "l1": 1500, "l2": 1450}, "total": 3000, "trimmed": []},
    ]
    with open(path, "w") as f:
        for t in traces:
            f.write(json.dumps(t) + "\n")
    return path


@pytest.fixture
def sample_narratives(tmp_dir):
    """Create sample narrative files."""
    narr_dir = os.path.join(tmp_dir, "narratives")
    os.makedirs(narr_dir)
    with open(os.path.join(narr_dir, "proj-1.md"), "w") as f:
        f.write("## 2026-03-20T10:00:00 [created] [general]\nNode created\n\n")
        f.write("## 2026-03-20T11:00:00 [log] [decision]\nChose Stripe\n\n")
        f.write("## 2026-03-20T12:00:00 [log] [risk]\nPCI compliance\n\n")
    with open(os.path.join(narr_dir, "task-1.md"), "w") as f:
        f.write("## 2026-03-21T10:00:00 [log] [technical]\nUsed PaymentIntent\n\n")
    return narr_dir


@pytest.fixture
def sample_knowledge(tmp_dir):
    """Create sample knowledge docs."""
    know_dir = os.path.join(tmp_dir, "knowledge")
    os.makedirs(os.path.join(know_dir, "proj-1"))
    os.makedirs(os.path.join(know_dir, "task-1"))
    with open(os.path.join(know_dir, "proj-1", "overview.md"), "w") as f:
        f.write("# Project A Overview\n")
    with open(os.path.join(know_dir, "proj-1", "requirements.md"), "w") as f:
        f.write("# Requirements\n")
    with open(os.path.join(know_dir, "task-1", "architecture.md"), "w") as f:
        f.write("# Arch\n")
    return know_dir


# --- Unit tests ---

class TestLoadJsonl:
    def test_load_valid(self, tmp_dir):
        path = os.path.join(tmp_dir, "test.jsonl")
        with open(path, "w") as f:
            f.write('{"a": 1}\n{"b": 2}\n')
        result = _load_jsonl(path)
        assert len(result) == 2
        assert result[0] == {"a": 1}

    def test_load_missing_file(self):
        result = _load_jsonl("/nonexistent/path.jsonl")
        assert result == []

    def test_skip_malformed(self, tmp_dir):
        path = os.path.join(tmp_dir, "bad.jsonl")
        with open(path, "w") as f:
            f.write('{"a": 1}\nnot json\n{"b": 2}\n')
        result = _load_jsonl(path)
        assert len(result) == 2


class TestNodeStats:
    def test_basic(self, sample_db):
        stats = _node_stats(sample_db)
        assert stats["total"] == 4
        assert stats["by_status"]["active"] == 2
        assert stats["by_status"]["done"] == 2
        assert stats["by_type"]["task"] == 3
        assert stats["by_type"]["project"] == 1
        assert stats["archived"] == 1

    def test_missing_db(self):
        stats = _node_stats("/nonexistent/db.sqlite")
        assert stats["total"] == 0


class TestToolStats:
    def test_basic(self, sample_events):
        events = _load_jsonl(sample_events)
        stats = _tool_stats(events)
        assert stats["total_calls"] == 6
        assert stats["by_tool"]["create_node"] == 3  # 2 node_created + 1 command_executed
        assert "2026-03-20" in stats["calls_per_day"]
        assert "2026-03-21" in stats["calls_per_day"]

    def test_success_rate(self, sample_events):
        events = _load_jsonl(sample_events)
        stats = _tool_stats(events)
        # 2 success out of 3 command_executed = 66.7%
        assert abs(stats["success_rate"] - 66.7) < 1

    def test_empty(self):
        stats = _tool_stats([])
        assert stats["total_calls"] == 0


class TestTokenStats:
    def test_basic(self, sample_traces):
        traces = _load_jsonl(sample_traces)
        stats = _token_stats(traces)
        assert stats["total_assemblies"] == 3
        assert stats["avg_tokens"] == 2000
        assert stats["min_tokens"] == 1000
        assert stats["max_tokens"] == 3000
        assert stats["over_budget_count"] == 0
        assert stats["trimmed_count"] == 1

    def test_layer_averages(self, sample_traces):
        traces = _load_jsonl(sample_traces)
        stats = _token_stats(traces)
        assert stats["avg_by_layer"]["l0"] == 100  # (100+200+0)/3
        assert stats["avg_by_layer"]["l1"] == 933  # (500+800+1500)/3

    def test_empty(self):
        stats = _token_stats([])
        assert stats["total_assemblies"] == 0


class TestNarrativeStats:
    def test_basic(self, sample_narratives):
        stats = _count_narrative_entries(sample_narratives)
        assert stats["total_files"] == 2
        assert stats["total_entries"] == 4
        assert stats["categories"]["decision"] == 1
        assert stats["categories"]["risk"] == 1
        assert stats["categories"]["technical"] == 1
        assert stats["categories"]["general"] == 1

    def test_missing_dir(self):
        stats = _count_narrative_entries("/nonexistent")
        assert stats["total_files"] == 0


class TestKnowledgeStats:
    def test_basic(self, sample_knowledge):
        stats = _count_knowledge_docs(sample_knowledge)
        assert stats["nodes_with_knowledge"] == 2
        assert stats["total_docs"] == 3
        assert stats["doc_types"]["overview"] == 1
        assert stats["doc_types"]["requirements"] == 1
        assert stats["doc_types"]["architecture"] == 1

    def test_missing_dir(self):
        stats = _count_knowledge_docs("/nonexistent")
        assert stats["nodes_with_knowledge"] == 0


@pytest.fixture
def env_paths(sample_db, sample_events, sample_traces, sample_narratives, sample_knowledge, monkeypatch):
    """Set environment variables pointing to test fixtures."""
    monkeypatch.setenv("FPMS_DB_PATH", sample_db)
    monkeypatch.setenv("FPMS_EVENTS_PATH", sample_events)
    monkeypatch.setenv("FPMS_NARRATIVES_DIR", sample_narratives)
    monkeypatch.setenv("FPMS_KNOWLEDGE_DIR", sample_knowledge)
    # Traces are already in the same tmp_dir as events, auto-detection will find them


class TestResolvePaths:
    def test_from_env(self, env_paths):
        paths = _resolve_paths()
        assert paths["db_path"].endswith("fpms.db")
        assert "narratives" in paths["narratives_dir"]
        assert "knowledge" in paths["knowledge_dir"]


class TestGenerateReport:
    def test_full_report(self, env_paths):
        report = generate_report()
        assert "generated_at" in report
        assert report["nodes"]["total"] == 4
        assert report["tools"]["total_calls"] == 6
        assert report["tokens"]["total_assemblies"] == 3
        assert report["narratives"]["total_files"] == 2
        assert report["knowledge"]["nodes_with_knowledge"] == 2
        assert "node_browser" in report


class TestHealthScore:
    def test_full_report_has_health(self, env_paths):
        report = generate_report()
        health = report["health"]
        assert "total" in health
        assert 0 <= health["total"] <= 100
        assert len(health["dimensions"]) == 5

    def test_dimension_names(self, env_paths):
        report = generate_report()
        names = [d["name"] for d in report["health"]["dimensions"]]
        assert "Node Management" in names
        assert "Recording Habits" in names
        assert "Knowledge Docs" in names
        assert "Token Efficiency" in names
        assert "Tool Utilization" in names

    def test_icons_assigned(self, env_paths):
        report = generate_report()
        for d in report["health"]["dimensions"]:
            assert d["icon"] in ("✅", "⚠️", "❌")

    def test_empty_report(self):
        """Health score with no data should not crash."""
        report = {
            "nodes": {"total": 0, "by_status": {}, "by_type": {}, "archived": 0},
            "tools": {"total_calls": 0, "by_tool": {}, "calls_per_day": {}, "success_rate": 100.0},
            "tokens": {"total_assemblies": 0, "avg_tokens": 0, "avg_by_layer": {}, "max_tokens": 0, "min_tokens": 0, "over_budget_count": 0, "trimmed_count": 0},
            "narratives": {"total_files": 0, "total_entries": 0, "categories": {}},
            "knowledge": {"nodes_with_knowledge": 0, "total_docs": 0, "doc_types": {}},
        }
        health = compute_health_score(report)
        assert health["total"] == 0 + 0 + 0 + 10 + 0  # token gets 5*2=10 for "no assemblies yet"
        assert len(health["dimensions"]) == 5

    def test_format_health(self, env_paths):
        report = generate_report()
        text = format_health_score(report["health"])
        assert "Health Score" in text
        assert "/100" in text


class TestFormatReport:
    def test_output_contains_sections(self, env_paths):
        report = generate_report()
        text = format_report(report)
        assert "FocalPoint Usage Report" in text
        assert "Node Stats" in text
        assert "Tool Usage" in text
        assert "Token Efficiency" in text
        assert "Narrative Stats" in text
        assert "Knowledge Stats" in text
        assert "Total nodes: 4" in text
