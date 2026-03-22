"""Write-back tests — FPMS status changes sync back to GitHub/Notion."""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from fpms.spine.adapters.github_adapter import GitHubAdapter
from fpms.spine.adapters.notion_adapter import NotionAdapter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_response(status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    return resp


# ---------------------------------------------------------------------------
# GitHub write_status
# ---------------------------------------------------------------------------


@patch("fpms.spine.adapters.github_adapter.httpx.patch")
def test_github_write_status_done_closes_issue(mock_patch):
    mock_patch.return_value = _mock_response(200)
    adapter = GitHubAdapter(token="test", default_repo="owner/repo")

    adapter.write_status("owner/repo#1", "done")

    mock_patch.assert_called_once()
    call_kwargs = mock_patch.call_args
    assert call_kwargs.kwargs["json"]["state"] == "closed"


@patch("fpms.spine.adapters.github_adapter.httpx.patch")
def test_github_write_status_active_reopens_issue(mock_patch):
    mock_patch.return_value = _mock_response(200)
    adapter = GitHubAdapter(token="test", default_repo="owner/repo")

    adapter.write_status("owner/repo#1", "active")

    call_kwargs = mock_patch.call_args
    assert call_kwargs.kwargs["json"]["state"] == "open"


@patch("fpms.spine.adapters.github_adapter.httpx.patch")
def test_github_write_status_timeout_raises_connection_error(mock_patch):
    import httpx
    mock_patch.side_effect = httpx.TimeoutException("timeout")
    adapter = GitHubAdapter(token="test", default_repo="owner/repo")

    with pytest.raises(ConnectionError):
        adapter.write_status("owner/repo#1", "done")


# ---------------------------------------------------------------------------
# GitHub write_comment
# ---------------------------------------------------------------------------


@patch("fpms.spine.adapters.github_adapter.httpx.post")
def test_github_write_comment(mock_post):
    mock_post.return_value = _mock_response(201)
    adapter = GitHubAdapter(token="test", default_repo="owner/repo")

    adapter.write_comment("owner/repo#1", "Task completed via FocalPoint")

    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args
    assert call_kwargs.kwargs["json"]["body"] == "Task completed via FocalPoint"


# ---------------------------------------------------------------------------
# GitHub reverse status mapping
# ---------------------------------------------------------------------------


def test_github_reverse_map_status():
    adapter = GitHubAdapter(token="test")
    assert adapter._reverse_map_status("done") == "closed"
    assert adapter._reverse_map_status("active") == "open"
    assert adapter._reverse_map_status("inbox") == "open"
    assert adapter._reverse_map_status("waiting") == "open"
    assert adapter._reverse_map_status("dropped") == "closed"


# ---------------------------------------------------------------------------
# Notion write_status
# ---------------------------------------------------------------------------


@patch("fpms.spine.adapters.notion_adapter.httpx.patch")
def test_notion_write_status_done(mock_patch):
    mock_patch.return_value = _mock_response(200)
    adapter = NotionAdapter(token="test", default_database_id="db-123")

    adapter.write_status("page-abc", "done")

    mock_patch.assert_called_once()
    call_kwargs = mock_patch.call_args
    props = call_kwargs.kwargs["json"]["properties"]
    assert props["Status"]["status"]["name"] == "Done"


@patch("fpms.spine.adapters.notion_adapter.httpx.patch")
def test_notion_write_status_active(mock_patch):
    mock_patch.return_value = _mock_response(200)
    adapter = NotionAdapter(token="test")

    adapter.write_status("page-abc", "active")

    call_kwargs = mock_patch.call_args
    props = call_kwargs.kwargs["json"]["properties"]
    assert props["Status"]["status"]["name"] == "In progress"


@patch("fpms.spine.adapters.notion_adapter.httpx.patch")
def test_notion_write_status_timeout_raises_connection_error(mock_patch):
    import httpx
    mock_patch.side_effect = httpx.TimeoutException("timeout")
    adapter = NotionAdapter(token="test")

    with pytest.raises(ConnectionError):
        adapter.write_status("page-abc", "done")


# ---------------------------------------------------------------------------
# Notion write_comment
# ---------------------------------------------------------------------------


@patch("fpms.spine.adapters.notion_adapter.httpx.patch")
def test_notion_write_comment(mock_patch):
    mock_patch.return_value = _mock_response(200)
    adapter = NotionAdapter(token="test")

    adapter.write_comment("page-abc", "Status updated via FocalPoint")

    mock_patch.assert_called_once()
    call_kwargs = mock_patch.call_args
    children = call_kwargs.kwargs["json"]["children"]
    assert len(children) == 1
    text = children[0]["paragraph"]["rich_text"][0]["text"]["content"]
    assert text == "Status updated via FocalPoint"


# ---------------------------------------------------------------------------
# Notion reverse status mapping
# ---------------------------------------------------------------------------


def test_notion_reverse_map_status():
    adapter = NotionAdapter(token="test")
    assert adapter._reverse_map_status("done") == "Done"
    assert adapter._reverse_map_status("active") == "In progress"
    assert adapter._reverse_map_status("inbox") == "Not started"


# ---------------------------------------------------------------------------
# Write-back hook — offline degradation
# ---------------------------------------------------------------------------


def test_writeback_failure_does_not_block_update(tmp_path):
    """If write_status fails, update_status should still succeed."""
    from fpms.spine import SpineEngine
    from fpms.spine.adapters.registry import AdapterRegistry
    from fpms.spine.adapters.base import BaseAdapter
    from fpms.spine.models import NodeSnapshot

    class FailingAdapter(BaseAdapter):
        @property
        def source_name(self):
            return "failing"

        def sync_node(self, source_id):
            return NodeSnapshot(
                source="failing", source_id=source_id,
                title="Test", status="active",
            )

        def list_updates(self, since=None):
            return []

        def write_status(self, source_id, new_status):
            raise ConnectionError("Network down")

    engine = SpineEngine(
        db_path=str(tmp_path / "test.db"),
        events_path=str(tmp_path / "events.jsonl"),
        narratives_dir=str(tmp_path / "narratives"),
    )

    registry = AdapterRegistry()
    registry.register(FailingAdapter())
    engine.set_adapter_registry(registry)

    # Create external node
    result = engine.execute_tool("create_node", {
        "title": "External Task",
        "summary": "Test external task",
        "is_root": True,
        "source": "failing",
        "source_id": "ext-001",
    })
    node_id = result.data["id"]

    # Activate it (inbox → active)
    result = engine.execute_tool("update_status", {
        "node_id": node_id, "new_status": "active",
    })
    assert result.success is True

    # Mark done (active → done) — write_status will fail but update should succeed
    result = engine.execute_tool("update_status", {
        "node_id": node_id, "new_status": "done",
    })
    assert result.success is True

    # Verify status actually changed in store
    node = engine.store.get_node(node_id)
    assert node.status == "done"


# ---------------------------------------------------------------------------
# Internal source should NOT trigger write-back
# ---------------------------------------------------------------------------


def test_internal_source_no_writeback(tmp_path):
    """Nodes with source='internal' should not trigger write-back."""
    from fpms.spine import SpineEngine

    engine = SpineEngine(
        db_path=str(tmp_path / "test.db"),
        events_path=str(tmp_path / "events.jsonl"),
        narratives_dir=str(tmp_path / "narratives"),
    )

    result = engine.execute_tool("create_node", {
        "title": "Internal Task", "summary": "Test internal task", "is_root": True, "source": "internal",
    })
    node_id = result.data["id"]

    result = engine.execute_tool("update_status", {
        "node_id": node_id, "new_status": "active",
    })
    assert result.success is True

    # active → done: should succeed without any adapter
    result = engine.execute_tool("update_status", {
        "node_id": node_id, "new_status": "done",
    })
    assert result.success is True
