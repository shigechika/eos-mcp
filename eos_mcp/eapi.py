"""pyeapi client wrapper with TLS compatibility and connection cache."""

from __future__ import annotations

import ssl
import threading
from typing import Any

import pyeapi

# EOS 4.28.x supports TLS 1.0–1.2 with legacy cipher suites.
# Python 3.14 raised the default security level, causing
# SSLV3_ALERT_HANDSHAKE_FAILURE.  Patch _create_unverified_context globally
# so pyeapi's HTTPS transport works with older EOS versions.
_orig_create_unverified_context = ssl._create_unverified_context


def _tls_compat_context(protocol=ssl.PROTOCOL_TLS_CLIENT, **kwargs):
    ctx = _orig_create_unverified_context(protocol, **kwargs)
    ctx.set_ciphers("DEFAULT:@SECLEVEL=0")
    ctx.minimum_version = ssl.TLSVersion.TLSv1
    return ctx


ssl._create_unverified_context = _tls_compat_context

# hostname -> pyeapi.client.Node
_cache: dict[str, pyeapi.client.Node] = {}
_lock = threading.Lock()


def get_node(
    host: str,
    username: str,
    password: str,
    transport: str = "https",
    verify: bool = False,
) -> pyeapi.client.Node:
    """Return a cached Node, creating a new connection if needed."""
    with _lock:
        if host not in _cache:
            _cache[host] = pyeapi.connect(
                host=host,
                username=username,
                password=password,
                transport=transport,
                verify=verify,
            )
        return _cache[host]


def clear_cache(host: str | None = None) -> None:
    """Remove cached node(s) so the next call creates a fresh connection."""
    with _lock:
        if host:
            _cache.pop(host, None)
        else:
            _cache.clear()


def run_show(node: pyeapi.client.Node, command: str) -> str:
    """Run a single show command and return text output."""
    result = node.execute([command], encoding="text")
    return result["result"][0].get("output", "")


def run_shows(node: pyeapi.client.Node, commands: list[str]) -> str:
    """Run multiple show commands and return labelled concatenated text."""
    result = node.execute(commands, encoding="text")
    parts = [
        f"--- {cmd} ---\n{result['result'][i].get('output', '')}"
        for i, cmd in enumerate(commands)
    ]
    return "\n".join(parts)


def get_running_config(node: pyeapi.client.Node) -> str:
    """Return running-config as text."""
    return run_show(node, "show running-config")


