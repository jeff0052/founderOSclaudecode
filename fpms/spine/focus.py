"""焦点调度器 — FocusScheduler: arbitration, LRU eviction, stash, decay.

管理 Agent 的注意力指针（当前正在处理哪个节点）。
约束（来自 SYSTEM-CONFIG §focus）：
  - primary: 最多 1 个
  - secondary: 最多 2 个（LRU 驱逐）
  - stash: LIFO，最多 2 条
  - 3 天无 touch → 从 primary/secondary 中移除
  - 24h stash 条目 → 写 narrative 后移除
  - 所有时间戳为 UTC
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any, List, Optional

from .models import FocusState

# ---------------------------------------------------------------------------
# Constants (SYSTEM-CONFIG §focus)
# ---------------------------------------------------------------------------

_MAX_SECONDARY = 2
_MAX_STASH = 2
_DECAY_DAYS = 3       # primary/secondary decay threshold
_STASH_HOURS = 24     # stash expiry threshold


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _to_utc(dt: datetime) -> datetime:
    """Ensure datetime is UTC-aware."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# FocusScheduler
# ---------------------------------------------------------------------------

class FocusScheduler:
    """焦点调度器。"""

    def __init__(self, store: Any, narrative_module: Any = None) -> None:
        self._store = store
        self._narrative = narrative_module
        self._state = self._load_state()

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def shift_focus(self, node_id: str, now: Optional[datetime] = None) -> FocusState:
        """将 node_id 设为新 primary，旧 primary 推入 secondary 前端。

        Args:
            node_id: 要聚焦的节点 id。
            now: 当前时间（测试用，默认 UTC now）。

        Returns:
            更新后的 FocusState。

        Raises:
            ValueError: 节点不存在或已归档。
        """
        now = _to_utc(now) if now is not None else _utc_now()
        self._validate_node(node_id)

        old_primary = self._state.primary

        # Push old primary into secondary (front)
        if old_primary is not None and old_primary != node_id:
            self._state.secondary.insert(0, old_primary)
            # LRU evict if secondary exceeds max
            while len(self._state.secondary) > _MAX_SECONDARY:
                self._state.secondary.pop()  # pop last = LRU

        # Remove node_id from secondary if it was there
        if node_id in self._state.secondary:
            self._state.secondary.remove(node_id)

        self._state.primary = node_id
        self._touch_internal(node_id, now)
        self._persist()
        return self._state

    def touch(self, node_id: str, now: Optional[datetime] = None) -> None:
        """更新 last_touched[node_id] 为当前时间并持久化。"""
        now = _to_utc(now) if now is not None else _utc_now()
        self._touch_internal(node_id, now)
        self._persist()

    def tick(self, now: Optional[datetime] = None) -> FocusState:
        """执行衰减检查：3 天焦点衰减 + 24h stash 衰减。

        Returns:
            更新后的 FocusState。
        """
        now = _to_utc(now) if now is not None else _utc_now()
        changed = False

        # --- 3-day focus decay ---
        decay_cutoff = now - timedelta(days=_DECAY_DAYS)

        if self._state.primary is not None:
            ts = self._get_last_touched(self._state.primary)
            if ts is not None and ts < decay_cutoff:
                self._state.primary = None
                changed = True

        surviving_secondary: List[str] = []
        for nid in self._state.secondary:
            ts = self._get_last_touched(nid)
            if ts is None or ts < decay_cutoff:
                changed = True  # decayed
            else:
                surviving_secondary.append(nid)
        if len(surviving_secondary) != len(self._state.secondary):
            self._state.secondary = surviving_secondary
            changed = True

        # --- 24h stash decay ---
        stash_cutoff = now - timedelta(hours=_STASH_HOURS)
        surviving_stash = []
        for entry in self._state.stash:
            stashed_at_str = entry.get("stashed_at", "")
            try:
                stashed_at = _to_utc(datetime.fromisoformat(stashed_at_str))
            except (ValueError, TypeError):
                # Malformed timestamp — treat as expired
                stashed_at = stash_cutoff - timedelta(seconds=1)

            if stashed_at < stash_cutoff:
                # Write to narrative, then discard
                self._write_stash_to_narrative(entry, now)
                changed = True
            else:
                surviving_stash.append(entry)

        self._state.stash = surviving_stash

        if changed:
            self._persist()

        return self._state

    def get_state(self) -> FocusState:
        """返回当前 FocusState（不修改状态）。"""
        return self._state

    def arbitrate(
        self,
        candidates: Optional[List[str]] = None,
        user_focus: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> FocusState:
        """仲裁焦点：user_focus (1) > candidates[0] (3) > historical (4)。

        Args:
            candidates: 候选节点列表（按优先级排序）。
            user_focus: 用户指定焦点（最高优先级）。
            now: 当前时间。

        Returns:
            更新后的 FocusState。
        """
        now = _to_utc(now) if now is not None else _utc_now()

        if user_focus is not None:
            try:
                return self.shift_focus(user_focus, now=now)
            except ValueError:
                pass  # invalid user_focus — fall through

        if candidates:
            for candidate in candidates:
                try:
                    return self.shift_focus(candidate, now=now)
                except ValueError:
                    continue  # skip invalid candidates

        # Historical: already loaded from session_state — just return current
        return self._state

    def push_stash(
        self,
        node_id: str,
        reason: str = "",
        now: Optional[datetime] = None,
    ) -> FocusState:
        """将 node_id 压入 stash（LIFO，最多 _MAX_STASH 条）。

        Args:
            node_id: 要存入 stash 的节点 id。
            reason: 备注原因。
            now: 当前时间。

        Returns:
            更新后的 FocusState。
        """
        now = _to_utc(now) if now is not None else _utc_now()

        entry = {
            "node_id": node_id,
            "stashed_at": now.isoformat(),
            "reason": reason,
        }

        # LIFO: insert at front
        self._state.stash.insert(0, entry)

        # Evict oldest if exceeds max
        while len(self._state.stash) > _MAX_STASH:
            self._state.stash.pop()  # pop last = oldest

        self._persist()
        return self._state

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _load_state(self) -> FocusState:
        """从 session_state 加载 FocusState，并清除无效节点。"""
        raw = self._store.get_session("focus_state")
        if raw is None:
            return FocusState()

        primary = raw.get("primary")
        secondary = raw.get("secondary") or []
        stash = raw.get("stash") or []
        last_touched = raw.get("last_touched") or {}

        # Validate primary
        if primary is not None:
            if not self._is_valid_node(primary):
                primary = None

        # Validate secondary — silently remove invalid
        validated_secondary: List[str] = [
            nid for nid in secondary if self._is_valid_node(nid)
        ]

        return FocusState(
            primary=primary,
            secondary=validated_secondary,
            stash=stash,
            last_touched=last_touched,
        )

    def _is_valid_node(self, node_id: str) -> bool:
        """检查节点存在且未归档。"""
        node = self._store.get_node(node_id)
        if node is None:
            return False
        if node.archived_at is not None:
            return False
        return True

    def _validate_node(self, node_id: str) -> None:
        """校验节点合法性，不合法抛 ValueError。"""
        if not self._is_valid_node(node_id):
            raise ValueError(
                f"Node '{node_id}' does not exist or is archived"
            )

    def _touch_internal(self, node_id: str, now: datetime) -> None:
        """更新 last_touched（不持久化）。"""
        self._state.last_touched[node_id] = now.isoformat()

    def _get_last_touched(self, node_id: str) -> Optional[datetime]:
        """从 last_touched 获取时间戳，返回 UTC-aware datetime 或 None。"""
        ts_str = self._state.last_touched.get(node_id)
        if ts_str is None:
            return None
        try:
            return _to_utc(datetime.fromisoformat(ts_str))
        except (ValueError, TypeError):
            return None

    def _write_stash_to_narrative(self, entry: dict, now: datetime) -> None:
        """将过期 stash 条目写入 narrative。narrative_module 不存在则静默跳过。"""
        if self._narrative is None:
            return

        node_id = entry.get("node_id", "unknown")
        reason = entry.get("reason", "")
        stashed_at = entry.get("stashed_at", "")

        content = f"Stash entry expired. Originally stashed at {stashed_at}."
        if reason:
            content += f" Reason: {reason}."

        try:
            self._narrative.append_narrative(
                node_id=node_id,
                timestamp=now.isoformat(),
                event_type="stash_expired",
                content=content,
            )
        except Exception:
            pass  # Narrative failures are non-fatal

    def _persist(self) -> None:
        """将 FocusState 序列化为 JSON 并写入 session_state。"""
        self._store.set_session("focus_state", {
            "primary": self._state.primary,
            "secondary": self._state.secondary,
            "stash": self._state.stash,
            "last_touched": self._state.last_touched,
        })
