"""Unit tests for eapi helpers (no live device required)."""

import datetime
from unittest.mock import MagicMock, patch

import eos_mcp.eapi as eapi_mod
from eos_mcp.eapi import (
    _get_environment_text,
    _timer_str,
    check_health,
    clear_cache,
    get_config_diff,
    push_config,
)

# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

_CLEAN_ENV = "System temperature status  : Ok\nSystem cooling status      : Ok\n"


def _run_health(
    facts_override=None,
    env_text=_CLEAN_ENV,
    intf_text="",
    mlag_text="state                            : disabled",
    syslog_text="",
):
    """Run check_health with mocked internals. Returns the result dict."""
    node = MagicMock()
    facts = {
        "hostname": "sw1",
        "model": "DCS-7050CX3",
        "version": "4.28.2F",
        "uptime_seconds": 90000,  # 1d 1h — no uptime warning
        "memory_total_kb": 4_000_000,
        "memory_free_kb": 2_000_000,  # 50% — no memory warning
    }
    if facts_override is not None:
        facts.update(facts_override)

    def _show(_node, cmd):
        if cmd == "show interfaces status":
            return intf_text
        if cmd == "show mlag":
            return mlag_text
        return ""

    with (
        patch("eos_mcp.eapi.get_device_facts", return_value=facts),
        patch("eos_mcp.eapi._get_environment_text", return_value=env_text),
        patch("eos_mcp.eapi._get_syslog_text", return_value=syslog_text),
        patch("eos_mcp.eapi.run_show", side_effect=_show),
    ):
        return check_health(node)


# ---------------------------------------------------------------------------
# _timer_str
# ---------------------------------------------------------------------------


def test_timer_str_zero():
    assert _timer_str(0) == "00:00:00"


def test_timer_str_five_minutes():
    assert _timer_str(300) == "00:05:00"


def test_timer_str_over_one_hour():
    assert _timer_str(3661) == "01:01:01"


def test_timer_str_exactly_one_day():
    assert _timer_str(86400) == "24:00:00"


# ---------------------------------------------------------------------------
# clear_cache
# ---------------------------------------------------------------------------


def test_clear_cache_empty_string_does_not_wipe_all(monkeypatch):
    """clear_cache('') must not clear all entries (falsy-string guard fix)."""
    fake = {"host1": object(), "host2": object()}
    monkeypatch.setattr(eapi_mod, "_cache", fake)
    clear_cache("")
    assert len(fake) == 2


def test_clear_cache_none_wipes_all(monkeypatch):
    fake = {"host1": object(), "host2": object()}
    monkeypatch.setattr(eapi_mod, "_cache", fake)
    clear_cache(None)
    assert len(fake) == 0


def test_clear_cache_specific_host(monkeypatch):
    sentinel = object()
    fake = {"host1": sentinel, "host2": object()}
    monkeypatch.setattr(eapi_mod, "_cache", fake)
    clear_cache("host1")
    assert "host1" not in fake
    assert "host2" in fake


# ---------------------------------------------------------------------------
# push_config
# ---------------------------------------------------------------------------


def test_push_config_dry_run_aborts_and_not_committed():
    node = MagicMock()
    config_lines = ["hostname sw1"]
    # diffs_idx = 1 + 1 = 2
    node.execute.return_value = {
        "result": [{"output": ""}, {"output": ""}, {"output": "--- diffs ---"}, {"output": ""}]
    }
    result = push_config(node, "sess", config_lines, dry_run=True)
    assert result["committed"] is False
    assert result["timer_seconds"] == 0
    cmds = node.execute.call_args[0][0]
    assert cmds[-1] == "abort"


def test_push_config_live_commit_sets_timer():
    node = MagicMock()
    config_lines = ["hostname sw1"]
    node.execute.return_value = {"result": [{"output": ""}, {"output": ""}, {"output": ""}, {"output": ""}]}
    result = push_config(node, "sess", config_lines, dry_run=False, commit_timer=600)
    assert result["committed"] is True
    assert result["timer_seconds"] == 600
    cmds = node.execute.call_args[0][0]
    assert "commit timer 00:10:00" in cmds[-1]


