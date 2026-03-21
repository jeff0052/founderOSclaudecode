"""Adapter layer — connects FPMS to external tools (GitHub, Notion, etc.)."""

from .base import BaseAdapter
from .registry import AdapterRegistry

__all__ = ["BaseAdapter", "AdapterRegistry"]
