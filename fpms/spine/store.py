"""数据持久化 — CRUD, Context Manager 事务, audit outbox, flush, 幂等。"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from .models import Edge, Node


class Store:
    def __init__(self, db_path: str, events_path: str):
        """初始化 Store，连接 SQLite + events.jsonl 路径。"""
        raise NotImplementedError

    # --- Node CRUD ---

    def create_node(self, node: Node) -> Node:
        """插入新节点。自动生成 id/timestamps。原子写入 DB + events。"""
        raise NotImplementedError

    def get_node(self, node_id: str) -> Node | None:
        """按 id 查询单个节点。"""
        raise NotImplementedError

    def update_node(self, node_id: str, fields: dict) -> Node:
        """更新节点指定字段。自动更新 updated_at。原子写入 DB + events。"""
        raise NotImplementedError

    def list_nodes(
        self,
        filters: dict | None = None,
        order_by: str = "updated_at",
        limit: int = 50,
        offset: int = 0,
    ) -> list[Node]:
        """条件查询节点列表。filters 支持 status/node_type/parent_id/is_root/archived/source。"""
        raise NotImplementedError

    # --- Edge CRUD ---

    def add_edge(self, edge: Edge) -> Edge:
        """添加边。原子写入 DB + events。"""
        raise NotImplementedError

    def remove_edge(self, source_id: str, target_id: str, edge_type: str) -> bool:
        """删除边。返回是否删除成功。"""
        raise NotImplementedError

    def get_edges(
        self,
        node_id: str,
        edge_type: str | None = None,
        direction: str = "outgoing",
    ) -> list[Edge]:
        """查询节点关联的边。direction: outgoing|incoming|both。"""
        raise NotImplementedError

    # --- Graph Queries ---

    def get_children(self, node_id: str, include_archived: bool = False) -> list[Node]:
        """获取直接子节点。"""
        raise NotImplementedError

    def get_parent(self, node_id: str) -> Node | None:
        """获取父节点。"""
        raise NotImplementedError

    def get_dependencies(self, node_id: str) -> list[Node]:
        """获取 depends_on 目标节点列表。"""
        raise NotImplementedError

    def get_dependents(self, node_id: str) -> list[Node]:
        """获取依赖本节点的节点列表（反向）。"""
        raise NotImplementedError

    def get_siblings(self, node_id: str) -> list[Node]:
        """获取同级节点（同 parent）。"""
        raise NotImplementedError

    def get_all_edges(self) -> list[Edge]:
        """获取全部边，用于 DAG 检测。"""
        raise NotImplementedError

    def get_ancestors(self, node_id: str) -> list[str]:
        """获取所有祖先节点 id（递归向上，WITH RECURSIVE CTE）。"""
        raise NotImplementedError

    def get_descendants(self, node_id: str) -> list[str]:
        """获取所有后代节点 id（递归向下，WITH RECURSIVE CTE）。"""
        raise NotImplementedError

    # --- Session State ---

    def get_session(self, key: str) -> dict | None:
        """读取 session_state 中的 JSON 值。"""
        raise NotImplementedError

    def set_session(self, key: str, value: dict) -> None:
        """写入 session_state。"""
        raise NotImplementedError

    # --- Transaction (Context Manager) ---

    @contextmanager
    def transaction(self) -> Generator[None, None, None]:
        """事务上下文管理器。用法: with store.transaction(): ...
        成功自动 commit，异常自动 rollback。
        禁止使用裸 begin/commit/rollback。"""
        raise NotImplementedError

    # --- Audit Outbox ---

    def write_event(self, event: dict) -> None:
        """写入审计事件到 audit_outbox 表（SQLite 内）。
        必须在 transaction() 上下文内调用。
        事后由 flush_events() 异步写入 events.jsonl。"""
        raise NotImplementedError

    def flush_events(self) -> int:
        """将 audit_outbox 中未 flush 的事件写入 events.jsonl。
        返回 flush 的事件数。可在心跳或 post-commit 时调用。"""
        raise NotImplementedError
