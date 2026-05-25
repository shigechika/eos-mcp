"""MCP server exposing Arista EOS device operations via eAPI.

Provides tools for show commands, device facts, config retrieval,
config push via configure session (with commit timer + confirm/abort),
config diff, session management, and tech-support collection.
"""

from __future__ import annotations

import concurrent.futures
import datetime
import os

from mcp.server.fastmcp import FastMCP

from eos_mcp import config as cfg_mod
from eos_mcp import eapi

mcp = FastMCP("eos-mcp")


def _config_path(override: str) -> str:
    return override or os.environ.get(cfg_mod.CONFIG_ENV_VAR, "")


def _connect(host: str, config_path: str) -> eapi.pyeapi.client.Node:
    """Load config and return a connected Node for host."""
    cfg, _ = cfg_mod.load(config_path)
    creds = cfg_mod.get_creds(cfg, host)
    return eapi.get_node(host=host, **creds)


def _resolve_hosts(
    cfg,
    hostnames: list[str] | None,
    tags: list[str] | None,
) -> list[str]:
    result = set(hostnames or [])
    if tags:
        result.update(cfg_mod.get_hosts(cfg, tags))
    return sorted(result)


def _ensure_config(config_path: str) -> str | None:
    """Return error string if config is unloadable, else None."""
    try:
        cfg_mod.load(config_path)
        return None
    except FileNotFoundError as e:
        return str(e)


@mcp.tool()
def get_router_list(tags: list[str] | None = None, config_path: str = "") -> str:
    """List EOS devices registered in config, optionally filtered by tags."""
    try:
        cfg, path = cfg_mod.load(_config_path(config_path))
    except FileNotFoundError as e:
        return f"Error: {e}"
    hosts = cfg_mod.get_hosts(cfg, tags)
    if not hosts:
        return f"No hosts found (config: {path}, tags: {tags})"
    lines = [f"Hosts ({len(hosts)}) from {path}:"]
    for h in hosts:
        host_tags = cfg.get(h, "tags", fallback="")
        lines.append(f"  {h}  tags={host_tags or '(none)'}")
    return "\n".join(lines)


@mcp.tool()
def get_device_facts(hostname: str, config_path: str = "") -> str:
    """Return structured device facts: hostname, model, serial, EOS version, uptime, memory."""
    try:
        node = _connect(hostname, _config_path(config_path))
        f = eapi.get_device_facts(node)
        uptime_h = int(f["uptime_seconds"]) // 3600
        uptime_d, uptime_h = divmod(uptime_h, 24)
        fqdn_line = f"\nfqdn:              {f['fqdn']}" if f["fqdn"] != f["hostname"] else ""
        return (
            f"hostname:          {f['hostname']}{fqdn_line}\n"
            f"model:             {f['model']}\n"
            f"serial:            {f['serial']}\n"
            f"EOS version:       {f['version']}\n"
            f"hardware revision: {f['hardware_revision']}\n"
            f"uptime:            {uptime_d}d {uptime_h}h\n"
            f"memory total:      {f['memory_total_kb'] // 1024} MB\n"
            f"memory free:       {f['memory_free_kb'] // 1024} MB\n"
            f"MAC:               {f['mac']}\n"
            f"architecture:      {f['architecture']}"
        )
    except Exception as e:
        eapi.clear_cache(hostname)
        return f"Error ({hostname}): {e}"


@mcp.tool()
def get_device_facts_batch(
    hostnames: list[str] | None = None,
    tags: list[str] | None = None,
    max_workers: int = 5,
    config_path: str = "",
) -> str:
    """Return device facts (model, serial, EOS version, uptime) for multiple devices in parallel."""
    try:
        cfg, _ = cfg_mod.load(_config_path(config_path))
    except FileNotFoundError as e:
        return f"Error: {e}"

    targets = _resolve_hosts(cfg, hostnames, tags)
    if not targets:
        return "No hosts resolved."

    cp = _config_path(config_path)

    def _run_one(host: str) -> tuple[str, str]:
        try:
            node = _connect(host, cp)
            f = eapi.get_device_facts(node)
            uptime_h = int(f["uptime_seconds"]) // 3600
            uptime_d, uptime_h = divmod(uptime_h, 24)
            return host, f"{f['model']}  EOS {f['version']}  serial={f['serial']}  up={uptime_d}d{uptime_h}h"
        except Exception as exc:
            eapi.clear_cache(host)
            return host, f"Error: {exc}"

    results: dict[str, str] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        for host, output in pool.map(_run_one, targets):
            results[host] = output

    lines = [f"Device facts ({len(targets)} hosts):"]
    for host in targets:
        lines.append(f"  {host:<35} {results.get(host, '')}")
    return "\n".join(lines)


