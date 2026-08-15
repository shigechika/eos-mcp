# Reference

## `health_check()`

Seven keys are present on every call:

| Key | Meaning |
|---|---|
| `status` | `healthy` / `degraded` / `error` |
| `service` | Always `eos-mcp` |
| `version` | Package version |
| `config_path` | Resolved `config.ini` path (present even when the load failed, so callers can see where it looked) |
| `device_count` | Number of `[hostname]` sections found |
| `tags` | Sorted, deduplicated `tags =` values across all devices |
| `config` | `ok` / `error` / `missing` |

`detail` is added only on `degraded` or `error`, carrying the reason (a
missing file, or a `config.ini` parse error).

Lightweight by design: it only reads and parses `config.ini` — it does
**not** open any eAPI/pyeapi connection to an EOS device, so it is safe to
call against a large fleet without touching the network. Every other tool
needs a real, populated `config.ini` at the resolved path to do anything.

## Tool index

| Tool | Purpose |
|---|---|
| `get_router_list(tags=None)` | List devices registered in `config.ini`, optionally filtered by tag |
| `get_device_facts(hostname)` | Model, serial, EOS version, hardware revision, uptime, memory, MAC, architecture |
| `get_device_facts_batch(hostnames=None, tags=None, max_workers=5)` | Same facts for multiple devices in parallel |
| `get_version(hostname)` | Model + EOS version (quick connectivity check) |
| `run_command(hostname, command)` | **Unrestricted.** Run one enable-mode command on one device |
| `run_commands(hostname, commands)` | **Unrestricted.** Run multiple enable-mode commands on one device |
| `run_command_batch(command, hostnames=None, tags=None, max_workers=5)` | **Unrestricted.** Run one command across multiple devices in parallel |
| `run_commands_batch(commands, hostnames=None, tags=None, max_workers=5)` | **Unrestricted.** Run multiple commands across multiple devices in parallel |
| `get_config(hostname)` | Retrieve running-config |
| `get_config_diff(hostname, rollback_id=1)` | Diff running-config vs. the Nth rollback checkpoint |
| `list_config_sessions(hostname)` | List configure sessions and their state (pending / pendingCommitTimer / completed) |
| `push_config(hostname, config_lines, session_name="mcp-push", dry_run=True, commit_timer=300)` | **Writes.** Push config via a named configure session; dry-run by default |
| `confirm_config_session(hostname, session_name="mcp-push")` | **Writes.** Finalize a pending commit-timer session |
| `abort_config_session(hostname, session_name="mcp-push")` | **Writes.** Discard a pending session |
| `collect_tech_support(hostname)` | Collect `show tech-support` output (large, 30+ seconds) |
| `daily_brief(hostnames=None, tags=None, max_workers=5, since_hours=24)` | Morning fleet health check: environment, errdisabled interfaces, uptime, MLAG, recent syslog alerts |

"Unrestricted" tools accept and execute any enable-mode command text
verbatim — see [Setup → Write operations](setup.md#write-operations) for
what that means in practice and what gates it.

## `daily_brief`

Runs `check_health()` against every resolved device in parallel and renders
one Markdown report: per-device `CRITICAL` / `WARNING` / `OK` status
(environment sensors, errdisabled interfaces, MLAG state, memory, and
syslog alerts matching BGP/OSPF/STP/LACP/MLAG/link-down patterns within the
last `since_hours` hours), followed by a fleet-wide summary count. A
connection failure to a device renders as a `CRITICAL: connection failed`
line for that device rather than dropping it from the report silently.

Targets are resolved from `hostnames`, `tags`, or both; if neither is given,
every device in `config.ini` is used.

## `get_config_diff`

`rollback_id=1` (the default) diffs against the most recent rollback
checkpoint; a higher `rollback_id` reaches further back. Diffing against
startup-config requires EOS 4.30+ — older releases fall back gracefully.

## CLI

```bash
eos-mcp                              # start the MCP server (stdio; default, no arguments)
eos-mcp -V | --version                # print version and exit
eos-mcp -h | --help                   # show usage
eos-mcp --check                       # verify config.ini and list devices, then exit
eos-mcp --check --check-host HOST     # also open an eAPI connection to HOST
```

Exit codes for `--check` / `--check-host`: `0` success, `1` a configuration
error (`config.ini` missing or unparsable), `2` a host-connection error
(host not found in config, or the eAPI call itself failed).

## TLS compatibility

EOS 4.28.x combined with Python's stricter default TLS policy (notably
under Python 3.14) can raise `SSLV3_ALERT_HANDSHAKE_FAILURE`. eos-mcp
patches the SSL context at import time (`SECLEVEL=0`, minimum TLS 1.0) so
older devices stay reachable without operator intervention. `verify = false`
is the default in `config.ini.example` for the same reason — most fleets in
the wild run internal, self-signed eAPI certificates.