def _timer_str(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def push_config(
    node: pyeapi.client.Node,
    session_name: str,
    config_lines: list[str],
    dry_run: bool = True,
    commit_timer: int = 300,
) -> dict[str, Any]:
    """Apply config lines via a named configure session.

    All commands are sent in a single eAPI call to maintain session context.
    When dry_run=True the session is aborted after showing diffs.
    When dry_run=False the session is committed with a rollback timer.

    Returns dict: {session_name, diffs, committed, timer_seconds}.
    """
    terminate = "abort" if dry_run else f"commit timer {_timer_str(commit_timer)}"
    cmds = (
        [f"configure session {session_name}"]
        + list(config_lines)
        + ["show session-config diffs", terminate]
    )
    result = node.execute(cmds, encoding="text")
    diffs_idx = 1 + len(config_lines)
    diffs = result["result"][diffs_idx].get("output", "(no diffs)")
    return {
        "session_name": session_name,
        "diffs": diffs,
        "committed": not dry_run,
        "timer_seconds": 0 if dry_run else commit_timer,
    }


def confirm_session(node: pyeapi.client.Node, session_name: str) -> str:
    """Confirm (finalize) a pending configure session commit timer."""
    node.execute([f"configure session {session_name} commit"])
    return f"Session '{session_name}' confirmed and committed."


def abort_session(node: pyeapi.client.Node, session_name: str) -> str:
    """Abort a pending configure session."""
    node.execute([f"configure session {session_name} abort"])
    return f"Session '{session_name}' aborted."


def collect_tech_support(node: pyeapi.client.Node) -> str:
    """Return show tech-support output (large — may take 30+ seconds)."""
    return run_show(node, "show tech-support")


def get_device_facts(node: pyeapi.client.Node) -> dict[str, Any]:
    """Return structured device facts from show version + show hostname.

    Keys: hostname, fqdn, model, serial, version, hardware_revision,
    uptime_seconds, memory_total_kb, memory_free_kb, mac, architecture.
    """
    result = node.execute(["show version", "show hostname"])
    v = result["result"][0]
    h = result["result"][1]
    return {
        "hostname": h.get("hostname", ""),
        "fqdn": h.get("fqdn", ""),
        "model": v.get("modelName", ""),
        "serial": v.get("serialNumber", ""),
        "version": v.get("version", ""),
        "hardware_revision": v.get("hardwareRevision", ""),
        "uptime_seconds": v.get("uptime", 0),
        "memory_total_kb": v.get("memTotal", 0),
        "memory_free_kb": v.get("memFree", 0),
        "mac": v.get("systemMacAddress", ""),
        "architecture": v.get("architecture", ""),
    }


def get_config_diff(node: pyeapi.client.Node, rollback_id: int = 1) -> str:
    """Return config diff between running-config and a rollback checkpoint.

    rollback_id=1  → diff vs most recent rollback checkpoint (default)
    rollback_id=N  → diff vs Nth rollback checkpoint

    Note: 'show running-config diffs' (vs startup) requires EOS 4.30+.
    This function uses 'show rollback config <N>' which is available on
    EOS 4.28+, falling back gracefully when no rollbacks exist.
    """
    candidates = [
        f"show rollback config {rollback_id}",
        f"show running-config diffs",
    ]
    last_err = ""
    for cmd in candidates:
        try:
            return run_show(node, cmd)
        except Exception as e:
            last_err = str(e)
    return f"Config diff not available on this EOS version: {last_err}"


def list_config_sessions(node: pyeapi.client.Node) -> str:
    """Return configure session list with state (show configuration sessions detail)."""
    return run_show(node, "show configuration sessions detail")


def _get_environment_text(node: pyeapi.client.Node) -> str:
    """Return environment status text, trying EOS 4.28+ and older syntax."""
    for cmd in ("show system environment all", "show environment all"):
        try:
            return run_show(node, cmd)
        except Exception:
            continue
    return ""


def check_health(node: pyeapi.client.Node) -> dict[str, Any]:
    """Run health checks for daily_brief.

    Checks: device facts (uptime, memory), environment (temperature/cooling/fans/PSUs),
    errdisabled interfaces, and MLAG status (when active).

    Returns dict: {anomalies: list[str], info: dict}.
    anomalies entries are prefixed with 'CRITICAL:' or 'WARNING:'.
    """
    anomalies: list[str] = []
    info: dict[str, Any] = {}

    # Device facts (uptime + memory — no extra API call)
    try:
        facts = get_device_facts(node)
        info["hostname"] = facts["hostname"]
        info["model"] = facts["model"]
        info["version"] = facts["version"]
        uptime_s = int(facts["uptime_seconds"])
        uptime_d, rem = divmod(uptime_s, 86400)
        uptime_h = rem // 3600
        info["uptime"] = f"{uptime_d}d {uptime_h}h"
        if uptime_d == 0:
            anomalies.append(f"WARNING: uptime {uptime_h}h — recent reboot?")
        total_kb = facts.get("memory_total_kb", 0)
        free_kb = facts.get("memory_free_kb", 0)
        if total_kb > 0:
            used_pct = (total_kb - free_kb) / total_kb * 100
            info["memory_pct"] = round(used_pct, 1)
            if used_pct >= 90:
                anomalies.append(
                    f"CRITICAL: memory {used_pct:.0f}% used ({free_kb // 1024} MB free)"
                )
            elif used_pct >= 80:
                anomalies.append(
                    f"WARNING: memory {used_pct:.0f}% used ({free_kb // 1024} MB free)"
                )
    except Exception as exc:
        anomalies.append(f"CRITICAL: cannot fetch facts: {exc}")

    # Environment (temperature / cooling / fans / PSUs)
    try:
        env = _get_environment_text(node)
        if env:
            if "System temperature status is: Ok" not in env:
                status_line = next(
                    (l.strip() for l in env.splitlines() if l.startswith("System temperature status")),
                    "temperature status unknown",
                )
                anomalies.append(f"CRITICAL: {status_line}")
            if "System cooling status is: Ok" not in env:
                status_line = next(
                    (l.strip() for l in env.splitlines() if l.startswith("System cooling status")),
                    "cooling status unknown",
                )
                anomalies.append(f"CRITICAL: {status_line}")
            for line in env.splitlines():
                stripped = line.strip()
                # Fan/PSU failure lines start with a digit (sensor/PSU index) or "PowerSupply"
                if stripped and " Fail" in stripped:
                    if stripped[0].isdigit() or stripped.startswith("PowerSupply"):
                        anomalies.append(f"CRITICAL: hardware Fail: {stripped}")
        else:
            anomalies.append("WARNING: environment status unavailable")
    except Exception as exc:
        anomalies.append(f"WARNING: environment check failed: {exc}")

    # Errdisabled interfaces
    try:
        intf_text = run_show(node, "show interfaces status")
        errdisabled = [
            line.split()[0]
            for line in intf_text.splitlines()
            if "errdisabled" in line and line.strip()
        ]
        info["errdisabled"] = errdisabled
        if errdisabled:
            anomalies.append(f"WARNING: errdisabled: {', '.join(errdisabled)}")
    except Exception as exc:
        anomalies.append(f"WARNING: interface check failed: {exc}")

    # MLAG status (ignore when disabled or not configured)
    try:
        mlag_text = run_show(node, "show mlag")
        mlag_state = ""
        mlag_neg = ""
        mlag_peer = ""
        for line in mlag_text.splitlines():
            stripped = line.strip()
            if stripped.startswith("state") and ":" in stripped:
                mlag_state = stripped.split(":", 1)[1].strip().lower()
            elif stripped.startswith("negotiation status") and ":" in stripped:
                mlag_neg = stripped.split(":", 1)[1].strip().lower()
            elif stripped.startswith("peer-link status") and ":" in stripped:
                mlag_peer = stripped.split(":", 1)[1].strip().lower()
        if mlag_state and mlag_state != "disabled":
            info["mlag_state"] = mlag_state
            info["mlag_neg"] = mlag_neg
            info["mlag_peer"] = mlag_peer
            if mlag_state != "active":
                anomalies.append(f"CRITICAL: MLAG state={mlag_state}")
            else:
                if mlag_neg and mlag_neg != "connected":
                    anomalies.append(f"CRITICAL: MLAG negotiation={mlag_neg}")
                if mlag_peer and mlag_peer != "up":
                    anomalies.append(f"CRITICAL: MLAG peer-link={mlag_peer}")
    except Exception:
        pass  # MLAG not configured on this device

    return {"anomalies": anomalies, "info": info}
