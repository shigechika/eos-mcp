"""Unit tests for config loader (no live device required)."""

import configparser
import textwrap
from pathlib import Path

import pytest

from eos_mcp.config import (
    CONFIG_ENV_VAR,
    _XDG_PATH,
    find_config_path,
    get_creds,
    get_hosts,
    load,
)


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


# ---------------------------------------------------------------------------
# load
# ---------------------------------------------------------------------------


def test_load_returns_parser_and_path(tmp_config):
    cfg, path = load(str(tmp_config))
    assert isinstance(cfg, configparser.ConfigParser)
    assert path == tmp_config


def test_load_raises_when_missing(tmp_path):
    missing = str(tmp_path / "nonexistent.ini")
    with pytest.raises(FileNotFoundError):
        load(missing)


# ---------------------------------------------------------------------------
# get_hosts
# ---------------------------------------------------------------------------


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


def test_get_hosts_empty_tags_returns_all(tmp_config):
    """tags=[] is falsy → same as no filter → returns all hosts."""
    cfg, _ = load(str(tmp_config))
    assert get_hosts(cfg, []) == ["sw1.example.com", "sw2.example.com"]


# ---------------------------------------------------------------------------
# get_creds
# ---------------------------------------------------------------------------


def test_get_creds_defaults(tmp_config):
    cfg, _ = load(str(tmp_config))
    creds = get_creds(cfg, "sw1.example.com")
    assert creds["username"] == "admin"
    assert creds["password"] == "secret"
    assert creds["transport"] == "https"
    assert creds["verify"] is False


def test_get_creds_host_override(tmp_path):
    """Host-specific values must override DEFAULT."""
    ini = tmp_path / "config.ini"
    ini.write_text(
        textwrap.dedent("""\
            [DEFAULT]
            username = admin
            password = default_pass
            transport = https
            verify = false

            [special.example.com]
            username = ops
            password = ops_pass
            transport = http
            verify = true
        """)
    )
    cfg, _ = load(str(ini))
    creds = get_creds(cfg, "special.example.com")
    assert creds["username"] == "ops"
    assert creds["password"] == "ops_pass"
    assert creds["transport"] == "http"
    assert creds["verify"] is True


# ---------------------------------------------------------------------------
# find_config_path
# ---------------------------------------------------------------------------


def test_find_config_path_explicit_override(tmp_path, monkeypatch):
    monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)
    monkeypatch.chdir(tmp_path)
    override = str(tmp_path / "custom.ini")
    assert find_config_path(override) == Path(override)


def test_find_config_path_env_var(tmp_path, monkeypatch):
    monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)
    monkeypatch.chdir(tmp_path)  # no local config.ini
    env_path = str(tmp_path / "env_config.ini")
    monkeypatch.setenv(CONFIG_ENV_VAR, env_path)
    assert find_config_path() == Path(env_path)


def test_find_config_path_local_ini(tmp_path, monkeypatch):
    monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)
    (tmp_path / "config.ini").write_text("[DEFAULT]\n")
    monkeypatch.chdir(tmp_path)
    assert find_config_path() == Path("config.ini")


def test_find_config_path_xdg_fallback(tmp_path, monkeypatch):
    """When no override, no env var, and no local config.ini → XDG path."""
    monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)
    monkeypatch.chdir(tmp_path)  # no config.ini here
    assert find_config_path() == _XDG_PATH
