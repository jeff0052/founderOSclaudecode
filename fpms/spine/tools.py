"""Tool Call 处理器 — 15 个 Tool handlers（10 写入 + 2 运行时 + 3 只读）。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import types as _types

    from .models import ToolResult
    from .store import Store


class ToolHandler:
    def __init__(
        self,
        store: Store,
        validator_module: _types.ModuleType,
        narrative_module: _types.ModuleType,
        risk_module: _types.ModuleType | None = None,
        rollup_module: _types.ModuleType | None = None,
        dashboard_module: _types.ModuleType | None = None,
    ):
        """初始化，注入所有依赖。risk/rollup/dashboard 为 v1 模块，v0 可传 None。"""
        raise NotImplementedError

    def handle(self, tool_name: str, params: dict) -> ToolResult:
        """路由 Tool Call 到对应 handler。返回 ToolResult。"""
        raise NotImplementedError

    # --- Write Tools (10) ---

    def handle_create_node(self, params: dict) -> ToolResult:
        """创建节点。Pydantic 校验输入 → validator → store.create_node。"""
        raise NotImplementedError

    def handle_update_status(self, params: dict) -> ToolResult:
        """更新节点状态。校验迁移合法性 → store.update_node。
        is_root=true 时自动清除 parent_id。"""
        raise NotImplementedError

    def handle_update_field(self, params: dict) -> ToolResult:
        """更新节点指定字段。白名单校验 → store.update_node。"""
        raise NotImplementedError

    def handle_attach_node(self, params: dict) -> ToolResult:
        """挂载节点到新 parent。已有 parent 时原子替换（detach old + attach new）。
        归档目标拒绝，DAG 环路拒绝。"""
        raise NotImplementedError

    def handle_detach_node(self, params: dict) -> ToolResult:
        """从 parent 脱离。"""
        raise NotImplementedError

    def handle_add_dependency(self, params: dict) -> ToolResult:
        """添加 depends_on 依赖。自依赖拒绝，环路拒绝，归档目标拒绝。"""
        raise NotImplementedError

    def handle_remove_dependency(self, params: dict) -> ToolResult:
        """移除 depends_on 依赖。"""
        raise NotImplementedError

    def handle_append_log(self, params: dict) -> ToolResult:
        """追加叙事日志。不重置 Anti-Amnesia 计时器。"""
        raise NotImplementedError

    def handle_unarchive(self, params: dict) -> ToolResult:
        """解封归档节点。status_changed_at 刷新为 NOW()。
        可选 new_status 做原子解封+状态迁移。"""
        raise NotImplementedError

    def handle_set_persistent(self, params: dict) -> ToolResult:
        """设置/取消 is_persistent 标记（归档豁免）。"""
        raise NotImplementedError

    # --- Runtime Tools (2) ---

    def handle_shift_focus(self, params: dict) -> ToolResult:
        """切换焦点到指定节点。"""
        raise NotImplementedError

    def handle_expand_context(self, params: dict) -> ToolResult:
        """扩展当前上下文。"""
        raise NotImplementedError

    # --- Read Tools (3) ---

    def handle_get_node(self, params: dict) -> ToolResult:
        """查询单个节点详情。"""
        raise NotImplementedError

    def handle_search_nodes(self, params: dict) -> ToolResult:
        """搜索节点。支持 status/parent_id/source 过滤 + 分页。
        summary 默认不含，include_summary=true 时含。"""
        raise NotImplementedError

    def handle_get_assembly_trace(self, params: dict) -> ToolResult:
        """查询最近的认知包组装轨迹（FR-10 可观测性）。"""
        raise NotImplementedError