def test_push_config_diffs_read_from_correct_index():
    """diffs must come from index 1+len(config_lines), not a hardcoded offset."""
    node = MagicMock()
    config_lines = ["hostname sw1", "ntp server 1.2.3.4"]  # 2 lines → diffs_idx=3
    mock_result = [
        {"output": "wrong_0"},
        {"output": "wrong_1"},
        {"output": "wrong_2"},
        {"output": "correct_diffs"},  # index 3 = diffs_idx
        {"output": "wrong_4"},
    ]
    node.execute.return_value = {"result": mock_result}
    result = push_config(node, "s", config_lines, dry_run=True)
    assert result["diffs"] == "correct_diffs"


# ---------------------------------------------------------------------------
# check_health — uptime
# ---------------------------------------------------------------------------


def test_check_health_uptime_sub_1h_warns_with_minutes():
    result = _run_health(facts_override={"uptime_seconds": 300})  # 5m
    assert any("WARNING: uptime 5m" in a for a in result["anomalies"])
    assert result["info"]["uptime"] == "5m"


def test_check_health_uptime_sub_1d_warns_with_hours():
    result = _run_health(facts_override={"uptime_seconds": 3 * 3600 + 30 * 60})  # 3h30m
    assert any("WARNING: uptime 3h" in a for a in result["anomalies"])
    assert result["info"]["uptime"] == "3h"


def test_check_health_uptime_over_1d_no_warning():
    result = _run_health(facts_override={"uptime_seconds": 90000})  # 1d 1h
    assert not any("uptime" in a for a in result["anomalies"])


# ---------------------------------------------------------------------------
# check_health — memory
# ---------------------------------------------------------------------------


def test_check_health_memory_critical_at_90_pct():
    result = _run_health(facts_override={"memory_total_kb": 4_000_000, "memory_free_kb": 400_000})
    assert any("CRITICAL: memory 90%" in a for a in result["anomalies"])


def test_check_health_memory_warning_at_80_pct():
    result = _run_health(facts_override={"memory_total_kb": 4_000_000, "memory_free_kb": 800_000})
    assert any("WARNING: memory 80%" in a for a in result["anomalies"])


def test_check_health_memory_ok_below_80_pct():
    result = _run_health(facts_override={"memory_total_kb": 4_000_000, "memory_free_kb": 2_000_000})
    assert not any("memory" in a for a in result["anomalies"])


# ---------------------------------------------------------------------------
# check_health — temperature (regression: absent line must NOT alert)
# ---------------------------------------------------------------------------


def test_check_health_temperature_absent_line_no_alert():
    """Regression: absent 'System temperature status' line must not trigger CRITICAL."""
    env = "System cooling status      : Ok\n"  # no temperature line
    result = _run_health(env_text=env)
    assert not any("temperature" in a.lower() for a in result["anomalies"])


def test_check_health_temperature_ok_no_alert():
    result = _run_health(env_text=_CLEAN_ENV)
    assert not any("temperature" in a.lower() for a in result["anomalies"])


def test_check_health_temperature_fail_is_critical():
    env = "System temperature status  : TempFail\nSystem cooling status      : Ok\n"
    result = _run_health(env_text=env)
    assert any("CRITICAL" in a and "temperature" in a.lower() for a in result["anomalies"])


# ---------------------------------------------------------------------------
# check_health — hardware Fail lines
# ---------------------------------------------------------------------------


def test_check_health_fantray_fail_is_critical():
    env = _CLEAN_ENV + "FanTray1 Fail\n"
    result = _run_health(env_text=env)
    assert any("CRITICAL: hardware Fail: FanTray1 Fail" in a for a in result["anomalies"])


