"""Adapter layer — connects FPMS to external tools (GitHub, Notion, etc.)."""

from .base import BaseAdapter
from .registry import AdapterRegistry
from .notion_adapter import NotionAdapter

__all__ = ["BaseAdapter", "AdapterRegistry", "NotionAdapter"]
