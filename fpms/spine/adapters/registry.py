"""AdapterRegistry — manages external tool adapter lifecycle."""

from __future__ import annotations

from typing import Dict, List

from .base import BaseAdapter


class AdapterRegistry:
    """Register, retrieve, and list external tool adapters."""

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
        return source in self._adapters

    def list_sources(self) -> List[str]:
        return list(self._adapters.keys())
