"""叙事文件管理 — Append-only MD 读写, 压缩摘要, repair event。"""

from __future__ import annotations


def append_narrative(
    narratives_dir: str,
    node_id: str,
    timestamp: str,
    event_type: str,
    content: str,
    mentions: list[str] | None = None,
) -> bool:
    """追加一条叙事到 narratives/{node_id}.md。
    格式: ## {timestamp} [{event_type}]\\n{content}
    返回是否写入成功。失败时不抛异常，返回 False。"""
    raise NotImplementedError


def read_narrative(
    narratives_dir: str,
    node_id: str,
    last_n_entries: int | None = None,
    since_days: int | None = None,
) -> str:
    """读取叙事内容。支持按条数或天数截取。"""
    raise NotImplementedError


def read_compressed(narratives_dir: str, node_id: str) -> str | None:
    """读取压缩摘要 {node_id}.compressed.md。不存在返回 None。"""
    raise NotImplementedError


def write_compressed(narratives_dir: str, node_id: str, content: str) -> None:
    """写入压缩摘要。"""
    raise NotImplementedError


def write_repair_event(
    narratives_dir: str, node_id: str, original_event: dict, error: str
) -> None:
    """写入修复事件记录。当 narrative 写入失败时调用。"""
    raise NotImplementedError
