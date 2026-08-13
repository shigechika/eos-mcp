# Repository overview

`eos-mcp` is an MCP (Model Context Protocol) server exposing Arista EOS
device operations (show commands, config retrieval/push, tech-support
collection, a daily health-check brief) to AI assistants over **eAPI**
(via `pyeapi`). Built on the official `mcp` Python SDK's `FastMCP`
(`eos_mcp/server.py`), with `eos_mcp/eapi.py` wrapping `pyeapi` connections
and `eos_mcp/config.py` loading device inventory/credentials from
`config.ini`.

See `CLAUDE.md` for the authoritative command list and architecture notes —
read it before reviewing changes to `server.py` or `eapi.py`.

# Build & validate

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest -v
```

This mirrors `.github/workflows/test.yml` (`pip install -e ".[dev]"` +
`pytest tests/ -v`, matrix over Python 3.10/3.12/3.13/3.14 on Ubuntu plus
one `windows-latest` job on 3.12), plus a `lint` job running `ruff check .`
and `ruff format --check .` at the pinned version. Style nits those two would
catch are already enforced, so flagging them adds nothing — but a change that
would fail them is worth raising.

# What to focus review on in this repo

## 1. Transport is stdio-only — stdout is a JSON-RPC channel, not a log stream

`eos_mcp/__main__.py` runs `mcp.run(transport="stdio")` unconditionally; this
server exposes no HTTP transport (if HTTP access is ever needed, it goes
through a separate stdio-to-HTTP bridge, not a mode of this process). Today,
`server.py`/`eapi.py`/`config.py` contain **no** `print()` or `logging` calls
at all — the only stdout writes in the codebase are the `print()`s in
`__main__.py`'s `_check_config()` (the `--check`/`--check-host` path), which
always `sys.exit()`s *before* `mcp.run()` is ever reached, so it never
interleaves with a live JSON-RPC session. Those existing prints are correct
as-is — don't flag them.
The rule for new code: any `print()` or unconfigured logging added to a tool
handler, `eapi.py`, or anywhere on the path `mcp.run()` executes would
corrupt the stdio JSON-RPC stream and must go to stderr instead.

## 2. FastMCP already wraps tool returns — don't ask for manual envelope code

`server.py`'s `@mcp.tool()`-decorated functions return plain strings/dicts;
FastMCP handles the MCP content-envelope wrapping. Do **not** suggest a tool
manually construct `{"content": [...], "isError": ...}` — that pattern is
relevant to other, lower-level (hand-rolled stdio) servers in this family,
not this one.

The actual convention here is the opposite of "let exceptions propagate":
every device-touching tool (`get_device_facts`, `run_command(s)`,
`push_config`, etc.) wraps the call in `try/except Exception` and calls
`eapi.clear_cache(hostname)` on failure so the next call reconnects instead
of reusing a possibly-broken cached connection — it does not re-raise. The
error format differs by tool shape: single-host tools return an
`f"Error ({hostname}): {e}"` string; the `_batch` tools return a per-host
`f"Error: {exc}"` line labelled separately by hostname; `daily_brief`
likewise returns a Markdown **string**, never a dict — the
`{"anomalies": [...], "info": {}}` shape is the internal per-host result
(and `check_health`'s return), rendered into the Markdown brief before the
tool returns, and a config-load failure returns an `f"Error: {e}"` string. A
new device-touching tool that lets an exception
propagate instead of following the catch/clear-cache pattern for its shape
is inconsistent with the rest of the file; flag it. `health_check` is the
deliberate exception: it never touches a device connection at all (verified
by `test_health_check_does_not_connect`), so it has nothing to clear-cache
on.

## 3. Device credentials are the sensitive surface

- Credentials (`username`/`password`/`transport`/`verify`) come from
  `config.ini` (`[DEFAULT]` section or per-host `[hostname]` section, see
  `eos_mcp/config.py:get_creds`) or the `EOS_MCP_CONFIG` env var pointing at
  one. Flag any diff that logs a password, or an eAPI request/response
  containing credentials — including at debug level.
- `verify=False` (skip TLS certificate verification) is the existing
  default in `get_creds`, `eapi.get_node`, and `config.ini.example`, and
  `eapi.py` also monkey-patches `ssl._create_unverified_context` to allow
  legacy ciphers/TLS 1.0 (comment in `eapi.py` explains: EOS 4.28.x
  compatibility under Python's stricter default TLS policy). Both are
  intentional, pre-existing, and documented in-code for reaching older EOS
  devices on a trusted management network — don't flag them as
  vulnerabilities to fix; a genuinely new/unrelated cert-verification
  bypass or credential leak elsewhere is still worth flagging.
- Tool inputs (`hostname`, `command`/`commands`, `config_lines`) come from
  an LLM acting on a user's behalf — treat them as adversarial. Note that
  `eapi.py` passes each command as a discrete element of the list handed to
  pyeapi's eAPI JSON-RPC call (`node.execute([...])`) — there is no
  string-concatenation/shell-building step, so this isn't a classic
  injection surface. The real risk to review for is that `run_command(s)`
  and `push_config` are *designed* to execute arbitrary EOS commands/config
  chosen by the caller with no allow-list: check that destructive-capable
  tools keep using the existing safety rails (`push_config`'s `dry_run=True`
  default, and the commit-timer + explicit `confirm_config_session`/
  `abort_config_session` step) rather than a new tool bypassing them.

## 4. Tool name/docstring quality

A new `@mcp.tool()`'s name and docstring are what the calling model uses to
decide whether/how to invoke it. Compare against the existing style in
`server.py` (e.g. `health_check`, `push_config`): state what side effects
occur (device connection? config change?), parameter defaults that matter
for safety (`dry_run=True`, `commit_timer=300`), and any precondition
(`confirm_config_session` must be called before the timer expires). Flag a
vague name or a docstring that omits a default a caller would need to know.

## 5. Test conventions

Tests use `unittest.mock` (`patch`/`MagicMock`) as the primary approach,
plus pytest's `monkeypatch` for a few cache-state tests; there is no
HTTP-layer mocking library in this repo — pyeapi is mocked at the
`eos_mcp.server._connect` / `eos_mcp.eapi.*` boundary, not at the transport
level. A new test that reaches for a different mocking approach for the
same boundary is inconsistent with `tests/test_server.py` and
`tests/test_eapi.py`; flag it. New device-touching tools need a test for
both a successful call and a connection/command failure (asserting the
tool's error output — a string or a dict, depending on tool shape — and,
where applicable, that `eapi.clear_cache` was invoked).

`tests/test_smoke_probes.py` guards `scripts/smoke_test.py`, which
exercises every registered tool against real devices. It asserts what can
be checked without them: every registered tool has a probe spec, no spec
targets a removed tool, the config-changing tools stay skipped, every
bounding parameter a tool offers is passed explicitly, and no
estate-specific literal (device name, address) is written into the specs —
this repository is public. A new tool therefore needs an entry in
`scripts/smoke_probes.py` or CI fails; that is deliberate, not an obstacle
to route around.

## 6. Two eapi.py invariants that look like simplification targets

Both live only in `eapi.py`'s own docstrings/comments, and a well-meaning
"cleanup" reintroduces a real bug:

- **Client-side syslog windowing (`_get_syslog_text` / `_window_syslog`,
  `eapi.py`).** EOS syslog timestamps carry no year, so the code deliberately
  fetches the **full** buffer and applies a device-clock-anchored, year-aware
  filter (with a 180-day `wrap_gap` heuristic and RFC3339/traditional format
  handling) instead of trusting EOS's native `show logging last N hours`. A
  diff that "simplifies" this to the native last-N-hours form reintroduces the
  prior-year-leak bug the subsystem exists to fix. The `_SYSLOG_ALERT_RE`
  BGP/OSPF patterns are **direction-guarded** (only down/reset transitions
  match) and matches are capped at `_SYSLOG_MAX_MATCHES` (10) per device —
  dropping a direction guard makes every normal session establishment a
  WARNING. This is the correctness core of `daily_brief`.
- **`push_config` session context (`eapi.py`).** All commands — `configure
  session <name>`, the `config_lines`, `show session-config diffs`, and the
  `abort`/commit-timer — must be sent in **one** `node.execute()` call to keep
  the configure-session context, and the diff is extracted **positionally**
  (`diffs_idx = 1 + len(config_lines)`). A refactor that splits the command
  list across multiple `execute()` calls, or inserts/reorders a command
  without updating that index arithmetic, silently breaks the push or reports
  the wrong output as the diff.

# Out of scope for review comments

- Formatting/style nits that `ruff check .` and `ruff format --check .`
  already enforce — see "Build & validate" above for the distinction that
  matters: restating such a nit adds nothing, while a change that would
  actually fail either gate is still worth raising. There is no `black` or
  `mypy` step, so don't hold this repo to a typing standard it hasn't
  opted into.
- `release-please.yml`'s use of `secrets.RELEASE_PLEASE_TOKEN` (falling back
  to `GITHUB_TOKEN`) is intentional and documented in the workflow's own
  comment (`GITHUB_TOKEN`-authored tags/releases don't trigger downstream
  workflows) — don't suggest reverting it.
- The TLS/cert-verification relaxations described in item 3 are intentional
  EOS-compatibility choices, not oversights.
