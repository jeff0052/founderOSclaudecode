# M1 GitHub Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add GitHub Adapter infrastructure to FPMS V4, enabling cross-tool sync of GitHub Issues/PRs as cognitive nodes with real-time and cached context loading.

**Architecture:** BaseAdapter ABC defines the unified interface (sync_node, list_updates, write_comment, search). GitHubAdapter implements it using httpx for HTTP. AdapterRegistry manages adapter lifecycle. BundleAssembler is extended to call adapters during L2 focus loading with offline degradation. SpineEngine wires everything together via sync_source/sync_all methods.

**Scope note:** `list_updates` event processing (incremental event-based sync) is deferred to M2, where Heartbeat will trigger periodic sync using `list_updates`. M1 focuses on per-node `sync_node` pulls (on-demand and during context loading). `search()` and `write_comment()` are also deferred — base interface is defined with `NotImplementedError` defaults.

**Tech Stack:** Python 3.11+, httpx (async HTTP client), pytest, SQLite (existing), Pydantic (input validation)

---

## File Structure

```
fpms/
├── spine/
│   ├── adapters/
│   │   ├── __init__.py          # re-exports BaseAdapter, AdapterRegistry
│   │   ├── base.py              # BaseAdapter ABC, NodeSnapshot, SourceEvent
│   │   ├── registry.py          # AdapterRegistry (register/get/list)
│   │   └── github_adapter.py    # GitHubAdapter implementation
│   ├── bundle.py                # MODIFY: add cross-source sync in L2 loading
│   ├── models.py                # MODIFY: add NodeSnapshot, SourceEvent dataclasses
│   └── __init__.py              # MODIFY: wire adapters into SpineEngine
tests/
├── test_adapter_base.py         # BaseAdapter ABC + data structures
├── test_adapter_registry.py     # Registry register/get/list
├── test_github_adapter.py       # GitHubAdapter with mocked HTTP
├── test_bundle_cross_source.py  # Cross-source context loading
└── test_m1_e2e.py               # M1 integration verification
```

---

### Task 1: Adapter Data Structures (models.py)

**Files:**
- Modify: `fpms/spine/models.py`
- Test: `tests/test_adapter_base.py`

- [ ] **Step 1: Write failing tests for NodeSnapshot and SourceEvent**

```python
# tests/test_adapter_base.py
"""Tests for Adapter data structures: NodeSnapshot, SourceEvent."""

import pytest
from fpms.spine.models import NodeSnapshot, SourceEvent


class TestNodeSnapshot:
    def test_create_minimal(self):
        snap = NodeSnapshot(
            source="github",
            source_id="octocat/repo#42",
            title="Fix login bug",
            status="active",
        )
        assert snap.source == "github"
        assert snap.source_id == "octocat/repo#42"
        assert snap.title == "Fix login bug"
        assert snap.status == "active"
        assert snap.source_url is None
        assert snap.assignee is None
        assert snap.updated_at is None
        assert snap.labels == []
        assert snap.raw == {}

    def test_create_full(self):
        snap = NodeSnapshot(
            source="github",
            source_id="octocat/repo#42",
            title="Fix login bug",
            status="active",
            source_url="https://github.com/octocat/repo/issues/42",
            assignee="jeff",
            updated_at="2026-03-20T10:00:00+08:00",
            labels=["bug", "urgent"],
            raw={"number": 42},
        )
        assert snap.assignee == "jeff"
        assert snap.labels == ["bug", "urgent"]
        assert snap.raw == {"number": 42}

    def test_snapshot_is_dataclass(self):
        from dataclasses import is_dataclass
        assert is_dataclass(NodeSnapshot)


class TestSourceEvent:
    def test_create_status_change(self):
        evt = SourceEvent(
            source="github",
            source_id="octocat/repo#42",
            event_type="status_change",
            timestamp="2026-03-20T10:00:00Z",
            data={"old": "open", "new": "closed"},
        )
        assert evt.event_type == "status_change"
        assert evt.data["old"] == "open"

    def test_create_comment(self):
        evt = SourceEvent(
            source="github",
            source_id="octocat/repo#42",
            event_type="comment",
            timestamp="2026-03-20T10:00:00Z",
            data={"body": "Working on this"},
        )
        assert evt.event_type == "comment"

    def test_event_is_dataclass(self):
        from dataclasses import is_dataclass
        assert is_dataclass(SourceEvent)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/ontanetwork/Documents/Onta Network/Founder OS/MemoryFPMS/V4" && python -m pytest tests/test_adapter_base.py -v`
Expected: FAIL with `ImportError: cannot import name 'NodeSnapshot'`

- [ ] **Step 3: Implement NodeSnapshot and SourceEvent in models.py**

Add to `fpms/spine/models.py` at the end (before any closing comments):

```python
# ---------------------------------------------------------------------------
# Adapter Data Structures (M1)
# ---------------------------------------------------------------------------

@dataclass
class NodeSnapshot:
    """External source snapshot — returned by Adapter.sync_node()."""
    source: str            # "github" | "notion"
    source_id: str         # external object ID (e.g. "octocat/repo#42")
    title: str
    status: str            # mapped to FounderOS status
    source_url: str | None = None
    assignee: str | None = None
    updated_at: str | None = None  # ISO 8601
    labels: list[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict)  # full API response for extensibility


@dataclass
class SourceEvent:
    """External source event — returned by Adapter.list_updates()."""
    source: str
    source_id: str
    event_type: str        # "status_change" | "comment" | "label_change" | "assigned" | "deleted"
    timestamp: str         # ISO 8601
    data: dict = field(default_factory=dict)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/ontanetwork/Documents/Onta Network/Founder OS/MemoryFPMS/V4" && python -m pytest tests/test_adapter_base.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
cd "/Users/ontanetwork/Documents/Onta Network/Founder OS/MemoryFPMS/V4"
git add fpms/spine/models.py tests/test_adapter_base.py
git commit -m "feat(m1): add NodeSnapshot and SourceEvent dataclasses"
```

---

### Task 2: BaseAdapter ABC

**Files:**
- Create: `fpms/spine/adapters/__init__.py`
- Create: `fpms/spine/adapters/base.py`
- Test: `tests/test_adapter_base.py` (append)

- [ ] **Step 1: Write failing tests for BaseAdapter ABC**

Append to `tests/test_adapter_base.py`:

