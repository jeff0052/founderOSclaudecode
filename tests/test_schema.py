"""schema.py 测试 — 建表、CHECK 约束、WAL 模式。"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from fpms.spine.schema import init_db, get_connection


@pytest.fixture
def db(tmp_path):
    """每个测试获得独立的临时数据库。"""
    path = str(tmp_path / "test.db")
    conn = init_db(path)
    yield conn
    conn.close()


# ---- 建表成功 ----

def test_all_tables_created(db):
    """所有 6 张表都存在。"""
    rows = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    names = {r[0] for r in rows}
    expected = {"nodes", "edges", "session_state", "audit_outbox",
                "recent_commands", "narrative_index"}
    assert expected.issubset(names)


# ---- WAL 模式 ----

def test_wal_mode_enabled(db):
    """WAL 模式已启用。"""
    mode = db.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "wal"


# ---- nodes CHECK 约束 ----

def _insert_node(db, **overrides):
    """辅助: 插入一个最小 node 行。"""
    now = datetime.now(timezone.utc).isoformat()
    defaults = dict(
        id="n-001", title="T", status="inbox", node_type="task",
        is_root=0, parent_id=None, created_at=now, updated_at=now,
        status_changed_at=now, source="internal", source_deleted=0,
        needs_compression=0, compression_in_progress=0,
        no_llm_compression=0, tags="[]",
    )
    defaults.update(overrides)
    cols = ", ".join(defaults.keys())
    placeholders = ", ".join(["?"] * len(defaults))
    db.execute(f"INSERT INTO nodes ({cols}) VALUES ({placeholders})",
               list(defaults.values()))
    db.commit()


def test_status_check_rejects_invalid(db):
    """nodes status CHECK 约束拒绝非法值。"""
    with pytest.raises(sqlite3.IntegrityError):
        _insert_node(db, status="bogus")


def test_status_check_accepts_valid(db):
    """nodes status CHECK 约束接受合法值。"""
    for i, s in enumerate(("inbox", "active", "waiting", "done", "dropped")):
        _insert_node(db, id=f"n-{i}", status=s)


def test_node_type_check_rejects_invalid(db):
    """nodes node_type CHECK 约束拒绝非法值。"""
    with pytest.raises(sqlite3.IntegrityError):
        _insert_node(db, node_type="epic")


def test_xor_root_with_parent_rejected(db):
    """is_root=1 AND parent_id IS NOT NULL → 拒绝。"""
    _insert_node(db, id="parent-1")
    with pytest.raises(sqlite3.IntegrityError):
        _insert_node(db, id="child-bad", is_root=1, parent_id="parent-1")


def test_xor_root_without_parent_accepted(db):
    """is_root=1 AND parent_id IS NULL → 允许。"""
    _insert_node(db, id="root-ok", is_root=1, parent_id=None)


def test_non_root_with_parent_accepted(db):
    """is_root=0 AND parent_id IS NOT NULL → 允许。"""
    _insert_node(db, id="parent-2")
    _insert_node(db, id="child-ok", is_root=0, parent_id="parent-2")


# ---- audit_outbox 表结构 ----

def test_audit_outbox_structure(db):
    """audit_outbox 表存在且有正确的列。"""
    info = db.execute("PRAGMA table_info(audit_outbox)").fetchall()
    col_names = {row[1] for row in info}
    assert {"id", "event_json", "created_at", "flushed"} == col_names


def test_audit_outbox_autoincrement(db):
    """audit_outbox id 自增。"""
    now = datetime.now(timezone.utc).isoformat()
    db.execute("INSERT INTO audit_outbox (event_json, created_at, flushed) VALUES (?, ?, ?)",
               ('{"e":1}', now, 0))
    db.execute("INSERT INTO audit_outbox (event_json, created_at, flushed) VALUES (?, ?, ?)",
               ('{"e":2}', now, 0))
    db.commit()
    rows = db.execute("SELECT id FROM audit_outbox ORDER BY id").fetchall()
    assert rows[0][0] < rows[1][0]


# ---- recent_commands 表结构 ----

def test_recent_commands_structure(db):
    """recent_commands 表存在且有正确的列。"""
    info = db.execute("PRAGMA table_info(recent_commands)").fetchall()
    col_names = {row[1] for row in info}
    assert {"command_id", "tool_name", "result_json", "created_at", "expires_at"} == col_names


# ---- session_state 表结构 ----

def test_session_state_structure(db):
    """session_state 表存在且有正确的列。"""
    info = db.execute("PRAGMA table_info(session_state)").fetchall()
    col_names = {row[1] for row in info}
    assert {"key", "value", "updated_at"} == col_names


def test_session_state_upsert(db):
    """session_state 支持 REPLACE (主键冲突覆盖)。"""
    now = datetime.now(timezone.utc).isoformat()
    db.execute("INSERT OR REPLACE INTO session_state VALUES (?, ?, ?)",
               ("k1", "v1", now))
    db.execute("INSERT OR REPLACE INTO session_state VALUES (?, ?, ?)",
               ("k1", "v2", now))
    db.commit()
    val = db.execute("SELECT value FROM session_state WHERE key='k1'").fetchone()[0]
    assert val == "v2"


# ---- get_connection 幂等 ----

def test_get_connection_idempotent(tmp_path):
    """get_connection 多次调用不报错。"""
    path = str(tmp_path / "idem.db")
    c1 = get_connection(path)
    c2 = get_connection(path)
    # 两次都能查到表
    tables = c2.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    assert len(tables) >= 6
    c1.close()
    c2.close()
