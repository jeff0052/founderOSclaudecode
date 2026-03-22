"""NotionAdapter unit tests — mock httpx, no real Notion API needed."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest

from fpms.spine.adapters.notion_adapter import NotionAdapter
from fpms.spine.models import NodeSnapshot, SourceEvent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_PAGE_RESPONSE = {
    "id": "abc12345-1234-1234-1234-123456789abc",
    "url": "https://www.notion.so/My-Task-abc123",
    "last_edited_time": "2026-03-22T10:00:00.000Z",
    "properties": {
        "Name": {
            "type": "title",
            "title": [{"plain_text": "Implement Notion sync"}],
        },
        "Status": {
            "type": "status",
            "status": {"name": "In progress"},
        },
        "Assignee": {
            "type": "people",
            "people": [{"name": "Jeff"}],
        },
    },
}

SAMPLE_PAGE_NO_STATUS = {
    "id": "def45678-1234-1234-1234-123456789def",
    "url": "https://www.notion.so/No-Status-def456",
    "last_edited_time": "2026-03-21T08:00:00.000Z",
    "properties": {
        "Title": {
            "type": "title",
            "title": [{"plain_text": "Task without status"}],
        },
    },
}

SAMPLE_DB_QUERY_RESPONSE = {
    "results": [
        {
            "id": "page-001",
            "url": "https://www.notion.so/page-001",
            "last_edited_time": "2026-03-22T12:00:00.000Z",
            "properties": {
                "Name": {
                    "type": "title",
                    "title": [{"plain_text": "Updated task"}],
                },
                "Status": {
                    "type": "status",
                    "status": {"name": "Done"},
                },
            },
        },
        {
            "id": "page-002",
            "url": "https://www.notion.so/page-002",
            "last_edited_time": "2026-03-22T11:00:00.000Z",
            "properties": {
                "Name": {
                    "type": "title",
                    "title": [{"plain_text": "Another task"}],
                },
                "Status": {
                    "type": "status",
                    "status": {"name": "In progress"},
                },
            },
        },
    ],
    "has_more": False,
}


def _mock_response(status_code: int, json_data: dict | None = None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    return resp


@pytest.fixture
def adapter():
    return NotionAdapter(
        token="ntn_test_token",
        default_database_id="db-123",
    )


# ---------------------------------------------------------------------------
# source_name
# ---------------------------------------------------------------------------


def test_source_name(adapter):
    assert adapter.source_name == "notion"


# ---------------------------------------------------------------------------
# sync_node — success
# ---------------------------------------------------------------------------


@patch("fpms.spine.adapters.notion_adapter.httpx.get")
def test_sync_node_success(mock_get, adapter):
    mock_get.return_value = _mock_response(200, SAMPLE_PAGE_RESPONSE)

    snap = adapter.sync_node("abc12345-1234-1234-1234-123456789abc")

    assert isinstance(snap, NodeSnapshot)
    assert snap.source == "notion"
    assert snap.source_id == "abc12345-1234-1234-1234-123456789abc"
    assert snap.title == "Implement Notion sync"
    assert snap.status == "active"  # "In progress" maps to "active"
    assert snap.assignee == "Jeff"
    assert snap.source_url == "https://www.notion.so/My-Task-abc123"
    assert snap.updated_at == "2026-03-22T10:00:00.000Z"


@patch("fpms.spine.adapters.notion_adapter.httpx.get")
def test_sync_node_no_status(mock_get, adapter):
    """Page without Status property should default to 'inbox'."""
    mock_get.return_value = _mock_response(200, SAMPLE_PAGE_NO_STATUS)

    snap = adapter.sync_node("def45678-1234-1234-1234-123456789def")

    assert snap.title == "Task without status"
    assert snap.status == "inbox"
    assert snap.assignee is None


# ---------------------------------------------------------------------------
# sync_node — error cases
# ---------------------------------------------------------------------------


@patch("fpms.spine.adapters.notion_adapter.httpx.get")
def test_sync_node_404_returns_none(mock_get, adapter):
    mock_get.return_value = _mock_response(404)
    assert adapter.sync_node("nonexistent-page-id") is None


@patch("fpms.spine.adapters.notion_adapter.httpx.get")
def test_sync_node_401_raises_permission_error(mock_get, adapter):
    mock_get.return_value = _mock_response(401)
    with pytest.raises(PermissionError):
        adapter.sync_node("some-page-id")


@patch("fpms.spine.adapters.notion_adapter.httpx.get")
def test_sync_node_403_raises_permission_error(mock_get, adapter):
    mock_get.return_value = _mock_response(403)
    with pytest.raises(PermissionError):
        adapter.sync_node("some-page-id")


@patch("fpms.spine.adapters.notion_adapter.httpx.get")
def test_sync_node_timeout_raises_connection_error(mock_get, adapter):
    import httpx
    mock_get.side_effect = httpx.TimeoutException("timeout")
    with pytest.raises(ConnectionError):
        adapter.sync_node("some-page-id")


# ---------------------------------------------------------------------------
# map_status
# ---------------------------------------------------------------------------


def test_map_status_default_mapping(adapter):
    assert adapter.map_status("Not started") == "inbox"
    assert adapter.map_status("In progress") == "active"
    assert adapter.map_status("Done") == "done"


def test_map_status_unknown_returns_inbox(adapter):
    assert adapter.map_status("Something Unknown") == "inbox"


def test_map_status_custom_mapping():
    custom = NotionAdapter(
        token="test",
        status_map={"Blocked": "waiting", "Cancelled": "dropped"},
    )
    assert custom.map_status("Blocked") == "waiting"
    assert custom.map_status("Cancelled") == "dropped"
    assert custom.map_status("Unknown") == "inbox"


# ---------------------------------------------------------------------------
# list_updates
# ---------------------------------------------------------------------------


@patch("fpms.spine.adapters.notion_adapter.httpx.post")
def test_list_updates_returns_events(mock_post, adapter):
    mock_post.return_value = _mock_response(200, SAMPLE_DB_QUERY_RESPONSE)

    events = adapter.list_updates()

    assert len(events) == 2
    assert all(isinstance(e, SourceEvent) for e in events)
    assert events[0].source == "notion"
    assert events[0].event_type == "page_updated"
    # Sorted by timestamp ascending — page-002 (11:00) before page-001 (12:00)
    assert events[0].timestamp <= events[1].timestamp
    assert events[0].source_id == "page-002"
    assert events[1].source_id == "page-001"


@patch("fpms.spine.adapters.notion_adapter.httpx.post")
def test_list_updates_with_since_filter(mock_post, adapter):
    mock_post.return_value = _mock_response(200, SAMPLE_DB_QUERY_RESPONSE)

    since = datetime(2026, 3, 22, tzinfo=timezone.utc)
    events = adapter.list_updates(since=since)

    # Verify the API was called with a filter
    call_args = mock_post.call_args
    body = call_args.kwargs.get("json") or call_args[1].get("json", {})
    assert "filter" in body


def test_list_updates_no_database_id():
    """Without default_database_id, list_updates returns empty."""
    adapter = NotionAdapter(token="test")
    assert adapter.list_updates() == []


@patch("fpms.spine.adapters.notion_adapter.httpx.post")
def test_list_updates_timeout(mock_post, adapter):
    import httpx
    mock_post.side_effect = httpx.TimeoutException("timeout")
    with pytest.raises(ConnectionError):
        adapter.list_updates()


# ---------------------------------------------------------------------------
# source_id validation
# ---------------------------------------------------------------------------


def test_parse_source_id_valid_uuid(adapter):
    page_id = "abc12345-1234-1234-1234-123456789abc"
    assert adapter._parse_source_id(page_id) == page_id


def test_parse_source_id_no_dashes(adapter):
    """Notion sometimes returns IDs without dashes."""
    page_id = "abc1234512341234123412345678 9abc"
    # Should accept any non-empty string as Notion page IDs vary in format
    result = adapter._parse_source_id(page_id.strip())
    assert result  # Just check it returns something


def test_parse_source_id_empty_raises(adapter):
    with pytest.raises(ValueError):
        adapter._parse_source_id("")
