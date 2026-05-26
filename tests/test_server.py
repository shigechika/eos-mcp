"""Unit tests for server helpers (no live device required)."""

import configparser
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from eos_mcp import config as cfg_mod
from eos_mcp.server import _resolve_hosts, get_device_facts, get_device_facts_batch


@pytest.fixture()
def cfg(tmp_path: Path) -> configparser.ConfigParser:
    ini = tmp_path / "config.ini"
    ini.write_text(
        textwrap.dedent("""\
            [DEFAULT]
            username = admin
            password = secret
            transport = https
            verify = false

            [sw1.example.com]
            tags = main,dc1

            [sw2.example.com]
            tags = backup,dc1

            [sw3.example.com]
            tags = main,dc2
        """)
    )
    parser, _ = cfg_mod.load(str(ini))
    return parser


# ---------------------------------------------------------------------------
# _resolve_hosts
# ---------------------------------------------------------------------------


def test_resolve_hosts_by_hostname_only(cfg):
    result = _resolve_hosts(cfg, ["sw1.example.com"], None)
    assert result == ["sw1.example.com"]


def test_resolve_hosts_by_tags_only(cfg):
    result = _resolve_hosts(cfg, None, ["main"])
    assert result == ["sw1.example.com", "sw3.example.com"]


def test_resolve_hosts_by_tags_returns_sorted(cfg):
    result = _resolve_hosts(cfg, None, ["dc1"])
    assert result == sorted(result)


def test_resolve_hosts_combined_deduplicates(cfg):
    """A host given explicitly AND matched via tag appears only once."""
    result = _resolve_hosts(cfg, ["sw1.example.com"], ["main"])
    assert result.count("sw1.example.com") == 1
    assert "sw3.example.com" in result


def test_resolve_hosts_both_none_returns_empty(cfg):
    """_resolve_hosts does NOT fallback to all hosts when both params are None.

    daily_brief has its own separate fallback; _resolve_hosts itself is strict.
    """
    result = _resolve_hosts(cfg, None, None)
    assert result == []


def test_resolve_hosts_empty_lists_returns_empty(cfg):
    result = _resolve_hosts(cfg, [], [])
    assert result == []


def test_resolve_hosts_multiple_hostnames(cfg):
    result = _resolve_hosts(cfg, ["sw2.example.com", "sw3.example.com"], None)
    assert result == ["sw2.example.com", "sw3.example.com"]


# ---------------------------------------------------------------------------
# get_device_facts — uptime display
# ---------------------------------------------------------------------------

_FACTS_BASE = {
    "hostname": "sw1",
    "fqdn": "sw1",
    "model": "DCS-7050TX-64-R",
    "serial": "ABCD1234",
    "version": "4.28.13.1M",
    "hardware_revision": "01.00",
    "uptime_seconds": 0,
    "memory_total_kb": 4_000_000,
    "memory_free_kb": 2_000_000,
    "mac": "fc:bd:67:00:00:01",
    "architecture": "i686",
}


def _facts_result(uptime_seconds: int) -> str:
    """Call get_device_facts with mocked eapi, return formatted string."""
    facts = {**_FACTS_BASE, "uptime_seconds": uptime_seconds}
    with (
        patch("eos_mcp.server._connect", return_value=MagicMock()),
        patch("eos_mcp.eapi.get_device_facts", return_value=facts),
    ):
        return get_device_facts("sw1.example.com")


def test_get_device_facts_uptime_sub_1h_shows_minutes():
    assert "uptime:            5m" in _facts_result(300)


def test_get_device_facts_uptime_sub_1d_shows_hours():
    assert "uptime:            3h" in _facts_result(3 * 3600 + 30 * 60)


def test_get_device_facts_uptime_over_1d_shows_days_hours():
    assert "uptime:            1d 2h" in _facts_result(86400 + 2 * 3600)


def test_get_device_facts_uptime_no_leading_zero_days():
    result = _facts_result(3 * 3600)
    assert "0d" not in result
    assert "uptime:            3h" in result


# ---------------------------------------------------------------------------
# get_device_facts_batch — uptime display
# ---------------------------------------------------------------------------


def _batch_result(uptime_seconds: int) -> str:
    """Call get_device_facts_batch with mocked eapi, return formatted string."""
    facts = {**_FACTS_BASE, "uptime_seconds": uptime_seconds}
    with (
        patch("eos_mcp.server._connect", return_value=MagicMock()),
        patch("eos_mcp.eapi.get_device_facts", return_value=facts),
        patch("eos_mcp.server.cfg_mod.load", return_value=(MagicMock(), "/fake.ini")),
        patch(
            "eos_mcp.server._resolve_hosts",
            return_value=["sw1.example.com"],
        ),
    ):
        return get_device_facts_batch(hostnames=["sw1.example.com"])


def test_get_device_facts_batch_uptime_sub_1h_shows_minutes():
    assert "up=5m" in _batch_result(300)


def test_get_device_facts_batch_uptime_sub_1d_shows_hours():
    assert "up=3h" in _batch_result(3 * 3600)


def test_get_device_facts_batch_uptime_over_1d_shows_compact():
    assert "up=1d2h" in _batch_result(86400 + 2 * 3600)


def test_get_device_facts_batch_uptime_no_leading_zero_days():
    result = _batch_result(3 * 3600)
    assert "0d" not in result