```python
from fpms.spine.adapters.base import BaseAdapter


class TestBaseAdapter:
    def test_cannot_instantiate(self):
        """BaseAdapter is abstract — instantiation must raise TypeError."""
        with pytest.raises(TypeError):
            BaseAdapter()

    def test_has_required_methods(self):
        """BaseAdapter defines sync_node, list_updates, write_comment, search."""
        import inspect
        methods = {name for name, _ in inspect.getmembers(BaseAdapter, predicate=inspect.isfunction)}
        assert "sync_node" in methods
        assert "list_updates" in methods
        assert "write_comment" in methods
        assert "search" in methods

    def test_concrete_subclass_must_implement_required(self):
        """Subclass missing sync_node/list_updates cannot be instantiated."""
        class Incomplete(BaseAdapter):
            pass
        with pytest.raises(TypeError):
            Incomplete()

    def test_concrete_subclass_with_required_methods(self):
        """Subclass implementing required methods can be instantiated."""
        class Complete(BaseAdapter):
            @property
            def source_name(self) -> str:
                return "test"

            def sync_node(self, source_id):
                return None

            def list_updates(self, since=None):
                return []

        adapter = Complete()
        assert adapter.source_name == "test"
        assert adapter.sync_node("x") is None
        assert adapter.list_updates() == []

    def test_write_comment_default_not_implemented(self):
        """write_comment and search have default NotImplementedError."""
        class Minimal(BaseAdapter):
            @property
            def source_name(self) -> str:
                return "test"

            def sync_node(self, source_id):
                return None

            def list_updates(self, since=None):
                return []

        adapter = Minimal()
        with pytest.raises(NotImplementedError):
            adapter.write_comment("id", "text")
        with pytest.raises(NotImplementedError):
            adapter.search("query")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/ontanetwork/Documents/Onta Network/Founder OS/MemoryFPMS/V4" && python -m pytest tests/test_adapter_base.py::TestBaseAdapter -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'fpms.spine.adapters'`

- [ ] **Step 3: Create adapters package and BaseAdapter**

Create `fpms/spine/adapters/__init__.py`:

```python
"""Adapter layer — connects FPMS to external tools (GitHub, Notion, etc.)."""

from .base import BaseAdapter
from .registry import AdapterRegistry

__all__ = ["BaseAdapter", "AdapterRegistry"]
```

Create `fpms/spine/adapters/base.py`:

```python
"""BaseAdapter ABC — unified interface for all external tool adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Optional

from ..models import NodeSnapshot, SourceEvent


class BaseAdapter(ABC):
    """Abstract base for external tool adapters.

    Required methods (must override):
      - source_name (property): adapter identifier, e.g. "github"
      - sync_node(source_id): pull latest state for one external object
      - list_updates(since): pull incremental change events

    Optional methods (default raises NotImplementedError):
      - write_comment(source_id, text): post comment to external tool
      - search(query): search external tool
    """

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Adapter identifier, e.g. 'github', 'notion'."""
        ...

    @abstractmethod
    def sync_node(self, source_id: str) -> Optional[NodeSnapshot]:
        """Pull the latest state for a single external object.

        Args:
            source_id: External object identifier (e.g. "octocat/repo#42").

        Returns:
            NodeSnapshot with mapped fields, or None if not found / deleted.
        """
        ...

    @abstractmethod
    def list_updates(self, since: Optional[datetime] = None) -> List[SourceEvent]:
        """Pull incremental change events since a given time.

        Args:
            since: Only return events after this timestamp. None = all recent.

        Returns:
            List of SourceEvent ordered by timestamp ascending.
        """
        ...

    def write_comment(self, source_id: str, text: str) -> None:
        """Post a comment/note to the external object. Optional."""
        raise NotImplementedError(
            f"{self.source_name} adapter does not support write_comment"
        )

    def search(self, query: str) -> List[NodeSnapshot]:
        """Search the external tool. Optional."""
        raise NotImplementedError(
            f"{self.source_name} adapter does not support search"
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/ontanetwork/Documents/Onta Network/Founder OS/MemoryFPMS/V4" && python -m pytest tests/test_adapter_base.py -v`
Expected: 11 passed (6 data structure + 5 ABC)

- [ ] **Step 5: Commit**

```bash
cd "/Users/ontanetwork/Documents/Onta Network/Founder OS/MemoryFPMS/V4"
git add fpms/spine/adapters/__init__.py fpms/spine/adapters/base.py tests/test_adapter_base.py
git commit -m "feat(m1): add BaseAdapter ABC with sync_node/list_updates interface"
```

---

### Task 3: AdapterRegistry

**Files:**
- Create: `fpms/spine/adapters/registry.py`
- Test: `tests/test_adapter_registry.py`

- [ ] **Step 1: Write failing tests for AdapterRegistry**

```python
# tests/test_adapter_registry.py
"""Tests for AdapterRegistry — register, get, list adapters."""

import pytest
from fpms.spine.adapters.base import BaseAdapter
from fpms.spine.adapters.registry import AdapterRegistry
from fpms.spine.models import NodeSnapshot


class _FakeAdapter(BaseAdapter):
    """Minimal concrete adapter for testing."""

    @property
    def source_name(self) -> str:
        return "fake"

    def sync_node(self, source_id):
        return NodeSnapshot(
            source="fake", source_id=source_id,
            title="Fake", status="active",
        )

    def list_updates(self, since=None):
        return []


class _AnotherAdapter(BaseAdapter):
    @property
    def source_name(self) -> str:
        return "another"

    def sync_node(self, source_id):
        return None

    def list_updates(self, since=None):
        return []


class TestAdapterRegistry:
    def test_register_and_get(self):
        reg = AdapterRegistry()
        adapter = _FakeAdapter()
        reg.register(adapter)
        assert reg.get("fake") is adapter

    def test_get_unregistered_raises(self):
        reg = AdapterRegistry()
        with pytest.raises(KeyError, match="No adapter registered for source 'github'"):
            reg.get("github")

    def test_list_sources(self):
        reg = AdapterRegistry()
        reg.register(_FakeAdapter())
        reg.register(_AnotherAdapter())
        sources = reg.list_sources()
        assert set(sources) == {"fake", "another"}

    def test_register_duplicate_replaces(self):
        reg = AdapterRegistry()
        a1 = _FakeAdapter()
        a2 = _FakeAdapter()
        reg.register(a1)
        reg.register(a2)
        assert reg.get("fake") is a2

    def test_has(self):
        reg = AdapterRegistry()
        assert not reg.has("fake")
        reg.register(_FakeAdapter())
        assert reg.has("fake")

    def test_empty_list(self):
        reg = AdapterRegistry()
        assert reg.list_sources() == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/ontanetwork/Documents/Onta Network/Founder OS/MemoryFPMS/V4" && python -m pytest tests/test_adapter_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'fpms.spine.adapters.registry'`

- [ ] **Step 3: Implement AdapterRegistry**

Create `fpms/spine/adapters/registry.py`:

```python
"""AdapterRegistry — manages external tool adapter lifecycle."""

from __future__ import annotations

from typing import Dict, List

from .base import BaseAdapter


class AdapterRegistry:
    """Register, retrieve, and list external tool adapters.

    Usage:
        registry = AdapterRegistry()
        registry.register(GitHubAdapter(token="..."))
        adapter = registry.get("github")
        snapshot = adapter.sync_node("octocat/repo#42")
    """

    def __init__(self) -> None:
        self._adapters: Dict[str, BaseAdapter] = {}

    def register(self, adapter: BaseAdapter) -> None:
        """Register an adapter. Replaces any existing adapter for the same source."""
        self._adapters[adapter.source_name] = adapter

    def get(self, source: str) -> BaseAdapter:
        """Get adapter by source name. Raises KeyError if not registered."""
        try:
            return self._adapters[source]
        except KeyError:
            raise KeyError(f"No adapter registered for source '{source}'")

    def has(self, source: str) -> bool:
        """Check if an adapter is registered for the given source."""
        return source in self._adapters

    def list_sources(self) -> List[str]:
        """List all registered source names."""
        return list(self._adapters.keys())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/ontanetwork/Documents/Onta Network/Founder OS/MemoryFPMS/V4" && python -m pytest tests/test_adapter_registry.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
cd "/Users/ontanetwork/Documents/Onta Network/Founder OS/MemoryFPMS/V4"
git add fpms/spine/adapters/registry.py tests/test_adapter_registry.py
git commit -m "feat(m1): add AdapterRegistry for adapter lifecycle management"
```

