# CLAUDE.md

## Overview

MCP server for Arista EOS network devices, exposing show commands, config
retrieval/push, tech-support collection, and a daily health-check brief to AI
assistants via eAPI (pyeapi). Default transport is stdio; `--transport
streamable-http` is also supported.

## Commands

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest -v                     # all tests
.venv/bin/pytest -v tests/test_eapi.py  # eapi helpers only
.venv/bin/ruff check .                  # lint (not run in CI; local only)
```

## Architecture

- `eos_mcp/server.py` — `FastMCP("eos-mcp")` with tools: `health_check`,
  `get_router_list`, `get_device_facts`(`_batch`), `get_version`,
  `get_config`, `get_config_diff`, `run_command(s)`(`_batch`),
  `push_config`, `confirm_config_session`, `abort_config_session`,
  `list_config_sessions`, `collect_tech_support`, `daily_brief`.
- `eos_mcp/eapi.py` — thin pyeapi wrapper: connection cache keyed by
  hostname (`get_node`/`clear_cache`), `push_config` (configure session with
  dry-run/commit-timer), `check_health` (env/errdisabled/MLAG/syslog scan for
  `daily_brief`). Also patches `ssl._create_unverified_context` at import
  time (`SECLEVEL=0`, min TLS 1.0) so pyeapi's HTTPS transport can still
  reach older EOS releases (4.28.x) under Python's stricter default TLS
  policy — intentional compat shim, not a bug.
- `eos_mcp/config.py` — XDG-style `config.ini` loader/discovery
  (`--config_path` arg > `EOS_MCP_CONFIG` env var > `./config.ini` >
  `~/.config/eos-mcp/config.ini`); `get_creds`/`get_hosts` read
  per-host `[section]` credentials/tags with `[DEFAULT]` fallback.
- `eos_mcp/__main__.py` — argparse CLI: `--check`/`--check-host` (config
  validation, exits before the server ever starts) and `--transport
  stdio|streamable-http` for `mcp.run(...)`.
- Note: `eapi.get_node()` calls `pyeapi.connect()` without `return_node=True`,
  so it actually returns a pyeapi `EapiConnection`, not a `Node` (the type
  hint says `Node`).

## Conventions

- Every device-touching tool wraps the call in `try/except Exception`, calls
  `eapi.clear_cache(hostname)` on failure (evicts the cached connection so
  the next call reconnects), and returns `f"Error ({hostname}): {e}"`
  instead of raising.
- Tests use `unittest.mock` (`patch`/`MagicMock`) exclusively; pyeapi is
  mocked at the `eos_mcp.server._connect` / `eos_mcp.eapi.*` boundary.
- `verify=False` (no TLS cert verification) is the default in
  `get_creds`/`get_node`/`config.ini.example`, matching the TLS-compat shim
  above — both are deliberate, for reaching older EOS devices.
