"""Unit tests for server helpers (no live device required)."""

import configparser
import textwrap
from pathlib import Path

import pytest

from eos_mcp import config as cfg_mod
from eos_mcp.server import _resolve_hosts


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