def test_check_health_psu_fail_is_critical():
    env = _CLEAN_ENV + "PowerSupply1 Fail\n"
    result = _run_health(env_text=env)
    assert any("CRITICAL: hardware Fail: PowerSupply1 Fail" in a for a in result["anomalies"])


# ---------------------------------------------------------------------------
# check_health — errdisabled interfaces
# ---------------------------------------------------------------------------


def test_check_health_errdisabled_interface_warns():
    intf = "Et1  errdisabled  disabled\n"
    result = _run_health(intf_text=intf)
    assert any("errdisabled" in a for a in result["anomalies"])
    assert "Et1" in result["info"]["errdisabled"]


# ---------------------------------------------------------------------------
# check_health — MLAG
# ---------------------------------------------------------------------------


def test_check_health_mlag_disabled_no_alert():
    result = _run_health(mlag_text="state                            : disabled")
    assert not any("MLAG" in a for a in result["anomalies"])


def test_check_health_mlag_active_ok_no_alert():
    mlag = (
        "state                            : active\n"
        "negotiation status               : connected\n"
        "peer-link status                 : up\n"
    )
    result = _run_health(mlag_text=mlag)
    assert not any("MLAG" in a for a in result["anomalies"])


def test_check_health_mlag_state_inactive_is_critical():
    mlag = "state                            : inactive\n"
    result = _run_health(mlag_text=mlag)
    assert any("CRITICAL: MLAG state=inactive" in a for a in result["anomalies"])


def test_check_health_mlag_negotiation_not_connected_is_critical():
    mlag = (
        "state                            : active\n"
        "negotiation status               : not-connected\n"
        "peer-link status                 : up\n"
    )
    result = _run_health(mlag_text=mlag)
    assert any("CRITICAL: MLAG negotiation=not-connected" in a for a in result["anomalies"])


# ---------------------------------------------------------------------------
# check_health — environment unavailable
# ---------------------------------------------------------------------------


def test_check_health_environment_unavailable_warns():
    """When _get_environment_text returns '', check_health must warn."""
    result = _run_health(env_text="")
    assert any("environment status unavailable" in a for a in result["anomalies"])


# ---------------------------------------------------------------------------
# check_health — all-ok baseline
# ---------------------------------------------------------------------------


def test_check_health_all_ok_no_anomalies():
    result = _run_health()
    assert result["anomalies"] == []
    assert result["info"]["hostname"] == "sw1"


# ---------------------------------------------------------------------------
# check_health — syslog scan
# ---------------------------------------------------------------------------

_SYSLOG_LINK_DOWN = (
    "Jun 17 18:24:01 sw1 Ebra: %LINEPROTO-5-UPDOWN: Line protocol on Interface Ethernet1, changed state to down"
)
_SYSLOG_LINK_UP = (
    "Jun 17 18:25:01 sw1 Ebra: %LINEPROTO-5-UPDOWN: Line protocol on Interface Ethernet1, changed state to up"
)
_SYSLOG_MLAG = "Jun 17 18:24:05 sw1 Mlag: %MLAG-4-INTF_INACTIVE_LOCAL: Local interface Port-Channel10 is inactive"
_SYSLOG_BENIGN = "Jun 17 18:24:00 sw1 Launcher: %LAUNCHER-6-PROCESS_START: Configuring process"
_SYSLOG_BGP_DOWN = (
    "Jun 17 18:24:10 sw1 Bgp: %BGP-5-ADJCHANGE: peer 10.0.0.1 (AS 65001) old "
    "state Established event Stop new state Idle"
)
_SYSLOG_BGP_UP = (
    "Jun 17 18:24:20 sw1 Bgp: %BGP-5-ADJCHANGE: peer 10.0.0.1 (AS 65001) old "
    "state OpenConfirm event RecvKeepAlive new state Established"
)
_SYSLOG_BGP_NOTIFICATION = (
    "Jun 17 18:24:30 sw1 Bgp: %BGP-5-NOTIFICATION: sent to neighbor 10.0.0.1 "
    "active 6/2 (Cease/administrative reset) 0 bytes"
)
_SYSLOG_OSPF_DOWN = (
    "Jun 17 18:24:40 sw1 Ospf: %OSPF-5-ADJCHANGE: Nbr 10.0.0.2 on Ethernet1 "
    "from FULL to DOWN, Neighbor Down: Dead timer expired"
)
_SYSLOG_OSPF_UP = (
    "Jun 17 18:24:50 sw1 Ospf: %OSPF-5-ADJCHANGE: Nbr 10.0.0.2 on Ethernet1 from LOADING to FULL, Loading Done"
)


