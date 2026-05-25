"""Unit tests for eapi helpers (no live device required)."""

import pytest

from eos_mcp.eapi import _timer_str, clear_cache


def test_timer_str_basic():
    assert _timer_str(0) == "00:00:00"
    assert _timer_str(300) == "00:05:00"
    assert _timer_str(3661) == "01:01:01"
    assert _timer_str(86400) == "24:00:00"


def test_clear_cache_empty_string_does_not_wipe_all(monkeypatch):
    """clear_cache('') must not clear all entries (falsy-string guard fix)."""
    import eos_mcp.eapi as eapi_mod

    fake_cache = {"host1": object(), "host2": object()}
    monkeypatch.setattr(eapi_mod, "_cache", fake_cache)

    clear_cache("")
    assert len(fake_cache) == 2, "clear_cache('') should not wipe the entire cache"


def test_clear_cache_none_wipes_all(monkeypatch):
    import eos_mcp.eapi as eapi_mod

    fake_cache = {"host1": object(), "host2": object()}
    monkeypatch.setattr(eapi_mod, "_cache", fake_cache)

    clear_cache(None)
    assert len(fake_cache) == 0


def test_clear_cache_specific_host(monkeypatch):
    import eos_mcp.eapi as eapi_mod

    sentinel = object()
    fake_cache = {"host1": sentinel, "host2": object()}
    monkeypatch.setattr(eapi_mod, "_cache", fake_cache)

    clear_cache("host1")
    assert "host1" not in fake_cache
    assert "host2" in fake_cache
