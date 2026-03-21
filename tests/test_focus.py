"""focus.py 测试 — FocusScheduler: arbitration, LRU eviction, stash, decay.

TDD: 先写测试，再实现。
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone, timedelta
from typing import Optional
from unittest.mock import MagicMock, call

import pytest

from fpms.spine.models import Node, FocusState
from fpms.spine.schema import init_db
from fpms.spine.store import Store
from fpms.spine.focus import FocusScheduler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _make_node(
    node_id: str,
    status: str = "active",
    archived_at: Optional[str] = None,
    node_type: str = "task",
) -> Node:
    now = _iso(_now())
    return Node(
        id=node_id,
        title=f"Node {node_id}",
        status=status,
        node_type=node_type,
        created_at=now,
        updated_at=now,
        status_changed_at=now,
        archived_at=archived_at,
    )


@pytest.fixture
def store(tmp_path):
    """Real Store backed by a temp SQLite DB."""
    db_path = str(tmp_path / "test.db")
    events_path = str(tmp_path / "events.jsonl")
    s = Store(db_path=db_path, events_path=events_path)
    yield s
    s._conn.close()


def _insert_node(store: Store, node: Node) -> None:
    """Insert a Node directly into DB without ID generation."""
    now = _iso(_now())
    store._conn.execute(
        """INSERT INTO nodes (
            id, title, status, node_type, is_root, parent_id,
            summary, why, next_step, owner, deadline, is_persistent,
            created_at, updated_at, status_changed_at, archived_at,
            source, source_id, source_url, source_synced_at, source_deleted,
            needs_compression, compression_in_progress, no_llm_compression, tags
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            node.id, node.title, node.status, node.node_type,
            int(node.is_root), node.parent_id,
            node.summary, node.why, node.next_step, node.owner,
            node.deadline, int(node.is_persistent),
            node.created_at, node.updated_at,
            node.status_changed_at or now,
            node.archived_at,
            node.source, node.source_id, node.source_url,
            node.source_synced_at, int(node.source_deleted),
            int(node.needs_compression), int(node.compression_in_progress),
            int(node.no_llm_compression),
            json.dumps(node.tags),
        ),
    )
    store._conn.commit()


def _make_scheduler(store: Store, narrative_module=None) -> FocusScheduler:
    return FocusScheduler(store, narrative_module=narrative_module)


# ===========================================================================
# TestShiftFocus
# ===========================================================================

class TestShiftFocus:
    """shift_focus 基本行为测试。"""

    def test_shift_sets_primary(self, store):
        """shift_focus 将 node_id 设置为 primary。"""
        node = _make_node("task-001")
        _insert_node(store, node)
        sched = _make_scheduler(store)

        state = sched.shift_focus("task-001")
        assert state.primary == "task-001"

    def test_old_primary_moves_to_secondary(self, store):
        """shift_focus 时旧 primary 移入 secondary 前端。"""
        node_a = _make_node("task-001")
        node_b = _make_node("task-002")
        _insert_node(store, node_a)
        _insert_node(store, node_b)
        sched = _make_scheduler(store)

        sched.shift_focus("task-001")
        state = sched.shift_focus("task-002")

        assert state.primary == "task-002"
        assert state.secondary[0] == "task-001"

    def test_lru_eviction_when_secondary_exceeds_two(self, store):
        """secondary 超过 2 个时，LRU（最后一个）被驱逐。"""
        for i in range(1, 5):
            _insert_node(store, _make_node(f"task-00{i}"))
        sched = _make_scheduler(store)

        sched.shift_focus("task-001")  # primary=001
        sched.shift_focus("task-002")  # primary=002, secondary=[001]
        sched.shift_focus("task-003")  # primary=003, secondary=[002, 001]
        state = sched.shift_focus("task-004")  # primary=004, secondary=[003, 002]; 001 evicted

        assert state.primary == "task-004"
        assert "task-003" in state.secondary
        assert "task-002" in state.secondary
        assert "task-001" not in state.secondary
        assert len(state.secondary) <= 2

    def test_shift_to_nonexistent_node_raises(self, store):
        """shift_focus 到不存在节点抛 ValueError。"""
        sched = _make_scheduler(store)
        with pytest.raises(ValueError):
            sched.shift_focus("nonexistent-id")

    def test_shift_to_archived_node_raises(self, store):
        """shift_focus 到已归档节点抛 ValueError。"""
        archived = _make_node("task-arc", archived_at=_iso(_now()))
        _insert_node(store, archived)
        sched = _make_scheduler(store)

        with pytest.raises(ValueError):
            sched.shift_focus("task-arc")

    def test_shift_updates_last_touched(self, store):
        """shift_focus 后 last_touched 被更新。"""
        node = _make_node("task-001")
        _insert_node(store, node)
        sched = _make_scheduler(store)

        now = _now()
        state = sched.shift_focus("task-001", now=now)
        assert "task-001" in state.last_touched

    def test_secondary_max_two(self, store):
        """secondary 最多保留 2 个节点。"""
        for i in range(1, 6):
            _insert_node(store, _make_node(f"task-00{i}"))
        sched = _make_scheduler(store)

        for i in range(1, 6):
            sched.shift_focus(f"task-00{i}")

        state = sched.get_state()
        assert len(state.secondary) <= 2