def test_check_health_syslog_link_down_warns():
    result = _run_health(syslog_text=_SYSLOG_LINK_DOWN)
    assert any("WARNING: syslog:" in a and "to down" in a for a in result["anomalies"])


def test_check_health_syslog_mlag_event_warns():
    result = _run_health(syslog_text=_SYSLOG_MLAG)
    assert any("WARNING: syslog:" in a and "MLAG-4" in a for a in result["anomalies"])


def test_check_health_syslog_link_up_not_flagged():
    """A line protocol coming *up* is not an alert."""
    result = _run_health(syslog_text=_SYSLOG_LINK_UP)
    assert not any("syslog" in a for a in result["anomalies"])


def test_check_health_syslog_bgp_down_warns():
    result = _run_health(syslog_text=_SYSLOG_BGP_DOWN)
    assert any("WARNING: syslog:" in a and "BGP-5-ADJCHANGE" in a for a in result["anomalies"])


def test_check_health_syslog_bgp_up_not_flagged():
    """A BGP session coming up (old state != Established) is not an alert."""
    result = _run_health(syslog_text=_SYSLOG_BGP_UP)
    assert not any("syslog" in a for a in result["anomalies"])


def test_check_health_syslog_bgp_notification_warns():
    """BGP-NOTIFICATION is always a reset, unconditionally flagged."""
    result = _run_health(syslog_text=_SYSLOG_BGP_NOTIFICATION)
    assert any("WARNING: syslog:" in a and "BGP-5-NOTIFICATION" in a for a in result["anomalies"])


def test_check_health_syslog_ospf_down_warns():
    result = _run_health(syslog_text=_SYSLOG_OSPF_DOWN)
    assert any("WARNING: syslog:" in a and "OSPF-5-ADJCHANGE" in a for a in result["anomalies"])


def test_check_health_syslog_ospf_up_not_flagged():
    """An OSPF neighbor reaching FULL is not an alert."""
    result = _run_health(syslog_text=_SYSLOG_OSPF_UP)
    assert not any("syslog" in a for a in result["anomalies"])


def test_check_health_syslog_benign_not_flagged():
    result = _run_health(syslog_text=_SYSLOG_BENIGN)
    assert not any("syslog" in a for a in result["anomalies"])


def test_check_health_syslog_empty_no_anomaly():
    result = _run_health(syslog_text="")
    assert not any("syslog" in a for a in result["anomalies"])


def test_check_health_syslog_truncates_at_max():
    """More than _SYSLOG_MAX_MATCHES alert lines yield a truncated marker."""
    lines = "\n".join(_SYSLOG_LINK_DOWN for _ in range(15))
    result = _run_health(syslog_text=lines)
    syslog_anoms = [a for a in result["anomalies"] if "syslog" in a]
    assert any("truncated" in a for a in syslog_anoms)
    # 10 real matches + 1 truncation marker
    assert len(syslog_anoms) == eapi_mod._SYSLOG_MAX_MATCHES + 1


# ---------------------------------------------------------------------------
# _get_syslog_text
# ---------------------------------------------------------------------------


_SHOW_CLOCK = "Fri Jun 26 16:00:00 2026\nTimezone: Japan"


