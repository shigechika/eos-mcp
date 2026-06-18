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
1. `--config_path` argument
2. `EOS_MCP_CONFIG` environment variable
3. `./config.ini` (current directory)
4. `~/.config/eos-mcp/config.ini`

## Usage

```bash
# Verify config and list devices
eos-mcp --check

# Test connectivity to a specific host
eos-mcp --check --check-host switch1.example.com

# Start MCP server (stdio transport, default)
eos-mcp
```

## Tools

| Tool | Description |
|---|---|
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

## Requirements

- Python >= 3.10
- Arista EOS with eAPI enabled (`management api http-commands`)
- Network access to port 443 (HTTPS) on target devices

## License

Apache-2.0