# ===========================================================================
# TestTouch
# ===========================================================================

class TestTouch:
    """touch 方法测试。"""

    def test_touch_updates_timestamp(self, store):
        """touch 更新 last_touched 中该 node 的时间戳。"""
        node = _make_node("task-001")
        _insert_node(store, node)
        sched = _make_scheduler(store)

        t1 = _now()
        sched.touch("task-001", now=t1)
        state = sched.get_state()
        assert "task-001" in state.last_touched
        # Timestamp should be close to t1
        stored_ts = datetime.fromisoformat(state.last_touched["task-001"])
        assert abs((stored_ts - t1).total_seconds()) < 2

    def test_touch_persists_to_session(self, store):
        """touch 后 session_state 中 last_touched 被持久化。"""
        node = _make_node("task-001")
        _insert_node(store, node)
        sched = _make_scheduler(store)

        sched.touch("task-001", now=_now())

        # Load fresh scheduler — should see the touch
        sched2 = _make_scheduler(store)
        state = sched2.get_state()
        assert "task-001" in state.last_touched

    def test_touch_overwrites_previous_timestamp(self, store):
        """touch 两次，第二次时间戳覆盖第一次。"""
        node = _make_node("task-001")
        _insert_node(store, node)
        sched = _make_scheduler(store)

        t1 = _now()
        t2 = t1 + timedelta(hours=1)
        sched.touch("task-001", now=t1)
        sched.touch("task-001", now=t2)

        state = sched.get_state()
        stored_ts = datetime.fromisoformat(state.last_touched["task-001"])
        assert abs((stored_ts - t2).total_seconds()) < 2


# ===========================================================================
# TestDecay
# ===========================================================================

class TestDecay:
    """3 天衰减：未 touch 超过 3 天的焦点被移除。"""

    def test_primary_decays_after_3_days(self, store):
        """primary 超过 3 天未 touch → 被移除（primary 变 None）。"""
        node = _make_node("task-001")
        _insert_node(store, node)
        sched = _make_scheduler(store)

        old_time = _now() - timedelta(days=4)
        sched.shift_focus("task-001", now=old_time)

        tick_time = _now()
        state = sched.tick(now=tick_time)
        assert state.primary is None

    def test_secondary_decays_after_3_days(self, store):
        """secondary 中超过 3 天未 touch 的节点被移除。"""
        node_a = _make_node("task-001")
        node_b = _make_node("task-002")
        _insert_node(store, node_a)
        _insert_node(store, node_b)
        sched = _make_scheduler(store)

        old_time = _now() - timedelta(days=4)
        sched.shift_focus("task-001", now=old_time)  # primary=001 (old)
        recent_time = _now() - timedelta(hours=1)
        sched.shift_focus("task-002", now=recent_time)  # primary=002, secondary=[001]

        state = sched.tick(now=_now())
        assert "task-001" not in state.secondary

    def test_recently_touched_not_decayed(self, store):
        """最近 touch 的节点不被衰减。"""
        node = _make_node("task-001")
        _insert_node(store, node)
        sched = _make_scheduler(store)

        recent = _now() - timedelta(hours=2)
        sched.shift_focus("task-001", now=recent)

        state = sched.tick(now=_now())
        assert state.primary == "task-001"

    def test_decay_exactly_3_days_not_removed(self, store):
        """恰好 3 天（未超过）→ 不被衰减（严格 > 3 天才衰减）。"""
        node = _make_node("task-001")
        _insert_node(store, node)
        sched = _make_scheduler(store)

        # Use a fixed tick_now so decay_cutoff = tick_now - 3d is exactly
        # equal to touch_time — boundary should NOT decay.
        tick_now = _now()
        touch_time = tick_now - timedelta(days=3)
        sched.shift_focus("task-001", now=touch_time)

        state = sched.tick(now=tick_now)
        # Exactly 3 days — should NOT be decayed (must be strictly > 3 days)
        assert state.primary == "task-001"


