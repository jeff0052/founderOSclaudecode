"""认知引擎 Spine — 公共 API 入口。"""

from __future__ import annotations

import os
from dataclasses import asdict
from typing import Optional

from .models import Alert, ContextBundle, Edge, Node, ToolResult
from .models import CreateNodeInput, UpdateFieldInput, UpdateStatusInput

__all__ = [
    "SpineEngine",
    "Node",
    "Edge",
    "ToolResult",
    "Alert",
    "ContextBundle",
    "CreateNodeInput",
    "UpdateStatusInput",
    "UpdateFieldInput",
]


class SpineEngine:
    """总控入口。初始化引擎，暴露所有公共方法。"""

    def __init__(
        self,
        db_path: str = "fpms/db/fpms.db",
        events_path: str = "fpms/events.jsonl",
        narratives_dir: str = "fpms/narratives",
    ):
        """初始化引擎。创建 Store + 加载所有 v1 模块。"""
        from .store import Store
        from .tools import ToolHandler
        from .command_executor import CommandExecutor
        from . import validator as validator_mod
        from . import narrative as narrative_mod
        from . import risk as risk_mod
        from . import rollup as rollup_mod
        from . import dashboard as dashboard_mod
        from . import archive as archive_mod
        from .focus import FocusScheduler
        from .heartbeat import Heartbeat
        from .bundle import BundleAssembler

        # Ensure DB directory exists
        db_dir = os.path.dirname(db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        self._store = Store(db_path, events_path)
        self._narratives_dir = narratives_dir

        # Core tool execution
        self._tool_handler = ToolHandler(
            store=self._store,
            validator_module=validator_mod,
            narrative_module=narrative_mod,
        )
        self._tool_handler.narratives_dir = narratives_dir

        self._executor = CommandExecutor(
            store=self._store,
            tool_handler=self._tool_handler,
        )

        # Cognitive layer modules
        self._risk_mod = risk_mod
        self._rollup_mod = rollup_mod
        self._dashboard_mod = dashboard_mod
        self._archive_mod = archive_mod
        self._narrative_mod = narrative_mod

        self._focus_scheduler = FocusScheduler(
            store=self._store,
            narrative_module=narrative_mod,
        )

        self._heartbeat = Heartbeat(
            store=self._store,
            risk_module=risk_mod,
            archive_module=archive_mod,
        )

        # Adapter registry (M1) — set via set_adapter_registry()
        self._adapter_registry = None

        self._bundle_assembler = BundleAssembler(
            store=self._store,
            dashboard_mod=dashboard_mod,
            heartbeat_obj=self._heartbeat,
            focus_scheduler=self._focus_scheduler,
            risk_mod=risk_mod,
            rollup_mod=rollup_mod,
            narrative_mod=narrative_mod,
            narratives_dir=narratives_dir,
            adapter_registry=self._adapter_registry,
        )

    @property
    def store(self) -> "Store":
        return self._store

    def set_adapter_registry(self, registry) -> None:
        """Set/replace the adapter registry. Updates BundleAssembler."""
        self._adapter_registry = registry
        self._bundle_assembler._adapter_registry = registry

    def execute_tool(self, tool_name: str, params: dict) -> ToolResult:
        """执行 Tool Call。入口方法。通过 CommandExecutor 实现幂等。"""
        command_id = params.get("command_id", "")
        if not command_id:
            import uuid
            command_id = str(uuid.uuid4())
            params["command_id"] = command_id
        return self._executor.execute(command_id, tool_name, params)

    def get_context_bundle(self, user_focus: str | None = None) -> ContextBundle:
        """获取当前认知包。可选指定焦点。"""
        # If user supplied a focus, shift focus first
        if user_focus is not None:
            try:
                state = self._focus_scheduler.shift_focus(user_focus)
                focus_node_id = state.primary
            except ValueError:
                # Invalid node — fall back to scheduler state
                focus_node_id = self._focus_scheduler.get_state().primary
        else:
            focus_node_id = self._focus_scheduler.get_state().primary

        return self._bundle_assembler.assemble(focus_node_id=focus_node_id)

    def heartbeat(self) -> dict:
        """执行心跳。返回告警和焦点建议。"""
        result = self._heartbeat.scan()

        # Archive candidates surfaced by heartbeat
        for nid in result.archive_candidates:
            try:
                self._archive_mod.execute_archive(self._store, nid)
            except Exception:
                pass

        # Focus suggestion: first focus candidate, or None
        focus_suggestion = result.focus_candidates[0] if result.focus_candidates else None

        # Count active/waiting for callers that rely on these keys
        active_nodes = self._store.list_nodes(filters={"status": "active"}, limit=1000)
        waiting_nodes = self._store.list_nodes(filters={"status": "waiting"}, limit=1000)

        return {
            "alerts": [asdict(a) for a in result.alerts],
            "focus_suggestion": focus_suggestion,
            "active_count": len(active_nodes),
            "waiting_count": len(waiting_nodes),
        }

    def bootstrap(self) -> ContextBundle:
        """冷启动。委托 recovery.bootstrap() 执行 FR-13 流程。"""
        from . import recovery as recovery_mod
        return recovery_mod.bootstrap(
            store=self._store,
            heartbeat=self._heartbeat,
            focus_scheduler=self._focus_scheduler,
            bundle_assembler=self._bundle_assembler,
            archive_module=self._archive_mod,
        )

    def sync_source(self, node_id: str) -> "Node":
        """Sync a single node from its external source adapter."""
        node = self._store.get_node(node_id)
        if node is None:
            raise ValueError(f"Node {node_id} not found")
        if node.source == "internal":
            return node
        if not node.source_id:
            raise ValueError(f"Node {node_id} has source='{node.source}' but no source_id")
        if self._adapter_registry is None or not self._adapter_registry.has(node.source):
            raise ValueError(f"No adapter for source '{node.source}'")

        adapter = self._adapter_registry.get(node.source)
        snapshot = adapter.sync_node(node.source_id)

        if snapshot is None:
            self._store.update_node(node_id, {"source_deleted": True})
            return self._store.get_node(node_id)

        from datetime import datetime, timezone
        update_fields = {
            "title": snapshot.title,
            "status": snapshot.status,
            "source_synced_at": datetime.now(timezone.utc).isoformat(),
        }
        if snapshot.assignee is not None:
            update_fields["owner"] = snapshot.assignee
        return self._store.update_node(node_id, update_fields)

    def sync_all(self, since: str | None = None) -> int:
        """Sync all external-source nodes. Returns count of synced nodes."""
        if self._adapter_registry is None:
            return 0

        count = 0
        for source_name in self._adapter_registry.list_sources():
            nodes = self._store.list_nodes(
                filters={"source": source_name, "archived": False},
                limit=1000,
            )
            adapter = self._adapter_registry.get(source_name)
            for node in nodes:
                if node.source_id:
                    try:
                        snapshot = adapter.sync_node(node.source_id)
                        if snapshot:
                            from datetime import datetime, timezone
                            update_fields = {
                                "title": snapshot.title,
                                "status": snapshot.status,
                                "source_synced_at": datetime.now(timezone.utc).isoformat(),
                            }
                            if snapshot.assignee is not None:
                                update_fields["owner"] = snapshot.assignee
                            self._store.update_node(node.id, update_fields)
                            count += 1
                    except Exception:
                        pass  # Skip failed syncs
        return count