def test_get_syslog_text_fetches_full_buffer_and_windows():
    """Fetches the full buffer, anchors on the device clock, drops out-of-window."""
    node = MagicMock()

    def _side(_n, cmd):
        if cmd == "show clock":
            return _SHOW_CLOCK
        if cmd == "show logging":
            return "Jun 20 10:00:00 sw1 Ebra: old-out-of-window\nJun 26 15:30:00 sw1 Ebra: recent-in-window"
        raise RuntimeError(f"unexpected {cmd}")

    with patch("eos_mcp.eapi.run_show", side_effect=_side):
        result = eapi_mod._get_syslog_text(node, 24)
    assert "recent-in-window" in result
    assert "old-out-of-window" not in result  # 6/20 is >24h before 6/26 16:00


def test_get_syslog_text_falls_back_to_native_window():
    node = MagicMock()
    calls = []

    def _side(_n, cmd):
        calls.append(cmd)
        if cmd == "show clock":
            return _SHOW_CLOCK
        if cmd == "show logging":
            raise RuntimeError("buffer too large")
        if cmd == "show logging last 18 hours":
            return "Jun 26 15:00:00 sw1 Ebra: recent-in-window"
        raise RuntimeError(f"unexpected {cmd}")

    with patch("eos_mcp.eapi.run_show", side_effect=_side):
        result = eapi_mod._get_syslog_text(node, 18)
    assert "recent-in-window" in result
    assert "show logging" in calls and "show logging last 18 hours" in calls


def test_get_syslog_text_both_fail_returns_empty():
    node = MagicMock()

    def _side(_n, cmd):
        if cmd == "show clock":
            return _SHOW_CLOCK
        raise RuntimeError("no log")

    with patch("eos_mcp.eapi.run_show", side_effect=_side):
        assert eapi_mod._get_syslog_text(node, 24) == ""


# ---------------------------------------------------------------------------
# _device_now / _window_syslog (year-less syslog reconstruction)
# ---------------------------------------------------------------------------


def test_device_now_parses_show_clock():
    node = MagicMock()
    with patch("eos_mcp.eapi.run_show", return_value="Fri Jun 26 16:01:37 2026\nTimezone: Japan"):
        dt = eapi_mod._device_now(node)
    assert (dt.year, dt.month, dt.day, dt.hour, dt.minute) == (2026, 6, 26, 16, 1)


def test_device_now_falls_back_when_unparseable():
    node = MagicMock()
    with patch("eos_mcp.eapi.run_show", return_value="garbage output"):
        dt = eapi_mod._device_now(node)
    assert isinstance(dt, datetime.datetime)


def test_window_syslog_drops_prior_year_same_date():
    """A flap from exactly one year ago must not count as recent (the nhv03 bug)."""
    now = datetime.datetime(2026, 6, 26, 16, 0, 0)
    buf = "\n".join(
        [
            "Jun 26 08:00:00 sw1 Ebra: %LINEPROTO-5-UPDOWN: Ethernet19 changed state to down",  # 2025
            "Nov 19 10:00:00 sw1 Ebra: boundary-2025",
            "Jan 05 03:00:00 sw1 Ebra: early-2026-out-of-window",
            "Jun 26 15:30:00 sw1 Ebra: recent-2026",
        ]
    )
    out = eapi_mod._window_syslog(buf, now, 24)
    assert "recent-2026" in out
    assert "Jun 26 08:00:00" not in out  # reconstructed to 2025 → dropped
    assert "boundary-2025" not in out
    assert "early-2026-out-of-window" not in out  # Jan 5 is >24h before Jun 26


def test_window_syslog_year_boundary_keeps_recent():
    """Dec→Jan: a Dec-31 entry minutes before a Jan-1 'now' stays in-window."""
    now = datetime.datetime(2026, 1, 1, 0, 30, 0)
    buf = "\n".join(
        [
            "Dec 31 23:50:00 sw1 Ebra: %LINEPROTO-5-UPDOWN: Ethernet1 changed state to down",  # 2025
            "Jan 01 00:20:00 sw1 Ebra: newyear-2026",
        ]
    )
    out = eapi_mod._window_syslog(buf, now, 24)
    assert "Dec 31 23:50:00" in out  # 40 min ago (2025) — kept
    assert "newyear-2026" in out