---

### Task 4: GitHubAdapter

**Files:**
- Create: `fpms/spine/adapters/github_adapter.py`
- Test: `tests/test_github_adapter.py`

**Note:** Uses httpx for HTTP. All tests use mocked responses (no real API calls).

- [ ] **Step 1: Write failing tests for GitHubAdapter**

```python
# tests/test_github_adapter.py
"""Tests for GitHubAdapter — sync_node, list_updates, status mapping.

All HTTP calls are mocked via monkeypatch. No real GitHub API calls.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from fpms.spine.adapters.github_adapter import GitHubAdapter
from fpms.spine.models import NodeSnapshot, SourceEvent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_issue_response(
    number=42,
    title="Fix login bug",
    state="open",
    html_url="https://github.com/octocat/repo/issues/42",
    assignee="jeff",
    labels=None,
    updated_at="2026-03-20T10:00:00Z",
):
    """Build a mock GitHub Issue API response dict."""
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
    """Build a mock GitHub Events API response list."""
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


# ---------------------------------------------------------------------------
# sync_node Tests
# ---------------------------------------------------------------------------

class TestSyncNode:
    def test_sync_open_issue(self, adapter):
        """Open issue maps to status=active."""
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
        """Closed issue maps to status=done."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _make_issue_response(state="closed")
        mock_resp.raise_for_status = MagicMock()

        with patch.object(adapter, "_get", return_value=mock_resp):
            snap = adapter.sync_node("octocat/repo#42")

        assert snap.status == "done"

    def test_sync_blocked_label(self, adapter):
        """Issue with 'blocked' label includes it in labels."""
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
        """404 response returns None (deleted/not found)."""
        mock_resp = MagicMock()
        mock_resp.status_code = 404

        with patch.object(adapter, "_get", return_value=mock_resp):
            snap = adapter.sync_node("octocat/repo#999")

        assert snap is None

    def test_sync_timeout_raises(self, adapter):
        """Network timeout raises ConnectionError."""
        import httpx
        with patch.object(adapter, "_get", side_effect=httpx.TimeoutException("timeout")):
            with pytest.raises(ConnectionError, match="GitHub API timeout"):
                adapter.sync_node("octocat/repo#42")

    def test_parse_source_id_formats(self, adapter):
        """source_id formats: 'owner/repo#42' or '#42' (uses default_repo)."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _make_issue_response()
        mock_resp.raise_for_status = MagicMock()

        with patch.object(adapter, "_get", return_value=mock_resp) as mock_get:
            adapter.sync_node("#42")
            # Should use default_repo
            call_url = mock_get.call_args[0][0]
            assert "octocat/repo" in call_url

    def test_sync_no_assignee(self, adapter):
        """Issue with no assignee sets assignee=None."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _make_issue_response(assignee=None)
        mock_resp.raise_for_status = MagicMock()

        with patch.object(adapter, "_get", return_value=mock_resp):
            snap = adapter.sync_node("octocat/repo#42")

        assert snap.assignee is None

    def test_sync_auth_failure_raises(self, adapter):
        """401/403 response raises PermissionError with clear message."""
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.raise_for_status = MagicMock(
            side_effect=Exception("401 Unauthorized")
        )

        with patch.object(adapter, "_get", return_value=mock_resp):
            with pytest.raises(PermissionError, match="GitHub API auth failed"):
                adapter.sync_node("octocat/repo#42")

    def test_parse_invalid_source_id(self, adapter):
        """Invalid source_id format raises ValueError."""
        with pytest.raises(ValueError, match="Invalid source_id format"):
            adapter.sync_node("invalid-format")


# ---------------------------------------------------------------------------
# list_updates Tests
# ---------------------------------------------------------------------------

class TestListUpdates:
    def test_list_returns_events(self, adapter):
        """list_updates returns SourceEvent list."""
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
        """list_updates passes since parameter to filter."""
        since = datetime(2026, 3, 19, tzinfo=timezone.utc)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _make_events_response()
        mock_resp.raise_for_status = MagicMock()

        with patch.object(adapter, "_get", return_value=mock_resp) as mock_get:
            adapter.list_updates(since=since)
            # Verify since was used (implementation detail)
            assert mock_get.called

    def test_list_empty(self, adapter):
        """Empty event list returns empty list."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = []
        mock_resp.raise_for_status = MagicMock()

        with patch.object(adapter, "_get", return_value=mock_resp):
            events = adapter.list_updates()

        assert events == []


# ---------------------------------------------------------------------------
# Status Mapping Tests
# ---------------------------------------------------------------------------

class TestStatusMapping:
    def test_open_maps_to_active(self, adapter):
        assert adapter.map_status("open") == "active"

    def test_closed_maps_to_done(self, adapter):
        assert adapter.map_status("closed") == "done"

    def test_unknown_maps_to_inbox(self, adapter):
        """Unknown GitHub state defaults to inbox."""
        assert adapter.map_status("unknown_state") == "inbox"

    def test_custom_mapping(self):
        """Custom status_map overrides defaults."""
        custom = GitHubAdapter(
            token="fake",
            default_repo="octocat/repo",
            status_map={"open": "waiting", "closed": "dropped"},
        )
        assert custom.map_status("open") == "waiting"
        assert custom.map_status("closed") == "dropped"


# ---------------------------------------------------------------------------
# source_name Property
# ---------------------------------------------------------------------------

class TestSourceName:
    def test_source_name(self, adapter):
        assert adapter.source_name == "github"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/ontanetwork/Documents/Onta Network/Founder OS/MemoryFPMS/V4" && python -m pytest tests/test_github_adapter.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'fpms.spine.adapters.github_adapter'`

- [ ] **Step 3: Install httpx dependency**

Run: `pip install httpx`

- [ ] **Step 4: Implement GitHubAdapter**

Create `fpms/spine/adapters/github_adapter.py`:

