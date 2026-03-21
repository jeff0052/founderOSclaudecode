"""认知层上下文包组装 — BundleAssembler。

将 L0/L_Alert/L1/L2 四层上下文组装为 ContextBundle，注入 LLM 提示词。

FR-10: L1 只展开焦点节点的直接子节点（depth=1），禁止递归展开。
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import List, Optional, Tuple, TYPE_CHECKING

from .models import ContextBundle, Node, RiskMarks

if TYPE_CHECKING:
    from .store import Store


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_L1_MAX_CHILDREN = 15
_L1_MAX_DEPENDENCIES = 10
_L1_MAX_DEPENDENTS = 10
_L1_MAX_SIBLINGS = 10
_DEFAULT_MAX_TOKENS = 10000

_STATUS_ICONS = {
    "inbox":   "📥",
    "active":  "▶",
    "waiting": "⏳",
    "done":    "✅",
    "dropped": "❌",
}


# ---------------------------------------------------------------------------
# BundleAssembler
# ---------------------------------------------------------------------------

class BundleAssembler:
    """组装 4 层认知上下文包。"""

    def __init__(
        self,
        store: "Store",
        dashboard_mod=None,
        heartbeat_obj=None,
        focus_scheduler=None,
        risk_mod=None,
        rollup_mod=None,
        narrative_mod=None,
        narratives_dir: str = "fpms/narratives",
        adapter_registry=None,
    ) -> None:
        self._store = store
        self._narratives_dir = narratives_dir

        # Resolve module defaults
        if dashboard_mod is None:
            from fpms.spine import dashboard as _dashboard
            dashboard_mod = _dashboard
        self._dashboard_mod = dashboard_mod

        if risk_mod is None:
            from fpms.spine import risk as _risk
            risk_mod = _risk
        self._risk_mod = risk_mod

        if rollup_mod is None:
            from fpms.spine import rollup as _rollup
            rollup_mod = _rollup
        self._rollup_mod = rollup_mod

        if narrative_mod is None:
            from fpms.spine import narrative as _narrative
            narrative_mod = _narrative
        self._narrative_mod = narrative_mod

        # Optional objects (may be None)
        self._heartbeat_obj = heartbeat_obj
        self._focus_scheduler = focus_scheduler

        # DB dir for trace file — derived from store's events path, or use CWD/fpms/db
        try:
            events_dir = os.path.dirname(store._events_path)
            if events_dir:
                self._db_dir = events_dir
            else:
                self._db_dir = "fpms/db"
        except AttributeError:
            self._db_dir = "fpms/db"

        self._adapter_registry = adapter_registry
        self._last_sync_status = None

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def assemble(
        self,
        focus_node_id: Optional[str] = None,
        now: Optional[datetime] = None,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
    ) -> ContextBundle:
        """Assemble the 4-layer context bundle.

        Args:
            focus_node_id: Optional node id to focus on.
            now:           Current time for decay checks (UTC).
            max_tokens:    Token budget for the bundle.

        Returns:
            ContextBundle with all layers populated.
        """
        if now is None:
            now = datetime.now(timezone.utc)

        self._last_sync_status = None

        # 1. Tick focus scheduler (handles decay/stash expiry)
        if self._focus_scheduler is not None:
            self._focus_scheduler.tick(now)
            # If no explicit focus, fall back to scheduler's primary
            if focus_node_id is None:
                state = self._focus_scheduler.get_state()
                focus_node_id = state.primary

        # 2. Build each layer
        l0 = self._build_l0()
        l_alert = self._build_l_alert()

        if focus_node_id is not None:
            # Verify the focus node exists
            focus_node = self._store.get_node(focus_node_id)
            if focus_node is None:
                # Node doesn't exist — treat as no-focus for L1/L2
                l1 = "# Neighborhood\nNo focus node selected."
                l2 = "# Focus\nNo focus node selected."
                focus_node_id = None
            else:
                l1 = self._build_l1(focus_node_id)
                l2 = self._build_l2(focus_node_id)
        else:
            l1 = "# Neighborhood\nNo focus node selected."
            l2 = "# Focus\nNo focus node selected."

        # 3. Apply token budget
        l0, l_alert, l1, l2 = self._trim_to_budget(l0, l_alert, l1, l2, max_tokens=max_tokens)

        # 4. Calculate total tokens
        total_tokens = self._estimate_tokens(l0 + l_alert + l1 + l2)

        # 5. Per-layer tokens for trace
        l0_tokens = self._estimate_tokens(l0)
        l_alert_tokens = self._estimate_tokens(l_alert)
        l1_tokens = self._estimate_tokens(l1)
        l2_tokens = self._estimate_tokens(l2)

        # 6. Write assembly trace
        self._write_assembly_trace(
            focus_node_id=focus_node_id,
            l0_tokens=l0_tokens,
            l_alert_tokens=l_alert_tokens,
            l1_tokens=l1_tokens,
            l2_tokens=l2_tokens,
            total_tokens=total_tokens,
        )

        return ContextBundle(
            l0_dashboard=l0,
            l_alert=l_alert,
            l1_neighborhood=l1,
            l2_focus=l2,
            total_tokens=total_tokens,
            focus_node_id=focus_node_id,
        )

    # -----------------------------------------------------------------------
    # Layer builders
    # -----------------------------------------------------------------------

    def _sync_focus_node(self, node: Node) -> tuple[Node, dict]:
        """Sync focus node from external source if applicable.

        Returns:
            (possibly updated node, sync_status dict)
        """
        sync_status = {"synced": False, "source": node.source}

        if node.source == "internal" or self._adapter_registry is None:
            return node, sync_status

        if not node.source_id:
            return node, sync_status

        if not self._adapter_registry.has(node.source):
            return node, sync_status

        try:
            adapter = self._adapter_registry.get(node.source)
            snapshot = adapter.sync_node(node.source_id)

            if snapshot is None:
                self._store.update_node(node.id, {"source_deleted": True})
                sync_status["synced"] = True
                sync_status["deleted"] = True
                node.source_deleted = True
                return node, sync_status

            update_fields = {
                "title": snapshot.title,
                "status": snapshot.status,
                "source_synced_at": datetime.now(timezone.utc).isoformat(),
            }
            if snapshot.assignee is not None:
                update_fields["owner"] = snapshot.assignee
            self._store.update_node(node.id, update_fields)

            node.title = snapshot.title
            node.status = snapshot.status
            if snapshot.assignee is not None:
                node.owner = snapshot.assignee
            node.source_synced_at = update_fields["source_synced_at"]

            sync_status["synced"] = True
            sync_status["snapshot_title"] = snapshot.title
            return node, sync_status

        except Exception as e:
            sync_status["error"] = str(e)
            sync_status["stale"] = True
            return node, sync_status

    def _build_l0(self) -> str:
        """Build L0: global dashboard."""
        try:
            content = self._dashboard_mod.render_dashboard(
                self._store,
                self._risk_mod,
                max_tokens=1000,
            )
        except Exception:
            content = ""
        return "# Dashboard\n" + content

    def _build_l_alert(self) -> str:
        """Build L_Alert: top-3 heartbeat alerts."""
        if self._heartbeat_obj is None:
            return "# Alerts\nNo alerts."

        try:
            result = self._heartbeat_obj.scan()
            alerts = result.alerts
        except Exception:
            return "# Alerts\nNo alerts."

        if not alerts:
            return "# Alerts\nNo alerts."

        lines = ["# Alerts"]
        for alert in alerts[:3]:
            lines.append(
                f"- [{alert.alert_type}] {alert.message} (node={alert.node_id})\n"
                f"  Action: {alert.suggested_action}"
            )
        return "\n".join(lines)

    def _build_l1(self, focus_node_id: str) -> str:
        """Build L1: neighborhood of the focus node (depth=1 only, FR-10)."""
        store = self._store
        lines = ["# Neighborhood"]

        # --- Parent (one-line summary) ---
        parent = store.get_parent(focus_node_id)
        if parent is not None:
            lines.append("\n## Parent")
            lines.append(self._render_node_line(parent))
        else:
            lines.append("\n## Parent")
            lines.append("(no parent — root node)")

        # --- Children: direct only, depth=1, sort by risk, Top 15, fold rest ---
        children = store.get_children(focus_node_id, include_archived=False)
        lines.append("\n## Children")

        if children:
            # Build risk map for children
            risk_map = self._risk_mod.compute_risk_marks_batch(
                children, store,
                now=datetime.now(timezone.utc),
            )
            # Sort by risk severity descending
            children_sorted = self._sort_by_risk(children, risk_map)

            shown = children_sorted[:_L1_MAX_CHILDREN]
            folded_count = len(children_sorted) - len(shown)

            for child in shown:
                risk = risk_map.get(child.id, RiskMarks())
                lines.append(self._render_node_line(child, risk))

            if folded_count > 0:
                lines.append(f"  ... [folded] {folded_count} more children")
        else:
            lines.append("(no children)")

        # --- Depends on: nodes this focus depends on, Top 10 ---
        deps = store.get_dependencies(focus_node_id)
        lines.append("\n## Depends on")
        if deps:
            risk_map_deps = self._risk_mod.compute_risk_marks_batch(
                deps, store, now=datetime.now(timezone.utc)
            )
            for dep in deps[:_L1_MAX_DEPENDENCIES]:
                risk = risk_map_deps.get(dep.id, RiskMarks())
                lines.append(self._render_node_line(dep, risk))
        else:
            lines.append("(none)")

        # --- Depended by: nodes that depend on focus, Top 10 ---
        dependents = store.get_dependents(focus_node_id)
        lines.append("\n## Depended by")
        if dependents:
            risk_map_deps = self._risk_mod.compute_risk_marks_batch(
                dependents, store, now=datetime.now(timezone.utc)
            )
            for dep in dependents[:_L1_MAX_DEPENDENTS]:
                risk = risk_map_deps.get(dep.id, RiskMarks())
                lines.append(self._render_node_line(dep, risk))
        else:
            lines.append("(none)")

        # --- Siblings: same parent, Top 10 ---
        siblings = store.get_siblings(focus_node_id)
        lines.append("\n## Siblings")
        if siblings:
            risk_map_sibs = self._risk_mod.compute_risk_marks_batch(
                siblings, store, now=datetime.now(timezone.utc)
            )
            siblings_sorted = self._sort_by_risk(siblings, risk_map_sibs)
            for sib in siblings_sorted[:_L1_MAX_SIBLINGS]:
                risk = risk_map_sibs.get(sib.id, RiskMarks())
                lines.append(self._render_node_line(sib, risk))
        else:
            lines.append("(none)")

        return "\n".join(lines)

    def _build_l2(self, focus_node_id: str) -> str:
        """Build L2: detailed focus node view with narrative."""
        store = self._store
        node = store.get_node(focus_node_id)
        if node is None:
            return f"# Focus: {focus_node_id}\n(node not found)"

        # Cross-source sync (M1)
        node, sync_status = self._sync_focus_node(node)
        self._last_sync_status = sync_status

        lines = [f"# Focus: {node.title}"]

        # Skeleton fields
        lines.append(f"id: {node.id}")
        lines.append(f"status: {node.status}")
        lines.append(f"type: {node.node_type}")
        if node.summary:
            lines.append(f"summary: {node.summary}")
        if node.why:
            lines.append(f"why: {node.why}")
        if node.next_step:
            lines.append(f"next_step: {node.next_step}")
        if node.owner:
            lines.append(f"owner: {node.owner}")
        if node.deadline:
            lines.append(f"deadline: {node.deadline}")
        if node.tags:
            lines.append(f"tags: {', '.join(node.tags)}")

        # Source info for external nodes (M1)
        if node.source != "internal":
            lines.append(f"source: {node.source}")
            if node.source_id:
                lines.append(f"source_id: {node.source_id}")
            if node.source_url:
                lines.append(f"source_url: {node.source_url}")
            if sync_status.get("stale"):
                lines.append(
                    f"[数据可能过时: sync failed — {sync_status.get('error', 'unknown')}]"
                )

        # Compressed summary (priority)
        compressed = self._narrative_mod.read_compressed(
            self._narratives_dir, focus_node_id
        )
        if compressed:
            lines.append("\n## Compressed Summary")
            lines.append(compressed.strip())

        # Recent narrative (last 5 entries)
        narrative = self._narrative_mod.read_narrative(
            self._narratives_dir, focus_node_id, last_n_entries=5
        )
        if narrative:
            lines.append("\n## Narrative")
            lines.append(narrative.strip())

        return "\n".join(lines)

    # -----------------------------------------------------------------------
    # Token budget trimming
    # -----------------------------------------------------------------------

    def _trim_to_budget(
        self,
        l0: str,
        l_alert: str,
        l1: str,
        l2: str,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
    ) -> Tuple[str, str, str, str]:
        """Trim layers to fit within max_tokens budget.

        Trim order:
          1. L1 siblings section
          2. L1 children section
          3. L1 depended_by section
          4. L1 depends_on section
          5. L1 parent section
          6. L2 narrative (last resort)
        """
        total = sum(self._estimate_tokens(t) for t in [l0, l_alert, l1, l2])
        if total <= max_tokens:
            return l0, l_alert, l1, l2

        # Helper: trim a named section in l1 to target token count
        def _trim_section(text: str, section_header: str, target_tokens: int) -> str:
            """Reduce the named section in text to fit within target_tokens."""
            idx = text.find(section_header)
            if idx == -1:
                return text

            # Find next section after this one
            next_idx = len(text)
            # Look for the next "\n## " after idx + len(section_header)
            search_start = idx + len(section_header)
            next_section = text.find("\n## ", search_start)
            if next_section != -1:
                next_idx = next_section

            # Content of the section (excluding header line)
            section_content = text[idx:next_idx]
            section_lines = section_content.split("\n")

            # Gradually reduce lines until we're within budget
            before = text[:idx]
            after = text[next_idx:]

            budget_for_section = max(target_tokens - self._estimate_tokens(before + after), 10)

            # Trim lines from the section
            trimmed_lines = list(section_lines)
            while (
                len(trimmed_lines) > 2
                and self._estimate_tokens("\n".join(trimmed_lines)) > budget_for_section
            ):
                trimmed_lines.pop()  # remove last line

            if len(trimmed_lines) < len(section_lines):
                trimmed_lines.append("  ... [trimmed]")

            return before + "\n".join(trimmed_lines) + after

        # Trim in order
        trim_order = [
            "\n## Siblings",
            "\n## Children",
            "\n## Depended by",
            "\n## Depends on",
            "\n## Parent",
        ]

        for section_header in trim_order:
            total = sum(self._estimate_tokens(t) for t in [l0, l_alert, l1, l2])
            if total <= max_tokens:
                break
            excess = total - max_tokens
            target = self._estimate_tokens(l1) - excess
            l1 = _trim_section(l1, section_header, max(target, 20))

        # Last resort: trim L2 narrative
        total = sum(self._estimate_tokens(t) for t in [l0, l_alert, l1, l2])
        if total > max_tokens:
            excess = total - max_tokens
            target_l2 = max(self._estimate_tokens(l2) - excess, 20)
            # Find narrative section and trim it
            narrative_idx = l2.find("\n## Narrative")
            if narrative_idx != -1:
                # Keep everything up to narrative section + trim content
                l2_before = l2[:narrative_idx]
                l2_narrative = l2[narrative_idx:]
                l2_lines = l2_narrative.split("\n")
                budget_for_narrative = max(
                    target_l2 - self._estimate_tokens(l2_before), 5
                )
                trimmed = list(l2_lines)
                while (
                    len(trimmed) > 2
                    and self._estimate_tokens("\n".join(trimmed)) > budget_for_narrative
                ):
                    trimmed.pop()
                if len(trimmed) < len(l2_lines):
                    trimmed.append("  ... [trimmed]")
                l2 = l2_before + "\n".join(trimmed)

        return l0, l_alert, l1, l2

    # -----------------------------------------------------------------------
    # Trace writing
    # -----------------------------------------------------------------------

    def _write_assembly_trace(
        self,
        focus_node_id: Optional[str],
        l0_tokens: int,
        l_alert_tokens: int,
        l1_tokens: int,
        l2_tokens: int,
        total_tokens: int,
        trimmed_items: Optional[List[str]] = None,
    ) -> None:
        """Write assembly trace to assembly_traces.jsonl in db_dir."""
        try:
            db_dir = self._db_dir
            os.makedirs(db_dir, exist_ok=True)
            trace_path = os.path.join(db_dir, "assembly_traces.jsonl")

            record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "focus_node_id": focus_node_id,
                "tokens_per_layer": {
                    "l0": l0_tokens,
                    "l_alert": l_alert_tokens,
                    "l1": l1_tokens,
                    "l2": l2_tokens,
                },
                "total": total_tokens,
                "trimmed": trimmed_items or [],
                "sync_status": self._last_sync_status,
            }

            with open(trace_path, "a") as f:
                f.write(json.dumps(record) + "\n")
        except Exception:
            pass  # Trace failures are non-fatal

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _estimate_tokens(self, text: str) -> int:
        """Simple token estimate: len(text) // 4."""
        return len(text) // 4

    def _render_node_line(self, node: Node, risk: Optional[RiskMarks] = None) -> str:
        """Render a node as a single markdown list item with risk decorations."""
        icon = _STATUS_ICONS.get(node.status, "▶")
        risk_parts: List[str] = []
        if risk is not None:
            if risk.blocked:
                risk_parts.append("🚨blocked")
            if risk.at_risk:
                risk_parts.append("🚨at-risk")
            if risk.stale:
                risk_parts.append("⚠️stale")

        risk_str = " ".join(risk_parts)
        if risk_str:
            return f"- [{node.status}] {node.id}: {node.title} {icon} {risk_str}"
        return f"- [{node.status}] {node.id}: {node.title} {icon}"

    def _sort_by_risk(
        self,
        nodes: List[Node],
        risk_map: dict,
    ) -> List[Node]:
        """Sort nodes by risk severity descending (blocked > at_risk > stale > none)."""
        def severity(n: Node) -> int:
            m = risk_map.get(n.id, RiskMarks())
            if m.blocked:
                return 3
            if m.at_risk:
                return 2
            if m.stale:
                return 1
            return 0

        return sorted(nodes, key=severity, reverse=True)
