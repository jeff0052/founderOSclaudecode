"""Tests for GitHubAdapter — sync_node, list_updates, status mapping.

All HTTP calls are mocked via monkeypatch. No real GitHub API calls.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from fpms.spine.adapters.github_adapter import GitHubAdapter
from fpms.spine.models import NodeSnapshot, SourceEvent


def _make_issue_response(
    number=42,
    title="Fix login bug",
    state="open",
    html_url="https://github.com/octocat/repo/issues/42",
    assignee="jeff",
    labels=None,
    updated_at="2026-03-20T10:00:00Z",
):
    return {
        "number": number,
        "title": title,
        "state": state,
        "html_url": html_url,
        "assignee": {"login": assignee} if assignee else None,
        "labels": [{"name": l} for l in (labels or [])],
        "updated_at": updated_at,
        "body": "Issue body text",
    }


def _make_events_response(events=None):
    if events is None:
        events = [
            {
                "type": "IssuesEvent",
                "created_at": "2026-03-20T10:00:00Z",
                "payload": {
                    "action": "closed",
                    "issue": {"number": 42, "title": "Fix login bug"},
                },
            },
        ]
    return events


@pytest.fixture
def adapter():
    return GitHubAdapter(token="fake-token", default_repo="octocat/repo")


class TestSyncNode:
    def test_sync_open_issue(self, adapter):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _make_issue_response(state="open")
        mock_resp.raise_for_status = MagicMock()

        with patch.object(adapter, "_get", return_value=mock_resp):
            snap = adapter.sync_node("octocat/repo#42")

        assert isinstance(snap, NodeSnapshot)
        assert snap.source == "github"
        assert snap.source_id == "octocat/repo#42"
        assert snap.title == "Fix login bug"
        assert snap.status == "active"
        assert snap.assignee == "jeff"

    def test_sync_closed_issue(self, adapter):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _make_issue_response(state="closed")
        mock_resp.raise_for_status = MagicMock()

        with patch.object(adapter, "_get", return_value=mock_resp):
            snap = adapter.sync_node("octocat/repo#42")

        assert snap.status == "done"

    def test_sync_blocked_label(self, adapter):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _make_issue_response(
            state="open", labels=["blocked", "bug"],
        )
        mock_resp.raise_for_status = MagicMock()

        with patch.object(adapter, "_get", return_value=mock_resp):
            snap = adapter.sync_node("octocat/repo#42")

        assert "blocked" in snap.labels
        assert "bug" in snap.labels

    def test_sync_not_found_returns_none(self, adapter):
        mock_resp = MagicMock()
        mock_resp.status_code = 404

        with patch.object(adapter, "_get", return_value=mock_resp):
            snap = adapter.sync_node("octocat/repo#999")

        assert snap is None

    def test_sync_timeout_raises(self, adapter):
        import httpx
        with patch.object(adapter, "_get", side_effect=httpx.TimeoutException("timeout")):
            with pytest.raises(ConnectionError, match="GitHub API timeout"):
                adapter.sync_node("octocat/repo#42")

    def test_parse_source_id_formats(self, adapter):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _make_issue_response()
        mock_resp.raise_for_status = MagicMock()

        with patch.object(adapter, "_get", return_value=mock_resp) as mock_get:
            adapter.sync_node("#42")
            call_url = mock_get.call_args[0][0]
            assert "octocat/repo" in call_url

    def test_sync_no_assignee(self, adapter):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _make_issue_response(assignee=None)
        mock_resp.raise_for_status = MagicMock()

        with patch.object(adapter, "_get", return_value=mock_resp):
            snap = adapter.sync_node("octocat/repo#42")

        assert snap.assignee is None

    def test_sync_auth_failure_raises(self, adapter):
        mock_resp = MagicMock()
        mock_resp.status_code = 401

        with patch.object(adapter, "_get", return_value=mock_resp):
            with pytest.raises(PermissionError, match="GitHub API auth failed"):
                adapter.sync_node("octocat/repo#42")

    def test_parse_invalid_source_id(self, adapter):
        with pytest.raises(ValueError, match="Invalid source_id format"):
            adapter.sync_node("invalid-format")


class TestListUpdates:
    def test_list_returns_events(self, adapter):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _make_events_response()
        mock_resp.raise_for_status = MagicMock()

        with patch.object(adapter, "_get", return_value=mock_resp):
            events = adapter.list_updates()

        assert len(events) >= 1
        assert isinstance(events[0], SourceEvent)
        assert events[0].source == "github"

    def test_list_with_since_filter(self, adapter):
        since = datetime(2026, 3, 19, tzinfo=timezone.utc)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _make_events_response()
        mock_resp.raise_for_status = MagicMock()

        with patch.object(adapter, "_get", return_value=mock_resp) as mock_get:
            adapter.list_updates(since=since)
            assert mock_get.called

    def test_list_empty(self, adapter):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = []
        mock_resp.raise_for_status = MagicMock()

        with patch.object(adapter, "_get", return_value=mock_resp):
            events = adapter.list_updates()

        assert events == []


class TestStatusMapping:
    def test_open_maps_to_active(self, adapter):
        assert adapter.map_status("open") == "active"

    def test_closed_maps_to_done(self, adapter):
        assert adapter.map_status("closed") == "done"

    def test_unknown_maps_to_inbox(self, adapter):
        assert adapter.map_status("unknown_state") == "inbox"

    def test_custom_mapping(self):
        custom = GitHubAdapter(
            token="fake",
            default_repo="octocat/repo",
            status_map={"open": "waiting", "closed": "dropped"},
        )
        assert custom.map_status("open") == "waiting"
        assert custom.map_status("closed") == "dropped"


class TestSourceName:
    def test_source_name(self, adapter):
        assert adapter.source_name == "github"
