"""Unit tests for eapi helpers (no live device required)."""

from unittest.mock import MagicMock, patch

import pytest

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

_CLEAN_ENV = (
    "System temperature status  : Ok\n"
    "System cooling status      : Ok\n"
)


def _run_health(
    facts_override=None,
    env_text=_CLEAN_ENV,
    intf_text="",
    mlag_text="state                            : disabled",
):
    """Run check_health with mocked internals. Returns the result dict."""
    node = MagicMock()
    facts = {
        "hostname": "sw1",
        "model": "DCS-7050CX3",
        "version": "4.28.2F",
        "uptime_seconds": 90000,   # 1d 1h — no uptime warning
        "memory_total_kb": 4_000_000,
        "memory_free_kb": 2_000_000,  # 50% — no memory warning
    }
    if facts_override:
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
    node.execute.return_value = {
        "result": [{"output": ""}, {"output": ""}, {"output": ""}, {"output": ""}]
    }
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
    assert result["info"]["uptime"] == "0d 3h"


def test_check_health_uptime_over_1d_no_warning():
    result = _run_health(facts_override={"uptime_seconds": 90000})  # 1d 1h
    assert not any("uptime" in a for a in result["anomalies"])


# ---------------------------------------------------------------------------
# check_health — memory
# ---------------------------------------------------------------------------


def test_check_health_memory_critical_at_90_pct():
    result = _run_health(
        facts_override={"memory_total_kb": 4_000_000, "memory_free_kb": 400_000}
    )
    assert any("CRITICAL: memory 90%" in a for a in result["anomalies"])


def test_check_health_memory_warning_at_80_pct():
    result = _run_health(
        facts_override={"memory_total_kb": 4_000_000, "memory_free_kb": 800_000}
    )
    assert any("WARNING: memory 80%" in a for a in result["anomalies"])


def test_check_health_memory_ok_below_80_pct():
    result = _run_health(
        facts_override={"memory_total_kb": 4_000_000, "memory_free_kb": 2_000_000}
    )
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
# check_health — all-ok baseline
# ---------------------------------------------------------------------------


def test_check_health_all_ok_no_anomalies():
    result = _run_health()
    assert result["anomalies"] == []
    assert result["info"]["hostname"] == "sw1"


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