```python
"""GitHubAdapter — sync GitHub Issues/PRs as FPMS cognitive nodes.

Uses httpx for HTTP requests. Stateless except for configuration.
All caching is handled by the caller (Store/BundleAssembler).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Dict, List, Optional

import httpx

from ..models import NodeSnapshot, SourceEvent
from .base import BaseAdapter

_DEFAULT_STATUS_MAP: Dict[str, str] = {
    "open": "active",
    "closed": "done",
}

_API_BASE = "https://api.github.com"
_TIMEOUT = 10.0  # seconds


class GitHubAdapter(BaseAdapter):
    """Adapter for GitHub Issues and PRs.

    Args:
        token: GitHub personal access token or fine-grained token.
        default_repo: Default "owner/repo" for shorthand source_ids (e.g. "#42").
        status_map: Custom GitHub state → FounderOS status mapping.
        timeout: HTTP request timeout in seconds.
    """

    def __init__(
        self,
        token: str,
        default_repo: str = "",
        status_map: Optional[Dict[str, str]] = None,
        timeout: float = _TIMEOUT,
    ) -> None:
        self._token = token
        self._default_repo = default_repo
        self._status_map = status_map or dict(_DEFAULT_STATUS_MAP)
        self._timeout = timeout

    @property
    def source_name(self) -> str:
        return "github"

    # -----------------------------------------------------------------------
    # BaseAdapter required methods
    # -----------------------------------------------------------------------

    def sync_node(self, source_id: str) -> Optional[NodeSnapshot]:
        """Pull latest state for a GitHub Issue/PR.

        Args:
            source_id: "owner/repo#number" or "#number" (uses default_repo).

        Returns:
            NodeSnapshot with mapped fields, or None if 404.

        Raises:
            ConnectionError: On network timeout.
        """
        owner, repo, number = self._parse_source_id(source_id)
        url = f"{_API_BASE}/repos/{owner}/{repo}/issues/{number}"

        try:
            resp = self._get(url)
        except httpx.TimeoutException:
            raise ConnectionError(
                f"GitHub API timeout for {source_id}. "
                "Check network or increase timeout."
            )

        if resp.status_code == 404:
            return None

        if resp.status_code in (401, 403):
            raise PermissionError(
                f"GitHub API auth failed for {source_id} "
                f"(HTTP {resp.status_code}). Check your token."
            )

        resp.raise_for_status()
        data = resp.json()

        return NodeSnapshot(
            source="github",
            source_id=f"{owner}/{repo}#{number}",
            title=data["title"],
            status=self.map_status(data["state"]),
            source_url=data.get("html_url"),
            assignee=data["assignee"]["login"] if data.get("assignee") else None,
            updated_at=data.get("updated_at"),
            labels=[label["name"] for label in data.get("labels", [])],
            raw=data,
        )

    def list_updates(self, since: Optional[datetime] = None) -> List[SourceEvent]:
        """Pull recent events from the default repo.

        Args:
            since: Only return events after this timestamp.

        Returns:
            List of SourceEvent sorted by timestamp ascending.
        """
        if not self._default_repo:
            return []

        owner, repo = self._default_repo.split("/", 1)
        url = f"{_API_BASE}/repos/{owner}/{repo}/events"

        try:
            resp = self._get(url)
        except httpx.TimeoutException:
            raise ConnectionError(
                f"GitHub API timeout for events on {self._default_repo}."
            )

        if resp.status_code != 200:
            return []

        raw_events = resp.json()
        events: List[SourceEvent] = []

        for raw in raw_events:
            ts = raw.get("created_at", "")

            # Filter by since
            if since is not None and ts:
                try:
                    event_time = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    if event_time <= since:
                        continue
                except ValueError:
                    pass

            event_type = raw.get("type", "")
            payload = raw.get("payload", {})

            # Map GitHub event types to SourceEvent
            if event_type == "IssuesEvent":
                action = payload.get("action", "")
                issue = payload.get("issue", {})
                issue_num = issue.get("number", 0)
                events.append(SourceEvent(
                    source="github",
                    source_id=f"{owner}/{repo}#{issue_num}",
                    event_type=f"issue_{action}",
                    timestamp=ts,
                    data={"action": action, "title": issue.get("title", "")},
                ))
            elif event_type == "PullRequestEvent":
                action = payload.get("action", "")
                pr = payload.get("pull_request", {})
                pr_num = pr.get("number", 0)
                events.append(SourceEvent(
                    source="github",
                    source_id=f"{owner}/{repo}#{pr_num}",
                    event_type=f"pr_{action}",
                    timestamp=ts,
                    data={"action": action, "title": pr.get("title", "")},
                ))

        # Sort by timestamp ascending
        events.sort(key=lambda e: e.timestamp)
        return events

    # -----------------------------------------------------------------------
    # Status mapping
    # -----------------------------------------------------------------------

    def map_status(self, github_state: str) -> str:
        """Map GitHub issue/PR state to FounderOS status.

        Default: open→active, closed→done. Unknown→inbox.
        """
        return self._status_map.get(github_state, "inbox")

    # -----------------------------------------------------------------------
    # HTTP helper
    # -----------------------------------------------------------------------

    def _get(self, url: str, params: Optional[dict] = None) -> httpx.Response:
        """Make authenticated GET request to GitHub API."""
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        return httpx.get(url, headers=headers, params=params, timeout=self._timeout)

    # -----------------------------------------------------------------------
    # source_id parsing
    # -----------------------------------------------------------------------

    def _parse_source_id(self, source_id: str) -> tuple[str, str, int]:
        """Parse 'owner/repo#number' or '#number' into (owner, repo, number).

        Raises:
            ValueError: If source_id format is invalid.
        """
        # Full format: owner/repo#42
        match = re.match(r"^([^/]+)/([^#]+)#(\d+)$", source_id)
        if match:
            return match.group(1), match.group(2), int(match.group(3))

        # Short format: #42 (uses default_repo)
        match = re.match(r"^#(\d+)$", source_id)
        if match:
            if not self._default_repo:
                raise ValueError(
                    f"Short source_id '{source_id}' requires default_repo to be set"
                )
            parts = self._default_repo.split("/", 1)
            return parts[0], parts[1], int(match.group(1))

        raise ValueError(
            f"Invalid source_id format: '{source_id}'. "
            "Expected 'owner/repo#number' or '#number'."
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd "/Users/ontanetwork/Documents/Onta Network/Founder OS/MemoryFPMS/V4" && python -m pytest tests/test_github_adapter.py -v`
Expected: 16 passed

- [ ] **Step 6: Commit**

```bash
cd "/Users/ontanetwork/Documents/Onta Network/Founder OS/MemoryFPMS/V4"
git add fpms/spine/adapters/github_adapter.py tests/test_github_adapter.py
git commit -m "feat(m1): add GitHubAdapter with sync_node, list_updates, status mapping"
```

---

### Task 5: Cross-Source Context Loading (bundle.py extension)

**Files:**
- Modify: `fpms/spine/bundle.py`
- Test: `tests/test_bundle_cross_source.py`

- [ ] **Step 1: Write failing tests for cross-source loading**

