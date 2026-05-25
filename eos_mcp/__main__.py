"""Allow running as: python -m eos_mcp"""

from __future__ import annotations

import argparse
import os
import sys

from eos_mcp import __version__
from eos_mcp import config as cfg_mod
from eos_mcp import eapi
from eos_mcp.server import _ensure_config, mcp


def _check_config(check_host: str | None = None) -> int:
    """Verify config.ini is loadable and optionally test eAPI connectivity."""
    err = _ensure_config("")
    if err:
        print(f"Configuration error: {err}", file=sys.stderr)
        return 1

    cfg, path = cfg_mod.load("")
    hosts = cfg_mod.get_hosts(cfg)
    print(f"OK: config loaded from {path}")
    print(f"Devices ({len(hosts)}): {', '.join(hosts) if hosts else '(none)'}")

    if check_host is None:
        return 0

    if not cfg.has_section(check_host):
        print(f"Error: host '{check_host}' not found in config", file=sys.stderr)
        return 2

    try:
        creds = cfg_mod.get_creds(cfg, check_host)
        node = eapi.get_node(host=check_host, **creds)
        result = node.execute(["show version"])
        model = result["result"][0].get("modelName", "?")
        version = result["result"][0].get("version", "?")
        print(f"OK: connected to {check_host} (model={model}, EOS={version})")
    except Exception as e:
        print(f"Connection error ({check_host}): {e}", file=sys.stderr)
        return 2

    return 0


def main() -> None:
    """Entry point for console_scripts."""
    parser = argparse.ArgumentParser(
        prog="eos-mcp",
        description=(
            "MCP server for Arista EOS. Exposes EOS device operations "
            "(show commands, config management, tech-support collection) "
            "to AI assistants via eAPI."
        ),
        epilog=(
            "Config file discovery order: --config_path argument > "
            f"{cfg_mod.CONFIG_ENV_VAR} env var > ./config.ini > "
            "~/.config/eos-mcp/config.ini."
        ),
    )
    parser.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify config.ini is loadable and list devices, then exit.",
    )
    parser.add_argument(
        "--check-host",
        metavar="HOSTNAME",
        help="With --check, also open an eAPI connection to HOSTNAME.",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default="stdio",
        help="Transport protocol (default: stdio)",
    )
    args = parser.parse_args()

    if args.check or args.check_host:
        sys.exit(_check_config(args.check_host))

    try:
        mcp.run(transport=args.transport)
    except KeyboardInterrupt:
        os._exit(0)


if __name__ == "__main__":
    main()
