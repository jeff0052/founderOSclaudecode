"""叙事文件管理 — Append-only MD 读写, 压缩摘要, repair event。"""

from __future__ import annotations

import fcntl
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional


def append_narrative(
    narratives_dir: str,
    node_id: str,
    timestamp: str,
    event_type: str,
    content: str,
    mentions: Optional[List[str]] = None,
) -> bool:
    """追加一条叙事到 narratives/{node_id}.md。
    格式: ## {timestamp} [{event_type}]\\n{content}
    返回是否写入成功。失败时不抛异常，返回 False。"""
    try:
        os.makedirs(narratives_dir, exist_ok=True)
        filepath = os.path.join(narratives_dir, f"{node_id}.md")

        block = f"## {timestamp} [{event_type}]\n{content}\n"
        if mentions:
            block += f"Mentions: {', '.join(mentions)}\n"
        block += "\n"

        with open(filepath, "a") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                f.write(block)
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        return True
    except Exception:
        return False


def read_narrative(
    narratives_dir: str,
    node_id: str,
    last_n_entries: Optional[int] = None,
    since_days: Optional[int] = None,
) -> str:
    """读取叙事内容。支持按条数或天数截取。"""
    filepath = os.path.join(narratives_dir, f"{node_id}.md")
    if not os.path.exists(filepath):
        return ""

    with open(filepath, "r") as f:
        raw = f.read()

    if not raw.strip():
        return ""

    # Split into entries by "## " header prefix
    parts = raw.split("\n## ")
    entries: List[str] = []
    for i, part in enumerate(parts):
        stripped = part.strip()
        if not stripped:
            continue
        if i == 0 and stripped.startswith("## "):
            # First chunk still has the leading "## "
            entries.append(stripped)
        elif i == 0:
            # First chunk without "## " — might be empty preamble
            if stripped:
                entries.append("## " + stripped)
        else:
            entries.append("## " + stripped)

    # Filter by since_days
    if since_days is not None:
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=since_days)
        filtered: List[str] = []
        for entry in entries:
            ts = _extract_timestamp(entry)
            if ts is not None and ts >= cutoff:
                filtered.append(entry)
        entries = filtered

    # Filter by last_n_entries
    if last_n_entries is not None and len(entries) > last_n_entries:
        entries = entries[-last_n_entries:]

    if not entries:
        return ""

    return "\n\n".join(entries) + "\n"


def _extract_timestamp(entry: str) -> Optional[datetime]:
    """Extract ISO timestamp from an entry header like '## 2025-01-15T10:00:00Z [...]'."""
    # Header format: ## {timestamp} [{event_type}]
    if not entry.startswith("## "):
        return None
    header_line = entry.split("\n", 1)[0]
    # Remove "## " prefix
    rest = header_line[3:]
    # Timestamp is everything before the first " ["
    bracket_idx = rest.find(" [")
    if bracket_idx == -1:
        return None
    ts_str = rest[:bracket_idx].strip()
    try:
        # Try ISO format with Z suffix
        ts_str_clean = ts_str.replace("Z", "+00:00")
        return datetime.fromisoformat(ts_str_clean)
    except (ValueError, AttributeError):
        return None


def read_compressed(narratives_dir: str, node_id: str) -> Optional[str]:
    """读取压缩摘要 {node_id}.compressed.md。不存在返回 None。"""
    filepath = os.path.join(narratives_dir, f"{node_id}.compressed.md")
    if not os.path.exists(filepath):
        return None
    with open(filepath, "r") as f:
        return f.read()


def write_compressed(narratives_dir: str, node_id: str, content: str) -> None:
    """写入压缩摘要。"""
    os.makedirs(narratives_dir, exist_ok=True)
    filepath = os.path.join(narratives_dir, f"{node_id}.compressed.md")
    with open(filepath, "w") as f:
        f.write(content)


def write_repair_event(
    narratives_dir: str, node_id: str, original_event: dict, error: str
) -> None:
    """写入修复事件记录。当 narrative 写入失败时调用。"""
    repair_dir = os.path.join(narratives_dir, "_repair")
    os.makedirs(repair_dir, exist_ok=True)
    filepath = os.path.join(repair_dir, f"{node_id}.repair.jsonl")
    record = {
        **original_event,
        "error": error,
        "repair_timestamp": datetime.now(timezone.utc).isoformat(),
    }
    with open(filepath, "a") as f:
        f.write(json.dumps(record) + "\n")
