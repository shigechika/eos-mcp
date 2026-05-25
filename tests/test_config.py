"""Unit tests for config loader (no live device required)."""

import configparser
import textwrap
from pathlib import Path

import pytest

from eos_mcp.config import find_config_path, get_creds, get_hosts, load


@pytest.fixture()
def tmp_config(tmp_path: Path) -> Path:
    cfg = tmp_path / "config.ini"
    cfg.write_text(
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
        """)
    )
    return cfg


def test_load_returns_parser_and_path(tmp_config):
    cfg, path = load(str(tmp_config))
    assert isinstance(cfg, configparser.ConfigParser)
    assert path == tmp_config


def test_load_raises_when_missing():
    with pytest.raises(FileNotFoundError):
        load("/nonexistent/path/config.ini")


def test_get_hosts_no_filter(tmp_config):
    cfg, _ = load(str(tmp_config))
    hosts = get_hosts(cfg)
    assert hosts == ["sw1.example.com", "sw2.example.com"]


def test_get_hosts_tag_filter(tmp_config):
    cfg, _ = load(str(tmp_config))
    assert get_hosts(cfg, ["main"]) == ["sw1.example.com"]
    assert get_hosts(cfg, ["backup"]) == ["sw2.example.com"]
    assert get_hosts(cfg, ["dc1"]) == ["sw1.example.com", "sw2.example.com"]
    assert get_hosts(cfg, ["nonexistent"]) == []


def test_get_creds_defaults(tmp_config):
    cfg, _ = load(str(tmp_config))
    creds = get_creds(cfg, "sw1.example.com")
    assert creds["username"] == "admin"
    assert creds["password"] == "secret"
    assert creds["transport"] == "https"
    assert creds["verify"] is False
