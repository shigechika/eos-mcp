<!-- mcp-name: io.github.shigechika/eos-mcp -->

# eos-mcp

English | [日本語](README.ja.md)

MCP server for Arista EOS device operations via eAPI.

Exposes EOS show commands, running-config retrieval, configuration push
(via configure session with commit timer), and tech-support collection
to MCP-compatible AI assistants.

Documentation: <https://shigechika.github.io/eos-mcp/>

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

### Write operations

Three tools change device state through a guarded path:

| Tool | API call | Gated by |
|---|---|---|
| `push_config` | Opens a `configure session <name>`, stages `config_lines`, then either `show session-config diffs` + `abort` (`dry_run=True`, the default) or `commit timer HH:MM:SS` (`dry_run=False`) — eAPI JSON-RPC Command API | The eAPI account's own EOS privilege level: it must be able to enter `configure session` mode (effectively privilege 15 / enable access). `dry_run=True` by default means an accidental call without an explicit `dry_run=False` only shows a diff and aborts. |
| `confirm_config_session` | `configure session <name> commit` — finalizes a pending commit-timer session started by `push_config` | Same EOS account privilege requirement as `push_config`. |
| `abort_config_session` | `configure session <name> abort` — discards a pending session | Same EOS account privilege requirement as `push_config`. |

Give the `config.ini` account for a device a lower-privilege, show-only role
and these three tools fail against the EOS API instead of writing; every
read-only tool for that device keeps working.

**`run_command`, `run_commands`, `run_command_batch`, and
`run_commands_batch` are not restricted to `show ...` commands**, despite
being documented and grouped as command runners. Nothing in the server
validates or whitelists the command text — it is passed to the eAPI Command
API verbatim — so these tools can execute arbitrary enable-mode EOS
commands, including `configure terminal ...` or `reload`, on any configured
device (a single host, or fleet-wide via `tags` in the `_batch` variants).
This is gated by the same EOS account privilege as `push_config`, but
without `push_config`'s `dry_run` / commit-timer safety net — a de facto
second write path worth remembering when deciding how privileged a device's
`config.ini` account should be.

## Usage

### Claude Code (plugin)

This repository doubles as a single-plugin marketplace, so Claude Code can
install the server for you:

```
/plugin marketplace add shigechika/eos-mcp
/plugin install eos-mcp@eos-mcp
```

The plugin launches `uvx eos-mcp` and reads `EOS_MCP_CONFIG`, the same
variable described in [Configuration](#configuration). Leave it unset and
the server falls through to its normal discovery order (`./config.ini`,
then `~/.config/eos-mcp/config.ini`). `/plugin install` only wires up the
server process — it cannot create the `config.ini` file or the per-device
eAPI credentials it holds; that file must already exist on the machine
running the plugin before any tool but `health_check` will succeed.

`uvx` must be on the `PATH` of the process that runs Claude Code — a login
shell usually has it, but a GUI-launched app may not; install
[uv](https://docs.astral.sh/uv/) system-wide if the plugin fails to start.

### Claude Code (manual)

In `.mcp.json`:

```json
{
  "mcpServers": {
    "eos-mcp": {
      "type": "stdio",
      "command": "eos-mcp"
    }
  }
}
```

Add `"env": { "EOS_MCP_CONFIG": "..." }` only if `config.ini` is not at one
of the default discovery locations above.

### Claude Desktop

Add the same entry to `claude_desktop_config.json`.

### From a shell

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