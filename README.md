<!-- mcp-name: io.github.shigechika/eos-mcp -->

# eos-mcp

MCP server for Arista EOS device operations via eAPI.

Exposes EOS show commands, running-config retrieval, configuration push
(via configure session with commit timer), and tech-support collection
to MCP-compatible AI assistants.

## Installation

```bash
pip install eos-mcp
```

## Configuration

Copy `config.ini.example` to `~/.config/eos-mcp/config.ini` and fill in credentials:

```ini
[DEFAULT]
username = admin
password = yourpassword
transport = https
verify = false

[switch1.example.com]
tags = main,dc1

[switch2.example.com]
tags = main,dc1
```

Config file discovery order:
1. `EOS_MCP_CONFIG` environment variable
2. `./config.ini` (current directory)
3. `~/.config/eos-mcp/config.ini`

(Individual MCP tool calls may also override the path via a `config_path`
parameter.)

## Usage

```bash
# Verify config and list devices
eos-mcp --check

# Test connectivity to a specific host
eos-mcp --check --check-host switch1.example.com

# Start MCP server (stdio transport)
eos-mcp
```

## Tools

| Tool | Description |
|---|---|
| `health_check` | Report server version and config status (lightweight; does NOT connect to devices) |
| `get_router_list` | List registered devices (optional tag filter) |
| `get_device_facts` | Return structured facts for one device (model, serial, EOS version, uptime, memory) |
| `get_device_facts_batch` | Return device facts for multiple devices in parallel |
| `get_version` | Return EOS version string (quick connectivity check) |
| `run_command` | Run a single enable-mode command on one device |
| `run_commands` | Run multiple enable-mode commands on one device |
| `run_command_batch` | Run an enable-mode command on multiple devices in parallel |
| `run_commands_batch` | Run multiple enable-mode commands on multiple devices in parallel |
| `get_config` | Retrieve running-config |
| `get_config_diff` | Show config diff vs rollback checkpoint |
| `list_config_sessions` | List configure sessions and their state |
| `push_config` | Push config via configure session (dry_run=True by default) |
| `confirm_config_session` | Confirm a pending commit timer session |
| `abort_config_session` | Abort a pending session |
| `collect_tech_support` | Collect show tech-support output |
| `daily_brief` | Health check (environment, errdisabled, uptime, MLAG, recent syslog alerts) across multiple devices |

## Development

### Live smoke test

Unit tests check logic against fixtures; they cannot tell you that a tool has
stopped returning real data. `scripts/smoke_test.py` runs **every registered
tool** against the configured devices and fails on empty, malformed or error
answers:

```bash
# uses the same inventory file as the server (EOS_MCP_CONFIG)
uv run python scripts/smoke_test.py
uv run python scripts/smoke_test.py --only facts --traceback
```

- **Read-only.** `push_config`, `confirm_config_session` and
  `abort_config_session` are skipped by name, and a test enforces that.
  `collect_tech_support` is skipped too — it changes nothing, but it is minutes
  of device CPU for an answer no assertion would read. The command-running
  tools are exercised with `show version`: they accept enable-mode commands in
  general, and a smoke test must not be the thing that types one that matters.
- **No payloads in the report.** Tool names and statuses only; error text is
  redacted too, since every error here is prefixed with the device it came from
  and the payloads are configuration.
- **Nothing estate-specific in the specs.** The device the per-host tools need
  is discovered at run time from the configured inventory, and skipped when it
  is empty. Two tests keep it that way: one refuses those parameters as
  literals, the other bans anything address-shaped anywhere in the file,
  because this repository is public.
- Every probe refuses the `Error (<host>): ...` line these tools return in
  place of raising — otherwise an unreachable device would read as a
  successful call.
- CI enforces the cheap half: a tool registered without a probe spec fails the
  build (`tests/test_smoke_probes.py`), so adding a tool forces the question
  "how would we know it works?".
- `scripts/smoke_harness.py` is the engine and holds no EOS knowledge: it is
  kept identical across the servers that share it, so fix engine bugs once and
  sync the file rather than patching this copy.

## Requirements

- Python >= 3.10
- Arista EOS with eAPI enabled (`management api http-commands`)
- Network access to port 443 (HTTPS) on target devices

## License

Apache-2.0