```python
# tests/test_bundle_cross_source.py
"""Tests for cross-source context loading in BundleAssembler.

When L2 focuses on a node with source != 'internal', the assembler
should call the adapter to sync fresh data and merge it into the bundle.
"""

import pytest
import os
import tempfile
from datetime import datetime, timezone
from unittest.mock import MagicMock

from fpms.spine.store import Store
from fpms.spine.bundle import BundleAssembler
from fpms.spine.models import Node, NodeSnapshot
from fpms.spine.adapters.registry import AdapterRegistry
from fpms.spine.adapters.base import BaseAdapter


class _MockGitHubAdapter(BaseAdapter):
    """Mock adapter that returns pre-configured snapshots."""

    def __init__(self, snapshots=None):
        self._snapshots = snapshots or {}

    @property
    def source_name(self) -> str:
        return "github"

    def sync_node(self, source_id):
        return self._snapshots.get(source_id)

    def list_updates(self, since=None):
        return []


@pytest.fixture
def tmp_env(tmp_path):
    """Create a temp environment with Store and dirs."""
    db_path = str(tmp_path / "test.db")
    events_path = str(tmp_path / "events.jsonl")
    narratives_dir = str(tmp_path / "narratives")
    os.makedirs(narratives_dir, exist_ok=True)

    store = Store(db_path, events_path)
    return store, narratives_dir, tmp_path


def _create_github_node(store, node_id="task-gh01", source_id="octocat/repo#42"):
    """Create a node pointing to a GitHub issue."""
    node = Node(
        id=node_id,
        title="Old title from last sync",
        status="active",
        node_type="task",
        is_root=True,
        source="github",
        source_id=source_id,
        source_url="https://github.com/octocat/repo/issues/42",
    )
    store.create_node(node)
    return node


class TestCrossSourceL2:
    def test_l2_shows_synced_title_when_adapter_available(self, tmp_env):
        """When adapter is registered, L2 merges latest external data."""
        store, narratives_dir, tmp_path = tmp_env

        node = _create_github_node(store)

        # Mock adapter returns updated title
        adapter = _MockGitHubAdapter(snapshots={
            "octocat/repo#42": NodeSnapshot(
                source="github",
                source_id="octocat/repo#42",
                title="New title from GitHub",
                status="active",
                assignee="jeff",
            ),
        })

        registry = AdapterRegistry()
        registry.register(adapter)

        assembler = BundleAssembler(
            store=store,
            adapter_registry=registry,
            narratives_dir=narratives_dir,
        )

        bundle = assembler.assemble(focus_node_id=node.id)

        # L2 should contain the synced title
        assert "New title from GitHub" in bundle.l2_focus
        # And show the source info
        assert "github" in bundle.l2_focus.lower() or "octocat/repo#42" in bundle.l2_focus

    def test_l2_uses_cache_when_adapter_fails(self, tmp_env):
        """When adapter raises, fall back to cached data, don't crash."""
        store, narratives_dir, tmp_path = tmp_env

        node = _create_github_node(store)

        # Adapter that always fails
        adapter = _MockGitHubAdapter()
        adapter.sync_node = MagicMock(side_effect=ConnectionError("offline"))

        registry = AdapterRegistry()
        registry.register(adapter)

        assembler = BundleAssembler(
            store=store,
            adapter_registry=registry,
            narratives_dir=narratives_dir,
        )

        # Should NOT crash — use cached data
        bundle = assembler.assemble(focus_node_id=node.id)
        assert bundle.l2_focus is not None
        assert "Old title from last sync" in bundle.l2_focus

    def test_l2_marks_stale_data(self, tmp_env):
        """When adapter fails, L2 includes staleness warning."""
        store, narratives_dir, tmp_path = tmp_env

        node = _create_github_node(store)

        adapter = _MockGitHubAdapter()
        adapter.sync_node = MagicMock(side_effect=ConnectionError("offline"))

        registry = AdapterRegistry()
        registry.register(adapter)

        assembler = BundleAssembler(
            store=store,
            adapter_registry=registry,
            narratives_dir=narratives_dir,
        )

        bundle = assembler.assemble(focus_node_id=node.id)
        # Should have staleness warning
        assert "过时" in bundle.l2_focus or "stale" in bundle.l2_focus.lower()

    def test_l2_internal_node_unaffected(self, tmp_env):
        """Internal nodes (source='internal') don't trigger adapter sync."""
        store, narratives_dir, tmp_path = tmp_env

        node = Node(
            id="task-int1", title="Local task",
            status="active", node_type="task", is_root=True,
            source="internal",
        )
        store.create_node(node)

        registry = AdapterRegistry()
        # No adapter registered — should be fine for internal nodes

        assembler = BundleAssembler(
            store=store,
            adapter_registry=registry,
            narratives_dir=narratives_dir,
        )

        bundle = assembler.assemble(focus_node_id=node.id)
        assert "Local task" in bundle.l2_focus

    def test_l2_no_registry_still_works(self, tmp_env):
        """BundleAssembler works without adapter_registry (backward compat)."""
        store, narratives_dir, tmp_path = tmp_env

        node = Node(
            id="task-int2", title="No registry task",
            status="active", node_type="task", is_root=True,
        )
        store.create_node(node)

        assembler = BundleAssembler(
            store=store,
            narratives_dir=narratives_dir,
        )

        bundle = assembler.assemble(focus_node_id=node.id)
        assert "No registry task" in bundle.l2_focus

    def test_sync_updates_local_node_fields(self, tmp_env):
        """After sync, local node's synced fields are updated in DB."""
        store, narratives_dir, tmp_path = tmp_env

        node = _create_github_node(store)

        adapter = _MockGitHubAdapter(snapshots={
            "octocat/repo#42": NodeSnapshot(
                source="github",
                source_id="octocat/repo#42",
                title="Updated title",
                status="done",
                assignee="alice",
                updated_at="2026-03-21T10:00:00Z",
            ),
        })

        registry = AdapterRegistry()
        registry.register(adapter)

        assembler = BundleAssembler(
            store=store,
            adapter_registry=registry,
            narratives_dir=narratives_dir,
        )

        assembler.assemble(focus_node_id=node.id)

        # Check the node was updated in DB
        updated = store.get_node(node.id)
        assert updated.title == "Updated title"
        assert updated.status == "done"


class TestAssemblyTraceSyncStatus:
    def test_trace_includes_sync_info(self, tmp_env):
        """Assembly trace records sync success/failure."""
        store, narratives_dir, tmp_path = tmp_env

        node = _create_github_node(store)

        adapter = _MockGitHubAdapter(snapshots={
            "octocat/repo#42": NodeSnapshot(
                source="github",
                source_id="octocat/repo#42",
                title="Synced",
                status="active",
            ),
        })

        registry = AdapterRegistry()
        registry.register(adapter)

        assembler = BundleAssembler(
            store=store,
            adapter_registry=registry,
            narratives_dir=narratives_dir,
        )

        assembler.assemble(focus_node_id=node.id)

        # Check assembly trace file exists and has sync info
        import json
        trace_path = os.path.join(assembler._db_dir, "assembly_traces.jsonl")
        assert os.path.exists(trace_path)
        with open(trace_path) as f:
            lines = f.readlines()
        last_trace = json.loads(lines[-1])
        assert "sync_status" in last_trace
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/ontanetwork/Documents/Onta Network/Founder OS/MemoryFPMS/V4" && python -m pytest tests/test_bundle_cross_source.py -v`
Expected: FAIL — BundleAssembler doesn't accept `adapter_registry` parameter

- [ ] **Step 3: Modify BundleAssembler to support cross-source sync**

In `fpms/spine/bundle.py`, make these exact changes:

**Change 1:** Add `adapter_registry` parameter to `__init__` — insert after `narratives_dir` param:

```python
# In __init__ signature, add after narratives_dir parameter:
    adapter_registry=None,       # AdapterRegistry for cross-source sync (M1)

# At end of __init__ body, add:
    self._adapter_registry = adapter_registry
    self._last_sync_status = None  # Populated by _sync_focus_node, read by trace writer
```

**Change 2:** Add `_sync_focus_node()` method — insert before `_build_l0`:

