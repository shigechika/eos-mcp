"""Unit tests for server helpers (no live device required)."""

import configparser
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from eos_mcp import config as cfg_mod
from eos_mcp.server import (
    _resolve_hosts,
    get_device_facts,
    get_device_facts_batch,
    health_check,
    run_commands_batch,
)


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


# ---------------------------------------------------------------------------
# run_commands_batch
# ---------------------------------------------------------------------------


def _run_cmds_batch(commands: list[str], hosts: list[str]) -> str:
    """Call run_commands_batch with mocked eapi."""
    fake_output = "\n".join(f"--- {cmd} ---\noutput of {cmd}" for cmd in commands)
    with (
        patch("eos_mcp.server._connect", return_value=MagicMock()),
        patch("eos_mcp.eapi.run_shows", return_value=fake_output),
        patch("eos_mcp.server.cfg_mod.load", return_value=(MagicMock(), "/fake.ini")),
        patch("eos_mcp.server._resolve_hosts", return_value=hosts),
    ):
        return run_commands_batch(commands=commands, hostnames=hosts)


def test_run_commands_batch_labels_each_host():
    result = _run_cmds_batch(["show version"], ["sw1.example.com", "sw2.example.com"])
    assert "# sw1.example.com" in result
    assert "# sw2.example.com" in result


def test_run_commands_batch_includes_command_output():
    result = _run_cmds_batch(["show version", "show mlag"], ["sw1.example.com"])
    assert "show version" in result
    assert "show mlag" in result


def test_run_commands_batch_no_hosts_returns_error():
    with (
        patch("eos_mcp.server.cfg_mod.load", return_value=(MagicMock(), "/fake.ini")),
        patch("eos_mcp.server._resolve_hosts", return_value=[]),
    ):
        result = run_commands_batch(commands=["show version"])
    assert "No hosts resolved" in result


# ---------------------------------------------------------------------------
# health_check — lightweight, does NOT connect to devices
# ---------------------------------------------------------------------------

# Keys every health_check result must always carry, regardless of outcome.
_HEALTH_KEYS = {"status", "service", "version", "config_path", "device_count", "tags", "config"}


def test_health_check_healthy(cfg, tmp_path):
    """With a parseable config, status is healthy and devices/tags are counted."""
    ini = tmp_path / "config.ini"
    ini.write_text(
        textwrap.dedent("""\
            [DEFAULT]
            username = admin
            password = secret

            [sw1.example.com]
            tags = main,dc1

            [sw2.example.com]
            tags = backup,dc1
        """)
    )
    with patch("eos_mcp.server.cfg_mod.load", return_value=cfg_mod.load(str(ini))):
        result = health_check(config_path=str(ini))
    assert _HEALTH_KEYS.issubset(result)
    assert result["status"] == "healthy"
    assert result["service"] == "eos-mcp"
    assert result["config"] == "ok"
    assert result["device_count"] == 2
    assert result["tags"] == ["backup", "dc1", "main"]
    assert "detail" not in result


def test_health_check_does_not_connect():
    """health_check must never open a device connection (_connect/get_node)."""
    with (
        patch("eos_mcp.server.cfg_mod.load", side_effect=cfg_mod.load),
        patch("eos_mcp.server._connect") as connect,
        patch("eos_mcp.eapi.get_node") as get_node,
    ):
        # No config -> error path, but still must not touch devices.
        health_check(config_path="/definitely/missing.ini")
    connect.assert_not_called()
    get_node.assert_not_called()


def test_health_check_config_missing():
    """A missing config file yields status=error / config=missing with a detail."""
    result = health_check(config_path="/definitely/missing.ini")
    assert _HEALTH_KEYS.issubset(result)
    assert result["status"] == "error"
    assert result["config"] == "missing"
    assert result["device_count"] == 0
    assert result["tags"] == []
    assert "detail" in result
    assert result["config_path"] == "/definitely/missing.ini"


def test_health_check_parse_error_degrades():
    """An unparseable config degrades (config=error) rather than raising."""
    with patch("eos_mcp.server.cfg_mod.load", side_effect=configparser.Error("bad ini")):
        result = health_check(config_path="/some/config.ini")
    assert result["status"] == "degraded"
    assert result["config"] == "error"
    assert "detail" in result
