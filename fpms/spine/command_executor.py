"""串行命令执行器 — 所有写操作通过这里，幂等检查 + 事务封装。"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone, timedelta
from typing import Optional

from .models import ToolResult
from .store import Store


class CommandExecutor:
    def __init__(self, store: Store):
        """初始化串行执行器。所有写操作必须通过这里。"""
        self._store = store

    def execute(self, command_id: str, tool_name: str, params: dict) -> ToolResult:
        """串行执行一个 Tool Call。
        1. 幂等检查：command_id 已存在 → 返回上次结果
        2. 不存在 → raise NotImplementedError (tools.py 后续提供路由)
        """
        # 1. Idempotency check
        cached = self._get_cached_result(command_id)
        if cached is not None:
            return cached

        # 2. No cached result — tools.py will provide routing later
        raise NotImplementedError(
            f"Tool routing not yet implemented for '{tool_name}'. "
            "tools.py will provide the actual dispatch logic."
        )

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
