"""不变量测试：DAG 永不成环。

覆盖 PRD-functional §FR-0 不变量 #2（全息防环 Unified DAG Check）：
- parent 环路 → 拒绝
- depends_on 环路 → 拒绝
- 跨维度环（child depends_on ancestor）→ 拒绝

这些测试永远不允许被后续 coding agent 修改。
"""

import pytest

from fpms.spine.validator import ValidationError, validate_dag_safety

from .conftest import make_edge, make_node


class TestParentCycleDetection:
    """parent_id 形成环路 → 必须拒绝。"""

    def test_direct_parent_cycle(self, store):
        """A→B→A 的直接 parent 环路。"""
        node_a = make_node("task-aaaa", title="A")
        node_b = make_node("task-bbbb", title="B", parent_id="task-aaaa")
        store.create_node(node_a)
        store.create_node(node_b)

        # B 已是 A 的子节点，现在尝试让 A 成为 B 的子节点 → 环路
        with pytest.raises(ValidationError) as exc_info:
            validate_dag_safety(store, "task-aaaa", "task-bbbb", "parent")

        assert exc_info.value.code == "CYCLE_DETECTED"

    def test_indirect_parent_cycle(self, store):
        """A→B→C→A 的间接 parent 环路。"""
        node_a = make_node("task-aaaa", title="A", is_root=True)
        node_b = make_node("task-bbbb", title="B", parent_id="task-aaaa")
        node_c = make_node("task-cccc", title="C", parent_id="task-bbbb")
        store.create_node(node_a)
        store.create_node(node_b)
        store.create_node(node_c)

        # 尝试 A.parent_id = C → 形成 A→B→C→A 环路
        with pytest.raises(ValidationError) as exc_info:
            validate_dag_safety(store, "task-aaaa", "task-cccc", "parent")

        assert exc_info.value.code == "CYCLE_DETECTED"

    def test_self_parent(self, store):
        """节点不能是自己的 parent。"""
        node_a = make_node("task-aaaa", title="A")
        store.create_node(node_a)

        with pytest.raises(ValidationError):
            validate_dag_safety(store, "task-aaaa", "task-aaaa", "parent")


class TestDependsCycleDetection:
    """depends_on 环路 → 必须拒绝。"""

    def test_direct_depends_cycle(self, store):
        """A depends_on B, B depends_on A → 拒绝。"""
        node_a = make_node("task-aaaa", title="A", is_root=True, status="active", summary="s")
        node_b = make_node("task-bbbb", title="B", is_root=True, status="active", summary="s")
        store.create_node(node_a)
        store.create_node(node_b)
        store.add_edge(make_edge("task-aaaa", "task-bbbb", "depends_on"))

        # B depends_on A → 形成互相依赖环路
        with pytest.raises(ValidationError) as exc_info:
            validate_dag_safety(store, "task-bbbb", "task-aaaa", "depends_on")

        assert exc_info.value.code == "CYCLE_DETECTED"

    def test_indirect_depends_cycle(self, store):
        """A→B→C→A 的 depends_on 链条。"""
        for nid in ["task-aaaa", "task-bbbb", "task-cccc"]:
            store.create_node(make_node(nid, title=nid, is_root=True, status="active", summary="s"))

        store.add_edge(make_edge("task-aaaa", "task-bbbb", "depends_on"))
        store.add_edge(make_edge("task-bbbb", "task-cccc", "depends_on"))

        # C depends_on A → 环路
        with pytest.raises(ValidationError) as exc_info:
            validate_dag_safety(store, "task-cccc", "task-aaaa", "depends_on")

        assert exc_info.value.code == "CYCLE_DETECTED"

    def test_self_dependency(self, store):
        """节点不能 depends_on 自己。"""
        node_a = make_node("task-aaaa", title="A", is_root=True, status="active", summary="s")
        store.create_node(node_a)

        with pytest.raises(ValidationError):
            validate_dag_safety(store, "task-aaaa", "task-aaaa", "depends_on")


class TestCrossDimensionCycle:
    """跨维度环路：child depends_on ancestor → 必须拒绝。

    PRD §FR-0 #2: 严禁子孙节点横向阻塞祖先节点。
    否则 rollup 冒泡与 blocked 标记互相死锁，子树永久冻结。
    """

    def test_child_depends_on_parent(self, store):
        """子节点 depends_on 父节点 → 拒绝。"""
        parent = make_node("goal-0001", title="Goal", is_root=True, node_type="goal",
                           status="active", summary="s")
        child = make_node("task-0001", title="Task", parent_id="goal-0001",
                          status="active", summary="s")
        store.create_node(parent)
        store.create_node(child)
        store.add_edge(make_edge("task-0001", "goal-0001", "parent"))

        # child depends_on parent → 跨维度死锁
        with pytest.raises(ValidationError) as exc_info:
            validate_dag_safety(store, "task-0001", "goal-0001", "depends_on")

        assert exc_info.value.code == "CYCLE_DETECTED"

    def test_grandchild_depends_on_grandparent(self, store):
        """孙节点 depends_on 祖父节点 → 拒绝。"""
        gp = make_node("goal-0001", title="Goal", is_root=True, node_type="goal",
                        status="active", summary="s")
        parent = make_node("proj-0001", title="Project", parent_id="goal-0001",
                           node_type="project", status="active", summary="s")
        child = make_node("task-0001", title="Task", parent_id="proj-0001",
                          status="active", summary="s")
        store.create_node(gp)
        store.create_node(parent)
        store.create_node(child)
        store.add_edge(make_edge("proj-0001", "goal-0001", "parent"))
        store.add_edge(make_edge("task-0001", "proj-0001", "parent"))

        # grandchild depends_on grandparent → 跨维度死锁
        with pytest.raises(ValidationError) as exc_info:
            validate_dag_safety(store, "task-0001", "goal-0001", "depends_on")

        assert exc_info.value.code == "CYCLE_DETECTED"

    def test_non_ancestor_dependency_allowed(self, store):
        """非祖先节点之间的 depends_on 应该允许（正常路径）。"""
        root = make_node("goal-0001", title="Goal", is_root=True, node_type="goal",
                         status="active", summary="s")
        task_a = make_node("task-aaaa", title="A", parent_id="goal-0001",
                           status="active", summary="s")
        task_b = make_node("task-bbbb", title="B", parent_id="goal-0001",
                           status="active", summary="s")
        store.create_node(root)
        store.create_node(task_a)
        store.create_node(task_b)
        store.add_edge(make_edge("task-aaaa", "goal-0001", "parent"))
        store.add_edge(make_edge("task-bbbb", "goal-0001", "parent"))

        # 同级兄弟之间的 depends_on → 应该允许
        validate_dag_safety(store, "task-aaaa", "task-bbbb", "depends_on")
