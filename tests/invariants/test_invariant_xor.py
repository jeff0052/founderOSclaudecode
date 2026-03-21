"""不变量测试：is_root XOR parent_id。

覆盖 PRD-functional §FR-0 不变量 #1b：
- is_root=True 且 parent_id≠None → 永不共存
- DB CHECK 约束拒绝违规行
- attach_node 时自动将 is_root 覆写为 false
- update_status(is_root=true) 时自动将 parent_id 覆写为 null

这些测试永远不允许被后续 coding agent 修改。
"""

import sqlite3

import pytest

from fpms.spine.schema import init_db
from fpms.spine.validator import ValidationError, validate_xor_constraint

from .conftest import make_node


class TestXORValidation:
    """Python 层 XOR 校验。"""

    def test_root_with_parent_rejected(self):
        """is_root=True + parent_id 非空 → 拒绝。"""
        with pytest.raises(ValidationError) as exc_info:
            validate_xor_constraint(is_root=True, parent_id="some-parent")

        assert exc_info.value.code == "XOR_VIOLATION"

    def test_root_without_parent_allowed(self):
        """is_root=True + parent_id=None → 合法。"""
        validate_xor_constraint(is_root=True, parent_id=None)

    def test_non_root_with_parent_allowed(self):
        """is_root=False + parent_id 非空 → 合法。"""
        validate_xor_constraint(is_root=False, parent_id="some-parent")

    def test_non_root_without_parent_allowed(self):
        """is_root=False + parent_id=None → 合法（inbox 新建节点）。"""
        validate_xor_constraint(is_root=False, parent_id=None)


class TestXORDatabaseConstraint:
    """SQLite CHECK 约束层 XOR 强制。"""

    def test_db_rejects_root_with_parent(self, db):
        """数据库 CHECK 约束拒绝 is_root=1 AND parent_id IS NOT NULL。"""
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()

        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                """INSERT INTO nodes (id, title, status, node_type, is_root, parent_id,
                   created_at, updated_at, status_changed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                ("test-xor1", "Bad Node", "inbox", "task", 1, "some-parent",
                 now, now, now),
            )

    def test_db_allows_root_without_parent(self, db):
        """数据库允许 is_root=1 AND parent_id IS NULL。"""
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()

        db.execute(
            """INSERT INTO nodes (id, title, status, node_type, is_root, parent_id,
               created_at, updated_at, status_changed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("test-xor2", "Root Node", "inbox", "goal", 1, None,
             now, now, now),
        )
        db.commit()

        row = db.execute("SELECT id, is_root, parent_id FROM nodes WHERE id='test-xor2'").fetchone()
        assert row is not None
        assert row[1] == 1  # is_root
        assert row[2] is None  # parent_id


class TestXORAutoCorrection:
    """系统自动修正 XOR 冲突（通过 Tool Call 层面）。"""

    def test_attach_clears_is_root(self, store):
        """attach_node 到一个 is_root=True 的节点 → is_root 自动清为 False。"""
        root = make_node("goal-0001", title="Goal", is_root=True, node_type="goal")
        child = make_node("task-0001", title="Task", is_root=True)
        store.create_node(root)
        store.create_node(child)

        # 实现中 attach 应自动清除 child 的 is_root
        from fpms.spine.tools import ToolHandler
        from fpms.spine import validator as validator_module
        from fpms.spine import narrative as narrative_module

        handler = ToolHandler(store, validator_module, narrative_module)
        result = handler.handle("attach_node", {
            "node_id": "task-0001",
            "parent_id": "goal-0001",
            "command_id": "cmd-attach-1",
        })

        updated = store.get_node("task-0001")
        assert updated.is_root is False
        assert updated.parent_id == "goal-0001"

    def test_set_root_clears_parent(self, store):
        """update_status(is_root=true) → parent_id 自动清为 null。"""
        root = make_node("goal-0001", title="Goal", is_root=True, node_type="goal")
        child = make_node("task-0001", title="Task", parent_id="goal-0001",
                          status="inbox", summary="ready")
        store.create_node(root)
        store.create_node(child)

        from fpms.spine.tools import ToolHandler
        from fpms.spine import validator as validator_module
        from fpms.spine import narrative as narrative_module

        handler = ToolHandler(store, validator_module, narrative_module)
        result = handler.handle("update_status", {
            "node_id": "task-0001",
            "new_status": "active",
            "is_root": True,
            "command_id": "cmd-root-1",
        })

        updated = store.get_node("task-0001")
        assert updated.is_root is True
        assert updated.parent_id is None
