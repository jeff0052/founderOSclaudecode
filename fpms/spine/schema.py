"""数据库初始化 — SQLite schema, 建表, WAL 模式。"""

from __future__ import annotations

import sqlite3


def init_db(db_path: str) -> sqlite3.Connection:
    """创建/打开 SQLite 数据库，建表，启用 WAL 模式。
    如果表已存在则跳过。返回连接对象。"""
    raise NotImplementedError


def get_connection(db_path: str) -> sqlite3.Connection:
    """获取已初始化的数据库连接。"""
    raise NotImplementedError
