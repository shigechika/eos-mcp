"""pyeapi client wrapper with TLS compatibility and connection cache."""

from __future__ import annotations

import datetime
import re
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

# Default look-back window (hours) for the check_health syslog scan.
_DEFAULT_SINCE_HOURS = 24

# Recent-log alert patterns for the check_health syslog scan. This mirrors the
# junos-mcp daily_brief syslog scan (BGP/OSPF/STP/ARP/IF-down) but matches EOS
# %FACILITY-SEVERITY-MNEMONIC tags. Matched case-insensitively against
# `show logging last <N> hours` output. Field-verified mnemonics on EOS 4.28:
# %LINEPROTO-5-UPDOWN, %SPANTREE-6-ROOTCHANGE, %MLAG-4-INTF_INACTIVE_LOCAL,
# %LAG-5-MEMBER_*.
# BGP/OSPF ADJCHANGE fire on both up and down transitions; only the down/reset
# direction is an anomaly, so each is direction-guarded (mirrors junos-mcp's
# BGP "Established->" filter): BGP requires "old state Established" (session
# was up and just dropped — a plain new-session establishment never matches
# this), OSPF requires "to DOWN" (neighbor lost, not a normal FULL formation
# step). BGP-NOTIFICATION is always a reset and needs no guard.
_SYSLOG_ALERT_RE = re.compile(
    r"%LINEPROTO-\d+-UPDOWN.*to\s+down"  # interface line protocol went down
    r"|%LINK-\d+-UPDOWN.*down"
    r"|%BGP-\d+-ADJCHANGE(?=.*\bold state Established\b)"  # BGP session dropped
    r"|%BGP-\d+-NOTIFICATION"  # BGP session reset (always a down/reset event)
    r"|%OSPF-\d+-ADJCHANGE(?=.*\bto DOWN\b)"  # OSPF adjacency lost
    r"|%SPANTREE-\d+-(ROOTCHANGE|TC|TOPOLOGY|PORT_BLOCKED|OVERRIDE)"  # STP topology change
    r"|%LAG-\d+-(MEMBER_REMOVED|INACTIVE)"  # LACP member left the bundle
    r"|%MLAG-[0-4]-"  # MLAG degraded (severity 0-4)
    r"|%ARP-\d+-",  # ARP anomaly (e.g. duplicate address)
    re.IGNORECASE,
)

# Cap syslog matches per device so a flapping link cannot flood the brief.
_SYSLOG_MAX_MATCHES = 10


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
        if host is not None:
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


# RFC3339 / high-resolution leading timestamp, e.g. "2026-06-26T09:22:56.123+09:00".
# We read the wall-clock fields and ignore the fraction/offset (the offset is the
# device's own, and we anchor windowing on the device clock).
_RFC3339_TS_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})")
# Traditional (RFC3164) leading "Mon DD HH:MM:SS", optionally followed by
# subseconds and any of the EOS `traditional` extras (timezone abbrev and/or a
# 4-digit year, in either order). Group 6 captures those trailing extras so an
# explicit year can be used when present; otherwise the year is reconstructed.
_SYSLOG_TS_RE = re.compile(
    r"^([A-Z][a-z]{2})\s+(\d{1,2})\s+(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?"
    r"((?:\s+(?:[A-Z]{2,5}|\d{4})(?=\s|$))*)"  # whole tokens only (not a hostname prefix)
)
_YEAR_RE = re.compile(r"\d{4}")
_MONTHS = {
    m: i
    for i, m in enumerate(
        ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
        start=1,
    )
}


def _device_now(node: pyeapi.client.Node) -> datetime.datetime:
    """Return the device's current local time (naive) from ``show clock``.

    EOS syslog timestamps carry no year, so the device clock — which does — is
    the anchor for reconstructing them. Falls back to the local host clock if
    ``show clock`` can't be read or parsed.
    """
    try:
        out = run_show(node, "show clock")
        # e.g. "Fri Jun 26 16:01:37 2026  Timezone: Japan ..."
        m = re.search(
            r"\b([A-Z][a-z]{2})\s+(\d{1,2})\s+(\d{2}):(\d{2}):(\d{2})\s+(\d{4})\b", out
        )
        # Use the same locale-independent month map as the syslog parser rather
        # than strptime("%b"), whose month names are locale-dependent.
        mon = _MONTHS.get(m.group(1)) if m else None
        if mon:
            return datetime.datetime(
                int(m.group(6)), mon, int(m.group(2)),
                int(m.group(3)), int(m.group(4)), int(m.group(5)),
            )
    except Exception:
        pass
    # Fallback: host clock. The primary show-clock path keeps device_now and the
    # syslog lines on the same (device-local) clock; this fallback assumes the
    # host wall time is close enough.
    return datetime.datetime.now()


