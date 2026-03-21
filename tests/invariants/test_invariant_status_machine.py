"""不变量测试：状态迁移合法性。

覆盖 PRD-functional §FR-0 + CLAUDE.md §Status Machine：
- 所有合法迁移通过
- 所有非法迁移被拒绝
- 前置条件校验（summary, parent/root, reason, 子节点终态）

这些测试永远不允许被后续 coding agent 修改。
"""

import pytest

from fpms.spine.models import Node
from fpms.spine.validator import ValidationError, validate_status_transition

from .conftest import make_node

# 合法迁移矩阵（来自 CLAUDE.md §Status Machine）
LEGAL_TRANSITIONS = [
    ("inbox", "active"),
    ("inbox", "waiting"),
    ("inbox", "dropped"),
    ("active", "waiting"),
    ("active", "done"),
    ("active", "dropped"),
    ("waiting", "active"),
    ("waiting", "done"),
    ("waiting", "dropped"),
    ("done", "active"),      # needs reason
    ("dropped", "inbox"),    # needs reason
]

# 非法迁移（不在合法矩阵中的所有组合）
ALL_STATUSES = ["inbox", "active", "waiting", "done", "dropped"]
ILLEGAL_TRANSITIONS = [
    (s, t) for s in ALL_STATUSES for t in ALL_STATUSES
    if s != t and (s, t) not in LEGAL_TRANSITIONS
]


class TestLegalTransitions:
    """所有合法状态迁移应通过（满足前置条件时）。"""

    @pytest.mark.parametrize("current,target", [
        ("inbox", "active"),
        ("inbox", "waiting"),
        ("inbox", "dropped"),
    ])
    def test_inbox_transitions(self, current, target):
        """inbox → active/waiting/dropped。"""
        node = make_node(
            status=current, is_root=True, summary="ready",
            parent_id=None,
        )
        # inbox→dropped 不需要 summary/parent，但我们给了也没问题
        if target in ("active", "waiting"):
            # 需要 summary + (parent OR root)
            assert node.summary is not None
            assert node.is_root is True

        warnings = validate_status_transition(current, target, node, children=[])
        assert isinstance(warnings, list)

    @pytest.mark.parametrize("current,target", [
        ("active", "waiting"),
        ("active", "done"),
        ("active", "dropped"),
    ])
    def test_active_transitions(self, current, target):
        """active → waiting/done/dropped。"""
        node = make_node(status=current, is_root=True, summary="in progress")
        warnings = validate_status_transition(current, target, node, children=[])
        assert isinstance(warnings, list)

    @pytest.mark.parametrize("current,target", [
        ("waiting", "active"),
        ("waiting", "done"),
        ("waiting", "dropped"),
    ])
    def test_waiting_transitions(self, current, target):
        """waiting → active/done/dropped。"""
        node = make_node(status=current, is_root=True, summary="waiting")
        warnings = validate_status_transition(current, target, node, children=[])
        assert isinstance(warnings, list)

    def test_done_to_active_with_reason(self):
        """done → active 需要 reason。"""
        node = make_node(status="done", is_root=True, summary="completed")
        warnings = validate_status_transition(
            "done", "active", node, children=[], reason="Reopened: found issues"
        )
        assert isinstance(warnings, list)

    def test_dropped_to_inbox_with_reason(self):
        """dropped → inbox 需要 reason。"""
        node = make_node(status="dropped", is_root=True, summary="dropped")
        warnings = validate_status_transition(
            "dropped", "inbox", node, children=[], reason="Reconsidering"
        )
        assert isinstance(warnings, list)


class TestIllegalTransitions:
    """所有非法状态迁移应被拒绝。"""

    @pytest.mark.parametrize("current,target", ILLEGAL_TRANSITIONS)
    def test_illegal_transition_rejected(self, current, target):
        """非法迁移 {current}→{target} 应抛出 ValidationError。"""
        node = make_node(status=current, is_root=True, summary="test")
        with pytest.raises(ValidationError) as exc_info:
            validate_status_transition(current, target, node, children=[],
                                        reason="test reason")

        assert exc_info.value.code is not None
        assert exc_info.value.suggestion is not None


class TestTransitionPreconditions:
    """前置条件不满足时应拒绝。"""

    def test_inbox_to_active_missing_summary(self):
        """inbox→active 缺 summary → 拒绝 + actionable suggestion。"""
        node = make_node(status="inbox", is_root=True, summary=None)

        with pytest.raises(ValidationError) as exc_info:
            validate_status_transition("inbox", "active", node, children=[])

        assert "summary" in exc_info.value.message.lower() or \
               "summary" in exc_info.value.suggestion.lower()

    def test_inbox_to_active_missing_parent_and_not_root(self):
        """inbox→active 缺 parent_id 且非 root → 拒绝。"""
        node = make_node(status="inbox", is_root=False, parent_id=None, summary="ready")

        with pytest.raises(ValidationError) as exc_info:
            validate_status_transition("inbox", "active", node, children=[])

        assert exc_info.value.code is not None

    def test_inbox_to_waiting_missing_summary(self):
        """inbox→waiting 缺 summary → 拒绝。"""
        node = make_node(status="inbox", is_root=True, summary=None)

        with pytest.raises(ValidationError):
            validate_status_transition("inbox", "waiting", node, children=[])

    def test_to_done_with_active_children(self):
        """→done 有活跃子节点 → 拒绝 + 列出未完成子节点。"""
        parent = make_node("goal-0001", status="active", is_root=True, summary="goal")
        active_child = make_node("task-0001", status="active", parent_id="goal-0001",
                                  summary="child")

        with pytest.raises(ValidationError) as exc_info:
            validate_status_transition("active", "done", parent,
                                        children=[active_child])

        # 错误消息应包含未完成子节点的信息
        assert "task-0001" in exc_info.value.message or \
               "child" in exc_info.value.message.lower()

    def test_to_done_all_children_terminal(self):
        """→done 所有子节点终态 → 允许。"""
        parent = make_node("goal-0001", status="active", is_root=True, summary="goal")
        done_child = make_node("task-0001", status="done", parent_id="goal-0001",
                                summary="child")
        dropped_child = make_node("task-0002", status="dropped", parent_id="goal-0001",
                                   summary="child2")

        warnings = validate_status_transition(
            "active", "done", parent, children=[done_child, dropped_child]
        )
        assert isinstance(warnings, list)

    def test_to_dropped_with_active_children_warns(self):
        """→dropped 有活跃子节点 → 允许但返回 warning。"""
        parent = make_node("goal-0001", status="active", is_root=True, summary="goal")
        active_child = make_node("task-0001", status="active", parent_id="goal-0001",
                                  summary="child")

        warnings = validate_status_transition(
            "active", "dropped", parent, children=[active_child]
        )

        assert len(warnings) > 0, "Should warn about active children"

    def test_done_to_active_missing_reason(self):
        """done→active 缺 reason → 拒绝。"""
        node = make_node(status="done", is_root=True, summary="done")

        with pytest.raises(ValidationError) as exc_info:
            validate_status_transition("done", "active", node, children=[],
                                        reason=None)

        assert "reason" in exc_info.value.message.lower() or \
               "reason" in exc_info.value.suggestion.lower()

    def test_dropped_to_inbox_missing_reason(self):
        """dropped→inbox 缺 reason → 拒绝。"""
        node = make_node(status="dropped", is_root=True, summary="dropped")

        with pytest.raises(ValidationError) as exc_info:
            validate_status_transition("dropped", "inbox", node, children=[],
                                        reason=None)

        assert "reason" in exc_info.value.message.lower() or \
               "reason" in exc_info.value.suggestion.lower()
