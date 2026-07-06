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
one `windows-latest` job on 3.12). `ruff` is configured in `pyproject.toml`
but there is no lint job in CI — don't invent style nits it would catch,
since it doesn't run here.

# What to focus review on in this repo

## 1. Transport is not stdio-only — check which mode a change affects

`eos_mcp/__main__.py` supports `--transport stdio` (default) and
`--transport streamable-http`, both dispatched via `mcp.run(transport=...)`.
Today, `server.py`/`eapi.py`/`config.py` contain **no** `print()` or
`logging` calls at all — the only stdout writes in the codebase are the
`print()`s in `__main__.py`'s `_check_config()` (the `--check`/`--check-host`
path), which always `sys.exit()`s *before* `mcp.run()` is ever reached, so it
never interleaves with a live JSON-RPC session. Those existing prints are
correct as-is — don't flag them.
The rule for new code: any `print()` or unconfigured logging added to a tool
handler, `eapi.py`, or anywhere on the path `mcp.run()` executes would
corrupt the stdio JSON-RPC stream and must go to stderr instead. This
constraint is specific to the stdio transport; under `streamable-http` a
stray stdout write wouldn't corrupt the protocol response, but since the
tool code is shared between both transports, treat the discipline as
universal for anything in `server.py`/`eapi.py`/`config.py`.

## 2. FastMCP already wraps tool returns — don't ask for manual envelope code

`server.py`'s `@mcp.tool()`-decorated functions return plain strings/dicts;
FastMCP handles the MCP content-envelope wrapping. Do **not** suggest a tool
manually construct `{"content": [...], "isError": ...}` — that pattern is
relevant to other, lower-level (hand-rolled stdio) servers in this family,
not this one.

The actual convention here is the opposite of "let exceptions propagate":
every device-touching tool (`get_device_facts`, `run_command(s)`,
`push_config`, etc.) wraps the call in `try/except Exception`, calls
`eapi.clear_cache(hostname)` on failure so the next call reconnects instead
of reusing a possibly-broken cached connection, and returns an
`f"Error ({hostname}): {e}"` string — it does not re-raise. A new
device-touching tool that lets an exception propagate instead of following
this catch/clear-cache/return-string pattern is inconsistent with the rest
of the file; flag it. `health_check` is the deliberate exception: it never
touches a device connection at all (verified by
`test_health_check_does_not_connect`), so it has nothing to clear-cache on.

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

All tests use `unittest.mock` (`patch`/`MagicMock`); there is no HTTP-layer
mocking library in this repo — pyeapi is mocked at the `eos_mcp.server._connect`
/ `eos_mcp.eapi.*` boundary, not at the transport level. A new test that
reaches for a different mocking approach for the same boundary is
inconsistent with `tests/test_server.py` and `tests/test_eapi.py`; flag it.
New device-touching tools need a test for both a successful call and a
connection/command failure (asserting the `Error (...)` string and, where
applicable, that `eapi.clear_cache` was invoked).

# Out of scope for review comments

- Formatting/style nits: there is no `ruff`/`black`/`mypy` step in CI, so
  don't hold this repo to a style standard it hasn't opted into.
- `release-please.yml`'s use of `secrets.RELEASE_PLEASE_TOKEN` (falling back
  to `GITHUB_TOKEN`) is intentional and documented in the workflow's own
  comment (`GITHUB_TOKEN`-authored tags/releases don't trigger downstream
  workflows) — don't suggest reverting it.
- The TLS/cert-verification relaxations described in item 3 are intentional
  EOS-compatibility choices, not oversights.
