"""Tool Call 处理器 — 15 个 Tool handlers（10 写入 + 2 运行时 + 3 只读）。"""

from __future__ import annotations

import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import narrative as narrative_mod
from . import validator as validator_mod
from .models import (
    CreateNodeInput,
    Edge,
    Node,
    ToolResult,
    UpdateFieldInput,
    UpdateStatusInput,
)
from .store import Store


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _event_id() -> str:
    return str(uuid.uuid4())


def _node_to_dict(node: Node) -> Dict[str, Any]:
    d = asdict(node)
    return d


class ToolHandler:
    def __init__(
        self,
        store: Store,
        validator_module: Any = None,
        narrative_module: Any = None,
        risk_module: Any = None,
        rollup_module: Any = None,
        dashboard_module: Any = None,
    ):
        """初始化，注入所有依赖。risk/rollup/dashboard 为 v1 模块，v0 可传 None。"""
        self.store = store
        self.validator = validator_module or validator_mod
        self.narrative = narrative_module or narrative_mod
        # v1 modules (unused in v0)
        self.risk = risk_module
        self.rollup = rollup_module
        self.dashboard = dashboard_module
        self.narratives_dir = "fpms/narratives"  # default, can be overridden

    # -----------------------------------------------------------------
    # Routing
    # -----------------------------------------------------------------

    _TOOL_MAP = {
        "create_node": "handle_create_node",
        "update_status": "handle_update_status",
        "update_field": "handle_update_field",
        "attach_node": "handle_attach_node",
        "detach_node": "handle_detach_node",
        "add_dependency": "handle_add_dependency",
        "remove_dependency": "handle_remove_dependency",
        "append_log": "handle_append_log",
        "unarchive": "handle_unarchive",
        "set_persistent": "handle_set_persistent",
        "shift_focus": "handle_shift_focus",
        "expand_context": "handle_expand_context",
        "get_node": "handle_get_node",
        "search_nodes": "handle_search_nodes",
        "get_assembly_trace": "handle_get_assembly_trace",
    }

    def handle(self, tool_name: str, params: dict) -> ToolResult:
        """路由 Tool Call 到对应 handler。返回 ToolResult。"""
        method_name = self._TOOL_MAP.get(tool_name)
        if method_name is None:
            return ToolResult(
                success=False,
                command_id=params.get("command_id", ""),
                error=f"Unknown tool: '{tool_name}'",
                suggestion=f"Available tools: {sorted(self._TOOL_MAP.keys())}",
            )
        handler = getattr(self, method_name)
        return handler(params)

    # --- Write Tools (10) ---

    def handle_create_node(self, params: dict) -> ToolResult:
        """创建节点。Pydantic 校验输入 → validator → store.create_node。"""
        command_id = params.get("command_id", "")
        try:
            inp = CreateNodeInput(**params)
        except Exception as e:
            return ToolResult(
                success=False,
                command_id=command_id,
                error=str(e),
                suggestion="Please check required fields: title (str). "
                "Optional: node_type, parent_id, is_root, summary, why, next_step, owner, deadline, source, source_id, source_url",
            )

        # XOR check
        try:
            self.validator.validate_xor_constraint(inp.is_root, inp.parent_id)
        except validator_mod.ValidationError as e:
            return ToolResult(
                success=False,
                command_id=command_id,
                error=e.message,
                suggestion=e.suggestion,
            )

        node = Node(
            id="",
            title=inp.title,
            status="inbox",
            node_type=inp.node_type,
            is_root=inp.is_root,
            parent_id=inp.parent_id,
            summary=inp.summary,
            why=inp.why,
            next_step=inp.next_step,
            owner=inp.owner,
            deadline=inp.deadline,
            source=inp.source,
            source_id=inp.source_id,
            source_url=inp.source_url,
        )

        ev_id = _event_id()

        with self.store.transaction():
            created = self.store.create_node(node)
            # Parent edge is auto-added by store.create_node (child -> parent convention)

        # Post-commit: narrative
        now = _now_iso()
        self.narrative.append_narrative(
            self.narratives_dir,
            created.id,
            now,
            "created",
            f"Node created: {created.title} (type={created.node_type}, status=inbox)",
        )

        return ToolResult(
            success=True,
            command_id=command_id,
            event_id=ev_id,
            data=_node_to_dict(created),
            affected_nodes=[created.id],
        )

    def handle_update_status(self, params: dict) -> ToolResult:
        """更新节点状态。校验迁移合法性 → store.update_node。
        is_root=true 时自动清除 parent_id。"""
        command_id = params.get("command_id", "")
        try:
            inp = UpdateStatusInput(**params)
        except Exception as e:
            return ToolResult(
                success=False,
                command_id=command_id,
                error=str(e),
                suggestion="Required: node_id (str), new_status (str). Optional: reason, is_root",
            )

        node = self.store.get_node(inp.node_id)
        if node is None:
            return ToolResult(
                success=False,
                command_id=command_id,
                error=f"Node '{inp.node_id}' not found.",
                suggestion="Check node_id or use search_nodes to find the correct id",
            )

        children = self.store.get_children(node.id)

        try:
            warnings = self.validator.validate_status_transition(
                node.status, inp.new_status, node, children, inp.reason
            )
        except validator_mod.ValidationError as e:
            return ToolResult(
                success=False,
                command_id=command_id,
                error=e.message,
                suggestion=e.suggestion,
            )

        now = _now_iso()
        update_fields: Dict[str, Any] = {
            "status": inp.new_status,
            "status_changed_at": now,
        }

        # is_root=True in params → auto-clear parent_id
        if inp.is_root is True:
            update_fields["is_root"] = True
            update_fields["parent_id"] = None

        with self.store.transaction():
            # If is_root auto-clear, also remove parent edge (child -> parent convention)
            if inp.is_root is True and node.parent_id:
                self.store.remove_edge(node.id, node.parent_id, "parent")
            updated = self.store.update_node(node.id, update_fields)

        ev_id = _event_id()

        # Post-commit: narrative
        self.narrative.append_narrative(
            self.narratives_dir,
            node.id,
            now,
            "status_change",
            f"Status changed: {node.status} → {inp.new_status}"
            + (f" (reason: {inp.reason})" if inp.reason else ""),
        )

        return ToolResult(
            success=True,
            command_id=command_id,
            event_id=ev_id,
            data=_node_to_dict(updated),
            affected_nodes=[node.id],
            warnings=warnings,
        )

    def handle_update_field(self, params: dict) -> ToolResult:
        """更新节点指定字段。白名单校验 → store.update_node。"""
        command_id = params.get("command_id", "")
        try:
            inp = UpdateFieldInput(**params)
        except Exception as e:
            return ToolResult(
                success=False,
                command_id=command_id,
                error=str(e),
                suggestion="Required: node_id (str), field (str), value. "
                "Allowed fields: title, summary, why, next_step, owner, deadline, node_type",
            )

        node = self.store.get_node(inp.node_id)
        if node is None:
            return ToolResult(
                success=False,
                command_id=command_id,
                error=f"Node '{inp.node_id}' not found.",
                suggestion="Check node_id or use search_nodes to find the correct id",
            )

        with self.store.transaction():
            updated = self.store.update_node(node.id, {inp.field: inp.value})

        ev_id = _event_id()

        # Post-commit: narrative
        now = _now_iso()
        self.narrative.append_narrative(
            self.narratives_dir,
            node.id,
            now,
            "field_update",
            f"Field '{inp.field}' updated to: {inp.value}",
        )

        return ToolResult(
            success=True,
            command_id=command_id,
            event_id=ev_id,
            data=_node_to_dict(updated),
            affected_nodes=[node.id],
        )

    def handle_attach_node(self, params: dict) -> ToolResult:
        """挂载节点到新 parent。已有 parent 时原子替换（detach old + attach new）。
        归档目标拒绝，DAG 环路拒绝。"""
        command_id = params.get("command_id", "")
        node_id = params.get("node_id")
        parent_id = params.get("parent_id")

        if not node_id or not parent_id:
            return ToolResult(
                success=False,
                command_id=command_id,
                error="Missing required fields: node_id and parent_id",
                suggestion="Provide both node_id and parent_id",
            )

        node = self.store.get_node(node_id)
        if node is None:
            return ToolResult(
                success=False,
                command_id=command_id,
                error=f"Node '{node_id}' not found.",
                suggestion="Check node_id or use search_nodes to find the correct id",
            )

        # Validate attach (active domain + DAG safety)
        try:
            self.validator.validate_attach(self.store, node_id, parent_id)
        except validator_mod.ValidationError as e:
            return ToolResult(
                success=False,
                command_id=command_id,
                error=e.message,
                suggestion=e.suggestion,
            )

        with self.store.transaction():
            # If node already has parent → detach old (child -> parent convention)
            if node.parent_id:
                self.store.remove_edge(node_id, node.parent_id, "parent")

            # Add new parent edge (child -> parent convention) + update node
            self.store.add_edge(Edge(
                source_id=node_id,
                target_id=parent_id,
                edge_type="parent",
            ))
            updated = self.store.update_node(node_id, {
                "parent_id": parent_id,
                "is_root": False,
            })

        ev_id = _event_id()

        # Post-commit: narrative
        now = _now_iso()
        self.narrative.append_narrative(
            self.narratives_dir,
            node_id,
            now,
            "attached",
            f"Node attached to parent '{parent_id}'"
            + (f" (detached from '{node.parent_id}')" if node.parent_id else ""),
        )

        return ToolResult(
            success=True,
            command_id=command_id,
            event_id=ev_id,
            data=_node_to_dict(updated),
            affected_nodes=[node_id, parent_id],
        )

    def handle_detach_node(self, params: dict) -> ToolResult:
        """从 parent 脱离。"""
        command_id = params.get("command_id", "")
        node_id = params.get("node_id")

        if not node_id:
            return ToolResult(
                success=False,
                command_id=command_id,
                error="Missing required field: node_id",
                suggestion="Provide node_id",
            )

        node = self.store.get_node(node_id)
        if node is None:
            return ToolResult(
                success=False,
                command_id=command_id,
                error=f"Node '{node_id}' not found.",
                suggestion="Check node_id or use search_nodes to find the correct id",
            )

        if not node.parent_id:
            return ToolResult(
                success=True,
                command_id=command_id,
                data=_node_to_dict(node),
                affected_nodes=[node_id],
                warnings=["Node has no parent, nothing to detach"],
            )

        old_parent = node.parent_id
        with self.store.transaction():
            self.store.remove_edge(node_id, old_parent, "parent")
            updated = self.store.update_node(node_id, {"parent_id": None})

        ev_id = _event_id()

        # Post-commit: narrative
        now = _now_iso()
        self.narrative.append_narrative(
            self.narratives_dir,
            node_id,
            now,
            "detached",
            f"Node detached from parent '{old_parent}'",
        )

        return ToolResult(
            success=True,
            command_id=command_id,
            event_id=ev_id,
            data=_node_to_dict(updated),
            affected_nodes=[node_id],
        )

    def handle_add_dependency(self, params: dict) -> ToolResult:
        """添加 depends_on 依赖。自依赖拒绝，环路拒绝，归档目标拒绝。"""
        command_id = params.get("command_id", "")
        source_id = params.get("source_id")
        target_id = params.get("target_id")

        if not source_id or not target_id:
            return ToolResult(
                success=False,
                command_id=command_id,
                error="Missing required fields: source_id and target_id",
                suggestion="Provide both source_id and target_id",
            )

        # Validate dependency (self-dep, active domain, DAG safety)
        try:
            self.validator.validate_dependency(self.store, source_id, target_id)
        except validator_mod.ValidationError as e:
            return ToolResult(
                success=False,
                command_id=command_id,
                error=e.message,
                suggestion=e.suggestion,
            )

        with self.store.transaction():
            self.store.add_edge(Edge(
                source_id=source_id,
                target_id=target_id,
                edge_type="depends_on",
            ))

        ev_id = _event_id()

        # Post-commit: narrative on source node
        now = _now_iso()
        self.narrative.append_narrative(
            self.narratives_dir,
            source_id,
            now,
            "dependency_added",
            f"Dependency added: {source_id} depends_on {target_id}",
        )

        return ToolResult(
            success=True,
            command_id=command_id,
            event_id=ev_id,
            data={"source_id": source_id, "target_id": target_id, "edge_type": "depends_on"},
            affected_nodes=[source_id, target_id],
        )

    def handle_remove_dependency(self, params: dict) -> ToolResult:
        """移除 depends_on 依赖。"""
        command_id = params.get("command_id", "")
        source_id = params.get("source_id")
        target_id = params.get("target_id")

        if not source_id or not target_id:
            return ToolResult(
                success=False,
                command_id=command_id,
                error="Missing required fields: source_id and target_id",
                suggestion="Provide both source_id and target_id",
            )

        removed = self.store.remove_edge(source_id, target_id, "depends_on")

        return ToolResult(
            success=True,
            command_id=command_id,
            data={"removed": removed, "source_id": source_id, "target_id": target_id},
            affected_nodes=[source_id] if removed else [],
            warnings=[] if removed else [f"No dependency edge found from {source_id} to {target_id}"],
        )

    def handle_append_log(self, params: dict) -> ToolResult:
        """追加叙事日志。不重置 Anti-Amnesia 计时器。"""
        command_id = params.get("command_id", "")
        node_id = params.get("node_id")
        content = params.get("content", "")
        event_type = params.get("event_type", "log")

        if not node_id:
            return ToolResult(
                success=False,
                command_id=command_id,
                error="Missing required field: node_id",
                suggestion="Provide node_id",
            )

        node = self.store.get_node(node_id)
        if node is None:
            return ToolResult(
                success=False,
                command_id=command_id,
                error=f"Node '{node_id}' not found.",
                suggestion="Check node_id or use search_nodes to find the correct id",
            )

        now = _now_iso()
        ok = self.narrative.append_narrative(
            self.narratives_dir,
            node_id,
            now,
            event_type,
            content,
        )
        # Important: do NOT reset Anti-Amnesia timer (don't touch session_state)

        return ToolResult(
            success=ok,
            command_id=command_id,
            data={"node_id": node_id, "event_type": event_type, "appended": ok},
            affected_nodes=[node_id],
            error=None if ok else "Failed to append narrative",
            suggestion=None if ok else "Check file system permissions for narratives directory",
        )

    def handle_unarchive(self, params: dict) -> ToolResult:
        """解封归档节点。status_changed_at 刷新为 NOW()。
        可选 new_status 做原子解封+状态迁移。"""
        command_id = params.get("command_id", "")
        node_id = params.get("node_id")
        new_status = params.get("new_status")

        if not node_id:
            return ToolResult(
                success=False,
                command_id=command_id,
                error="Missing required field: node_id",
                suggestion="Provide node_id",
            )

        node = self.store.get_node(node_id)
        if node is None:
            return ToolResult(
                success=False,
                command_id=command_id,
                error=f"Node '{node_id}' not found.",
                suggestion="Check node_id or use search_nodes to find the correct id",
            )

        if node.archived_at is None:
            return ToolResult(
                success=False,
                command_id=command_id,
                error=f"Node '{node_id}' is not archived.",
                suggestion="Only archived nodes can be unarchived. Use get_node to check status.",
            )

        now = _now_iso()
        update_fields: Dict[str, Any] = {
            "archived_at": None,
            "status_changed_at": now,
        }

        # Optional status transition
        if new_status:
            children = self.store.get_children(node.id)
            try:
                warnings = self.validator.validate_status_transition(
                    node.status, new_status, node, children
                )
            except validator_mod.ValidationError as e:
                return ToolResult(
                    success=False,
                    command_id=command_id,
                    error=e.message,
                    suggestion=e.suggestion,
                )
            update_fields["status"] = new_status
        else:
            warnings = []

        with self.store.transaction():
            updated = self.store.update_node(node_id, update_fields)

        ev_id = _event_id()

        # Post-commit: narrative
        self.narrative.append_narrative(
            self.narratives_dir,
            node_id,
            now,
            "unarchived",
            f"Node unarchived" + (f", status set to {new_status}" if new_status else ""),
        )

        return ToolResult(
            success=True,
            command_id=command_id,
            event_id=ev_id,
            data=_node_to_dict(updated),
            affected_nodes=[node_id],
            warnings=warnings,
        )

    def handle_set_persistent(self, params: dict) -> ToolResult:
        """设置/取消 is_persistent 标记（归档豁免）。"""
        command_id = params.get("command_id", "")
        node_id = params.get("node_id")
        is_persistent = params.get("is_persistent")

        if not node_id:
            return ToolResult(
                success=False,
                command_id=command_id,
                error="Missing required field: node_id",
                suggestion="Provide node_id",
            )

        if is_persistent is None:
            return ToolResult(
                success=False,
                command_id=command_id,
                error="Missing required field: is_persistent",
                suggestion="Provide is_persistent (true/false)",
            )

        node = self.store.get_node(node_id)
        if node is None:
            return ToolResult(
                success=False,
                command_id=command_id,
                error=f"Node '{node_id}' not found.",
                suggestion="Check node_id or use search_nodes to find the correct id",
            )

        with self.store.transaction():
            updated = self.store.update_node(node_id, {"is_persistent": bool(is_persistent)})

        return ToolResult(
            success=True,
            command_id=command_id,
            data=_node_to_dict(updated),
            affected_nodes=[node_id],
        )

    # --- Runtime Tools (2) ---

    def handle_shift_focus(self, params: dict) -> ToolResult:
        """切换焦点到指定节点。"""
        command_id = params.get("command_id", "")
        node_id = params.get("node_id")

        if not node_id:
            return ToolResult(
                success=False,
                command_id=command_id,
                error="Missing required field: node_id",
                suggestion="Provide node_id",
            )

        node = self.store.get_node(node_id)
        if node is None:
            return ToolResult(
                success=False,
                command_id=command_id,
                error=f"Node '{node_id}' not found.",
                suggestion="Check node_id or use search_nodes to find the correct id",
            )

        with self.store.transaction():
            self.store.set_session("focus_list", [node_id])

        return ToolResult(
            success=True,
            command_id=command_id,
            data={"focus_list": [node_id]},
            affected_nodes=[node_id],
        )

    def handle_expand_context(self, params: dict) -> ToolResult:
        """扩展当前上下文。v0: 返回节点上下文信息。"""
        command_id = params.get("command_id", "")
        node_id = params.get("node_id")

        if not node_id:
            return ToolResult(
                success=False,
                command_id=command_id,
                error="Missing required field: node_id",
                suggestion="Provide node_id",
            )

        node = self.store.get_node(node_id)
        if node is None:
            return ToolResult(
                success=False,
                command_id=command_id,
                error=f"Node '{node_id}' not found.",
                suggestion="Check node_id or use search_nodes to find the correct id",
            )

        # v0: return basic context info
        parent = self.store.get_parent(node_id)
        children = self.store.get_children(node_id)
        dependencies = self.store.get_dependencies(node_id)

        context = {
            "node": _node_to_dict(node),
            "parent": _node_to_dict(parent) if parent else None,
            "children": [_node_to_dict(c) for c in children],
            "dependencies": [_node_to_dict(d) for d in dependencies],
        }

        return ToolResult(
            success=True,
            command_id=command_id,
            data=context,
            affected_nodes=[node_id],
        )

    # --- Read Tools (3) ---

    def handle_get_node(self, params: dict) -> ToolResult:
        """查询单个节点详情。"""
        command_id = params.get("command_id", "")
        node_id = params.get("node_id")

        if not node_id:
            return ToolResult(
                success=False,
                command_id=command_id,
                error="Missing required field: node_id",
                suggestion="Provide node_id",
            )

        node = self.store.get_node(node_id)
        if node is None:
            return ToolResult(
                success=False,
                command_id=command_id,
                error=f"Node '{node_id}' not found.",
                suggestion="Check node_id or use search_nodes to find the correct id",
            )

        return ToolResult(
            success=True,
            command_id=command_id,
            data=_node_to_dict(node),
        )

    def handle_search_nodes(self, params: dict) -> ToolResult:
        """搜索节点。支持 status/parent_id/source 过滤 + 分页。
        summary 默认不含，include_summary=true 时含。"""
        command_id = params.get("command_id", "")
        filters = params.get("filters", {})
        limit = params.get("limit", 50)
        offset = params.get("offset", 0)
        include_summary = params.get("include_summary", False)

        nodes = self.store.list_nodes(filters=filters, limit=limit, offset=offset)
        results = []
        for n in nodes:
            d = _node_to_dict(n)
            if not include_summary:
                d.pop("summary", None)
            results.append(d)

        return ToolResult(
            success=True,
            command_id=command_id,
            data={"nodes": results, "count": len(results)},
        )

    def handle_get_assembly_trace(self, params: dict) -> ToolResult:
        """查询最近的认知包组装轨迹（FR-10 可观测性）。v0: 返回空列表。"""
        command_id = params.get("command_id", "")
        return ToolResult(
            success=True,
            command_id=command_id,
            data={"traces": [], "message": "Assembly trace is not available in v0"},
        )
