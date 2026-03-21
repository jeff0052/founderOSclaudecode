"""数据持久化 — CRUD, Context Manager 事务, audit outbox, flush, 幂等。"""

from __future__ import annotations

import json
import os
import secrets
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from typing import Dict, Generator, List, Optional

from .models import Edge, Node
from .schema import init_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TYPE_PREFIX = {
    "goal": "goal",
    "project": "proj",
    "milestone": "mile",
    "task": "task",
    "unknown": "node",
}


def _generate_id(node_type: str) -> str:
    prefix = _TYPE_PREFIX.get(node_type, "node")
    hex4 = secrets.token_hex(2)  # 4 hex chars
    return f"{prefix}-{hex4}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_node(row: tuple, col_names: List[str]) -> Node:
    d = dict(zip(col_names, row))
    return Node(
        id=d["id"],
        title=d["title"],
        status=d["status"],
        node_type=d["node_type"],
        is_root=bool(d["is_root"]),
        parent_id=d["parent_id"],
        summary=d.get("summary"),
        why=d.get("why"),
        next_step=d.get("next_step"),
        owner=d.get("owner"),
        deadline=d.get("deadline"),
        is_persistent=bool(d.get("is_persistent", 0)),
        created_at=d["created_at"],
        updated_at=d["updated_at"],
        status_changed_at=d["status_changed_at"],
        archived_at=d.get("archived_at"),
        source=d.get("source", "internal"),
        source_id=d.get("source_id"),
        source_url=d.get("source_url"),
        source_synced_at=d.get("source_synced_at"),
        source_deleted=bool(d.get("source_deleted", 0)),
        needs_compression=bool(d.get("needs_compression", 0)),
        compression_in_progress=bool(d.get("compression_in_progress", 0)),
        no_llm_compression=bool(d.get("no_llm_compression", 0)),
        tags=json.loads(d.get("tags") or "[]"),
    )


def _row_to_edge(row: tuple, col_names: List[str]) -> Edge:
    d = dict(zip(col_names, row))
    return Edge(
        source_id=d["source_id"],
        target_id=d["target_id"],
        edge_type=d["edge_type"],
        created_at=d["created_at"],
    )


