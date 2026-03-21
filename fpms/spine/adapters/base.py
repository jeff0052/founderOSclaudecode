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
        ...

    @abstractmethod
    def list_updates(self, since: Optional[datetime] = None) -> List[SourceEvent]:
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
