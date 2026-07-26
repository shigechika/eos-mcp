"""Probe specs for this server's tools — the EOS-specific half of the smoke test.

Every registered tool needs an entry here (the harness fails on a tool with no
spec), so adding a tool forces a decision: how would we know it works?

Three constraints shape everything below.

**Read-only.** These tools drive production switches. Everything that can
change one — pushing config, confirming or aborting a session — is skipped by
name and must stay skipped; the test suite enforces it. Collecting a
tech-support bundle is skipped too: it changes nothing, but it is minutes of
device CPU for an answer no assertion here would read.

**No inventory-specific values in this file.** This repository is public, so a
probe may not name a device. The tools that take a hostname get one from an
``args_factory`` that reads the configured inventory at run time, and skip when
it is empty.

**Bounded.** The fan-out tools run against every configured device by default;
each probe pins the parallelism explicitly rather than inheriting it.

Assertions are shape-first: these tools answer with formatted text and render
their failures as ordinary text rather than raising, so every probe both pins
the shape a working answer has and refuses the ``Error (<host>): ...`` line the
tool produces instead. A device that answers "no rollback checkpoint" is fine;
a device that could not be reached is not.
"""

import re
from typing import Any

from smoke_harness import Caller, Probe, SkipProbe

#: A command every EOS device answers and no device is changed by. Chosen over
#: a device-specific show so the probe stays valid on any inventory.
SHOW_COMMAND = "show version"

#: A field its output always carries. The tools label the command either way —
#: "--- show version ---" or "# <host>" appear whether the RPC answered or
#: failed — so the label proves nothing and the body has to be named.
SHOW_COMMAND_MARKER = r"(?i)software image version|image version"

#: One worker: the probes below hit a single discovered device, and pinning the
#: value keeps a scheduled run from inheriting a fan-out sized for an operator
#: sweeping the estate.
MAX_WORKERS = 1


async def _first_host(call: Caller) -> dict[str, Any]:
    """Discover a configured device at run time for the per-host tools."""
    payload = await call("get_router_list", {})
    text = payload if isinstance(payload, str) else str(payload)
    # "Hosts (N) from <path>:" then one indented "  <host>  tags=..." per
    # device. The header is not indented, so it cannot be mistaken for an
    # entry, and the name runs to the two-space separator because a
    # configuration section name may contain a space.
    match = re.search(r"^ {2}(\S.*?) {2}tags=", text, re.MULTILINE)
    if not match:
        raise SkipProbe("no device configured to probe with")
    return {"hostname": match.group(1)}


async def _first_host_as_target(call: Caller) -> dict[str, Any]:
    """The same device, shaped for the tools that take a list of targets."""
    args = await _first_host(call)
    return {"hostnames": [args["hostname"]]}


#: Every tool renders a failed connection as text rather than raising, so each
#: probe has to refuse that line explicitly — otherwise an unreachable device
#: reads as a successful call.
NO_ERROR = (r"^Error[ (:]", r"^No hosts resolved")