def test_window_syslog_tolerates_minor_out_of_order():
    """An NTP backward step (buffer order vs clock) must not flip the year."""
    now = datetime.datetime(2026, 6, 26, 16, 0, 0)
    buf = "\n".join(
        [
            "Jun 26 15:05:00 sw1 Ebra: before-ntp-step",  # earlier in buffer, later clock
            "Jun 26 15:00:30 sw1 Ebra: after-ntp-step",  # NTP stepped back ~4.5 min
        ]
    )
    out = eapi_mod._window_syslog(buf, now, 24)
    # Both are today; the ~4.5 min reverse jump must not be read as a year wrap.
    assert "before-ntp-step" in out
    assert "after-ntp-step" in out


def test_window_syslog_newest_line_slightly_after_clock_kept():
    """A newest line a few minutes after device_now must not be dropped."""
    now = datetime.datetime(2026, 6, 26, 16, 0, 0)
    buf = "Jun 26 16:03:00 sw1 Ebra: %LINEPROTO-5-UPDOWN: Ethernet1 changed state to down"
    out = eapi_mod._window_syslog(buf, now, 24)
    assert "16:03:00" in out  # not flipped to prior year by the prev=device_now anchor


def test_window_syslog_parses_rfc3339():
    """high-resolution (RFC3339) lines carry the year; window by it directly."""
    now = datetime.datetime(2026, 6, 26, 16, 0, 0)
    buf = "\n".join(
        [
            "2026-06-20T10:00:00.000000+09:00 sw1 Ebra: rfc3339-old",  # >24h → drop
            "2026-06-26T15:30:00.123456+09:00 sw1 Ebra: rfc3339-recent",  # 30m → keep
        ]
    )
    out = eapi_mod._window_syslog(buf, now, 24)
    assert "rfc3339-recent" in out
    assert "rfc3339-old" not in out


def test_window_syslog_traditional_with_year():
    """traditional+year uses the explicit year (and ignores a timezone token)."""
    now = datetime.datetime(2026, 6, 26, 16, 0, 0)
    buf = "\n".join(
        [
            "Jun 26 08:00:00 2025 sw1 Ebra: %LINEPROTO-5-UPDOWN: Et19 changed state to down",  # 2025 → drop
            "Jun 26 15:30:00 JST 2026 sw1 Ebra: trad-year-tz-recent",  # explicit 2026 + tz → keep
        ]
    )
    out = eapi_mod._window_syslog(buf, now, 24)
    assert "trad-year-tz-recent" in out
    assert "Jun 26 08:00:00 2025" not in out  # explicit 2025 → out of window


def test_window_syslog_traditional_timezone_no_year_reconstructs():
    """traditional+timezone has no year → reconstruct; tz token is ignored."""
    now = datetime.datetime(2026, 6, 26, 16, 0, 0)
    buf = "Jun 26 15:30:00 JST sw1 Ebra: tz-only-recent"
    out = eapi_mod._window_syslog(buf, now, 24)
    assert "tz-only-recent" in out  # reconstructed to 2026, in window


def test_window_syslog_mixed_formats():
    """A buffer mixing RFC3339, traditional+year and year-less all window right."""
    now = datetime.datetime(2026, 6, 26, 16, 0, 0)
    buf = "\n".join(
        [
            "Jun 20 10:00:00 2026 sw1 Ebra: trad-year-old",  # explicit 2026, >24h → drop
            "Jun 26 15:30:00 sw1 Ebra: yearless-recent",  # reconstruct 2026 → keep
            "Jun 26 15:45:00 2026 sw1 Ebra: trad-year-recent",  # explicit 2026 → keep
            "2026-06-26T15:50:00+09:00 sw1 Ebra: rfc3339-recent",  # RFC3339 → keep
        ]
    )
    out = eapi_mod._window_syslog(buf, now, 24)
    assert "rfc3339-recent" in out
    assert "trad-year-recent" in out
    assert "yearless-recent" in out
    assert "trad-year-old" not in out