```python
def _sync_focus_node(self, node: Node) -> tuple[Node, dict]:
    """Sync focus node from external source if applicable.

    Returns:
        (possibly updated node, sync_status dict)
    """
    sync_status = {"synced": False, "source": node.source}

    if node.source == "internal" or self._adapter_registry is None:
        return node, sync_status

    if not node.source_id:
        return node, sync_status

    if not self._adapter_registry.has(node.source):
        return node, sync_status

    try:
        adapter = self._adapter_registry.get(node.source)
        snapshot = adapter.sync_node(node.source_id)

        if snapshot is None:
            self._store.update_node(node.id, {"source_deleted": True})
            sync_status["synced"] = True
            sync_status["deleted"] = True
            node.source_deleted = True
            return node, sync_status

        update_fields = {
            "title": snapshot.title,
            "status": snapshot.status,
            "source_synced_at": datetime.now(timezone.utc).isoformat(),
        }
        if snapshot.assignee is not None:
            update_fields["owner"] = snapshot.assignee
        self._store.update_node(node.id, update_fields)

        node.title = snapshot.title
        node.status = snapshot.status
        if snapshot.assignee is not None:
            node.owner = snapshot.assignee
        node.source_synced_at = update_fields["source_synced_at"]

        sync_status["synced"] = True
        sync_status["snapshot_title"] = snapshot.title
        return node, sync_status

    except Exception as e:
        sync_status["error"] = str(e)
        sync_status["stale"] = True
        return node, sync_status
```

**Change 3:** Modify `_build_l2` — replace the existing method entirely:

```python
def _build_l2(self, focus_node_id: str) -> str:
    """Build L2: detailed focus node view with narrative."""
    store = self._store
    node = store.get_node(focus_node_id)
    if node is None:
        return f"# Focus: {focus_node_id}\n(node not found)"

    # Cross-source sync (M1)
    node, sync_status = self._sync_focus_node(node)
    self._last_sync_status = sync_status

    lines = [f"# Focus: {node.title}"]

    # Skeleton fields (unchanged from original)
    lines.append(f"id: {node.id}")
    lines.append(f"status: {node.status}")
    lines.append(f"type: {node.node_type}")
    if node.summary:
        lines.append(f"summary: {node.summary}")
    if node.why:
        lines.append(f"why: {node.why}")
    if node.next_step:
        lines.append(f"next_step: {node.next_step}")
    if node.owner:
        lines.append(f"owner: {node.owner}")
    if node.deadline:
        lines.append(f"deadline: {node.deadline}")
    if node.tags:
        lines.append(f"tags: {', '.join(node.tags)}")

    # Source info for external nodes (M1)
    if node.source != "internal":
        lines.append(f"source: {node.source}")
        if node.source_id:
            lines.append(f"source_id: {node.source_id}")
        if node.source_url:
            lines.append(f"source_url: {node.source_url}")
        if sync_status.get("stale"):
            lines.append(
                f"[数据可能过时: sync failed — {sync_status.get('error', 'unknown')}]"
            )

    # Compressed summary (priority) — unchanged
    compressed = self._narrative_mod.read_compressed(
        self._narratives_dir, focus_node_id
    )
    if compressed:
        lines.append("\n## Compressed Summary")
        lines.append(compressed.strip())

    # Recent narrative (last 5 entries) — unchanged
    narrative = self._narrative_mod.read_narrative(
        self._narratives_dir, focus_node_id, last_n_entries=5
    )
    if narrative:
        lines.append("\n## Narrative")
        lines.append(narrative.strip())

    return "\n".join(lines)
```

**Change 4:** Update `_write_assembly_trace` signature and body — add `sync_status` parameter:

```python
def _write_assembly_trace(
    self,
    focus_node_id: Optional[str],
    l0_tokens: int,
    l_alert_tokens: int,
    l1_tokens: int,
    l2_tokens: int,
    total_tokens: int,
    trimmed_items: Optional[List[str]] = None,
) -> None:
    """Write assembly trace to assembly_traces.jsonl in db_dir."""
    try:
        db_dir = self._db_dir
        os.makedirs(db_dir, exist_ok=True)
        trace_path = os.path.join(db_dir, "assembly_traces.jsonl")

        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "focus_node_id": focus_node_id,
            "tokens_per_layer": {
                "l0": l0_tokens,
                "l_alert": l_alert_tokens,
                "l1": l1_tokens,
                "l2": l2_tokens,
            },
            "total": total_tokens,
            "trimmed": trimmed_items or [],
            "sync_status": self._last_sync_status,  # M1: cross-source sync info
        }

        with open(trace_path, "a") as f:
            f.write(json.dumps(record) + "\n")
    except Exception:
        pass  # Trace failures are non-fatal
```

**Change 5:** In `assemble()`, reset `_last_sync_status` before building layers:

```python
# Add at the start of assemble(), before building layers:
self._last_sync_status = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/ontanetwork/Documents/Onta Network/Founder OS/MemoryFPMS/V4" && python -m pytest tests/test_bundle_cross_source.py -v`
Expected: 7 passed

- [ ] **Step 5: Run full test suite to verify no regressions**

Run: `cd "/Users/ontanetwork/Documents/Onta Network/Founder OS/MemoryFPMS/V4" && python -m pytest tests/ -v --tb=short`
Expected: All existing tests still pass (adapter_registry defaults to None = backward compatible)

- [ ] **Step 6: Commit**

```bash
cd "/Users/ontanetwork/Documents/Onta Network/Founder OS/MemoryFPMS/V4"
git add fpms/spine/bundle.py tests/test_bundle_cross_source.py
git commit -m "feat(m1): cross-source context loading with offline degradation in BundleAssembler"
```

---

### Task 6: SpineEngine Wiring (sync_source, sync_all)

**Files:**
- Modify: `fpms/spine/__init__.py`
- Modify: `fpms/spine/models.py` (__all__ update)
- Test: `tests/test_m1_e2e.py` (integration tests)

- [ ] **Step 1: Write integration tests**

