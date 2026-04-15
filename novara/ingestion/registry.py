"""Adapter registry — discovers and stores all registered source adapters."""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from novara.ingestion.base_adapter import BaseAdapter

log = structlog.get_logger(__name__)

_registry: dict[str, type[BaseAdapter]] = {}


def register(adapter_cls: type[BaseAdapter]) -> type[BaseAdapter]:
    """Class decorator that registers an adapter in the global registry.

    Usage::

        @register
        class RoyalRoadAdapter(BaseAdapter):
            SITE_KEY = "royalroad"
            ...
    """
    key = adapter_cls.SITE_KEY
    if key in _registry:
        raise ValueError(
            f"Adapter for site key {key!r} is already registered. "
            f"Existing: {_registry[key].__name__}, new: {adapter_cls.__name__}"
        )
    _registry[key] = adapter_cls
    log.debug("adapter_registered", site_key=key, adapter=adapter_cls.__name__)
    return adapter_cls


def get_adapter(site_key: str) -> type[BaseAdapter]:
    """Return the registered adapter class for the given site key.

    Raises:
        KeyError: if no adapter is registered for site_key.
    """
    if site_key not in _registry:
        raise KeyError(
            f"No adapter registered for site key {site_key!r}. "
            f"Available: {sorted(_registry)}"
        )
    return _registry[site_key]


def list_adapters() -> dict[str, type[BaseAdapter]]:
    """Return a copy of the full registry."""
    return dict(_registry)


def autodiscover() -> None:
    """Import all modules in novara/ingestion/adapters/ to trigger registration.

    Called once at application startup.  Idempotent — safe to call multiple times.
    """
    adapters_pkg = Path(__file__).parent / "adapters"
    package_name = "novara.ingestion.adapters"

    for module_info in pkgutil.iter_modules([str(adapters_pkg)]):
        module_path = f"{package_name}.{module_info.name}"
        try:
            importlib.import_module(module_path)
            log.debug("adapter_module_loaded", module=module_path)
        except Exception:
            log.exception("adapter_module_load_failed", module=module_path)
