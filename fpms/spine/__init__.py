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
        self._knowledge_dir = os.path.join(os.path.dirname(narratives_dir), "knowledge")

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
        self._tool_handler._adapter_registry = registry

    def execute_tool(self, tool_name: str, params: dict) -> ToolResult:
        """执行 Tool Call。入口方法。通过 CommandExecutor 实现幂等。"""
        command_id = params.get("command_id", "")
        if not command_id:
            import uuid
            command_id = str(uuid.uuid4())
            params["command_id"] = command_id
        return self._executor.execute(command_id, tool_name, params)

    def get_context_bundle(self, user_focus: str | None = None, role: str = "all") -> ContextBundle:
        """获取当前认知包。可选指定焦点和角色。"""
        if user_focus is not None:
            try:
                state = self._focus_scheduler.shift_focus(user_focus)
                focus_node_id = state.primary
            except ValueError:
                focus_node_id = self._focus_scheduler.get_state().primary
        else:
            focus_node_id = self._focus_scheduler.get_state().primary

        return self._bundle_assembler.assemble(focus_node_id=focus_node_id, role=role)

    def activate_workbench(self, node_id: str, role: str = "execution") -> dict:
        """Activate the workbench — prepare AI working context. Stateless."""
        from .bundle import _ROLE_BUDGETS
        from . import knowledge as knowledge_mod

        node = self._store.get_node(node_id)
        if node is None:
            raise ValueError(f"Node '{node_id}' not found")

        # Role-filtered context bundle
        bundle = self._bundle_assembler.assemble(focus_node_id=node_id, role=role)

        # Assemble context text
        context_parts = []
        if bundle.l0_dashboard.strip():
            context_parts.append(bundle.l0_dashboard)
        if bundle.l_alert.strip() and "No alerts" not in bundle.l_alert:
            context_parts.append(bundle.l_alert)
        context_parts.append(bundle.l1_neighborhood)
        context_parts.append(bundle.l2_focus)
        context_text = "\n\n".join(context_parts)

        # Knowledge docs (with inheritance)
        knowledge = knowledge_mod.get_knowledge(
            self._knowledge_dir, node_id, store=self._store, inherit=True,
        )

        # Subtasks sorted by dependency
        children = self._store.get_children(node_id, include_archived=False)
        subtasks = self._sort_subtasks_by_deps(children)

        # Suggested next: first non-terminal subtask
        suggested_next = None
        for st in subtasks:
            if st["status"] not in ("done", "dropped"):
                suggested_next = {"id": st["id"], "title": st["title"]}
                break

        # Role-specific narrative extractions
        decisions = self._extract_narrative_by_category(node_id, "decision")
        risks = self._extract_narrative_by_category(node_id, "risk")

        # Role prompt
        role_prompt = self._load_role_prompt(role)

        # Token budget
        budget = _ROLE_BUDGETS.get(role, _ROLE_BUDGETS["all"])

        result = {
            "goal": node.title,
            "knowledge": knowledge if isinstance(knowledge, dict) else {},
            "context": context_text,
            "subtasks": subtasks,
            "suggested_next": suggested_next,
            "role_prompt": role_prompt,
            "token_budget": {
                "total": budget["total"],
                "l0": budget.get("l0") or 0,
                "l1": budget.get("l1") or 0,
                "l2": budget.get("l2") or 0,
            },
        }

        # Add role-specific fields
        if role == "strategy":
            result["decisions"] = decisions
        elif role == "review":
            result["risks"] = risks

        return result

    def _sort_subtasks_by_deps(self, children: list) -> list:
        """Topological sort of subtasks by dependency order (Kahn's algorithm)."""
        if not children:
            return []

        child_ids = {c.id for c in children}
        child_map = {c.id: c for c in children}

        deps = {}
        for c in children:
            child_deps = self._store.get_dependencies(c.id)
            deps[c.id] = {d.id for d in child_deps if d.id in child_ids}

        in_degree = {cid: len(deps.get(cid, set())) for cid in child_ids}
        queue = sorted(cid for cid in child_ids if in_degree[cid] == 0)
        sorted_ids = []

        while queue:
            current = queue.pop(0)
            sorted_ids.append(current)
            for cid in child_ids:
                if current in deps.get(cid, set()):
                    in_degree[cid] -= 1
                    if in_degree[cid] == 0:
                        queue.append(cid)
            queue.sort()

        for cid in child_ids:
            if cid not in sorted_ids:
                sorted_ids.append(cid)

        return [
            {"id": child_map[cid].id, "title": child_map[cid].title,
             "status": child_map[cid].status, "summary": child_map[cid].summary}
            for cid in sorted_ids
        ]

    def _extract_narrative_by_category(self, node_id: str, category: str) -> list:
        """Extract narrative entries of a specific category as structured list."""
        raw = self._narrative_mod.read_narrative(
            self._narratives_dir, node_id, categories=[category]
        )
        if not raw.strip():
            return []
        entries = []
        for block in raw.split("\n## "):
            block = block.strip()
            if not block:
                continue
            if not block.startswith("## "):
                block = "## " + block
            lines = block.split("\n", 1)
            content = lines[1].strip() if len(lines) > 1 else ""
            if content:
                entries.append({"content": content})
        return entries

    def _load_role_prompt(self, role: str) -> str:
        """Load role prompt from fpms/prompts/{role}.md."""
        prompt_map = {"strategy": "strategy", "review": "review", "execution": "execution"}
        filename = prompt_map.get(role)
        if not filename:
            return ""
        import fpms
        pkg_dir = os.path.dirname(fpms.__file__)
        prompt_path = os.path.join(pkg_dir, "prompts", f"{filename}.md")
        if os.path.exists(prompt_path):
            with open(prompt_path) as f:
                return f.read()
        return ""

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