```python
# tests/test_m1_e2e.py
"""M1 Integration Tests — end-to-end GitHub adapter flow.

Verifies:
1. Create node pointing to GitHub Issue → sync → context contains external data
2. GitHub Issue status change → list_updates → local node synced
3. Mixed local + GitHub tree → rollup correct
4. Offline → degraded context (no crash)
5. Assembly trace records sync info
"""

import pytest
import os
from datetime import datetime, timezone
from unittest.mock import MagicMock

from fpms.spine import SpineEngine
from fpms.spine.models import NodeSnapshot, SourceEvent
from fpms.spine.adapters.registry import AdapterRegistry
from fpms.spine.adapters.base import BaseAdapter


class _MockGitHubAdapter(BaseAdapter):
    def __init__(self, snapshots=None, events=None):
        self._snapshots = snapshots or {}
        self._events = events or []
        self.sync_called = []

    @property
    def source_name(self):
        return "github"

    def sync_node(self, source_id):
        self.sync_called.append(source_id)
        return self._snapshots.get(source_id)

    def list_updates(self, since=None):
        if since:
            return [e for e in self._events if e.timestamp > since.isoformat()]
        return self._events


@pytest.fixture
def engine_with_adapter(tmp_path):
    """Create SpineEngine with a mock GitHub adapter."""
    db_path = str(tmp_path / "test.db")
    events_path = str(tmp_path / "events.jsonl")
    narratives_dir = str(tmp_path / "narratives")

    engine = SpineEngine(
        db_path=db_path,
        events_path=events_path,
        narratives_dir=narratives_dir,
    )

    adapter = _MockGitHubAdapter(snapshots={
        "octocat/repo#42": NodeSnapshot(
            source="github",
            source_id="octocat/repo#42",
            title="Fix login from GitHub",
            status="active",
            assignee="jeff",
        ),
    })

    registry = AdapterRegistry()
    registry.register(adapter)
    engine.set_adapter_registry(registry)

    return engine, adapter


class TestM1CreateAndSync:
    def test_create_github_node_and_get_context(self, engine_with_adapter):
        """Create a node pointing to GitHub, get context bundle with synced data."""
        engine, adapter = engine_with_adapter

        result = engine.execute_tool("create_node", {
            "title": "Fix login bug",
            "node_type": "task",
            "is_root": True,
            "source": "github",
            "source_id": "octocat/repo#42",
            "source_url": "https://github.com/octocat/repo/issues/42",
        })
        assert result.success
        node_id = result.data["node"]["id"]

        bundle = engine.get_context_bundle(user_focus=node_id)
        # L2 should contain synced title from GitHub
        assert "Fix login from GitHub" in bundle.l2_focus

    def test_sync_source_updates_node(self, engine_with_adapter):
        """sync_source pulls latest from adapter and updates local node."""
        engine, adapter = engine_with_adapter

        result = engine.execute_tool("create_node", {
            "title": "Old title",
            "node_type": "task",
            "is_root": True,
            "source": "github",
            "source_id": "octocat/repo#42",
        })
        node_id = result.data["node"]["id"]

        updated = engine.sync_source(node_id)
        assert updated.title == "Fix login from GitHub"
        assert updated.source_synced_at is not None


class TestM1MixedTree:
    def test_mixed_local_and_github_rollup(self, engine_with_adapter):
        """Tree with both local and GitHub nodes rolls up correctly."""
        engine, adapter = engine_with_adapter

        # Create local root goal
        root_result = engine.execute_tool("create_node", {
            "title": "Q1 Launch",
            "node_type": "goal",
            "is_root": True,
            "summary": "Launch by end of Q1",
        })
        root_id = root_result.data["node"]["id"]

        # Activate root
        engine.execute_tool("update_status", {
            "node_id": root_id,
            "new_status": "active",
        })

        # Create GitHub child task
        gh_result = engine.execute_tool("create_node", {
            "title": "Fix login bug (from GH)",
            "node_type": "task",
            "parent_id": root_id,
            "source": "github",
            "source_id": "octocat/repo#42",
            "summary": "Linked to GitHub issue",
        })
        gh_id = gh_result.data["node"]["id"]

        # Activate GitHub child
        engine.execute_tool("update_status", {
            "node_id": gh_id,
            "new_status": "active",
        })

        # Create local child task
        local_result = engine.execute_tool("create_node", {
            "title": "Write tests",
            "node_type": "task",
            "parent_id": root_id,
            "summary": "Unit tests for all modules",
        })
        local_id = local_result.data["node"]["id"]

        engine.execute_tool("update_status", {
            "node_id": local_id,
            "new_status": "active",
        })

        # Get context — should include both children
        bundle = engine.get_context_bundle(user_focus=root_id)
        assert root_id in (bundle.focus_node_id or "")


class TestM1SyncAll:
    def test_sync_all_updates_multiple_nodes(self, engine_with_adapter):
        """sync_all pulls latest data for all external-source nodes."""
        engine, adapter = engine_with_adapter

        # Create two GitHub nodes
        r1 = engine.execute_tool("create_node", {
            "title": "Issue 42", "node_type": "task", "is_root": True,
            "source": "github", "source_id": "octocat/repo#42",
        })
        r2 = engine.execute_tool("create_node", {
            "title": "Issue 99", "node_type": "task", "is_root": True,
            "source": "github", "source_id": "octocat/repo#99",
        })

        # Add snapshot for #99
        adapter._snapshots["octocat/repo#99"] = NodeSnapshot(
            source="github", source_id="octocat/repo#99",
            title="Updated 99", status="done",
        )

        count = engine.sync_all()
        assert count >= 1  # At least one synced (the one with matching snapshot)

    def test_sync_all_no_registry_returns_zero(self, tmp_path):
        """sync_all with no adapter registry returns 0."""
        engine = SpineEngine(
            db_path=str(tmp_path / "test.db"),
            events_path=str(tmp_path / "events.jsonl"),
            narratives_dir=str(tmp_path / "narratives"),
        )
        assert engine.sync_all() == 0


class TestM1SourceDeleted:
    def test_deleted_node_marked_in_db(self, engine_with_adapter):
        """When adapter returns None, node is marked source_deleted=True."""
        engine, adapter = engine_with_adapter

        # Remove snapshot so sync returns None
        adapter._snapshots.clear()

        result = engine.execute_tool("create_node", {
            "title": "Will be deleted", "node_type": "task", "is_root": True,
            "source": "github", "source_id": "octocat/repo#deleted",
        })
        node_id = result.data["node"]["id"]

        updated = engine.sync_source(node_id)
        assert updated.source_deleted is True

    def test_deleted_node_still_renders_in_l2(self, engine_with_adapter):
        """source_deleted node still appears in L2 context (cognitive data preserved)."""
        engine, adapter = engine_with_adapter
        adapter._snapshots.clear()

        result = engine.execute_tool("create_node", {
            "title": "Deleted externally", "node_type": "task", "is_root": True,
            "source": "github", "source_id": "octocat/repo#gone",
        })
        node_id = result.data["node"]["id"]

        bundle = engine.get_context_bundle(user_focus=node_id)
        assert "Deleted externally" in bundle.l2_focus


class TestM1SourceIdGuard:
    def test_sync_source_without_source_id_raises(self, engine_with_adapter):
        """sync_source on a node with source='github' but no source_id raises."""
        engine, adapter = engine_with_adapter

        result = engine.execute_tool("create_node", {
            "title": "No source_id", "node_type": "task", "is_root": True,
            "source": "github",
            # source_id intentionally omitted
        })
        node_id = result.data["node"]["id"]

        with pytest.raises(ValueError, match="no source_id"):
            engine.sync_source(node_id)


class TestM1OfflineDegradation:
    def test_adapter_failure_uses_cache(self, tmp_path):
        """When adapter fails, bundle still works with cached data."""
        db_path = str(tmp_path / "test.db")
        events_path = str(tmp_path / "events.jsonl")
        narratives_dir = str(tmp_path / "narratives")

        engine = SpineEngine(
            db_path=db_path,
            events_path=events_path,
            narratives_dir=narratives_dir,
        )

        # Adapter that always fails
        failing_adapter = _MockGitHubAdapter()
        failing_adapter.sync_node = MagicMock(side_effect=ConnectionError("offline"))

        registry = AdapterRegistry()
        registry.register(failing_adapter)
        engine.set_adapter_registry(registry)

        # Create node
        result = engine.execute_tool("create_node", {
            "title": "Cached title",
            "node_type": "task",
            "is_root": True,
            "source": "github",
            "source_id": "octocat/repo#99",
        })
        node_id = result.data["node"]["id"]

        # Should not crash
        bundle = engine.get_context_bundle(user_focus=node_id)
        assert bundle.l2_focus is not None
        assert "Cached title" in bundle.l2_focus
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/ontanetwork/Documents/Onta Network/Founder OS/MemoryFPMS/V4" && python -m pytest tests/test_m1_e2e.py -v`
Expected: FAIL — SpineEngine doesn't have `set_adapter_registry` or working `sync_source`

