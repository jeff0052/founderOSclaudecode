"""models.py 测试 — dataclass 字段 + Pydantic 校验。"""

from __future__ import annotations

import dataclasses
from typing import Optional

import pytest
from pydantic import ValidationError

from fpms.spine.models import (
    Alert,
    ContextBundle,
    CreateNodeInput,
    Edge,
    Node,
    ToolResult,
    UpdateFieldInput,
    UpdateStatusInput,
)


# ---------------------------------------------------------------------------
# Node dataclass
# ---------------------------------------------------------------------------

class TestNode:
    def test_all_fields_present(self):
        """Node 包含所有预期字段。"""
        names = {f.name for f in dataclasses.fields(Node)}
        expected = {
            "id", "title", "status", "node_type", "is_root", "parent_id",
            "summary", "why", "next_step", "owner", "deadline",
            "is_persistent", "created_at", "updated_at", "status_changed_at",
            "archived_at", "source", "source_id", "source_url",
            "source_synced_at", "source_deleted", "needs_compression",
            "compression_in_progress", "no_llm_compression", "tags",
        }
        assert expected.issubset(names)

    def test_defaults(self):
        """Node 默认值正确。"""
        n = Node(id="x", title="T", status="inbox", node_type="task")
        assert n.is_root is False
        assert n.parent_id is None
        assert n.source == "internal"
        assert n.tags == []
        assert n.is_persistent is False
        assert n.needs_compression is False


# ---------------------------------------------------------------------------
# Edge dataclass
# ---------------------------------------------------------------------------

class TestEdge:
    def test_all_fields_present(self):
        names = {f.name for f in dataclasses.fields(Edge)}
        assert names == {"source_id", "target_id", "edge_type", "created_at"}

    def test_creation(self):
        e = Edge(source_id="a", target_id="b", edge_type="parent")
        assert e.created_at == ""


# ---------------------------------------------------------------------------
# ToolResult dataclass
# ---------------------------------------------------------------------------

class TestToolResult:
    def test_all_fields_present(self):
        names = {f.name for f in dataclasses.fields(ToolResult)}
        expected = {
            "success", "command_id", "event_id", "data", "error",
            "suggestion", "affected_nodes", "warnings",
        }
        assert expected == names

    def test_defaults(self):
        tr = ToolResult(success=True, command_id="cmd-1")
        assert tr.event_id is None
        assert tr.data is None
        assert tr.error is None
        assert tr.suggestion is None
        assert tr.affected_nodes == []
        assert tr.warnings == []


# ---------------------------------------------------------------------------
# Alert dataclass
# ---------------------------------------------------------------------------

class TestAlert:
    def test_all_fields_present(self):
        names = {f.name for f in dataclasses.fields(Alert)}
        assert names == {"node_id", "alert_type", "message", "severity", "first_seen"}

    def test_creation(self):
        a = Alert(node_id="n1", alert_type="stale", message="m", severity=1,
                  first_seen="2026-01-01T00:00:00Z")
        assert a.severity == 1


# ---------------------------------------------------------------------------
# ContextBundle dataclass
# ---------------------------------------------------------------------------

class TestContextBundle:
    def test_all_fields_present(self):
        names = {f.name for f in dataclasses.fields(ContextBundle)}
        expected = {
            "l0_dashboard", "l_alert", "l1_neighborhood", "l2_focus",
            "total_tokens", "focus_node_id",
        }
        assert expected == names

    def test_defaults(self):
        cb = ContextBundle(
            l0_dashboard="d", l_alert="a", l1_neighborhood="n",
            l2_focus="f", total_tokens=100,
        )
        assert cb.focus_node_id is None
        assert cb.total_tokens == 100


# ---------------------------------------------------------------------------
# CreateNodeInput (Pydantic)
# ---------------------------------------------------------------------------

class TestCreateNodeInput:
    def test_type_coercion_bool(self):
        """字符串 'true' 自动强转为 bool True。"""
        inp = CreateNodeInput(title="T", is_root="true")  # type: ignore[arg-type]
        assert inp.is_root is True

    def test_invalid_node_type_rejected(self):
        with pytest.raises(ValidationError):
            CreateNodeInput(title="T", node_type="epic")

    def test_valid_node_types(self):
        for nt in ("goal", "project", "milestone", "task", "unknown"):
            inp = CreateNodeInput(title="T", node_type=nt)
            assert inp.node_type == nt

    def test_deadline_iso8601_valid(self):
        inp = CreateNodeInput(title="T", deadline="2026-03-20T18:00:00+08:00")
        assert inp.deadline is not None

    def test_deadline_iso8601_invalid(self):
        with pytest.raises(ValidationError):
            CreateNodeInput(title="T", deadline="next-friday")

    def test_source_fields_defaults(self):
        inp = CreateNodeInput(title="T")
        assert inp.source == "internal"
        assert inp.source_id is None
        assert inp.source_url is None

    def test_source_fields_set(self):
        inp = CreateNodeInput(
            title="T", source="github", source_id="123",
            source_url="https://github.com/x",
        )
        assert inp.source == "github"
        assert inp.source_id == "123"


# ---------------------------------------------------------------------------
# UpdateStatusInput (Pydantic)
# ---------------------------------------------------------------------------

class TestUpdateStatusInput:
    def test_valid_statuses(self):
        for s in ("inbox", "active", "waiting", "done", "dropped"):
            inp = UpdateStatusInput(node_id="n1", new_status=s)
            assert inp.new_status == s

    def test_invalid_status_rejected(self):
        with pytest.raises(ValidationError):
            UpdateStatusInput(node_id="n1", new_status="deleted")


# ---------------------------------------------------------------------------
# UpdateFieldInput (Pydantic)
# ---------------------------------------------------------------------------

class TestUpdateFieldInput:
    def test_valid_fields(self):
        for f in ("title", "summary", "why", "next_step", "owner", "deadline", "node_type"):
            inp = UpdateFieldInput(node_id="n1", field=f, value="v")
            assert inp.field == f

    def test_field_whitelist_rejects_invalid(self):
        with pytest.raises(ValidationError):
            UpdateFieldInput(node_id="n1", field="status", value="active")

    def test_field_whitelist_rejects_id(self):
        with pytest.raises(ValidationError):
            UpdateFieldInput(node_id="n1", field="id", value="new-id")
