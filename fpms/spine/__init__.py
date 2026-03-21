"""认知引擎 Spine — 公共 API 入口。"""

from __future__ import annotations

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
        """初始化引擎。创建 Store + 加载所有模块。"""
        raise NotImplementedError

    def execute_tool(self, tool_name: str, params: dict) -> ToolResult:
        """执行 Tool Call。入口方法。"""
        raise NotImplementedError

    def get_context_bundle(self, user_focus: str | None = None) -> ContextBundle:
        """获取当前认知包。可选指定焦点。"""
        raise NotImplementedError

    def heartbeat(self) -> dict:
        """执行心跳。返回告警和焦点建议。
        注：v1 实现后返回类型将改为 HeartbeatResult（定义在 heartbeat.py）。"""
        raise NotImplementedError

    def bootstrap(self) -> ContextBundle:
        """冷启动。返回初始认知包。"""
        raise NotImplementedError

    def sync_source(self, node_id: str) -> Node:
        """从外部工具同步单个节点的最新状态。"""
        raise NotImplementedError

    def sync_all(self, since: str | None = None) -> int:
        """增量同步所有外部源节点。返回更新数量。"""
        raise NotImplementedError