# ===========================================================================
# TestStash
# ===========================================================================

class TestStash:
    """stash 测试：LIFO，最大 2 条，24h 衰减写 narrative。"""

    def _make_scheduler_with_narrative(self, store):
        """Create a scheduler with a mock narrative module."""
        mock_narrative = MagicMock()
        mock_narrative.append_narrative = MagicMock(return_value=True)
        sched = FocusScheduler(store, narrative_module=mock_narrative)
        return sched, mock_narrative

    def test_stash_push_adds_entry(self, store):
        """push_stash 添加一条记录到 stash。"""
        node = _make_node("task-001")
        _insert_node(store, node)
        sched = _make_scheduler(store)

        sched.push_stash("task-001", reason="interrupted")
        state = sched.get_state()
        assert len(state.stash) == 1
        assert state.stash[0]["node_id"] == "task-001"
        assert state.stash[0]["reason"] == "interrupted"

    def test_stash_lifo_order(self, store):
        """stash 是 LIFO：最后 push 的在最前。"""
        node_a = _make_node("task-001")
        node_b = _make_node("task-002")
        _insert_node(store, node_a)
        _insert_node(store, node_b)
        sched = _make_scheduler(store)

        sched.push_stash("task-001", reason="first")
        sched.push_stash("task-002", reason="second")
        state = sched.get_state()

        # LIFO: task-002 should be at front (index 0)
        assert state.stash[0]["node_id"] == "task-002"
        assert state.stash[1]["node_id"] == "task-001"

    def test_stash_max_two(self, store):
        """stash 最多 2 条；超出时最旧的被丢弃。"""
        for i in range(1, 4):
            _insert_node(store, _make_node(f"task-00{i}"))
        sched = _make_scheduler(store)

        sched.push_stash("task-001", reason="a")
        sched.push_stash("task-002", reason="b")
        sched.push_stash("task-003", reason="c")  # should evict task-001

        state = sched.get_state()
        assert len(state.stash) == 2
        node_ids = [e["node_id"] for e in state.stash]
        assert "task-001" not in node_ids

    def test_stash_decay_writes_narrative(self, store, tmp_path):
        """stash 条目超过 24h → 写 narrative，从 stash 中移除。"""
        node = _make_node("task-001")
        _insert_node(store, node)

        # Build a stash entry that's already 25h old
        old_stash_entry = {
            "node_id": "task-001",
            "stashed_at": _iso(_now() - timedelta(hours=25)),
            "reason": "old stash",
        }

        mock_narrative = MagicMock()
        mock_narrative.append_narrative = MagicMock(return_value=True)
        sched = FocusScheduler(store, narrative_module=mock_narrative)

        # Manually insert old stash entry
        sched._state.stash = [old_stash_entry]
        sched._persist()

        state = sched.tick(now=_now())

        # Should have been removed from stash
        assert len(state.stash) == 0
        # narrative.append_narrative should have been called
        assert mock_narrative.append_narrative.called

    def test_stash_recent_entry_not_expired(self, store):
        """stash 条目不足 24h → 不被清除。"""
        node = _make_node("task-001")
        _insert_node(store, node)
        sched = _make_scheduler(store)

        recent_time = _now() - timedelta(hours=2)
        sched.push_stash("task-001", reason="recent", now=recent_time)

        state = sched.tick(now=_now())
        assert len(state.stash) == 1


# ===========================================================================
# TestArbitrate
# ===========================================================================