- [ ] **Step 3: Wire adapters into SpineEngine**

Modify `fpms/spine/__init__.py`:

1. Add `adapter_registry` parameter to SpineEngine.__init__
2. Add `set_adapter_registry()` method
3. Implement `sync_source()` and `sync_all()`
4. Pass adapter_registry to BundleAssembler

Key changes:

```python
class SpineEngine:
    def __init__(
        self,
        db_path: str = "fpms/db/fpms.db",
        events_path: str = "fpms/events.jsonl",
        narratives_dir: str = "fpms/narratives",
    ):
        # ... existing init ...

        # Adapter registry (M1)
        self._adapter_registry = None

        # BundleAssembler gets adapter_registry=None initially
        self._bundle_assembler = BundleAssembler(
            store=self._store,
            # ... existing params ...
            adapter_registry=self._adapter_registry,
        )

    def set_adapter_registry(self, registry) -> None:
        """Set/replace the adapter registry. Updates BundleAssembler."""
        from .adapters.registry import AdapterRegistry
        self._adapter_registry = registry
        self._bundle_assembler._adapter_registry = registry

    def sync_source(self, node_id: str) -> Node:
        """Sync a single node from its external source adapter."""
        node = self._store.get_node(node_id)
        if node is None:
            raise ValueError(f"Node {node_id} not found")
        if node.source == "internal":
            return node
        if not node.source_id:
            raise ValueError(f"Node {node_id} has source='{node.source}' but no source_id")
        if self._adapter_registry is None or not self._adapter_registry.has(node.source):
            raise ValueError(f"No adapter for source '{node.source}'")

        adapter = self._adapter_registry.get(node.source)
        snapshot = adapter.sync_node(node.source_id)

        if snapshot is None:
            self._store.update_node(node_id, {"source_deleted": True})
            return self._store.get_node(node_id)

        from datetime import datetime, timezone
        update_fields = {
            "title": snapshot.title,
            "status": snapshot.status,
            "source_synced_at": datetime.now(timezone.utc).isoformat(),
        }
        if snapshot.assignee is not None:
            update_fields["owner"] = snapshot.assignee
        return self._store.update_node(node_id, update_fields)

    def sync_all(self, since: str | None = None) -> int:
        """Sync all external-source nodes. Returns count of synced nodes."""
        if self._adapter_registry is None:
            return 0

        count = 0
        for source_name in self._adapter_registry.list_sources():
            nodes = self._store.list_nodes(
                filters={"source": source_name, "archived": False},
                limit=1000,
            )
            adapter = self._adapter_registry.get(source_name)
            for node in nodes:
                if node.source_id:
                    try:
                        snapshot = adapter.sync_node(node.source_id)
                        if snapshot:
                            from datetime import datetime, timezone
                            self._store.update_node(node.id, {
                                "title": snapshot.title,
                                "status": snapshot.status,
                                "source_synced_at": datetime.now(timezone.utc).isoformat(),
                            })
                            count += 1
                    except Exception:
                        pass  # Skip failed syncs
        return count
```

- [ ] **Step 4: Run M1 integration tests**

Run: `cd "/Users/ontanetwork/Documents/Onta Network/Founder OS/MemoryFPMS/V4" && python -m pytest tests/test_m1_e2e.py -v`
Expected: All passed

- [ ] **Step 5: Run full test suite**

Run: `cd "/Users/ontanetwork/Documents/Onta Network/Founder OS/MemoryFPMS/V4" && python -m pytest tests/ -v --tb=short`
Expected: All tests pass (existing + new M1 tests)

- [ ] **Step 6: Commit**

```bash
cd "/Users/ontanetwork/Documents/Onta Network/Founder OS/MemoryFPMS/V4"
git add fpms/spine/__init__.py tests/test_m1_e2e.py
git commit -m "feat(m1): wire adapters into SpineEngine with sync_source/sync_all"
```

---

### Task 7: M1 Acceptance Verification

**Files:**
- No new files — verification only

This task runs all acceptance scenarios from TASK-DECOMPOSITION.md §T-M1.4.

- [ ] **Step 1: Run full test suite**

Run: `cd "/Users/ontanetwork/Documents/Onta Network/Founder OS/MemoryFPMS/V4" && python -m pytest tests/ -v --tb=short 2>&1 | tail -20`
Expected: All tests pass

- [ ] **Step 2: Verify acceptance scenario 1 — GitHub node sync**

Covered by: `test_m1_e2e.py::TestM1CreateAndSync::test_create_github_node_and_get_context`

- [ ] **Step 3: Verify acceptance scenario 2 — Status change sync**

Covered by: `test_m1_e2e.py::TestM1CreateAndSync::test_sync_source_updates_node`

- [ ] **Step 4: Verify acceptance scenario 3 — Mixed tree rollup**

Covered by: `test_m1_e2e.py::TestM1MixedTree::test_mixed_local_and_github_rollup`

- [ ] **Step 5: Verify acceptance scenario 4 — Offline degradation**

Covered by: `test_m1_e2e.py::TestM1OfflineDegradation::test_adapter_failure_uses_cache`
Also: `test_bundle_cross_source.py::TestCrossSourceL2::test_l2_uses_cache_when_adapter_fails`

- [ ] **Step 6: Verify acceptance scenario 5 — Assembly trace with sync info**

Covered by: `test_bundle_cross_source.py::TestAssemblyTraceSyncStatus::test_trace_includes_sync_info`

- [ ] **Step 7: Verify backward compatibility**

Covered by: `test_bundle_cross_source.py::TestCrossSourceL2::test_l2_no_registry_still_works`
All existing v0/v1 tests must still pass without adapter_registry.

- [ ] **Step 8: Final commit — update ROADMAP**

```bash
cd "/Users/ontanetwork/Documents/Onta Network/Founder OS/MemoryFPMS/V4"
# Update ROADMAP.md to mark M1 as complete
git add 4-implementation/ROADMAP.md
git commit -m "docs: mark M1 GitHub Integration as complete in ROADMAP"
```

---

## Dependency Graph

```
Task 1 (NodeSnapshot/SourceEvent) ──┐
                                     ├── Task 4 (GitHubAdapter)
Task 2 (BaseAdapter ABC) ───────────┤
                                     ├── Task 5 (Cross-source bundle.py)
Task 3 (AdapterRegistry) ───────────┤
                                     └── Task 6 (SpineEngine wiring)
                                              │
                                              └── Task 7 (Acceptance)
```

**Parallelizable batches:**
- **Batch 1**: Task 1 + Task 2 + Task 3 (all independent)
- **Batch 2**: Task 4 (depends on 1+2) + Task 5 (depends on 1+2+3) — can partially parallelize
- **Batch 3**: Task 6 (depends on 3+4+5)
- **Batch 4**: Task 7 (depends on all)