@mcp.tool()
def get_version(hostname: str, config_path: str = "") -> str:
    """Return EOS version string for a device (quick connectivity check)."""
    try:
        node = _connect(hostname, _config_path(config_path))
        result = node.execute(["show version"])
        v = result["result"][0]
        return f"{v.get('modelName', '?')}  EOS {v.get('version', '?')}"
    except Exception as e:
        eapi.clear_cache(hostname)
        return f"Error ({hostname}): {e}"


@mcp.tool()
def get_config_diff(hostname: str, rollback_id: int = 1, config_path: str = "") -> str:
    """Show config diff on an EOS device.

    rollback_id=1 (default) → diff vs most recent rollback checkpoint.
    rollback_id=N           → diff vs Nth rollback checkpoint.
    Note: diff vs startup-config requires EOS 4.30+; older versions fall back gracefully.
    """
    try:
        node = _connect(hostname, _config_path(config_path))
        diff = eapi.get_config_diff(node, rollback_id)
        return diff if diff.strip() else "(no diff — running-config matches checkpoint)"
    except Exception as e:
        eapi.clear_cache(hostname)
        return f"Error ({hostname}): {e}"


@mcp.tool()
def list_config_sessions(hostname: str, config_path: str = "") -> str:
    """List configure sessions and their state on an EOS device.

    Shows pending, pendingCommitTimer, and completed sessions.
    Useful for tracking in-flight push_config operations.
    """
    try:
        node = _connect(hostname, _config_path(config_path))
        return eapi.list_config_sessions(node)
    except Exception as e:
        eapi.clear_cache(hostname)
        return f"Error ({hostname}): {e}"


@mcp.tool()
def run_command(hostname: str, command: str, config_path: str = "") -> str:
    """Run a single enable-mode command on an EOS device and return text output."""
    try:
        node = _connect(hostname, _config_path(config_path))
        return eapi.run_show(node, command)
    except Exception as e:
        eapi.clear_cache(hostname)
        return f"Error ({hostname}): {e}"


@mcp.tool()
def run_commands(hostname: str, commands: list[str], config_path: str = "") -> str:
    """Run multiple enable-mode commands on one EOS device and return labelled output."""
    try:
        node = _connect(hostname, _config_path(config_path))
        return eapi.run_shows(node, commands)
    except Exception as e:
        eapi.clear_cache(hostname)
        return f"Error ({hostname}): {e}"


@mcp.tool()
def run_command_batch(
    command: str,
    hostnames: list[str] | None = None,
    tags: list[str] | None = None,
    max_workers: int = 5,
    config_path: str = "",
) -> str:
    """Run an enable-mode command on multiple EOS devices in parallel.

    Specify targets via 'hostnames', 'tags', or both.
    """
    try:
        cfg, _ = cfg_mod.load(_config_path(config_path))
    except FileNotFoundError as e:
        return f"Error: {e}"

    targets = _resolve_hosts(cfg, hostnames, tags)
    if not targets:
        return "No hosts resolved (check hostnames/tags)."

    cp = _config_path(config_path)

    def _run_one(host: str) -> tuple[str, str]:
        try:
            node = _connect(host, cp)
            return host, eapi.run_show(node, command)
        except Exception as exc:
            eapi.clear_cache(host)
            return host, f"Error: {exc}"

    results: dict[str, str] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        for host, output in pool.map(_run_one, targets):
            results[host] = output

    lines = []
    for host in targets:
        lines.append(f"# {host}")
        lines.append(results.get(host, ""))
        lines.append("")
    return "\n".join(lines)


@mcp.tool()
def get_config(hostname: str, config_path: str = "") -> str:
    """Retrieve the running-config from an EOS device."""
    try:
        node = _connect(hostname, _config_path(config_path))
        return eapi.get_running_config(node)
    except Exception as e:
        eapi.clear_cache(hostname)
        return f"Error ({hostname}): {e}"


@mcp.tool()
def push_config(
    hostname: str,
    config_lines: list[str],
    session_name: str = "mcp-push",
    dry_run: bool = True,
    commit_timer: int = 300,
    config_path: str = "",
) -> str:
    """Push configuration to an EOS device via a named configure session.

    When dry_run=True (default) shows diffs and aborts — no changes applied.
    When dry_run=False commits with a rollback timer (default 300 seconds).
    Call confirm_config_session before the timer expires to finalize.
    """
    try:
        node = _connect(hostname, _config_path(config_path))
        result = eapi.push_config(
            node=node,
            session_name=session_name,
            config_lines=config_lines,
            dry_run=dry_run,
            commit_timer=commit_timer,
        )
    except Exception as e:
        eapi.clear_cache(hostname)
        return f"Error ({hostname}): {e}"

    if result["committed"]:
        status = f"COMMITTED — timer={result['timer_seconds']}s, confirm with confirm_config_session"
    else:
        status = "DRY RUN — session aborted, no changes applied"
    return f"Session '{result['session_name']}' [{status}]\n\nDiffs:\n{result['diffs']}"