class TestArbitrate:
    """arbitrate 优先级测试：user_focus > candidates > historical。"""

    def test_user_focus_wins(self, store):
        """user_focus 提供时，优先设置为 primary。"""
        node_a = _make_node("task-001")
        node_b = _make_node("task-002")
        _insert_node(store, node_a)
        _insert_node(store, node_b)
        sched = _make_scheduler(store)

        state = sched.arbitrate(candidates=["task-001"], user_focus="task-002")
        assert state.primary == "task-002"

    def test_candidates_used_when_no_user_focus(self, store):
        """无 user_focus 时，candidates[0] 设为 primary。"""
        node_a = _make_node("task-001")
        node_b = _make_node("task-002")
        _insert_node(store, node_a)
        _insert_node(store, node_b)
        sched = _make_scheduler(store)

        state = sched.arbitrate(candidates=["task-001", "task-002"])
        assert state.primary == "task-001"

    def test_historical_kept_when_no_input(self, store):
        """无 user_focus 也无 candidates 时，保留历史 primary。"""
        node = _make_node("task-001")
        _insert_node(store, node)
        sched = _make_scheduler(store)
        sched.shift_focus("task-001")

        # New scheduler loads from session — no new input
        sched2 = _make_scheduler(store)
        state = sched2.arbitrate()
        assert state.primary == "task-001"

    def test_arbitrate_returns_focus_state(self, store):
        """arbitrate 返回 FocusState 对象。"""
        node = _make_node("task-001")
        _insert_node(store, node)
        sched = _make_scheduler(store)

        result = sched.arbitrate(user_focus="task-001")
        assert isinstance(result, FocusState)

    def test_arbitrate_ignores_invalid_candidate(self, store):
        """candidates 中含无效节点时，跳过；找有效的候选。"""
        valid = _make_node("task-valid")
        _insert_node(store, valid)
        sched = _make_scheduler(store)

        # First candidate doesn't exist, second is valid
        state = sched.arbitrate(candidates=["nonexistent-id", "task-valid"])
        # Should fall through to "task-valid" or keep historical (None)
        # Implementation may skip all invalid and keep historical
        # Accept either None or "task-valid" depending on implementation strategy
        assert state.primary in (None, "task-valid")


# ===========================================================================
# TestPersistence
# ===========================================================================

class TestPersistence:
    """focus state 持久化测试。"""

    def test_state_persists_across_schedulers(self, store):
        """FocusState 在 session_state 中持久化，新 scheduler 加载后可用。"""
        node = _make_node("task-001")
        _insert_node(store, node)
        sched = _make_scheduler(store)
        sched.shift_focus("task-001")

        sched2 = _make_scheduler(store)
        state = sched2.get_state()
        assert state.primary == "task-001"

    def test_secondary_persists(self, store):
        """secondary 列表也被持久化。"""
        node_a = _make_node("task-001")
        node_b = _make_node("task-002")
        _insert_node(store, node_a)
        _insert_node(store, node_b)
        sched = _make_scheduler(store)

        sched.shift_focus("task-001")
        sched.shift_focus("task-002")

        sched2 = _make_scheduler(store)
        state = sched2.get_state()
        assert "task-001" in state.secondary

    def test_last_touched_persists(self, store):
        """last_touched 被持久化。"""
        node = _make_node("task-001")
        _insert_node(store, node)
        sched = _make_scheduler(store)

        t = _now()
        sched.shift_focus("task-001", now=t)

        sched2 = _make_scheduler(store)
        state = sched2.get_state()
        assert "task-001" in state.last_touched


# ===========================================================================
# TestValidation
# ===========================================================================

