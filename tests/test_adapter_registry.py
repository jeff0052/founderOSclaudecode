"""Tests for AdapterRegistry — register, get, list adapters."""

import pytest
from fpms.spine.adapters.base import BaseAdapter
from fpms.spine.adapters.registry import AdapterRegistry
from fpms.spine.models import NodeSnapshot


class _FakeAdapter(BaseAdapter):
    @property
    def source_name(self) -> str:
        return "fake"
    def sync_node(self, source_id):
        return NodeSnapshot(source="fake", source_id=source_id, title="Fake", status="active")
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
