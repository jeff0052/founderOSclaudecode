"""校验层 — 状态迁移, DAG 环路检测, XOR 约束, 活跃域隔离, Actionable Errors。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import Node
    from .store import Store


class ValidationError(Exception):
    """校验失败时抛出。包含 code, message, suggestion。
    message 必须是 Actionable Error：告诉 LLM 哪里错了 + 下一步该调什么工具。"""

    def __init__(self, code: str, message: str, suggestion: str):
        self.code = code
        self.message = message
        self.suggestion = suggestion
        super().__init__(message)


def validate_status_transition(
    current: str,
    target: str,
    node: Node,
    children: list[Node],
    reason: str | None = None,
) -> list[str]:
    """校验状态迁移合法性。不合法则 raise ValidationError（含 actionable suggestion）。
    返回 warnings 列表（例如 dropped 有活跃子节点时的警告）。
    - inbox→active/waiting: 需要 summary + (parent_id OR is_root)
    - →done: 所有子节点必须终态
    - →dropped: 警告但允许
    - done→active / dropped→inbox: 需要 reason
    """
    raise NotImplementedError


def validate_dag_safety(
    store: Store, source_id: str, target_id: str, edge_type: str
) -> None:
    """统一 DAG 环路检测（合并 parent + depends_on 图）。
    使用 SQLite WITH RECURSIVE CTE 在数据库层检测环路。
    有环则 raise ValidationError。"""
    raise NotImplementedError


def validate_xor_constraint(is_root: bool, parent_id: str | None) -> None:
    """检查 is_root 和 parent_id 互斥。违反则 raise ValidationError。"""
    raise NotImplementedError


def validate_active_domain(node: Node) -> None:
    """检查目标节点非归档状态。已归档则 raise ValidationError。"""
    raise NotImplementedError


def validate_attach(store: Store, node_id: str, new_parent_id: str) -> None:
    """综合校验 attach: 活跃域 + DAG 安全 + XOR。"""
    raise NotImplementedError


def validate_dependency(store: Store, source_id: str, target_id: str) -> None:
    """综合校验 add_dependency: 活跃域 + DAG 安全 + 不能自依赖。"""
    raise NotImplementedError
