"""Invariant tests 共享 fixtures。

这些 fixtures 提供完整的 Store + Validator + Narrative 环境，
用于铁律测试。每个测试用例获得独立的临时数据库。
"""

from __future__ import annotations

import os
import tempfile
from typing import Optional

import pytest

from fpms.spine.models import Edge, Node
from fpms.spine.schema import init_db
from fpms.spine.store import Store


@pytest.fixture
def tmp_dir(tmp_path):
    """提供临时目录，包含 narratives 子目录。"""
    narratives_dir = tmp_path / "narratives"
    narratives_dir.mkdir()
    return tmp_path


@pytest.fixture
def db_path(tmp_dir):
    """临时 SQLite 数据库路径。"""
    return str(tmp_dir / "test.db")


@pytest.fixture
def events_path(tmp_dir):
    """临时 events.jsonl 路径。"""
    return str(tmp_dir / "events.jsonl")


@pytest.fixture
def narratives_dir(tmp_dir):
    """临时 narratives 目录路径。"""
    return str(tmp_dir / "narratives")


@pytest.fixture
def db(db_path):
    """已初始化的 SQLite 连接（WAL 模式，所有表已建好）。"""
    conn = init_db(db_path)
    yield conn
    conn.close()


@pytest.fixture
def store(db_path, events_path):
    """完整的 Store 实例。"""
    return Store(db_path=db_path, events_path=events_path)


def make_node(
    node_id: str = "task-0001",
    title: str = "Test Node",
    status: str = "inbox",
    node_type: str = "task",
    is_root: bool = False,
    parent_id: Optional[str] = None,
    summary: Optional[str] = None,
    **kwargs,
) -> Node:
    """快速创建 Node 对象的工厂函数。"""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    return Node(
        id=node_id,
        title=title,
        status=status,
        node_type=node_type,
        is_root=is_root,
        parent_id=parent_id,
        summary=summary,
        created_at=now,
        updated_at=now,
        status_changed_at=now,
        **kwargs,
    )


def make_edge(
    source_id: str,
    target_id: str,
    edge_type: str = "parent",
) -> Edge:
    """快速创建 Edge 对象的工厂函数。"""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    return Edge(
        source_id=source_id,
        target_id=target_id,
        edge_type=edge_type,
        created_at=now,
    )
