# Setup

## Install

```bash
pip install eos-mcp
```

From source:

```bash
git clone https://github.com/shigechika/eos-mcp.git
cd eos-mcp
uv sync            # or: pip install -e ".[dev]"
```

## config.ini

Copy `config.ini.example` to `~/.config/eos-mcp/config.ini` and fill in
credentials:

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

This file is the server's only credential mechanism — there is no
plain-string environment variable for a device username or password. Every
tool except `health_check`'s config-status probe loads it and fails without
a populated file at the resolved path.

Config file discovery order:

1. `EOS_MCP_CONFIG` environment variable
2. `./config.ini` (current directory)
3. `~/.config/eos-mcp/config.ini`

Individual MCP tool calls may also override the path via a `config_path`
parameter — still a local file path, not inline credentials.

## Verify before wiring it into anything

```bash
# Verify config.ini loads and list devices
eos-mcp --check

# Also open an eAPI connection to one host
eos-mcp --check --check-host switch1.example.com
```

Exit `0` means success; `1` is a configuration error (missing or unparsable
`config.ini`); `2` is a host-connection error (host not in config, or the
eAPI call itself failed). Running this once turns "the tool returns
nothing" into a question you have already answered.

## Register with an MCP client

### Claude Code (plugin)

This repository doubles as a single-plugin marketplace, so Claude Code can
install the server for you:

```
/plugin marketplace add shigechika/eos-mcp
/plugin install eos-mcp@eos-mcp
```

The plugin launches `uvx eos-mcp` and reads `EOS_MCP_CONFIG`, the same
variable described in [config.ini](#configini) above. Leave it unset and
the server falls through to its normal discovery order (`./config.ini`,
then `~/.config/eos-mcp/config.ini`). `/plugin install` only wires up the
server process — it cannot create the `config.ini` file or the per-device
eAPI credentials it holds; that file must already exist on the machine
running the plugin before any tool but `health_check` will succeed.

`uvx` must be on the `PATH` of the process that runs Claude Code — a login
shell usually has it, but a GUI-launched app may not; install
[uv](https://docs.astral.sh/uv/) system-wide if the plugin fails to start.

### Claude Code (manual)

`.mcp.json`:

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

### Direct execution

```bash
export EOS_MCP_CONFIG=~/.config/eos-mcp/config.ini
eos-mcp
```

## Write operations

Three tools change device state through a guarded path:

| Tool | API call | Gated by |
|---|---|---|
| `push_config` | Opens a `configure session <name>`, stages `config_lines`, then either `show session-config diffs` + `abort` (`dry_run=True`, the default) or `commit timer HH:MM:SS` (`dry_run=False`) — eAPI JSON-RPC Command API | The eAPI account's own EOS privilege level: it must be able to enter `configure session` mode (effectively privilege 15 / enable access). `dry_run=True` by default means an accidental call without an explicit `dry_run=False` only shows a diff and aborts. |
| `confirm_config_session` | `configure session <name> commit` — finalizes a pending commit-timer session started by `push_config` | Same EOS account privilege requirement as `push_config`. |
| `abort_config_session` | `configure session <name> abort` — discards a pending session | Same EOS account privilege requirement as `push_config`. |

Give the `config.ini` account for a device a lower-privilege, show-only
role and these three tools fail against the EOS API instead of writing;
every read-only tool for that device keeps working.

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

## Next

[Reference](reference.md) covers the full tool index, the `health_check`
contract, and the CLI.