def _window_syslog(
    text: str, device_now: datetime.datetime, since_hours: int
) -> str:
    """Keep only syslog lines within the last ``since_hours`` of ``device_now``.

    Handles every EOS ``logging format timestamp`` rendering:

    - ``high-resolution`` (RFC3339, ``2026-06-26T09:22:56.123+09:00``) — the year
      is present, parsed directly (wall-clock fields; the offset is the device's
      own and we anchor on the device clock).
    - ``traditional year`` / ``traditional ... year`` (``Jun 26 09:22:56 2026``,
      with optional timezone abbrev in either order) — the explicit year is used.
    - ``traditional timezone`` and the default (``Jun 26 09:22:56`` [``JST``]) —
      no year, so it is reconstructed from the device clock by walking the
      (chronological) buffer newest→oldest, decrementing the year on a
      near-full-year forward jump (so a one-year-ago entry isn't mistaken for
      today). Any line carrying an explicit year (RFC3339 or traditional+year)
      re-anchors the reconstruction year, so a mixed buffer during a format
      switch resolves correctly.

    Lines without a parseable timestamp (continuations) are kept — the caller's
    alert regex decides their relevance. Year reconstruction assumes a
    reasonably dense buffer (EOS's ring buffer is dense in practice).
    """
    cutoff = device_now - datetime.timedelta(hours=since_hours)
    # Only a near-year forward jump (while moving *back* through the buffer)
    # means the calendar actually wrapped; smaller forward deltas are NTP
    # backward steps or async-logging reorder, NOT a year change — tolerate them
    # so one out-of-order pair can't flip the year and drop the rest of the buffer.
    wrap_gap = datetime.timedelta(days=180)
    dated: list[tuple[datetime.datetime | None, str]] = []
    year = device_now.year
    prev = device_now
    for line in reversed(text.splitlines()):
        iso = _RFC3339_TS_RE.match(line)
        if iso:
            try:
                dt = datetime.datetime(*(int(iso.group(i)) for i in range(1, 7)))
            except ValueError:
                dated.append((None, line))
                continue
            year, prev = dt.year, dt  # explicit year re-anchors reconstruction
            dated.append((dt, line))
            continue
        m = _SYSLOG_TS_RE.match(line)
        mon = _MONTHS.get(m.group(1)) if m else None
        if mon is None:
            dated.append((None, line))
            continue
        day, hh, mm, ss = (int(m.group(i)) for i in (2, 3, 4, 5))
        # An explicit, plausible 4-digit year among the trailing tokens (a
        # `traditional year` line) is authoritative and re-anchors reconstruction.
        # The range guard keeps a numeric hostname (e.g. "7280r3") from posing as a year.
        explicit = next(
            (y for y in (int(t) for t in _YEAR_RE.findall(m.group(6))) if 2000 <= y <= 2099),
            None,
        )
        if explicit is not None:
            year = explicit
        try:
            dt = datetime.datetime(year, mon, day, hh, mm, ss)
            if explicit is None and dt > prev + wrap_gap:  # ~full-year jump ⇒ year boundary
                year -= 1
                dt = datetime.datetime(year, mon, day, hh, mm, ss)
        except ValueError:  # e.g. Feb 29 in a reconstructed non-leap year
            dated.append((None, line))
            continue
        prev = dt
        dated.append((dt, line))
    dated.reverse()
    return "\n".join(line for dt, line in dated if dt is None or dt >= cutoff)


def _get_syslog_text(node: pyeapi.client.Node, since_hours: int) -> str:
    """Return syslog text windowed to the last ``since_hours`` hours.

    EOS syslog timestamps carry no year, so EOS's native ``show logging last
    <N> hours`` can leak prior-year entries (same month/day/time). We therefore
    fetch the full buffer (dense, so year reconstruction is reliable) and apply
    a client-side, year-aware filter anchored to the device clock. Falls back to
    the native time-windowed form, then to empty, if a fetch is rejected.
    """
    device_now = _device_now(node)
    for cmd in ("show logging", f"show logging last {since_hours} hours"):
        try:
            text = run_show(node, cmd)
        except Exception:
            continue
        return _window_syslog(text, device_now, since_hours)
    return ""


def check_health(
    node: pyeapi.client.Node, since_hours: int = _DEFAULT_SINCE_HOURS
) -> dict[str, Any]:
    """Run health checks for daily_brief.

    Checks: device facts (uptime, memory), environment (temperature/cooling/fans/PSUs),
    errdisabled interfaces, MLAG status (when active), and recent syslog alerts
    (BGP/OSPF/STP/LACP/MLAG/link-down) within the last ``since_hours`` hours.

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
        uptime_h, rem2 = divmod(rem, 3600)
        uptime_m = rem2 // 60
        if uptime_d == 0 and uptime_h == 0:
            info["uptime"] = f"{uptime_m}m"
        elif uptime_d == 0:
            info["uptime"] = f"{uptime_h}h"
        else:
            info["uptime"] = f"{uptime_d}d {uptime_h}h"
        if uptime_d == 0:
            display = f"{uptime_m}m" if uptime_h == 0 else f"{uptime_h}h"
            anomalies.append(f"WARNING: uptime {display} — recent reboot?")
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
            for _prefix in ("System temperature status", "System cooling status"):
                _sline = next((l.strip() for l in env.splitlines() if l.startswith(_prefix)), None)
                if _sline is not None and "Ok" not in _sline:
                    anomalies.append(f"CRITICAL: {_sline}")
            for line in env.splitlines():
                stripped = line.strip()
                # Fan/PSU failure: lines starting with a digit, PowerSupply, or Fan (FanTray, Fan1/1…)
                if stripped and " Fail" in stripped:
                    if stripped[0].isdigit() or stripped.startswith(("PowerSupply", "Fan")):
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

    # Recent syslog alerts within the look-back window
    try:
        syslog = _get_syslog_text(node, since_hours)
        count = 0
        for line in syslog.splitlines():
            if count >= _SYSLOG_MAX_MATCHES:
                anomalies.append(
                    f"WARNING: syslog: ... ({count}+ alert lines, truncated)"
                )
                break
            if _SYSLOG_ALERT_RE.search(line):
                anomalies.append(f"WARNING: syslog: {line.strip()[:120]}")
                count += 1
    except Exception as exc:
        anomalies.append(f"WARNING: syslog check failed: {exc}")

    return {"anomalies": anomalies, "info": info}
