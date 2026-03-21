"""串行命令执行器 — 所有写操作通过这里，幂等检查 + 事务封装。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import ToolResult
    from .store import Store


class CommandExecutor:
    def __init__(self, store: Store):
        """初始化串行执行器。所有写操作必须通过这里。"""
        raise NotImplementedError

    def execute(self, command_id: str, tool_name: str, params: dict) -> ToolResult:
        """串行执行一个 Tool Call。
        1. 幂等检查：command_id 已存在 → 返回上次结果
        2. Pydantic 校验输入
        3. 路由到 ToolHandler
        4. 在同一事务内写入 facts + audit_outbox + recent_commands
        5. Post-commit: narrative append + flush events
        """
        raise NotImplementedError
