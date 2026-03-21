"""串行命令执行器 — 所有写操作通过这里，幂等检查 + 事务封装。"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone, timedelta
from typing import Optional, TYPE_CHECKING

from .models import ToolResult
from .store import Store

if TYPE_CHECKING:
    from .tools import ToolHandler


class CommandExecutor:
    def __init__(self, store: Store, tool_handler: Optional[ToolHandler] = None):
        """初始化串行执行器。所有写操作必须通过这里。
        如果未传入 tool_handler，自动创建默认 ToolHandler。"""
        self._store = store
        if tool_handler is None:
            from .tools import ToolHandler as _TH
            from . import validator as _validator_mod
            from . import narrative as _narrative_mod
            tool_handler = _TH(store, _validator_mod, _narrative_mod)
        self._tool_handler = tool_handler

    def set_tool_handler(self, handler: ToolHandler) -> None:
        """Set the tool handler for routing (allows breaking circular init)."""
        self._tool_handler = handler

    def execute(self, command_id: str, tool_name: str, params: dict) -> ToolResult:
        """串行执行一个 Tool Call。
        1. 幂等检查：command_id 已存在 → 返回上次结果
        2. 路由到 ToolHandler.handle(tool_name, params)
        3. 保存结果到 recent_commands
        4. Post-commit: flush events
        """
        # 1. Idempotency check
        cached = self._get_cached_result(command_id)
        if cached is not None:
            return cached

        # 2. Route to ToolHandler
        if self._tool_handler is None:
            raise NotImplementedError(
                "ToolHandler not set on CommandExecutor. "
                "Call set_tool_handler() or pass tool_handler to __init__."
            )

        # Inject command_id into params so handlers can use it
        params_with_id = dict(params)
        params_with_id["command_id"] = command_id

        result = self._tool_handler.handle(tool_name, params_with_id)

        # 3. Write audit event with command_id for traceability
        self._store.write_event({
            "event_type": "command_executed",
            "tool_name": tool_name,
            "command_id": command_id,
            "success": result.success,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # 4. Save result for idempotency
        self.save_command_result(command_id, tool_name, result)

        # 5. Post-commit: flush events
        self._store.flush_events()

        return result

    def _get_cached_result(self, command_id: str) -> Optional[ToolResult]:
        """Check recent_commands for a cached result."""
        row = self._store._conn.execute(
            "SELECT result_json FROM recent_commands WHERE command_id=?",
            (command_id,),
        ).fetchone()
        if row is None:
            return None

        data = json.loads(row[0])
        return ToolResult(
            success=data["success"],
            command_id=data["command_id"],
            event_id=data.get("event_id"),
            data=data.get("data"),
            error=data.get("error"),
            suggestion=data.get("suggestion"),
            affected_nodes=data.get("affected_nodes", []),
            warnings=data.get("warnings", []),
        )

    def save_command_result(self, command_id: str, tool_name: str, result: ToolResult) -> None:
        """Save a command result to recent_commands for idempotency (24h TTL)."""
        now = datetime.now(timezone.utc)
        expires = now + timedelta(hours=24)
        result_json = json.dumps({
            "success": result.success,
            "command_id": result.command_id,
            "event_id": result.event_id,
            "data": result.data,
            "error": result.error,
            "suggestion": result.suggestion,
            "affected_nodes": result.affected_nodes,
            "warnings": result.warnings,
        })
        self._store._conn.execute(
            """INSERT OR REPLACE INTO recent_commands
               (command_id, tool_name, result_json, created_at, expires_at)
               VALUES (?,?,?,?,?)""",
            (command_id, tool_name, result_json, now.isoformat(), expires.isoformat()),
        )