@mcp.tool()
def confirm_config_session(
    hostname: str,
    session_name: str = "mcp-push",
    config_path: str = "",
) -> str:
    """Confirm (finalize) a pending configure session commit timer on an EOS device."""
    try:
        node = _connect(hostname, _config_path(config_path))
        return eapi.confirm_session(node, session_name)
    except Exception as e:
        eapi.clear_cache(hostname)
        return f"Error ({hostname}): {e}"


@mcp.tool()
def abort_config_session(
    hostname: str,
    session_name: str = "mcp-push",
    config_path: str = "",
) -> str:
    """Abort a pending configure session on an EOS device."""
    try:
        node = _connect(hostname, _config_path(config_path))
        return eapi.abort_session(node, session_name)
    except Exception as e:
        eapi.clear_cache(hostname)
        return f"Error ({hostname}): {e}"


@mcp.tool()
def collect_tech_support(hostname: str, config_path: str = "") -> str:
    """Collect show tech-support from an EOS device (large output, 30+ seconds)."""
    try:
        node = _connect(hostname, _config_path(config_path))
        return eapi.collect_tech_support(node)
    except Exception as e:
        eapi.clear_cache(hostname)
        return f"Error ({hostname}): {e}"


@mcp.tool()
def daily_brief(
    hostnames: list[str] | None = None,
    tags: list[str] | None = None,
    max_workers: int = 5,
    config_path: str = "",
) -> str:
    """Run health checks on EOS devices and return a Markdown daily brief.

    Checks environment (temperature, cooling, fans, PSUs), errdisabled interfaces,
    and device uptime. Returns CRITICAL/WARNING/OK per device with a summary.
    Specify targets via 'hostnames', 'tags', or both (default: all configured devices).
    """
    try:
        cfg, _ = cfg_mod.load(_config_path(config_path))
    except FileNotFoundError as e:
        return f"Error: {e}"

    targets = _resolve_hosts(cfg, hostnames, tags)
    if not targets and hostnames is None and tags is None:
        targets = cfg_mod.get_hosts(cfg, None)
    if not targets:
        return "No hosts resolved."

    cp = _config_path(config_path)

    def _run_one(host: str) -> tuple[str, dict]:
        try:
            node = _connect(host, cp)
            return host, eapi.check_health(node)
        except Exception as exc:
            eapi.clear_cache(host)
            return host, {
                "anomalies": [f"CRITICAL: connection failed: {exc}"],
                "info": {},
            }

    results: dict[str, dict] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        for host, result in pool.map(_run_one, targets):
            results[host] = result

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [f"## EOS デイリーブリーフ（{now}）", ""]

    critical_count = warning_count = ok_count = 0

    for host in targets:
        r = results.get(host, {})
        anomalies = r.get("anomalies", [])
        info = r.get("info", {})

        criticals = [a for a in anomalies if a.startswith("CRITICAL")]
        warnings = [a for a in anomalies if a.startswith("WARNING")]

        if criticals:
            status = "CRITICAL"
            critical_count += 1
        elif warnings:
            status = "WARNING"
            warning_count += 1
        else:
            status = "OK"
            ok_count += 1

        model = info.get("model", "?")
        version = info.get("version", "?")
        uptime = info.get("uptime", "?")

        lines.append(f"### {host} [{status}]")
        lines.append(f"- model: {model}  EOS {version}  uptime: {uptime}")

        for a in criticals + warnings:
            lines.append(f"- {a}")

        if not anomalies:
            mem_pct = info.get("memory_pct")
            mem_str = f"  メモリ: {mem_pct}%" if mem_pct is not None else ""
            mlag_state = info.get("mlag_state", "")
            if mlag_state == "active":
                mlag_str = f"  MLAG: Active/{info.get('mlag_neg', '?').capitalize()}"
            elif mlag_state and mlag_state != "disabled":
                mlag_str = f"  MLAG: {mlag_state}"
            else:
                mlag_str = ""
            lines.append(f"- 環境: OK{mem_str}{mlag_str}  errdisabled: なし")

        lines.append("")

    lines += [
        "### サマリー",
        f"- CRITICAL: {critical_count} 台",
        f"- WARNING:  {warning_count} 台",
        f"- OK:       {ok_count} 台",
    ]
    return "\n".join(lines)