class TestValidation:
    """加载时自动清除无效/已归档节点。"""

    def test_invalid_primary_removed_on_load(self, store):
        """session_state 中的 primary 不存在于 DB → 加载时清除。"""
        # Manually write invalid state to session
        store.set_session("focus_state", {
            "primary": "ghost-node",
            "secondary": [],
            "stash": [],
            "last_touched": {},
        })

        sched = _make_scheduler(store)
        state = sched.get_state()
        assert state.primary is None

    def test_archived_primary_removed_on_load(self, store):
        """primary 节点已归档 → 加载时清除。"""
        archived = _make_node("task-arc", archived_at=_iso(_now()))
        _insert_node(store, archived)

        store.set_session("focus_state", {
            "primary": "task-arc",
            "secondary": [],
            "stash": [],
            "last_touched": {},
        })

        sched = _make_scheduler(store)
        state = sched.get_state()
        assert state.primary is None

    def test_invalid_secondary_removed_on_load(self, store):
        """secondary 中的无效节点被静默移除。"""
        valid = _make_node("task-valid")
        _insert_node(store, valid)

        store.set_session("focus_state", {
            "primary": None,
            "secondary": ["ghost-node", "task-valid"],
            "stash": [],
            "last_touched": {},
        })

        sched = _make_scheduler(store)
        state = sched.get_state()
        assert "ghost-node" not in state.secondary
        assert "task-valid" in state.secondary

    def test_archived_secondary_removed_on_load(self, store):
        """secondary 中的已归档节点被静默移除。"""
        archived = _make_node("task-arc", archived_at=_iso(_now()))
        _insert_node(store, archived)

        store.set_session("focus_state", {
            "primary": None,
            "secondary": ["task-arc"],
            "stash": [],
            "last_touched": {},
        })

        sched = _make_scheduler(store)
        state = sched.get_state()
        assert "task-arc" not in state.secondary


# ===========================================================================
# TestNoFocusMode
# ===========================================================================

class TestNoFocusMode:
    """空焦点状态测试。"""

    def test_empty_state_primary_none(self, store):
        """未设置焦点时 primary=None。"""
        sched = _make_scheduler(store)
        state = sched.get_state()
        assert state.primary is None

    def test_empty_state_secondary_empty(self, store):
        """未设置焦点时 secondary=[]。"""
        sched = _make_scheduler(store)
        state = sched.get_state()
        assert state.secondary == []

    def test_tick_on_empty_state_safe(self, store):
        """空状态调用 tick 不报错。"""
        sched = _make_scheduler(store)
        state = sched.tick(now=_now())
        assert state.primary is None


# ===========================================================================
# TestStashDecayNarrative
# ===========================================================================

class TestStashDecayNarrative:
    """stash 衰减写 narrative 的详细测试。"""

    def test_decay_writes_correct_node_id_to_narrative(self, store):
        """衰减时 narrative 写入的 node_id 正确。"""
        node = _make_node("task-stash")
        _insert_node(store, node)

        mock_narrative = MagicMock()
        mock_narrative.append_narrative = MagicMock(return_value=True)
        sched = FocusScheduler(store, narrative_module=mock_narrative)

        old_entry = {
            "node_id": "task-stash",
            "stashed_at": _iso(_now() - timedelta(hours=30)),
            "reason": "test reason",
        }
        sched._state.stash = [old_entry]
        sched._persist()

        sched.tick(now=_now())

        # Verify append_narrative was called with the correct node_id
        args, kwargs = mock_narrative.append_narrative.call_args
        # First positional arg after narratives_dir is node_id
        assert "task-stash" in args or kwargs.get("node_id") == "task-stash"

    def test_no_narrative_call_when_no_module(self, store):
        """没有 narrative_module 时衰减不报错（静默跳过）。"""
        node = _make_node("task-001")
        _insert_node(store, node)
        sched = FocusScheduler(store, narrative_module=None)

        old_entry = {
            "node_id": "task-001",
            "stashed_at": _iso(_now() - timedelta(hours=30)),
            "reason": "no module",
        }
        sched._state.stash = [old_entry]
        sched._persist()

        # Should not raise
        state = sched.tick(now=_now())
        assert len(state.stash) == 0

    def test_multiple_stash_entries_all_expired_written(self, store):
        """多个过期 stash 条目都写入 narrative 并被清除。"""
        for i in range(1, 3):
            _insert_node(store, _make_node(f"task-00{i}"))

        mock_narrative = MagicMock()
        mock_narrative.append_narrative = MagicMock(return_value=True)
        sched = FocusScheduler(store, narrative_module=mock_narrative)

        old_time = _iso(_now() - timedelta(hours=30))
        sched._state.stash = [
            {"node_id": "task-001", "stashed_at": old_time, "reason": "a"},
            {"node_id": "task-002", "stashed_at": old_time, "reason": "b"},
        ]
        sched._persist()

        state = sched.tick(now=_now())
        assert len(state.stash) == 0
        assert mock_narrative.append_narrative.call_count == 2
