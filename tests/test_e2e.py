"""端到端冒烟测试 — 跨模块验证完整系统流程（9 个场景）。"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Optional

import pytest

from fpms.spine.models import Edge, Node, ToolResult
from fpms.spine.store import Store
from fpms.spine.tools import ToolHandler
from fpms.spine.command_executor import CommandExecutor
from fpms.spine import validator as validator_mod
from fpms.spine import narrative as narrative_mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_dirs(tmp_path):
    """Return paths for db, events, and narratives in a temp directory."""
    db_path = str(tmp_path / "e2e_test.db")
    events_path = str(tmp_path / "events.jsonl")
    narratives_dir = str(tmp_path / "narratives")
    return db_path, events_path, narratives_dir


@pytest.fixture
def store(tmp_dirs):
    db_path, events_path, _ = tmp_dirs
    return Store(db_path, events_path)


@pytest.fixture
def handler(store, tmp_dirs):
    _, _, narratives_dir = tmp_dirs
    h = ToolHandler(store)
    h.narratives_dir = narratives_dir
    return h


@pytest.fixture
def executor(store, handler):
    return CommandExecutor(store, tool_handler=handler)


def _cmd_id(prefix: str, idx: int = 0) -> str:
    """Generate a unique command_id for test use."""
    return f"e2e-{prefix}-{idx}"


# ===========================================================================
# Scenario A: Basic Lifecycle
# ===========================================================================

class TestScenarioA_BasicLifecycle:
    """Create goal→project→task tree, then walk inbox→active→done bottom-up."""

    def test_full_lifecycle(self, executor, store, tmp_dirs):
        _, _, narratives_dir = tmp_dirs

        # 1. Create goal (is_root=true)
        r = executor.execute("a-create-goal", "create_node", {
            "title": "Ship v1",
            "node_type": "goal",
            "is_root": True,
            "summary": "Ship product v1",
        })
        assert r.success, r.error
        goal_id = r.data["id"]

        # 2. Create project, attach to goal
        r = executor.execute("a-create-proj", "create_node", {
            "title": "Backend API",
            "node_type": "project",
        })
        assert r.success, r.error
        proj_id = r.data["id"]

        r = executor.execute("a-attach-proj", "attach_node", {
            "node_id": proj_id,
            "parent_id": goal_id,
        })
        assert r.success, r.error

        # 3. Create task, attach to project
        r = executor.execute("a-create-task", "create_node", {
            "title": "Write tests",
            "node_type": "task",
        })
        assert r.success, r.error
        task_id = r.data["id"]

        r = executor.execute("a-attach-task", "attach_node", {
            "node_id": task_id,
            "parent_id": proj_id,
        })
        assert r.success, r.error

        # 4. Verify 3-level tree
        goal_children = store.get_children(goal_id)
        assert len(goal_children) == 1
        assert goal_children[0].id == proj_id

        proj_children = store.get_children(proj_id)
        assert len(proj_children) == 1
        assert proj_children[0].id == task_id

        task_children = store.get_children(task_id)
        assert len(task_children) == 0

        # 5. task: inbox → active (need summary first)
        r = executor.execute("a-task-summary", "update_field", {
            "node_id": task_id,
            "field": "summary",
            "value": "Write comprehensive tests",
        })
        assert r.success, r.error

        r = executor.execute("a-task-active", "update_status", {
            "node_id": task_id,
            "new_status": "active",
        })
        assert r.success, r.error

        # 6. task: active → done
        r = executor.execute("a-task-done", "update_status", {
            "node_id": task_id,
            "new_status": "done",
        })
        assert r.success, r.error

        # 7. project: inbox → active → done
        r = executor.execute("a-proj-summary", "update_field", {
            "node_id": proj_id,
            "field": "summary",
            "value": "Backend API project",
        })
        assert r.success, r.error

        r = executor.execute("a-proj-active", "update_status", {
            "node_id": proj_id,
            "new_status": "active",
        })
        assert r.success, r.error

        r = executor.execute("a-proj-done", "update_status", {
            "node_id": proj_id,
            "new_status": "done",
        })
        assert r.success, r.error

        # 8. goal: inbox → active → done
        r = executor.execute("a-goal-active", "update_status", {
            "node_id": goal_id,
            "new_status": "active",
        })
        assert r.success, r.error

        r = executor.execute("a-goal-done", "update_status", {
            "node_id": goal_id,
            "new_status": "done",
        })
        assert r.success, r.error

        # Final verification
        goal = store.get_node(goal_id)
        proj = store.get_node(proj_id)
        task = store.get_node(task_id)
        assert goal.status == "done"
        assert proj.status == "done"
        assert task.status == "done"


# ===========================================================================
# Scenario B: Dependencies & Blocking
# ===========================================================================

class TestScenarioB_DependenciesBlocking:
    """Create task-A and task-B with dependency, verify cycle rejection."""

    def test_dependency_and_cycle_rejection(self, executor, store):
        # Create task-A
        r = executor.execute("b-create-a", "create_node", {
            "title": "Task A",
            "node_type": "task",
            "is_root": True,
            "summary": "First task",
        })
        assert r.success, r.error
        task_a_id = r.data["id"]

        # Create task-B
        r = executor.execute("b-create-b", "create_node", {
            "title": "Task B",
            "node_type": "task",
            "is_root": True,
            "summary": "Second task",
        })
        assert r.success, r.error
        task_b_id = r.data["id"]

        # task-B depends_on task-A
        r = executor.execute("b-dep-ba", "add_dependency", {
            "source_id": task_b_id,
            "target_id": task_a_id,
        })
        assert r.success, r.error

        # Attempt reverse dependency → cycle rejected
        r = executor.execute("b-dep-ab-cycle", "add_dependency", {
            "source_id": task_a_id,
            "target_id": task_b_id,
        })
        assert not r.success
        assert "CYCLE" in r.error.upper() or "环" in r.error

        # task-A → done (should work — no children blocking)
        r = executor.execute("b-a-active", "update_status", {
            "node_id": task_a_id,
            "new_status": "active",
        })
        assert r.success, r.error

        r = executor.execute("b-a-done", "update_status", {
            "node_id": task_a_id,
            "new_status": "done",
        })
        assert r.success, r.error
        assert store.get_node(task_a_id).status == "done"


# ===========================================================================
# Scenario C: Status Rollback
# ===========================================================================

class TestScenarioC_StatusRollback:
    """done→active with reason, dropped→inbox with reason, verify narrative."""

    def test_done_to_active_with_reason(self, executor, store, tmp_dirs):
        _, _, narratives_dir = tmp_dirs

        # Create and advance to done
        r = executor.execute("c1-create", "create_node", {
            "title": "Rollback Test",
            "node_type": "task",
            "is_root": True,
            "summary": "Test rollback",
        })
        assert r.success
        nid = r.data["id"]

        r = executor.execute("c1-active", "update_status", {
            "node_id": nid, "new_status": "active",
        })
        assert r.success

        r = executor.execute("c1-done", "update_status", {
            "node_id": nid, "new_status": "done",
        })
        assert r.success

        # done → active WITH reason
        r = executor.execute("c1-reactivate", "update_status", {
            "node_id": nid, "new_status": "active", "reason": "Requirements changed",
        })
        assert r.success, r.error

        # Verify reason in narrative
        narrative = narrative_mod.read_narrative(narratives_dir, nid)
        assert "Requirements changed" in narrative

    def test_dropped_to_inbox_with_reason(self, executor, store, tmp_dirs):
        _, _, narratives_dir = tmp_dirs

        r = executor.execute("c2-create", "create_node", {
            "title": "Drop Test",
            "node_type": "task",
            "is_root": True,
            "summary": "Test drop rollback",
        })
        assert r.success
        nid = r.data["id"]

        # inbox → dropped
        r = executor.execute("c2-drop", "update_status", {
            "node_id": nid, "new_status": "dropped",
        })
        assert r.success

        # dropped → inbox WITH reason
        r = executor.execute("c2-restore", "update_status", {
            "node_id": nid, "new_status": "inbox", "reason": "Stakeholder insisted",
        })
        assert r.success, r.error

        narrative = narrative_mod.read_narrative(narratives_dir, nid)
        assert "Stakeholder insisted" in narrative


# ===========================================================================
# Scenario D: Archive Boundary
# ===========================================================================

class TestScenarioD_ArchiveBoundary:
    """Unarchive refreshes status_changed_at; attach/dependency to archived → rejected."""

    def _make_archived_node(self, store):
        """Helper: create a node and manually archive it via SQL."""
        node = Node(
            id="", title="Archived Node", status="done", node_type="task",
            is_root=True,
        )
        created = store.create_node(node)
        # Manually set archived_at
        now = datetime.now(timezone.utc).isoformat()
        with store.transaction():
            store._conn.execute(
                "UPDATE nodes SET archived_at=? WHERE id=?", (now, created.id)
            )
        return store.get_node(created.id)

    def test_unarchive_refreshes_status_changed_at(self, executor, store):
        archived = self._make_archived_node(store)
        old_sca = archived.status_changed_at

        r = executor.execute("d-unarchive", "unarchive", {
            "node_id": archived.id,
        })
        assert r.success, r.error

        refreshed = store.get_node(archived.id)
        assert refreshed.archived_at is None
        assert refreshed.status_changed_at != old_sca
        # The new status_changed_at should be a valid ISO timestamp
        datetime.fromisoformat(refreshed.status_changed_at)

    def test_attach_to_archived_rejected(self, executor, store):
        archived = self._make_archived_node(store)

        # Create a live node
        r = executor.execute("d-create-live", "create_node", {
            "title": "Live Node", "node_type": "task",
        })
        assert r.success
        live_id = r.data["id"]

        # Try to attach live node to archived node → rejected
        r = executor.execute("d-attach-archived", "attach_node", {
            "node_id": live_id,
            "parent_id": archived.id,
        })
        assert not r.success
        assert "ARCHIVED" in r.error.upper() or "归档" in r.error

    def test_add_dependency_to_archived_rejected(self, executor, store):
        archived = self._make_archived_node(store)

        r = executor.execute("d-create-dep", "create_node", {
            "title": "Dep Node", "node_type": "task", "is_root": True,
        })
        assert r.success
        dep_id = r.data["id"]

        # Try to add dependency to archived node → rejected
        r = executor.execute("d-dep-archived", "add_dependency", {
            "source_id": dep_id,
            "target_id": archived.id,
        })
        assert not r.success
        assert "ARCHIVED" in r.error.upper() or "归档" in r.error


# ===========================================================================
# Scenario E: Audit Completeness
# ===========================================================================

class TestScenarioE_AuditCompleteness:
    """After operations: audit_outbox has records, flush → events.jsonl valid JSON."""

    def test_audit_and_flush(self, executor, store, tmp_dirs):
        _, events_path, _ = tmp_dirs

        # Perform several operations
        r = executor.execute("e-create", "create_node", {
            "title": "Audit Test", "node_type": "task", "is_root": True,
            "summary": "Testing audit",
        })
        assert r.success
        nid = r.data["id"]

        r = executor.execute("e-active", "update_status", {
            "node_id": nid, "new_status": "active",
        })
        assert r.success

        r = executor.execute("e-done", "update_status", {
            "node_id": nid, "new_status": "done",
        })
        assert r.success

        # Verify audit_outbox has records
        rows = store._conn.execute(
            "SELECT COUNT(*) FROM audit_outbox"
        ).fetchone()
        assert rows[0] > 0, "audit_outbox should have records"

        # Verify events.jsonl exists and has lines
        assert os.path.exists(events_path), "events.jsonl should exist after executor flush"

        with open(events_path, "r") as f:
            lines = [line.strip() for line in f if line.strip()]

        assert len(lines) > 0, "events.jsonl should have lines"

        # Each line is valid JSON with tool_name + timestamp
        for line in lines:
            event = json.loads(line)
            assert "tool_name" in event, f"Event missing tool_name: {event}"
            assert "timestamp" in event, f"Event missing timestamp: {event}"


# ===========================================================================
# Scenario F: Idempotency
# ===========================================================================

class TestScenarioF_Idempotency:
    """Same command_id twice → only 1 node created."""

    def test_same_command_id_creates_one_node(self, executor, store):
        cmd_id = "f-idempotent-create"

        r1 = executor.execute(cmd_id, "create_node", {
            "title": "Idempotent Node", "node_type": "task", "is_root": True,
        })
        assert r1.success

        r2 = executor.execute(cmd_id, "create_node", {
            "title": "Idempotent Node", "node_type": "task", "is_root": True,
        })
        assert r2.success

        # Both should return the same node ID
        assert r1.data["id"] == r2.data["id"]

        # Only 1 node in the DB with that title
        rows = store._conn.execute(
            "SELECT COUNT(*) FROM nodes WHERE title='Idempotent Node'"
        ).fetchone()
        assert rows[0] == 1


# ===========================================================================
# Scenario G: Actionable Errors
# ===========================================================================

class TestScenarioG_ActionableErrors:
    """Trigger 3+ different ValidationErrors, each with suggestion mentioning a Tool."""

    def test_missing_summary_error(self, executor, store):
        """inbox→active without summary → error with suggestion mentioning update_field."""
        r = executor.execute("g1-create", "create_node", {
            "title": "No Summary", "node_type": "task", "is_root": True,
        })
        assert r.success
        nid = r.data["id"]

        r = executor.execute("g1-activate", "update_status", {
            "node_id": nid, "new_status": "active",
        })
        assert not r.success
        assert r.suggestion is not None
        assert "update_field" in r.suggestion

    def test_missing_reason_error(self, executor, store):
        """done→active without reason → error with suggestion mentioning update_status."""
        r = executor.execute("g2-create", "create_node", {
            "title": "Done Node", "node_type": "task", "is_root": True,
            "summary": "Has summary",
        })
        assert r.success
        nid = r.data["id"]

        executor.execute("g2-active", "update_status", {
            "node_id": nid, "new_status": "active",
        })
        executor.execute("g2-done", "update_status", {
            "node_id": nid, "new_status": "done",
        })

        # done→active without reason
        r = executor.execute("g2-reactivate", "update_status", {
            "node_id": nid, "new_status": "active",
        })
        assert not r.success
        assert r.suggestion is not None
        assert "update_status" in r.suggestion

    def test_illegal_transition_error(self, executor, store):
        """done→waiting → illegal transition with suggestion listing legal targets."""
        r = executor.execute("g3-create", "create_node", {
            "title": "Transition Node", "node_type": "task", "is_root": True,
            "summary": "Has summary",
        })
        assert r.success
        nid = r.data["id"]

        executor.execute("g3-active", "update_status", {
            "node_id": nid, "new_status": "active",
        })
        executor.execute("g3-done", "update_status", {
            "node_id": nid, "new_status": "done",
        })

        # done→waiting is illegal
        r = executor.execute("g3-illegal", "update_status", {
            "node_id": nid, "new_status": "waiting",
        })
        assert not r.success
        assert r.suggestion is not None
        # Suggestion should mention legal transitions
        assert "active" in r.suggestion.lower()


# ===========================================================================
# Scenario H: External Source Nodes
# ===========================================================================

class TestScenarioH_ExternalSourceNodes:
    """Create node with source="github", verify fields, update source_*, search by source."""

    def test_external_source_lifecycle(self, executor, store):
        # Create node with external source fields
        r = executor.execute("h-create-gh", "create_node", {
            "title": "Fix CI pipeline",
            "node_type": "task",
            "is_root": True,
            "summary": "GitHub issue for CI fix",
            "source": "github",
            "source_id": "octocat/repo#42",
            "source_url": "https://github.com/octocat/repo/issues/42",
        })
        assert r.success, r.error
        gh_id = r.data["id"]

        # get_node returns complete source_* fields
        node = store.get_node(gh_id)
        assert node.source == "github"
        assert node.source_id == "octocat/repo#42"
        assert node.source_url == "https://github.com/octocat/repo/issues/42"
        assert node.source_synced_at is None
        assert node.source_deleted is False

        # Update source_synced_at
        now = datetime.now(timezone.utc).isoformat()
        with store.transaction():
            store.update_node(gh_id, {"source_synced_at": now})
        node = store.get_node(gh_id)
        assert node.source_synced_at is not None

        # Update source_deleted
        with store.transaction():
            store.update_node(gh_id, {"source_deleted": True})
        node = store.get_node(gh_id)
        assert node.source_deleted is True

        # Create an internal node for contrast
        r = executor.execute("h-create-internal", "create_node", {
            "title": "Internal Task",
            "node_type": "task",
            "is_root": True,
        })
        assert r.success

        # search_nodes(source="github") returns only github nodes
        r = executor.execute("h-search-gh", "search_nodes", {
            "filters": {"source": "github"},
        })
        assert r.success
        assert r.data["count"] >= 1
        for n in r.data["nodes"]:
            assert n["source"] == "github"

        # search_nodes(source="internal") does not return github node
        r = executor.execute("h-search-internal", "search_nodes", {
            "filters": {"source": "internal"},
        })
        assert r.success
        node_ids = [n["id"] for n in r.data["nodes"]]
        assert gh_id not in node_ids


# ===========================================================================
# Scenario I: Compression Control & Tags
# ===========================================================================

class TestScenarioI_CompressionAndTags:
    """Verify compression control fields and tags defaults + updates."""

    def test_compression_defaults_and_update(self, executor, store):
        # Create node → needs_compression defaults false
        r = executor.execute("i-create", "create_node", {
            "title": "Compress Test",
            "node_type": "task",
            "is_root": True,
        })
        assert r.success
        nid = r.data["id"]

        node = store.get_node(nid)
        assert node.needs_compression is False
        assert node.no_llm_compression is False

        # Update needs_compression=true
        with store.transaction():
            store.update_node(nid, {"needs_compression": True})
        node = store.get_node(nid)
        assert node.needs_compression is True

        # Update no_llm_compression=true
        with store.transaction():
            store.update_node(nid, {"no_llm_compression": True})
        node = store.get_node(nid)
        assert node.no_llm_compression is True

    def test_tags_defaults_and_update(self, executor, store):
        # Create node → tags defaults []
        r = executor.execute("i-create-tags", "create_node", {
            "title": "Tags Test",
            "node_type": "task",
            "is_root": True,
        })
        assert r.success
        nid = r.data["id"]

        node = store.get_node(nid)
        assert node.tags == []

        # Update tags
        with store.transaction():
            store.update_node(nid, {"tags": ["urgent", "backend"]})
        node = store.get_node(nid)
        assert node.tags == ["urgent", "backend"]
