"""Tests for the adapter registry."""

import pytest

from novara.ingestion.registry import autodiscover, get_adapter, list_adapters, register
from novara.ingestion.base_adapter import BaseAdapter


def test_autodiscover_loads_adapters() -> None:
    autodiscover()
    adapters = list_adapters()
    assert "royalroad" in adapters
    assert "wuxiaworld" in adapters


def test_get_adapter_returns_correct_class() -> None:
    autodiscover()
    cls = get_adapter("royalroad")
    assert cls.SITE_KEY == "royalroad"
    assert cls.SITE_NAME == "Royal Road"


def test_get_adapter_raises_for_unknown() -> None:
    with pytest.raises(KeyError, match="nonexistent_site"):
        get_adapter("nonexistent_site")


def test_register_decorator() -> None:
    # Use a unique key to avoid collision with existing adapters
    class _TestAdapter(BaseAdapter):
        SITE_KEY = "__test_register__"
        SITE_NAME = "Test"
        BASE_URL = "https://example.com"

        async def scrape_title(self, source_url):  # type: ignore
            pass

        async def scrape_chapter_listing(self, source_url):  # type: ignore
            pass

        async def scrape_chapter(self, chapter_url):  # type: ignore
            pass

    # Manually register without the decorator to avoid contaminating module state
    from novara.ingestion.registry import _registry
    _registry["__test_register__"] = _TestAdapter

    cls = get_adapter("__test_register__")
    assert cls is _TestAdapter

    # Clean up
    del _registry["__test_register__"]


def test_list_adapters_returns_copy() -> None:
    autodiscover()
    a = list_adapters()
    b = list_adapters()
    assert a is not b  # Should be a copy
