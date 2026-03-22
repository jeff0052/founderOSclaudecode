"""NotionAdapter — sync Notion pages/databases as FocalPoint cognitive nodes.

Uses httpx for HTTP requests. Stateless except for configuration.
All caching is handled by the caller (Store/BundleAssembler).
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

import httpx

from ..models import NodeSnapshot, SourceEvent
from .base import BaseAdapter

_DEFAULT_STATUS_MAP: Dict[str, str] = {
    "Not started": "inbox",
    "In progress": "active",
    "Done": "done",
}

_API_BASE = "https://api.notion.com/v1"
_NOTION_VERSION = "2022-06-28"
_TIMEOUT = 10.0


class NotionAdapter(BaseAdapter):
    """Adapter for Notion pages and databases.

    Args:
        token: Notion integration token (starts with ntn_ or secret_).
        default_database_id: Default database ID for list_updates queries.
        status_map: Custom Notion status name -> FocalPoint status mapping.
        timeout: HTTP request timeout in seconds.
    """

    def __init__(
        self,
        token: str,
        default_database_id: str = "",
        status_map: Optional[Dict[str, str]] = None,
        timeout: float = _TIMEOUT,
    ) -> None:
        self._token = token
        self._default_database_id = default_database_id
        self._status_map = status_map or dict(_DEFAULT_STATUS_MAP)
        self._timeout = timeout

    @property
    def source_name(self) -> str:
        return "notion"

    def sync_node(self, source_id: str) -> Optional[NodeSnapshot]:
        """Pull latest state for a Notion page.

        Args:
            source_id: Notion page UUID.

        Returns:
            NodeSnapshot with mapped fields, or None if 404.

        Raises:
            ConnectionError: On network timeout.
            PermissionError: On 401/403.
            ValueError: On empty source_id.
        """
        page_id = self._parse_source_id(source_id)
        url = f"{_API_BASE}/pages/{page_id}"

        try:
            resp = self._get(url)
        except httpx.TimeoutException:
            raise ConnectionError(
                f"Notion API timeout for page {source_id}. "
                "Check network or increase timeout."
            )

        if resp.status_code == 404:
            return None

        if resp.status_code in (401, 403):
            raise PermissionError(
                f"Notion API auth failed for page {source_id} "
                f"(HTTP {resp.status_code}). Check your integration token."
            )

        resp.raise_for_status()
        data = resp.json()

        properties = data.get("properties", {})
        title = self._extract_title(properties)
        status = self._extract_status(properties)
        assignee = self._extract_assignee(properties)

        return NodeSnapshot(
            source="notion",
            source_id=data.get("id", source_id),
            title=title,
            status=self.map_status(status) if status else "inbox",
            source_url=data.get("url"),
            assignee=assignee,
            updated_at=data.get("last_edited_time"),
            labels=[],
            raw=data,
        )

    def list_updates(self, since: Optional[datetime] = None) -> List[SourceEvent]:
        """Query the default database for recently updated pages.

        Args:
            since: Only return pages edited after this timestamp.

        Returns:
            List of SourceEvent sorted by timestamp ascending.
        """
        if not self._default_database_id:
            return []

        url = f"{_API_BASE}/databases/{self._default_database_id}/query"
        body: dict = {}

        if since is not None:
            body["filter"] = {
                "timestamp": "last_edited_time",
                "last_edited_time": {
                    "after": since.isoformat(),
                },
            }

        body["sorts"] = [
            {"timestamp": "last_edited_time", "direction": "ascending"}
        ]

        try:
            resp = self._post(url, json=body)
        except httpx.TimeoutException:
            raise ConnectionError(
                f"Notion API timeout querying database {self._default_database_id}."
            )

        if resp.status_code != 200:
            return []

        results = resp.json().get("results", [])
        events: List[SourceEvent] = []

        for page in results:
            page_id = page.get("id", "")
            properties = page.get("properties", {})
            title = self._extract_title(properties)
            ts = page.get("last_edited_time", "")

            events.append(SourceEvent(
                source="notion",
                source_id=page_id,
                event_type="page_updated",
                timestamp=ts,
                data={"title": title},
            ))

        events.sort(key=lambda e: e.timestamp)
        return events

    def write_status(self, source_id: str, new_status: str) -> None:
        """Update Notion page status property.

        Args:
            source_id: Notion page UUID
            new_status: FocalPoint status (done→Done, active→In progress, etc.)
        """
        page_id = self._parse_source_id(source_id)
        url = f"{_API_BASE}/pages/{page_id}"
        notion_status = self._reverse_map_status(new_status)

        try:
            resp = self._patch(url, json={
                "properties": {
                    "Status": {"status": {"name": notion_status}}
                }
            })
        except httpx.TimeoutException:
            raise ConnectionError(
                f"Notion API timeout writing status for page {source_id}."
            )
        resp.raise_for_status()

    def write_comment(self, source_id: str, text: str) -> None:
        """Append a comment block to a Notion page.

        Args:
            source_id: Notion page UUID
            text: Comment text
        """
        page_id = self._parse_source_id(source_id)
        url = f"{_API_BASE}/blocks/{page_id}/children"

        try:
            resp = self._patch(url, json={
                "children": [{
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{"type": "text", "text": {"content": text}}]
                    }
                }]
            })
        except httpx.TimeoutException:
            raise ConnectionError(
                f"Notion API timeout writing comment for page {source_id}."
            )
        resp.raise_for_status()

    def map_status(self, notion_status: str) -> str:
        """Map Notion status name to FocalPoint status. Unknown -> inbox."""
        return self._status_map.get(notion_status, "inbox")

    def _reverse_map_status(self, fp_status: str) -> str:
        """Map FocalPoint status back to Notion status name."""
        reverse = {v: k for k, v in self._status_map.items()}
        return reverse.get(fp_status, "Not started")

    # --- Private helpers ---

    def _get(self, url: str, params: Optional[dict] = None) -> httpx.Response:
        """Make authenticated GET request to Notion API."""
        return httpx.get(
            url, headers=self._headers(), params=params, timeout=self._timeout
        )

    def _post(self, url: str, json: Optional[dict] = None) -> httpx.Response:
        """Make authenticated POST request to Notion API."""
        return httpx.post(
            url, headers=self._headers(), json=json, timeout=self._timeout
        )

    def _patch(self, url: str, json: Optional[dict] = None) -> httpx.Response:
        """Make authenticated PATCH request to Notion API."""
        return httpx.patch(
            url, headers=self._headers(), json=json, timeout=self._timeout
        )

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._token}",
            "Notion-Version": _NOTION_VERSION,
            "Content-Type": "application/json",
        }

    def _parse_source_id(self, source_id: str) -> str:
        """Validate and return page ID. Notion page IDs are UUIDs."""
        if not source_id or not source_id.strip():
            raise ValueError("source_id cannot be empty")
        return source_id.strip()

    def _extract_title(self, properties: dict) -> str:
        """Extract title from Notion page properties."""
        for prop in properties.values():
            if prop.get("type") == "title":
                title_items = prop.get("title", [])
                if title_items:
                    return "".join(item.get("plain_text", "") for item in title_items)
        return "Untitled"

    def _extract_status(self, properties: dict) -> Optional[str]:
        """Extract status from Notion page properties (status or select type)."""
        for prop in properties.values():
            if prop.get("type") == "status":
                status_obj = prop.get("status")
                if status_obj:
                    return status_obj.get("name")
            elif prop.get("type") == "select":
                select_obj = prop.get("select")
                if select_obj:
                    return select_obj.get("name")
        return None

    def _extract_assignee(self, properties: dict) -> Optional[str]:
        """Extract first assignee from Notion people property."""
        for prop in properties.values():
            if prop.get("type") == "people":
                people = prop.get("people", [])
                if people:
                    return people[0].get("name")
        return None
