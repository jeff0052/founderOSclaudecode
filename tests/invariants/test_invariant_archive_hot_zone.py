"""不变量测试：归档不破坏热区。

覆盖 PRD-functional §FR-0 + §附录7 拓扑安全：
- attach_node 到已归档节点 → 拒绝
- add_dependency 到已归档节点 → 拒绝
- 活跃域隔离：写操作目标必须是非归档节点

这些测试永远不允许被后续 coding agent 修改。
"""

from datetime import datetime, timezone

import pytest

from fpms.spine.validator import (
    ValidationError,
    validate_active_domain,
    validate_attach,
    validate_dependency,
)

from .conftest import make_node


class TestActiveDomainValidation:
    """活跃域校验：已归档节点不可作为写操作目标。"""

    def test_archived_node_rejected(self):
        """已归档节点 → 拒绝。"""
        now = datetime.now(timezone.utc).isoformat()
        archived_node = make_node(
            "task-arch", title="Archived", status="done", archived_at=now,
        )

        with pytest.raises(ValidationError) as exc_info:
            validate_active_domain(archived_node)

        assert exc_info.value.code is not None

    def test_non_archived_node_allowed(self):
        """非归档节点 → 允许。"""
        active_node = make_node("task-0001", title="Active", status="active")
        validate_active_domain(active_node)  # 不应抛异常

    def test_done_but_not_archived_allowed(self):
        """done 但未归档的节点 → 允许（归档有 7 天冷却期）。"""
        done_node = make_node("task-done", title="Done", status="done", archived_at=None)
        validate_active_domain(done_node)  # 不应抛异常


class TestAttachToArchivedNode:
    """attach_node 到已归档节点 → 拒绝。"""

    def test_attach_to_archived_parent(self, store):
        """尝试将节点挂载到已归档的父节点 → 拒绝。"""
        now = datetime.now(timezone.utc).isoformat()

        archived_parent = make_node(
            "goal-arch", title="Archived Goal", status="done",
            is_root=True, node_type="goal", archived_at=now,
        )
        child = make_node("task-0001", title="Child Task", status="inbox")

        store.create_node(archived_parent)
        store.create_node(child)

        with pytest.raises(ValidationError):
            validate_attach(store, "task-0001", "goal-arch")

    def test_attach_to_active_parent_allowed(self, store):
        """将节点挂载到活跃父节点 → 允许。"""
        active_parent = make_node(
            "goal-0001", title="Active Goal", status="active",
            is_root=True, node_type="goal", summary="active",
        )
        child = make_node("task-0001", title="Child Task", status="inbox")

        store.create_node(active_parent)
        store.create_node(child)

        validate_attach(store, "task-0001", "goal-0001")  # 不应抛异常


class TestDependencyToArchivedNode:
    """add_dependency 到已归档节点 → 拒绝。"""

    def test_depend_on_archived_node(self, store):
        """依赖已归档节点 → 拒绝。"""
        now = datetime.now(timezone.utc).isoformat()

        archived = make_node(
            "task-arch", title="Archived Task", status="done",
            is_root=True, archived_at=now,
        )
        active = make_node(
            "task-0001", title="Active Task", status="active",
            is_root=True, summary="active",
        )

        store.create_node(archived)
        store.create_node(active)

        with pytest.raises(ValidationError):
            validate_dependency(store, "task-0001", "task-arch")

    def test_depend_on_active_node_allowed(self, store):
        """依赖活跃节点 → 允许。"""
        node_a = make_node(
            "task-aaaa", title="A", status="active", is_root=True, summary="a",
        )
        node_b = make_node(
            "task-bbbb", title="B", status="active", is_root=True, summary="b",
        )

        store.create_node(node_a)
        store.create_node(node_b)

        validate_dependency(store, "task-aaaa", "task-bbbb")  # 不应抛异常