def test_window_syslog_numeric_hostname_not_misread_as_year():
    """A 4-digit-leading hostname (default format, no year) must not pose as a year."""
    now = datetime.datetime(2026, 6, 26, 16, 0, 0)
    buf = "\n".join(
        [
            "Jun 20 10:00:00 7280r3 Ebra: numeric-host-old",  # >24h; hostname starts 7280
            "Jun 26 15:30:00 7280r3 Ebra: numeric-host-recent",
        ]
    )
    out = eapi_mod._window_syslog(buf, now, 24)
    assert "numeric-host-recent" in out
    # If "7280" were read as the year, the old line would never fall out of window.
    assert "numeric-host-old" not in out


def test_window_syslog_traditional_year_then_timezone_order():
    """traditional with `year timezone` order (not just `timezone year`)."""
    now = datetime.datetime(2026, 6, 26, 16, 0, 0)
    buf = "Jun 26 15:30:00 2026 JST sw1 Ebra: year-then-tz"
    out = eapi_mod._window_syslog(buf, now, 24)
    assert "year-then-tz" in out


def test_window_syslog_rfc3339_zulu_offset():
    now = datetime.datetime(2026, 6, 26, 16, 0, 0)
    buf = "2026-06-26T15:30:00Z sw1 Ebra: zulu-recent"
    out = eapi_mod._window_syslog(buf, now, 24)
    assert "zulu-recent" in out


def test_window_syslog_keeps_untimestamped_lines():
    now = datetime.datetime(2026, 6, 26, 16, 0, 0)
    out = eapi_mod._window_syslog("a continuation line without timestamp", now, 24)
    assert "continuation line" in out


# ---------------------------------------------------------------------------
# _get_environment_text
# ---------------------------------------------------------------------------


def test_get_environment_text_first_cmd_succeeds():
    node = MagicMock()
    with patch("eos_mcp.eapi.run_show", return_value="temp: Ok") as mock_show:
        result = _get_environment_text(node)
    assert result == "temp: Ok"
    assert mock_show.call_count == 1


def test_get_environment_text_first_fails_second_succeeds():
    node = MagicMock()
    calls = []

    def _side(n, cmd):
        calls.append(cmd)
        if len(calls) == 1:
            raise RuntimeError("unknown command")
        return "env data"

    with patch("eos_mcp.eapi.run_show", side_effect=_side):
        result = _get_environment_text(node)
    assert result == "env data"
    assert len(calls) == 2


def test_get_environment_text_both_fail_returns_empty():
    node = MagicMock()
    with patch("eos_mcp.eapi.run_show", side_effect=RuntimeError("no env")):
        result = _get_environment_text(node)
    assert result == ""


# ---------------------------------------------------------------------------
# get_config_diff
# ---------------------------------------------------------------------------


def test_get_config_diff_first_cmd_succeeds():
    node = MagicMock()
    with patch("eos_mcp.eapi.run_show", return_value="+hostname sw1"):
        result = get_config_diff(node)
    assert result == "+hostname sw1"


def test_get_config_diff_first_fails_second_succeeds():
    node = MagicMock()
    calls = []

    def _side(n, cmd):
        calls.append(cmd)
        if len(calls) == 1:
            raise RuntimeError("no rollback")
        return "+hostname sw1"

    with patch("eos_mcp.eapi.run_show", side_effect=_side):
        result = get_config_diff(node)
    assert result == "+hostname sw1"
    assert len(calls) == 2


def test_get_config_diff_both_fail_returns_message():
    node = MagicMock()
    with patch("eos_mcp.eapi.run_show", side_effect=RuntimeError("not supported")):
        result = get_config_diff(node)
    assert result.startswith("Config diff not available")
