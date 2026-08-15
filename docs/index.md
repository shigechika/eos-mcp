# eos-mcp

MCP server for [Arista EOS](https://www.arista.com/en/products/eos) device
operations via eAPI (`pyeapi`).

Built for two things: a morning `daily_brief` across a fleet (environment,
errdisabled interfaces, uptime, MLAG, recent syslog alerts), and a set of
operational tools — show commands, config retrieval and diff, and a guarded
config-push workflow — for the moment you need to look at, or change, one
device.

## Tools by area

| Area | Tools |
|---|---|
| Inventory | `get_router_list`, `get_device_facts`, `get_device_facts_batch`, `get_version` |
| Commands | `run_command`, `run_commands`, `run_command_batch`, `run_commands_batch` |
| Configuration | `get_config`, `get_config_diff`, `list_config_sessions`, `push_config`, `confirm_config_session`, `abort_config_session` |
| Diagnostics | `collect_tech_support` |
| Morning patrol | `health_check`, `daily_brief` |

**Three tools change device state through a guarded path:** `push_config`,
`confirm_config_session`, `abort_config_session`. **`run_command` and its
batch/multi-command siblings are a second, unguarded write path** — nothing
in the server restricts them to `show ...` commands, so a caller can pass
`configure terminal ...` or `reload` and it runs verbatim. See
[Reference](reference.md) for the full breakdown of what gates each one.

## Design notes

**The only credential store is a local file.** Unlike a server that takes a
device username/password as plain environment variables, eos-mcp reads
`config.ini` — a `[DEFAULT]` section plus one `[hostname]` section per
device, holding the actual eAPI username, password, transport, and
`verify` setting for the fleet. Every tool except `health_check`'s
config-status probe needs a populated file at the resolved path
(`EOS_MCP_CONFIG` → `./config.ini` → `~/.config/eos-mcp/config.ini`) before
it can do anything.

**`push_config` defaults to dry-run.** It opens a named `configure session`,
stages the given lines, and — unless the caller explicitly passes
`dry_run=False` — shows the diff and aborts, so nothing commits. A real push
uses `commit timer`, so a session that is never finalized with
`confirm_config_session` rolls itself back on its own.

**TLS compatibility is a deliberate shim, not a workaround left in by
accident.** EOS 4.28.x under Python's stricter default TLS policy can fail
the handshake; eos-mcp patches the SSL context (`SECLEVEL=0`, minimum TLS
1.0) at import time so older devices stay reachable. `verify = false` is the
default in `config.ini.example` for the same reason.

## Next steps

- [Setup](setup.md) — install, `config.ini`, environment variables,
  registering with an MCP client
- [Reference](reference.md) — every tool, the write-tool privilege gate,
  CLI, exit codes
