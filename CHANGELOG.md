# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0](https://github.com/shigechika/eos-mcp/compare/v0.2.2...v0.3.0) (2026-06-18)


### Features

* **daily_brief:** scan recent syslog for link/BGP/OSPF/STP/LACP/MLAG alerts ([#11](https://github.com/shigechika/eos-mcp/issues/11)) ([b296ebd](https://github.com/shigechika/eos-mcp/commit/b296ebde93cc11a11edc27d267735f218525f7e5))

## [0.2.2](https://github.com/shigechika/eos-mcp/compare/v0.2.1...v0.2.2) (2026-05-26)


### Bug Fixes

* add GH_REPO env to gh release upload ([#9](https://github.com/shigechika/eos-mcp/issues/9)) ([01c4bad](https://github.com/shigechika/eos-mcp/commit/01c4badf3dc0d1f01e53c873859260c71801e55f))

## [0.2.1](https://github.com/shigechika/eos-mcp/compare/v0.2.0...v0.2.1) (2026-05-26)


### Bug Fixes

* uptime display and add run_commands_batch tool ([#7](https://github.com/shigechika/eos-mcp/issues/7)) ([2fe6626](https://github.com/shigechika/eos-mcp/commit/2fe6626f8c8642164947ecf15733c64d7d016967))

## [0.2.0](https://github.com/shigechika/eos-mcp/compare/v0.1.0...v0.2.0) (2026-05-26)


### Features

* initial release v0.1.0 ([f61a624](https://github.com/shigechika/eos-mcp/commit/f61a6245b1ea29be403ee4acd8ee0af54999053c))


### Bug Fixes

* address code review findings and add release automation ([4c8ebac](https://github.com/shigechika/eos-mcp/commit/4c8ebac18ed2abddde708149842c84bf11ee561e))


### Reverts

* server.json version to 0.0.0 (managed by release workflow) ([e7178b9](https://github.com/shigechika/eos-mcp/commit/e7178b90099b09b374997cbefc7ef3daa539cc77))

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
