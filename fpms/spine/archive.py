"""归档候选扫描与执行 — FR-6 归档规则实现。

规则（所有条件必须同时满足）：
1. status in ("done", "dropped")          — 终态节点
2. status_changed_at < NOW() - 7 days     — 冷却期已过
3. archived_at IS NULL                    — 尚未归档
4. is_persistent = False                  — 非豁免节点
5. 无未归档的 depends_on 依赖者           — get_dependents() 中没有 archived_at IS NULL 的节点
6. 无未归档的后代节点                     — get_descendants() 中没有 archived_at IS NULL 的节点

底部优先（bottom-up）顺序：叶节点（后代已全部归档或无后代）先返回。

SYSTEM-CONFIG 常量：
  archive.cooldown_days = 7
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from .store import Store


# ---------------------------------------------------------------------------
# Constants (SYSTEM-CONFIG)
# ---------------------------------------------------------------------------

_TERMINAL_STATES = frozenset({"done", "dropped"})
_COOLDOWN_DAYS = 7


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_iso(ts: str) -> datetime:
    """Parse an ISO 8601 timestamp string to an aware datetime (UTC if no tz)."""
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _is_eligible(store: "Store", node_id: str, now: datetime) -> bool:
    """Return True if the node meets all FR-6 archive conditions."""
    node = store.get_node(node_id)
    if node is None:
        return False

    # Condition 1: terminal status
    if node.status not in _TERMINAL_STATES:
        return False

    # Condition 2: cooldown period elapsed
    if not node.status_changed_at:
        return False
    changed_at = _parse_iso(node.status_changed_at)
    if changed_at >= now - timedelta(days=_COOLDOWN_DAYS):
        return False

    # Condition 3: not already archived
    if node.archived_at is not None:
        return False

    # Condition 4: not persistent (exempt)
    if node.is_persistent:
        return False

    # Condition 5: no unarchived dependents (nodes that depend_on this node)
    dependents = store.get_dependents(node_id)
    for dep in dependents:
        if dep.archived_at is None:
            return False

    # Condition 6: no unarchived descendants
    descendant_ids = store.get_descendants(node_id)
    for desc_id in descendant_ids:
        desc = store.get_node(desc_id)
        if desc is not None and desc.archived_at is None:
            return False

    return True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def scan_archive_candidates(
    store: "Store",
    now: Optional[datetime] = None,
) -> List[str]:
    """扫描满足 FR-6 所有归档条件的节点，返回其 ID 列表。

    底部优先（bottom-up）顺序：叶节点（所有后代已归档或无后代）排在前面，
    确保批量归档时子节点在父节点之前处理。

    Args:
        store: Store 实例。
        now:   可注入的当前时间（UTC aware）。默认为 datetime.now(utc)。

    Returns:
        符合归档条件的节点 ID 列表（底部优先顺序）。
    """
    if now is None:
        now = _now_utc()

    # Fetch all non-archived terminal nodes that have passed cooldown
    # We do broad pre-filtering in Python after listing; the store's list_nodes
    # supports filtering by archived=False which narrows the result set.
    cooldown_cutoff = (now - timedelta(days=_COOLDOWN_DAYS)).isoformat()

    # Pull all unarchived nodes and filter to terminal + old enough
    # Use a large limit to get all candidates; the active node set is
    # bounded in practice.
    candidates_raw = []
    offset = 0
    batch_size = 200
    while True:
        nodes = store.list_nodes(
            filters={"archived": False},
            order_by="updated_at",
            limit=batch_size,
            offset=offset,
        )
        if not nodes:
            break
        for node in nodes:
            if node.status not in _TERMINAL_STATES:
                continue
            if not node.status_changed_at:
                continue
            changed_at = _parse_iso(node.status_changed_at)
            if changed_at >= now - timedelta(days=_COOLDOWN_DAYS):
                continue
            if node.is_persistent:
                continue
            candidates_raw.append(node.id)
        if len(nodes) < batch_size:
            break
        offset += batch_size

    # Further filter: check dependents and descendants
    eligible = [nid for nid in candidates_raw if _is_eligible(store, nid, now)]

    # Sort bottom-up: nodes with no unarchived descendants come first.
    # Since eligible nodes already have all descendants archived (that's
    # the eligibility condition), we can simply sort by descendant count
    # ascending — nodes with fewer total descendants are "deeper" leaves.
    def _descendant_count(node_id: str) -> int:
        return len(store.get_descendants(node_id))

    eligible.sort(key=_descendant_count)

    return eligible


def execute_archive(
    store: "Store",
    node_id: str,
    now: Optional[datetime] = None,
) -> bool:
    """归档单个节点。

    在执行前重新校验所有 FR-6 条件（防止扫描后状态变化）。

    Args:
        store:   Store 实例。
        node_id: 要归档的节点 ID。
        now:     可注入的当前时间（UTC aware）。

    Returns:
        True  — 条件满足，已成功归档。
        False — 条件不满足，跳过（不修改节点）。
    """
    if now is None:
        now = _now_utc()

    if not _is_eligible(store, node_id, now):
        return False

    now_iso = now.isoformat()
    store.update_node(node_id, {"archived_at": now_iso})
    return True


def execute_archive_batch(
    store: "Store",
    node_ids: List[str],
    now: Optional[datetime] = None,
) -> int:
    """批量归档节点列表。

    按传入顺序依次执行（scan_archive_candidates 已保证底部优先顺序）。
    每个节点独立校验条件；不满足条件的节点被跳过。

    Args:
        store:    Store 实例。
        node_ids: 节点 ID 列表（应为 scan_archive_candidates 的返回值）。
        now:      可注入的当前时间（UTC aware）。

    Returns:
        成功归档的节点数量。
    """
    if now is None:
        now = _now_utc()

    count = 0
    for node_id in node_ids:
        if execute_archive(store, node_id, now=now):
            count += 1
    return count
