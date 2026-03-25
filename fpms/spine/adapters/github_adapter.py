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
        status_map: Custom GitHub state -> FounderOS status mapping.
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

    def sync_node(self, source_id: str) -> Optional[NodeSnapshot]:
        """Pull latest state for a GitHub Issue/PR.

        Args:
            source_id: "owner/repo#number" or "#number" (uses default_repo).

        Returns:
            NodeSnapshot with mapped fields, or None if 404.

        Raises:
            ConnectionError: On network timeout.
            PermissionError: On 401/403.
            ValueError: On invalid source_id format.
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
        """Pull recent events from the default repo."""
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

            if since is not None and ts:
                try:
                    event_time = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    if event_time <= since:
                        continue
                except ValueError:
                    pass

            event_type = raw.get("type", "")
            payload = raw.get("payload", {})

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

        events.sort(key=lambda e: e.timestamp)
        return events

    def write_status(self, source_id: str, new_status: str) -> None:
        """Update GitHub Issue state (open/closed).

        Args:
            source_id: "owner/repo#number"
            new_status: FocalPoint status (done→closed, others→open)
        """
        owner, repo, number = self._parse_source_id(source_id)
        url = f"{_API_BASE}/repos/{owner}/{repo}/issues/{number}"
        gh_state = self._reverse_map_status(new_status)

        try:
            resp = self._patch(url, json={"state": gh_state})
        except httpx.TimeoutException:
            raise ConnectionError(
                f"GitHub API timeout writing status for {source_id}."
            )
        resp.raise_for_status()

    def write_comment(self, source_id: str, text: str) -> None:
        """Post a comment to a GitHub Issue/PR.

        Args:
            source_id: "owner/repo#number"
            text: Comment body
        """
        owner, repo, number = self._parse_source_id(source_id)
        url = f"{_API_BASE}/repos/{owner}/{repo}/issues/{number}/comments"

        try:
            resp = self._post(url, json={"body": text})
        except httpx.TimeoutException:
            raise ConnectionError(
                f"GitHub API timeout writing comment for {source_id}."
            )
        resp.raise_for_status()

    def map_status(self, github_state: str) -> str:
        """Map GitHub issue/PR state to FounderOS status. Unknown->inbox."""
        return self._status_map.get(github_state, "inbox")

    def _reverse_map_status(self, fp_status: str) -> str:
        """Map FocalPoint status back to GitHub state."""
        if fp_status in ("done", "dropped"):
            return "closed"
        return "open"

    def _get(self, url: str, params: Optional[dict] = None) -> httpx.Response:
        """Make authenticated GET request to GitHub API."""
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        return httpx.get(url, headers=headers, params=params, timeout=self._timeout)

    def _post(self, url: str, json: Optional[dict] = None) -> httpx.Response:
        """Make authenticated POST request to GitHub API."""
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        return httpx.post(url, headers=headers, json=json, timeout=self._timeout)

    def _patch(self, url: str, json: Optional[dict] = None) -> httpx.Response:
        """Make authenticated PATCH request to GitHub API."""
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        return httpx.patch(url, headers=headers, json=json, timeout=self._timeout)

    def _parse_source_id(self, source_id: str) -> tuple[str, str, int]:
        """Parse 'owner/repo#number' or '#number' into (owner, repo, number)."""
        match = re.match(r"^([^/]+)/([^#]+)#(\d+)$", source_id)
        if match:
            return match.group(1), match.group(2), int(match.group(3))

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
