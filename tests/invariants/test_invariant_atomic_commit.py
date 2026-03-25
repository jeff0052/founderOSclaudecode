"""不变量测试：DB + outbox 原子性。

覆盖 PRD-functional §FR-0 不变量 #3, #5, #6：
- facts + audit_outbox 在同一事务内，崩溃后无半提交
- SQLite 事务提交为系统主提交点
- MD 写入失败不回滚 SQLite + 生成 repair event

这些测试永远不允许被后续 coding agent 修改。
"""

import json
import os

import pytest

from fpms.spine.store import Store

from .conftest import make_node


class TestAtomicFactsAndOutbox:
    """事实层 + audit_outbox 原子提交。"""

    def test_create_node_writes_both(self, store):
        """create_node 在同一事务内写入 nodes 表 + audit_outbox。"""
        node = make_node("task-0001", title="Atomic Test")
        result = store.create_node(node)

        # 验证 node 存在
        stored = store.get_node("task-0001")
        assert stored is not None
        assert stored.title == "Atomic Test"

        # 验证 audit_outbox 有对应记录（未 flush）
        # 直接查 SQLite 确认
        conn = store._conn  # 内部连接（测试用）
        row = conn.execute(
            "SELECT COUNT(*) FROM audit_outbox WHERE flushed=0"
        ).fetchone()
        assert row[0] >= 1, "audit_outbox should have at least 1 unflushed event"

    def test_transaction_rollback_on_error(self, store):
        """事务内异常 → 自动 rollback，DB 无脏数据。"""
        initial_count = len(store.list_nodes())

        try:
            with store.transaction():
                node = make_node("task-fail", title="Should Not Persist")
                store.create_node(node)
                raise RuntimeError("Simulated crash")
        except RuntimeError:
            pass

        # 节点不应存在
        assert store.get_node("task-fail") is None
        assert len(store.list_nodes()) == initial_count

    def test_no_partial_commit_on_crash(self, store):
        """模拟：写入 node 成功但 outbox 写入前崩溃 → 两者都不应存在。

        这个测试验证 facts 和 outbox 在同一事务内。
        如果实现正确（同一事务），异常回滚后两者都消失。
        """
        initial_count = len(store.list_nodes())

        try:
            with store.transaction():
                # 手动模拟：写入 node 后、写入 outbox 前崩溃
                node = make_node("task-partial", title="Partial")
                store.create_node(node)
                # 强制异常模拟崩溃
                raise Exception("Simulated mid-transaction crash")
        except Exception:
            pass

        # 确认无半提交
        assert store.get_node("task-partial") is None


class TestFlushEvents:
    """audit_outbox → events.jsonl flush 正确性。"""

    def test_flush_writes_to_jsonl(self, store, events_path):
        """flush_events 将 outbox 事件写入 events.jsonl + 标记 flushed=1。"""
        node = make_node("task-0001", title="Flush Test")
        store.create_node(node)

        count = store.flush_events()
        assert count >= 1

        # events.jsonl 应有内容
        assert os.path.exists(events_path)
        with open(events_path) as f:
            lines = f.readlines()
        assert len(lines) >= 1

        # 每行可 JSON parse
        for line in lines:
            event = json.loads(line.strip())
            assert "tool_name" in event or "event_type" in event

    def test_flush_marks_flushed(self, store):
        """flush 后 outbox 中的事件被标记为 flushed=1。"""
        node = make_node("task-0002", title="Flushed Test")
        store.create_node(node)

        store.flush_events()

        conn = store._conn
        row = conn.execute(
            "SELECT COUNT(*) FROM audit_outbox WHERE flushed=0"
        ).fetchone()
        assert row[0] == 0, "All events should be flushed"

    def test_double_flush_no_duplicate(self, store, events_path):
        """连续两次 flush 不产生重复事件。"""
        node = make_node("task-0003", title="Double Flush")
        store.create_node(node)

        count1 = store.flush_events()
        count2 = store.flush_events()

        assert count2 == 0, "Second flush should produce 0 new events"


class TestNarrativeFailureDoesNotRollbackSQLite:
    """MD 写入失败不回滚 SQLite（PRD §FR-0 不变量 #6）。"""

    def test_narrative_failure_preserves_facts(self, store, narratives_dir):
        """narrative 写入失败时，SQLite 中的事实仍然存在。"""
        from fpms.spine import narrative

        # 让 narratives 目录不可写来模拟失败
        node = make_node("task-narr", title="Narrative Fail Test",
                         status="active", summary="s", is_root=True)
        store.create_node(node)

        # 模拟 narrative 写入失败（实现应该 catch 并生成 repair event）
        success = narrative.append_narrative(
            narratives_dir="/nonexistent/path",
            node_id="task-narr",
            timestamp="2026-03-21T00:00:00Z",
            event_type="status_change",
            content="Should fail but not rollback DB",
        )

        # narrative 写入失败
        assert success is False

        # SQLite 中的节点仍然存在
        stored = store.get_node("task-narr")
        assert stored is not None
        assert stored.title == "Narrative Fail Test"
