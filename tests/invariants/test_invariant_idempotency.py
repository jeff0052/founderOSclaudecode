"""不变量测试：command_id 幂等。

覆盖 PRD-functional §FR-0 + ARCHITECTURE.md §Idempotency Protocol：
- 相同 command_id 重复调用返回相同结果
- 不产生重复数据（节点、边、审计事件）
- recent_commands 表记录命令结果

这些测试永远不允许被后续 coding agent 修改。
"""

import pytest

from fpms.spine.command_executor import CommandExecutor
from fpms.spine.store import Store

from .conftest import make_node


class TestIdempotentExecution:
    """相同 command_id 的 Tool Call 必须幂等。"""

    def test_duplicate_create_node_returns_same_result(self, store):
        """用相同 command_id 调用 create_node 两次 → 返回相同结果，只创建一个节点。"""
        executor = CommandExecutor(store)

        params = {
            "title": "Idempotent Node",
            "node_type": "task",
            "is_root": True,
        }

        result1 = executor.execute("cmd-idem-001", "create_node", params)
        result2 = executor.execute("cmd-idem-001", "create_node", params)

        # 两次返回相同结果
        assert result1.success is True
        assert result2.success is True
        assert result1.command_id == result2.command_id
        assert result1.data == result2.data

        # 只创建了一个节点
        nodes = store.list_nodes()
        matching = [n for n in nodes if n.title == "Idempotent Node"]
        assert len(matching) == 1

    def test_duplicate_update_status_no_double_transition(self, store):
        """用相同 command_id 调用 update_status 两次 → 不产生重复状态迁移。"""
        executor = CommandExecutor(store)

        # 先创建节点
        create_result = executor.execute("cmd-create-1", "create_node", {
            "title": "Status Test",
            "node_type": "task",
            "is_root": True,
            "summary": "ready",
        })
        node_id = create_result.data["id"] if create_result.data else None
        assert node_id is not None

        # 用相同 command_id 迁移状态两次
        params = {"node_id": node_id, "new_status": "active"}
        result1 = executor.execute("cmd-status-1", "update_status", params)
        result2 = executor.execute("cmd-status-1", "update_status", params)

        assert result1.success == result2.success

        # 节点状态只改了一次
        node = store.get_node(node_id)
        assert node.status == "active"

    def test_different_command_ids_are_independent(self, store):
        """不同 command_id → 独立执行，各自创建节点。"""
        executor = CommandExecutor(store)

        params1 = {"title": "Node A", "node_type": "task", "is_root": True}
        params2 = {"title": "Node B", "node_type": "task", "is_root": True}

        result1 = executor.execute("cmd-a", "create_node", params1)
        result2 = executor.execute("cmd-b", "create_node", params2)

        assert result1.success is True
        assert result2.success is True
        assert result1.data["id"] != result2.data["id"]

    def test_no_duplicate_audit_events(self, store):
        """幂等调用不产生重复的审计事件。"""
        executor = CommandExecutor(store)

        params = {"title": "Audit Test", "node_type": "task", "is_root": True}

        executor.execute("cmd-audit-1", "create_node", params)
        executor.execute("cmd-audit-1", "create_node", params)

        # 查 audit_outbox 中该 command_id 的事件数
        conn = store._conn
        row = conn.execute(
            "SELECT COUNT(*) FROM audit_outbox WHERE event_json LIKE ?",
            ('%cmd-audit-1%',),
        ).fetchone()

        # 应该只有 1 条（第一次执行产生的）
        assert row[0] == 1, "Duplicate command_id should not produce duplicate audit events"


class TestRecentCommandsTable:
    """recent_commands 表记录正确。"""

    def test_command_result_stored(self, store):
        """执行后 recent_commands 表有记录。"""
        executor = CommandExecutor(store)

        executor.execute("cmd-store-1", "create_node", {
            "title": "Stored Command",
            "node_type": "task",
            "is_root": True,
        })

        conn = store._conn
        row = conn.execute(
            "SELECT command_id, tool_name, result_json FROM recent_commands WHERE command_id=?",
            ("cmd-store-1",),
        ).fetchone()

        assert row is not None
        assert row[0] == "cmd-store-1"
        assert row[1] == "create_node"
        assert row[2] is not None  # result_json 非空
