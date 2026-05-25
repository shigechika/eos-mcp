"""Configuration file loader (XDG-compliant).

Config file discovery order:
  1. explicit override argument
  2. EOS_MCP_CONFIG environment variable
  3. ./config.ini (current directory)
  4. ~/.config/eos-mcp/config.ini
"""

from __future__ import annotations

import configparser
import os
from pathlib import Path

CONFIG_ENV_VAR = "EOS_MCP_CONFIG"
_XDG_PATH = Path.home() / ".config" / "eos-mcp" / "config.ini"


def find_config_path(override: str = "") -> Path:
    """Resolve config file path using discovery order."""
    if override:
        return Path(override)
    env = os.environ.get(CONFIG_ENV_VAR, "")
    if env:
        return Path(env)
    local = Path("config.ini")
    if local.exists():
        return local
    return _XDG_PATH


def load(config_path: str = "") -> tuple[configparser.ConfigParser, Path]:
    """Load config and return (ConfigParser, resolved_path).

    Raises FileNotFoundError if the resolved path does not exist.
    """
    path = find_config_path(config_path)
    cfg = configparser.ConfigParser()
    read = cfg.read(path)
    if not read:
        raise FileNotFoundError(f"Config file not found: {path}")
    return cfg, path


def get_hosts(cfg: configparser.ConfigParser, tags: list[str] | None = None) -> list[str]:
    """Return section names (hostnames), optionally filtered by tags.

    A host matches if it has *any* of the requested tags.
    """
    result = []
    for section in cfg.sections():
        if tags:
            raw = cfg.get(section, "tags", fallback="")
            host_tags = {t.strip() for t in raw.split(",") if t.strip()}
            if not host_tags.intersection(tags):
                continue
        result.append(section)
    return result


def get_creds(cfg: configparser.ConfigParser, host: str) -> dict[str, str | bool]:
    """Return connection credentials for a host (falls back to DEFAULT)."""
    defaults = cfg.defaults()
    return {
        "username": cfg.get(host, "username", fallback=defaults.get("username", "")),
        "password": cfg.get(host, "password", fallback=defaults.get("password", "")),
        "transport": cfg.get(host, "transport", fallback=defaults.get("transport", "https")),
        "verify": cfg.getboolean(host, "verify", fallback=False),
    }
