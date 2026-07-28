# CLAUDE.md

## Overview

MCP server for Arista EOS network devices, exposing show commands, config
retrieval/push, tech-support collection, and a daily health-check brief to AI
assistants via eAPI (pyeapi). Transport is stdio only — no HTTP transport is
exposed by this server; front it with a dedicated stdio-to-HTTP bridge (e.g.
`mcp-stdio`) if HTTP access is needed.

## Commands

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest -v                     # all tests
.venv/bin/pytest -v tests/test_eapi.py  # eapi helpers only
.venv/bin/ruff check .                  # lint (gated in CI)
.venv/bin/ruff format --check .         # format (gated in CI)
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
- `eos_mcp/config.py` — XDG-style `config.ini` loader/discovery (per-call
  `config_path` tool parameter > `EOS_MCP_CONFIG` env var > `./config.ini` >
  `~/.config/eos-mcp/config.ini`); `get_creds`/`get_hosts` read
  per-host `[section]` credentials/tags with `[DEFAULT]` fallback.
- `eos_mcp/__main__.py` — argparse CLI: `--check`/`--check-host` (config
  validation, exits before the server ever starts), then `mcp.run(transport="stdio")`.
- Note: `eapi.get_node()` calls `pyeapi.connect()` without `return_node=True`,
  so it actually returns a pyeapi `EapiConnection`, not a `Node` (the type
  hint says `Node`).

## Conventions

- Every device-touching tool wraps the call in `try/except Exception` and
  calls `eapi.clear_cache(hostname)` on failure (evicts the cached
  connection so the next call reconnects) instead of raising. Single-host
  tools (`get_device_facts`, `run_command(s)`, `push_config`, etc.) return
  `f"Error ({hostname}): {e}"`; the `_batch` tools return a per-host
  `f"Error: {exc}"` line labelled separately by hostname; `daily_brief`
  likewise returns a **Markdown string** (never a dict) — it assembles the
  per-host results (each internally an `{"anomalies": [...], "info": {}}`
  dict) into `"\n".join(lines)`, and returns `f"Error: {e}"` on a
  config-load failure.
- Tests use `unittest.mock` (`patch`/`MagicMock`) as the primary approach,
  plus pytest's `monkeypatch` for a few cache-state tests; pyeapi is mocked
  at the `eos_mcp.server._connect` / `eos_mcp.eapi.*` boundary.
- `verify=False` (no TLS cert verification) is the default in
  `get_creds`/`get_node`/`config.ini.example`, matching the TLS-compat shim
  above — both are deliberate, for reaching older EOS devices.
- `scripts/` holds the live smoke test: `smoke_test.py` (CLI), its per-tool
  specs in `smoke_probes.py`, and `smoke_harness.py` — the server-agnostic
  engine, kept identical across the servers that share it, so fix engine bugs
  once and sync the file rather than patching this copy (it is excluded from
  `ruff format` for that reason; `ruff check` still applies). It runs every
  registered tool against real devices (see README);
  `tests/test_smoke_probes.py` is the offline half and needs only the tool
  registry. Adding a tool without a probe spec fails CI: decide when you add
  the tool how anyone would know it works. Probes never touch a
  config-changing tool, name no device (the hostname comes from an
  `args_factory` reading the inventory), and refuse the `Error (<host>): ...`
  line — otherwise an unreachable device reads as a successful call.
