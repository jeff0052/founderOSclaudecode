"""Tests for fpms.spine.narrative — append-only narrative read/write."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timedelta, timezone
from typing import List

import pytest

from fpms.spine.narrative import (
    append_narrative,
    read_compressed,
    read_narrative,
    write_compressed,
    write_repair_event,
)


@pytest.fixture
def narr_dir(tmp_path):
    """Return a temporary narratives directory path (not yet created)."""
    return str(tmp_path / "narratives")


# ── append_narrative format ──────────────────────────────────────────────


class TestAppendNarrative:
    def test_basic_format(self, narr_dir):
        ok = append_narrative(narr_dir, "node-1", "2025-01-15T10:00:00Z", "created", "Hello world")
        assert ok is True
        filepath = os.path.join(narr_dir, "node-1.md")
        content = open(filepath).read()
        assert "## 2025-01-15T10:00:00Z [created]" in content
        assert "Hello world" in content

    def test_mentions_line(self, narr_dir):
        append_narrative(
            narr_dir, "node-2", "2025-01-15T10:00:00Z", "linked",
            "Linked nodes", mentions=["alpha", "beta"],
        )
        content = open(os.path.join(narr_dir, "node-2.md")).read()
        assert "Mentions: alpha, beta" in content

    def test_append_only_no_overwrite(self, narr_dir):
        append_narrative(narr_dir, "node-a", "2025-01-01T00:00:00Z", "init", "First entry")
        append_narrative(narr_dir, "node-a", "2025-01-02T00:00:00Z", "update", "Second entry")
        content = open(os.path.join(narr_dir, "node-a.md")).read()
        assert "First entry" in content
        assert "Second entry" in content
        # Both headers present
        assert content.count("## ") == 2

    def test_auto_create_directory(self, tmp_path):
        deep_dir = str(tmp_path / "a" / "b" / "c" / "narratives")
        ok = append_narrative(deep_dir, "deep", "2025-01-01T00:00:00Z", "test", "Deep path")
        assert ok is True
        assert os.path.isfile(os.path.join(deep_dir, "deep.md"))

    def test_returns_false_on_failure(self):
        # Use a path that cannot be created (null byte in path)
        ok = append_narrative("/dev/null/impossible\x00dir", "x", "ts", "t", "c")
        assert ok is False

    def test_never_raises(self):
        """append_narrative must return False, never raise."""
        result = append_narrative("/dev/null/impossible\x00dir", "x", "ts", "t", "c")
        assert isinstance(result, bool)


# ── read_narrative ───────────────────────────────────────────────────────


class TestReadNarrative:
    def test_empty_when_missing(self, narr_dir):
        result = read_narrative(narr_dir, "nonexistent")
        assert result == ""

    def test_last_n_entries(self, narr_dir):
        for i in range(5):
            append_narrative(
                narr_dir, "node-r", f"2025-01-{10+i:02d}T00:00:00Z",
                "update", f"Entry {i}",
            )
        result = read_narrative(narr_dir, "node-r", last_n_entries=2)
        assert "Entry 3" in result
        assert "Entry 4" in result
        assert "Entry 0" not in result
        assert "Entry 1" not in result
        assert "Entry 2" not in result

    def test_since_days(self, narr_dir):
        now = datetime.now(timezone.utc)
        old_ts = (now - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
        recent_ts = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

        append_narrative(narr_dir, "node-s", old_ts, "old", "Old event")
        append_narrative(narr_dir, "node-s", recent_ts, "new", "Recent event")

        result = read_narrative(narr_dir, "node-s", since_days=7)
        assert "Recent event" in result
        assert "Old event" not in result

    def test_both_filters(self, narr_dir):
        now = datetime.now(timezone.utc)
        # Create 5 recent entries
        for i in range(5):
            ts = (now - timedelta(hours=5 - i)).strftime("%Y-%m-%dT%H:%M:%SZ")
            append_narrative(narr_dir, "node-b", ts, "update", f"Recent {i}")
        # Create 1 old entry at the beginning (but it was appended first, so it is first)
        # Actually, let's rebuild: old first, then recent
        os.remove(os.path.join(narr_dir, "node-b.md"))
        old_ts = (now - timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
        append_narrative(narr_dir, "node-b", old_ts, "old", "Old one")
        for i in range(5):
            ts = (now - timedelta(hours=5 - i)).strftime("%Y-%m-%dT%H:%M:%SZ")
            append_narrative(narr_dir, "node-b", ts, "update", f"Recent {i}")

        # since_days=7 filters out old; last_n_entries=2 takes last 2 of remaining
        result = read_narrative(narr_dir, "node-b", last_n_entries=2, since_days=7)
        assert "Old one" not in result
        assert "Recent 3" in result
        assert "Recent 4" in result
        assert "Recent 0" not in result


# ── compressed round-trip ────────────────────────────────────────────────


class TestCompressed:
    def test_read_missing_returns_none(self, narr_dir):
        assert read_compressed(narr_dir, "ghost") is None

    def test_write_read_roundtrip(self, narr_dir):
        write_compressed(narr_dir, "node-c", "Summary of events")
        result = read_compressed(narr_dir, "node-c")
        assert result == "Summary of events"

    def test_overwrite(self, narr_dir):
        write_compressed(narr_dir, "node-c", "Version 1")
        write_compressed(narr_dir, "node-c", "Version 2")
        assert read_compressed(narr_dir, "node-c") == "Version 2"


# ── write_repair_event ───────────────────────────────────────────────────


class TestRepairEvent:
    def test_writes_jsonl(self, narr_dir):
        event = {"node_id": "node-x", "event_type": "created", "content": "test"}
        write_repair_event(narr_dir, "node-x", event, "disk full")
        filepath = os.path.join(narr_dir, "_repair", "node-x.repair.jsonl")
        assert os.path.isfile(filepath)
        lines = open(filepath).readlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["error"] == "disk full"
        assert record["node_id"] == "node-x"
        assert "repair_timestamp" in record

    def test_appends_multiple(self, narr_dir):
        event = {"node_id": "node-y"}
        write_repair_event(narr_dir, "node-y", event, "err1")
        write_repair_event(narr_dir, "node-y", event, "err2")
        filepath = os.path.join(narr_dir, "_repair", "node-y.repair.jsonl")
        lines = open(filepath).readlines()
        assert len(lines) == 2


# ── concurrent append (file lock) ───────────────────────────────────────


class TestConcurrentAppend:
    def test_no_data_loss(self, narr_dir):
        """Multiple threads appending concurrently must not lose entries."""
        n_threads = 10
        n_per_thread = 20
        results: List[bool] = []
        lock = threading.Lock()

        def worker(thread_id: int):
            for i in range(n_per_thread):
                ok = append_narrative(
                    narr_dir, "concurrent",
                    f"2025-01-01T{thread_id:02d}:{i:02d}:00Z",
                    "update",
                    f"Thread-{thread_id}-Entry-{i}",
                )
                with lock:
                    results.append(ok)

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All writes succeeded
        assert all(results)
        assert len(results) == n_threads * n_per_thread

        # All entries are present in the file
        content = open(os.path.join(narr_dir, "concurrent.md")).read()
        entry_count = content.count("## ")
        assert entry_count == n_threads * n_per_thread