class Store:
    def __init__(self, db_path: str, events_path: str):
        """初始化 Store，连接 SQLite + events.jsonl 路径。"""
        self._conn = init_db(db_path)
        self._conn.row_factory = None  # ensure tuple rows
        self._events_path = events_path
        self._in_transaction: bool = False

    # ---- internal helpers ----

    def _node_columns(self) -> List[str]:
        info = self._conn.execute("PRAGMA table_info(nodes)").fetchall()
        return [row[1] for row in info]

    def _edge_columns(self) -> List[str]:
        info = self._conn.execute("PRAGMA table_info(edges)").fetchall()
        return [row[1] for row in info]

    # --- Node CRUD ---

    def create_node(self, node: Node) -> Node:
        """插入新节点。自动生成 id/timestamps。原子写入 DB + events。"""
        with self.transaction():
            return self._create_node_inner(node)

    def _create_node_inner(self, node: Node) -> Node:
        """Internal: insert node, auto-add parent edge, write event."""
        now = _now_iso()

        # Generate ID with collision retry
        if not node.id:
            for _ in range(10):
                candidate = _generate_id(node.node_type)
                existing = self._conn.execute(
                    "SELECT 1 FROM nodes WHERE id=?", (candidate,)
                ).fetchone()
                if not existing:
                    node.id = candidate
                    break
            else:
                raise RuntimeError("Failed to generate unique node id after 10 retries")

        node.created_at = now
        node.updated_at = now
        node.status_changed_at = now

        tags_json = json.dumps(node.tags) if node.tags else "[]"

        self._conn.execute(
            """INSERT INTO nodes (
                id, title, status, node_type, is_root, parent_id,
                summary, why, next_step, owner, deadline, is_persistent,
                created_at, updated_at, status_changed_at, archived_at,
                source, source_id, source_url, source_synced_at, source_deleted,
                needs_compression, compression_in_progress, no_llm_compression,
                tags
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                node.id, node.title, node.status, node.node_type,
                int(node.is_root), node.parent_id,
                node.summary, node.why, node.next_step, node.owner,
                node.deadline, int(node.is_persistent),
                node.created_at, node.updated_at, node.status_changed_at,
                node.archived_at,
                node.source, node.source_id, node.source_url,
                node.source_synced_at, int(node.source_deleted),
                int(node.needs_compression), int(node.compression_in_progress),
                int(node.no_llm_compression),
                tags_json,
            ),
        )

        # Auto-add parent edge if parent_id is set (child -> parent convention)
        if node.parent_id:
            self._conn.execute(
                "INSERT OR IGNORE INTO edges (source_id, target_id, edge_type, created_at) VALUES (?,?,?,?)",
                (node.id, node.parent_id, "parent", now),
            )

        self.write_event({
            "type": "node_created",
            "tool_name": "create_node",
            "event_type": "node_created",
            "node_id": node.id,
            "title": node.title,
            "node_type": node.node_type,
            "timestamp": now,
        })

        return node

    def get_node(self, node_id: str) -> Optional[Node]:
        """按 id 查询单个节点。"""
        cols = self._node_columns()
        row = self._conn.execute(
            "SELECT * FROM nodes WHERE id=?", (node_id,)
        ).fetchone()
        if row is None:
            return None
        return _row_to_node(row, cols)

    def update_node(self, node_id: str, fields: dict) -> Node:
        """更新节点指定字段。自动更新 updated_at。原子写入 DB + events。"""
        with self.transaction():
            return self._update_node_inner(node_id, fields)

    def _update_node_inner(self, node_id: str, fields: dict) -> Node:
        """Internal: update node fields and write event."""
        now = _now_iso()
        fields["updated_at"] = now

        # Serialize tags if present
        if "tags" in fields and isinstance(fields["tags"], list):
            fields["tags"] = json.dumps(fields["tags"])

        # Convert booleans to int for SQLite
        bool_fields = {
            "is_root", "is_persistent", "source_deleted",
            "needs_compression", "compression_in_progress", "no_llm_compression",
        }
        for k in bool_fields:
            if k in fields and isinstance(fields[k], bool):
                fields[k] = int(fields[k])

        set_clause = ", ".join(f"{k}=?" for k in fields)
        values = list(fields.values()) + [node_id]

        self._conn.execute(
            f"UPDATE nodes SET {set_clause} WHERE id=?", values
        )

        self.write_event({
            "type": "node_updated",
            "tool_name": "update_node",
            "event_type": "node_updated",
            "node_id": node_id,
            "fields": list(fields.keys()),
            "timestamp": now,
        })

        node = self.get_node(node_id)
        if node is None:
            raise ValueError(f"Node {node_id} not found after update")
        return node

    def list_nodes(
        self,
        filters: Optional[Dict] = None,
        order_by: str = "updated_at",
        limit: int = 50,
        offset: int = 0,
    ) -> List[Node]:
        """条件查询节点列表。"""
        cols = self._node_columns()
        where_parts: List[str] = []
        params: List = []

        if filters:
            for key, val in filters.items():
                if key == "archived":
                    if val:
                        where_parts.append("archived_at IS NOT NULL")
                    else:
                        where_parts.append("archived_at IS NULL")
                elif key == "is_root":
                    where_parts.append("is_root=?")
                    params.append(int(val))
                elif key in ("status", "node_type", "parent_id", "source"):
                    where_parts.append(f"{key}=?")
                    params.append(val)

        where_sql = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""

        # Whitelist order_by to prevent injection
        allowed_order = {"updated_at", "created_at", "title", "status"}
        if order_by not in allowed_order:
            order_by = "updated_at"

        sql = f"SELECT * FROM nodes{where_sql} ORDER BY {order_by} DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = self._conn.execute(sql, params).fetchall()
        return [_row_to_node(r, cols) for r in rows]

    # --- Edge CRUD ---

    def add_edge(self, edge: Edge) -> Edge:
        """添加边。原子写入 DB + events。"""
        with self.transaction():
            return self._add_edge_inner(edge)

    def _add_edge_inner(self, edge: Edge) -> Edge:
        """Internal: insert edge and write event."""
        now = _now_iso()
        if not edge.created_at:
            edge.created_at = now

        self._conn.execute(
            "INSERT OR IGNORE INTO edges (source_id, target_id, edge_type, created_at) VALUES (?,?,?,?)",
            (edge.source_id, edge.target_id, edge.edge_type, edge.created_at),
        )

        self.write_event({
            "type": "edge_added",
            "tool_name": "add_edge",
            "event_type": "edge_added",
            "source_id": edge.source_id,
            "target_id": edge.target_id,
            "edge_type": edge.edge_type,
            "timestamp": now,
        })

        return edge

    def remove_edge(self, source_id: str, target_id: str, edge_type: str) -> bool:
        """删除边。返回是否删除成功。"""
        cursor = self._conn.execute(
            "DELETE FROM edges WHERE source_id=? AND target_id=? AND edge_type=?",
            (source_id, target_id, edge_type),
        )
        return cursor.rowcount > 0

    def get_edges(
        self,
        node_id: str,
        edge_type: Optional[str] = None,
        direction: str = "outgoing",
    ) -> List[Edge]:
        """查询节点关联的边。direction: outgoing|incoming|both。"""
        cols = self._edge_columns()
        parts: List[str] = []
        params: List = []

        if direction == "outgoing":
            parts.append("source_id=?")
            params.append(node_id)
        elif direction == "incoming":
            parts.append("target_id=?")
            params.append(node_id)
        else:  # both
            parts.append("(source_id=? OR target_id=?)")
            params.extend([node_id, node_id])

        if edge_type is not None:
            parts.append("edge_type=?")
            params.append(edge_type)

        sql = "SELECT * FROM edges WHERE " + " AND ".join(parts)
        rows = self._conn.execute(sql, params).fetchall()
        return [_row_to_edge(r, cols) for r in rows]

    # --- Graph Queries ---

    def get_children_all(self, node_id: str) -> List[Node]:
        """获取全部子节点（含已归档），用于 rollup 计算。"""
        cols = self._node_columns()
        sql = "SELECT * FROM nodes WHERE parent_id=?"
        rows = self._conn.execute(sql, (node_id,)).fetchall()
        return [_row_to_node(r, cols) for r in rows]

    def get_children(self, node_id: str, include_archived: bool = False) -> List[Node]:
        """获取直接子节点。"""
        cols = self._node_columns()
        if include_archived:
            sql = "SELECT * FROM nodes WHERE parent_id=?"
            rows = self._conn.execute(sql, (node_id,)).fetchall()
        else:
            sql = "SELECT * FROM nodes WHERE parent_id=? AND archived_at IS NULL"
            rows = self._conn.execute(sql, (node_id,)).fetchall()
        return [_row_to_node(r, cols) for r in rows]

    def get_parent(self, node_id: str) -> Optional[Node]:
        """获取父节点。"""
        node = self.get_node(node_id)
        if node is None or node.parent_id is None:
            return None
        return self.get_node(node.parent_id)

    def get_dependencies(self, node_id: str) -> List[Node]:
        """获取 depends_on 目标节点列表。"""
        cols = self._node_columns()
        sql = """
            SELECT n.* FROM nodes n
            JOIN edges e ON n.id = e.target_id
            WHERE e.source_id=? AND e.edge_type='depends_on'
        """
        rows = self._conn.execute(sql, (node_id,)).fetchall()
        return [_row_to_node(r, cols) for r in rows]

    def get_dependents(self, node_id: str) -> List[Node]:
        """获取依赖本节点的节点列表（反向）。"""
        cols = self._node_columns()
        sql = """
            SELECT n.* FROM nodes n
            JOIN edges e ON n.id = e.source_id
            WHERE e.target_id=? AND e.edge_type='depends_on'
        """
        rows = self._conn.execute(sql, (node_id,)).fetchall()
        return [_row_to_node(r, cols) for r in rows]

    def get_siblings(self, node_id: str) -> List[Node]:
        """获取同级节点（同 parent）。"""
        node = self.get_node(node_id)
        if node is None or node.parent_id is None:
            return []
        children = self.get_children(node.parent_id, include_archived=False)
        return [c for c in children if c.id != node_id]

    def get_all_edges(self) -> List[Edge]:
        """获取全部边，用于 DAG 检测。"""
        cols = self._edge_columns()
        rows = self._conn.execute("SELECT * FROM edges").fetchall()
        return [_row_to_edge(r, cols) for r in rows]

    def get_ancestors(self, node_id: str) -> List[str]:
        """获取所有祖先节点 id（递归向上，WITH RECURSIVE CTE）。"""
        sql = """
            WITH RECURSIVE ancestors(id) AS (
                SELECT parent_id FROM nodes WHERE id=?
                UNION
                SELECT n.parent_id FROM nodes n
                JOIN ancestors a ON n.id = a.id
                WHERE n.parent_id IS NOT NULL
            )
            SELECT id FROM ancestors WHERE id IS NOT NULL
        """
        rows = self._conn.execute(sql, (node_id,)).fetchall()
        return [r[0] for r in rows]

    def get_descendants(self, node_id: str) -> List[str]:
        """获取所有后代节点 id（递归向下，WITH RECURSIVE CTE）。"""
        sql = """
            WITH RECURSIVE descendants(id) AS (
                SELECT id FROM nodes WHERE parent_id=?
                UNION
                SELECT n.id FROM nodes n
                JOIN descendants d ON n.parent_id = d.id
            )
            SELECT id FROM descendants
        """
        rows = self._conn.execute(sql, (node_id,)).fetchall()
        return [r[0] for r in rows]

    # --- Session State ---

    def get_session(self, key: str) -> Optional[dict]:
        """读取 session_state 中的 JSON 值。"""
        row = self._conn.execute(
            "SELECT value FROM session_state WHERE key=?", (key,)
        ).fetchone()
        if row is None:
            return None
        return json.loads(row[0])

    def set_session(self, key: str, value: dict) -> None:
        """写入 session_state。"""
        now = _now_iso()
        self._conn.execute(
            "INSERT OR REPLACE INTO session_state (key, value, updated_at) VALUES (?,?,?)",
            (key, json.dumps(value), now),
        )

    # --- Transaction (Context Manager) ---

    @contextmanager
    def transaction(self) -> Generator[None, None, None]:
        """事务上下文管理器。支持嵌套（re-entrant）：内层不开新事务。"""
        if self._in_transaction:
            # Already inside a transaction — just yield without nesting
            yield
            return
        self._in_transaction = True
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            yield
            self._conn.commit()
        except BaseException:
            self._conn.rollback()
            raise
        finally:
            self._in_transaction = False

    # --- Audit Outbox ---

    def write_event(self, event: dict) -> None:
        """写入审计事件到 audit_outbox 表（SQLite 内）。"""
        now = _now_iso()
        self._conn.execute(
            "INSERT INTO audit_outbox (event_json, created_at, flushed) VALUES (?,?,?)",
            (json.dumps(event), now, 0),
        )

    def flush_events(self) -> int:
        """将 audit_outbox 中未 flush 的事件写入 events.jsonl。返回 flush 的事件数。"""
        rows = self._conn.execute(
            "SELECT id, event_json FROM audit_outbox WHERE flushed=0 ORDER BY id"
        ).fetchall()

        if not rows:
            return 0

        # Ensure directory exists
        events_dir = os.path.dirname(self._events_path)
        if events_dir:
            os.makedirs(events_dir, exist_ok=True)

        with open(self._events_path, "a") as f:
            for row_id, event_json in rows:
                f.write(event_json + "\n")

        ids = [r[0] for r in rows]
        placeholders = ",".join("?" * len(ids))
        self._conn.execute(
            f"UPDATE audit_outbox SET flushed=1 WHERE id IN ({placeholders})", ids
        )
        self._conn.commit()

        return len(rows)
