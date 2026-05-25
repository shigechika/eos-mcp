# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-05-25

### Added

- 15 MCP tools for Arista EOS device operations via eAPI:
  `get_router_list`, `get_version`, `get_device_facts`, `get_device_facts_batch`,
  `run_command`, `run_commands`, `run_command_batch`,
  `get_config`, `get_config_diff`,
  `list_config_sessions`, `push_config`, `confirm_config_session`, `abort_config_session`,
  `collect_tech_support`, `daily_brief`
- TLS compatibility patch for EOS 4.28.x + Python 3.14 (`SSLV3_ALERT_HANDSHAKE_FAILURE` workaround)
- Connection cache per hostname to avoid redundant eAPI handshakes
- Config file auto-discovery: `--config_path` > `EOS_MCP_CONFIG` env var > `./config.ini` > `~/.config/eos-mcp/config.ini`
- `daily_brief`: parallel health check across multiple devices (environment, memory, MLAG, errdisabled)
- `push_config`: safe config push via configure session with commit timer and dry-run mode
