"""心跳扫描 — 风险检测、告警生成、去重、Anti-Amnesia。

FR-8 告警优先级表：
  1  urgent_deadline    at_risk AND deadline < 24h
  2  critical_blocked   blocked AND has dependents
  3  deadline_warning   at_risk (24h–48h window)
  4  stale_warning      stale (status_changed_at > 72h)
  5  inbox_stale        status==inbox AND created_at > 7d

去重规则：
  - 相同 (alert_type, node_id) 在 24h 内不重复推送（SUPPRESS）。
  - 超过 24h 无实质性操作 → Anti-Amnesia 强制重推。
  - 实质性操作（update_status, update_field, attach_node, detach_node,
    add_dependency, remove_dependency）重置去重计时器。
  - append_log 不是实质性操作，不重置 Anti-Amnesia 计时器。

SYSTEM-CONFIG 常量：
  heartbeat.inbox_stale_days = 7
  heartbeat.dedup_window_hours = 24
  heartbeat.top_n_alerts = 3
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .store import Store

from .models import DedupeRecord, HeartbeatAlert, HeartbeatResult


# ---------------------------------------------------------------------------
# Constants (SYSTEM-CONFIG)
# ---------------------------------------------------------------------------

_INBOX_STALE_DAYS = 7
_DEDUP_WINDOW_HOURS = 24
_TOP_N_ALERTS = 3
_TERMINAL_STATES = frozenset({"done", "dropped"})

# Tools considered "substantive" for Anti-Amnesia purposes
_SUBSTANTIVE_TOOLS = frozenset({
    "update_status",
    "update_field",
    "attach_node",
    "detach_node",
    "add_dependency",
    "remove_dependency",
})

_SESSION_KEY_LAST_ALERTS = "last_alerts"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_iso(ts: str) -> datetime:
    """Parse ISO 8601 string to timezone-aware datetime (UTC if no tz)."""
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Heartbeat class
# ---------------------------------------------------------------------------

class Heartbeat:
    """Heartbeat scanner — generates structured alerts with dedup and Anti-Amnesia."""

    def __init__(self, store: "Store", risk_module=None, archive_module=None):
        self._store = store

        if risk_module is None:
            from fpms.spine import risk as _risk
            risk_module = _risk
        self._risk = risk_module

        if archive_module is None:
            from fpms.spine import archive as _archive
            archive_module = _archive
        self._archive = archive_module

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def scan(self, now: Optional[datetime] = None) -> HeartbeatResult:
        """Run a full heartbeat scan and return a HeartbeatResult.

        Steps:
          1. Fetch all non-archived nodes.
          2. Compute risk marks batch.
          3. Map risks → raw alerts.
          4. Load dedup state from session.
          5. Apply dedup / Anti-Amnesia logic.
          6. Derive focus candidates (severity 1-2).
          7. Scan archive candidates.
          8. Persist dedup state.
          9. Sort by severity, return top-N + candidates.
        """
        if now is None:
            now = _now_utc()

        store = self._store

        # Step 1: fetch all non-archived nodes
        nodes = store.list_nodes(filters={"archived": False}, limit=1000)

        # Step 2: compute risk marks
        risk_marks: Dict[str, object] = self._risk.compute_risk_marks_batch(
            nodes, store, now
        )

        # Step 3: map risks → raw alerts
        raw_alerts: List[HeartbeatAlert] = []
        for node in nodes:
            if node.status in _TERMINAL_STATES:
                continue
            marks = risk_marks.get(node.id)
            if marks is None:
                continue
            raw_alerts.extend(self._node_to_alerts(node, marks, store, now))

        # Step 4: load dedup state
        dedup_state_raw = store.get_session(_SESSION_KEY_LAST_ALERTS)
        # dedup_state_raw is a dict: { "<alert_type>|<node_id>" → DedupeRecord dict }
        dedup_state: Dict[str, dict] = dedup_state_raw or {}

        # Step 5: dedup filtering
        pushed_alerts: List[HeartbeatAlert] = []
        for alert in raw_alerts:
            key = f"{alert.alert_type}|{alert.node_id}"
            record = dedup_state.get(key)

            if record is None:
                # New alert — push it
                pushed_alerts.append(alert)
                dedup_state[key] = {
                    "alert_type": alert.alert_type,
                    "node_id": alert.node_id,
                    "last_pushed_at": now.isoformat(),
                    "last_acted_at": now.isoformat(),
                }
            else:
                last_pushed = _parse_iso(record["last_pushed_at"])
                hours_since_push = (now - last_pushed).total_seconds() / 3600.0

                # Check if substantive action happened since last push
                substantive = self._check_substantive_action(
                    alert.node_id, record["last_pushed_at"], store
                )

                if substantive:
                    # Reset dedup — re-push
                    pushed_alerts.append(alert)
                    dedup_state[key] = {
                        "alert_type": alert.alert_type,
                        "node_id": alert.node_id,
                        "last_pushed_at": now.isoformat(),
                        "last_acted_at": now.isoformat(),
                    }
                elif hours_since_push < _DEDUP_WINDOW_HOURS:
                    # Within 24h, no action → suppress
                    pass
                else:
                    # Anti-Amnesia: >= 24h, no action → force re-push
                    pushed_alerts.append(alert)
                    dedup_state[key] = {
                        "alert_type": alert.alert_type,
                        "node_id": alert.node_id,
                        "last_pushed_at": now.isoformat(),
                        "last_acted_at": record.get("last_acted_at", now.isoformat()),
                    }

        # Sort by severity (1=highest)
        pushed_alerts.sort(key=lambda a: a.severity)

        # Step 6: focus candidates from severity 1-2
        focus_candidates: List[str] = []
        seen_focus: set = set()
        for alert in pushed_alerts:
            if alert.severity <= 2 and alert.node_id not in seen_focus:
                focus_candidates.append(alert.node_id)
                seen_focus.add(alert.node_id)

        # Step 7: archive candidates
        archive_candidates = self._archive.scan_archive_candidates(store, now)

        # Step 8: persist dedup state
        store.set_session(_SESSION_KEY_LAST_ALERTS, dedup_state)

        # Step 9: top-N alerts
        top_alerts = pushed_alerts[:_TOP_N_ALERTS]

        return HeartbeatResult(
            alerts=top_alerts,
            focus_candidates=focus_candidates,
            archive_candidates=archive_candidates,
            nodes_scanned=len(nodes),
        )

    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------

    def _node_to_alerts(
        self,
        node,
        marks,
        store: "Store",
        now: datetime,
    ) -> List[HeartbeatAlert]:
        """Convert a node's RiskMarks to zero or more HeartbeatAlerts."""
        alerts: List[HeartbeatAlert] = []

        # urgent_deadline: at_risk AND deadline < 24h
        if marks.at_risk and marks.deadline_hours is not None and marks.deadline_hours < 24.0:
            alerts.append(HeartbeatAlert(
                alert_type="urgent_deadline",
                severity=1,
                node_id=node.id,
                message=f"Deadline in {marks.deadline_hours:.1f}h — immediate action required.",
                suggested_action="Review and complete or reschedule this task.",
            ))
        # critical_blocked: blocked AND has dependents
        elif marks.blocked:
            dependents = store.get_dependents(node.id)
            if dependents:
                alerts.append(HeartbeatAlert(
                    alert_type="critical_blocked",
                    severity=2,
                    node_id=node.id,
                    message=(
                        f"Node is blocked by {marks.blocked_by} and "
                        f"{len(dependents)} node(s) depend on it."
                    ),
                    suggested_action="Resolve blocking dependency to unblock downstream nodes.",
                ))

        # deadline_warning: at_risk but deadline >= 24h (i.e., 24–48h window)
        if marks.at_risk and (marks.deadline_hours is None or marks.deadline_hours >= 24.0):
            alerts.append(HeartbeatAlert(
                alert_type="deadline_warning",
                severity=3,
                node_id=node.id,
                message=f"Deadline approaching in {marks.deadline_hours:.1f}h.",
                suggested_action="Plan work to meet the upcoming deadline.",
            ))

        # stale_warning
        if marks.stale:
            alerts.append(HeartbeatAlert(
                alert_type="stale_warning",
                severity=4,
                node_id=node.id,
                message="No status change in over 72 hours.",
                suggested_action="Update status or log progress on this node.",
            ))

        # inbox_stale (checked independently of risk marks)
        if self._is_inbox_stale(node, now):
            alerts.append(HeartbeatAlert(
                alert_type="inbox_stale",
                severity=5,
                node_id=node.id,
                message="Node has been in inbox for over 7 days.",
                suggested_action="Triage this node: activate, drop, or reschedule.",
            ))

        return alerts

    def _check_substantive_action(
        self,
        node_id: str,
        since_iso: str,
        store: "Store",
    ) -> bool:
        """Return True if a substantive tool was invoked on node_id since since_iso.

        Substantive tools: update_status, update_field, attach_node, detach_node,
                           add_dependency, remove_dependency.
        append_log is NOT substantive (Anti-Amnesia protection).
        """
        rows = store._conn.execute(
            "SELECT event_json FROM audit_outbox WHERE created_at > ? ORDER BY id",
            (since_iso,),
        ).fetchall()

        for (event_json,) in rows:
            try:
                event = json.loads(event_json)
            except (json.JSONDecodeError, TypeError):
                continue

            # Match node_id
            if event.get("node_id") != node_id:
                continue

            # Match substantive tool
            tool = event.get("tool_name") or event.get("type") or ""
            if tool in _SUBSTANTIVE_TOOLS:
                return True

        return False

    def _is_inbox_stale(self, node, now: datetime) -> bool:
        """Return True if node is inbox AND created_at older than 7 days.

        Uses created_at, NOT status_changed_at (per FR-7).
        """
        if node.status != "inbox":
            return False
        if not node.created_at:
            return False
        created = _parse_iso(node.created_at)
        age_days = (now - created).total_seconds() / 86400.0
        return age_days > _INBOX_STALE_DAYS