PROBES: dict[str, Probe] = {
    # -- server / inventory --------------------------------------------------
    "health_check": Probe(
        require_keys=("status", "service"),
        must_match=(r'"status": "(healthy|degraded)"',),
        allow_empty=True,
    ),
    # The inventory is what every other probe discovers from, so an empty one
    # is a failure here even though it is only a skip further down.
    "get_router_list": Probe(
        must_match=(r"^Hosts \(\d+\) from ",),
        must_not_match=(r"^No hosts found", *NO_ERROR),
    ),
    # -- per-device reads ----------------------------------------------------
    "get_version": Probe(
        args_factory=_first_host,
        must_match=(r"EOS ",),
        must_not_match=NO_ERROR,
    ),
    "get_device_facts": Probe(
        args_factory=_first_host,
        must_match=(r"^hostname: ", r"^EOS version: ", r"^uptime: "),
        must_not_match=NO_ERROR,
    ),
    "get_config": Probe(
        args_factory=_first_host,
        # A running-config always carries a hostname line; asserting a minimum
        # size as well catches a truncated or empty read.
        must_match=(r"^hostname ",),
        min_chars=200,
        must_not_match=NO_ERROR,
    ),
    # The old assertion offered "\\S" as an alternative, which any answer at
    # all satisfies. The two real answers are named instead, and the sentence
    # the eAPI layer returns when it could not run either command — which is
    # not an "Error:" line, so nothing else would have caught it.
    "get_config_diff": Probe(
        args_factory=_first_host,
        args={"rollback_id": 1},
        must_match=(r"^\(no diff — running-config matches checkpoint\)|^! Command:|^[-+@]",),
        must_not_match=(*NO_ERROR, r"^Config diff not available"),
    ),
    "list_config_sessions": Probe(
        args_factory=_first_host,
        # An estate with no open sessions is the desired state, and EOS answers
        # with an empty table rather than an error, so this asserts only that
        # the device answered something.
        min_chars=1,
        must_not_match=NO_ERROR,
    ),
    # -- command execution ---------------------------------------------------
    # Exercised with a show command: these tools accept enable-mode commands in
    # general, and the smoke test must not be the thing that types one that
    # matters.
    "run_command": Probe(
        args_factory=_first_host,
        args={"command": SHOW_COMMAND},
        must_match=(r"\S",),
        min_chars=20,
        must_not_match=NO_ERROR,
    ),
    "run_commands": Probe(
        args_factory=_first_host,
        args={"commands": [SHOW_COMMAND, "show hostname"]},
        # The "--- <command> ---" labels alone are ~44 characters, so a length
        # bound was satisfied by an entirely empty result.
        must_match=(rf"^--- {SHOW_COMMAND} ---", SHOW_COMMAND_MARKER),
        must_not_match=NO_ERROR,
    ),
    "run_command_batch": Probe(
        args_factory=_first_host_as_target,
        args={"command": SHOW_COMMAND, "max_workers": MAX_WORKERS},
        # "# <host>" heads each device's section — and is printed even when
        # that device answered nothing, hence the second pattern.
        must_match=(r"^# \S", SHOW_COMMAND_MARKER),
        must_not_match=NO_ERROR,
    ),
    "run_commands_batch": Probe(
        args_factory=_first_host_as_target,
        args={"commands": [SHOW_COMMAND], "max_workers": MAX_WORKERS},
        must_match=(r"^# \S", SHOW_COMMAND_MARKER),
        must_not_match=NO_ERROR,
    ),
    # The header is printed before any device answers, and a per-host failure
    # is "Error: ..." placed after a padded hostname — mid-line, where the
    # line-anchored guard cannot see it. Both halves are named here.
    "get_device_facts_batch": Probe(
        args_factory=_first_host_as_target,
        args={"max_workers": MAX_WORKERS},
        must_match=(r"^Device facts \(\d+ hosts\):", r"EOS \S+\s+serial="),
        must_not_match=(*NO_ERROR, r"\s+Error: "),
    ),
    # -- morning patrol ------------------------------------------------------
    # The header is assembled before any device is contacted, and a connection
    # failure becomes "- CRITICAL: connection failed: ..." inside the host's
    # section — never an "Error:" line. Requiring the per-host section proves
    # the brief got that far; refusing that one anomaly separates "this device
    # has a problem" (a real answer, left to pass) from "the tool could not
    # reach it at all".
    "daily_brief": Probe(
        args_factory=_first_host_as_target,
        args={"max_workers": MAX_WORKERS, "since_hours": 24},
        must_match=(r"^## EOS ", r"^### \S+ \[(OK|WARNING|CRITICAL)\]"),
        must_not_match=(*NO_ERROR, r"CRITICAL: connection failed"),
        timeout=600,
    ),
    # -- tools that change a device: never exercised -------------------------
    "push_config": Probe(skip="writes to a production switch"),
    "confirm_config_session": Probe(skip="commits a pending configuration change"),
    "abort_config_session": Probe(skip="discards someone else's pending session"),
    "collect_tech_support": Probe(skip="minutes of device CPU for an answer no assertion here would read"),
}
