# Review rules for this repository

Review rules on top of the reviewer's default focus. Three things:
which findings are blocking here, which classes to report that the
default focus would otherwise skip, and which are noise. The reasoning
behind the rules lives in `.github/copilot-instructions.md` (its
numbered focus items are cited below) and `CLAUDE.md`, which the
reviewer also receives.

## Always blocking

- **A device credential reaching a log line or a tool response (§3).**
  A password from `config.ini` or `EOS_MCP_CONFIG`, or an eAPI
  request/response carrying credentials — at any level, debug
  included.
- **A destructive-capable tool that bypasses the existing safety rails
  (§3).** `run_command(s)` and `push_config` execute arbitrary EOS
  commands and configuration chosen by the caller, with no allow-list;
  the rails are what make that acceptable. A new tool must keep
  `push_config`'s `dry_run=True` default and the commit-timer plus
  explicit `confirm_config_session` / `abort_config_session` step
  rather than routing around them.
- **"Simplifying" the client-side syslog windowing (§6).** EOS syslog
  timestamps carry no year, so `_get_syslog_text` / `_window_syslog`
  fetch the full buffer and apply a device-clock-anchored, year-aware
  filter on purpose. Replacing that with EOS's native `show logging
  last N hours` reintroduces the prior-year-leak bug the subsystem
  exists to fix. Dropping a direction guard from `_SYSLOG_ALERT_RE`, or
  the `_SYSLOG_MAX_MATCHES` cap, belongs here too: without the guard
  every normal BGP or OSPF session establishment becomes a WARNING.
  This is the correctness core of `daily_brief`.
- **Breaking `push_config`'s single-`execute()` session context (§6).**
  `configure session <name>`, the `config_lines`, `show session-config
  diffs` and the `abort`/commit-timer must go in **one**
  `node.execute()` call to keep the configure-session context, and the
  diff is extracted **positionally** via `diffs_idx = 1 +
  len(config_lines)`. Splitting the list across calls, or
  inserting/reordering a command without updating that arithmetic,
  silently breaks the push or reports the wrong output as the diff.

## Report even though the default focus would not

- **A new `@mcp.tool()`'s name and docstring (§4).** The calling model
  decides whether and how to invoke a tool by reading them, so this is
  functional here rather than cosmetic — report it even though
  docstring accuracy is normally out of scope when reviewing code. The
  bar set by `health_check` and `push_config`: state the side effects
  (does it connect to a device? change configuration?), the defaults
  that matter for safety (`dry_run=True`, `commit_timer=300`), and any
  precondition (`confirm_config_session` must be called before the
  timer expires).
- **A diff that adds a device-touching tool and also touches `tests/`
  without covering a connection or command failure (§5)**, as
  advisory — including, where applicable, that `eapi.clear_cache` was
  invoked. Judge it from the diff only: you receive changed files, so a
  pull request that leaves `tests/` alone may well be covered by tests
  you were not given.
- **A test mocking a boundary this suite already mocks differently
  (§5)**, as advisory. pyeapi is faked at the
  `eos_mcp.server._connect` / `eos_mcp.eapi.*` boundary using
  `unittest.mock`, with `monkeypatch` for a few cache-state tests;
  there is no HTTP-layer mocking library here, and reaching for one is
  inconsistent with `tests/test_server.py` and `tests/test_eapi.py`.

## Never report

- The **existing** TLS relaxations: `verify=False` as the default in
  `get_creds`, `eapi.get_node` and `config.ini.example`, and
  `eapi.py`'s monkey-patch of `ssl._create_unverified_context` for
  legacy ciphers and TLS 1.0. Both are deliberate, pre-existing and
  documented in-code for reaching EOS 4.28.x devices on a trusted
  management network. This covers those specific choices only — a
  genuinely new or unrelated certificate-verification bypass, anywhere
  else, stays blocking above.
- Command injection via the eAPI call path. `eapi.py` hands each
  command to pyeapi as a discrete list element (`node.execute([...])`);
  there is no string concatenation or shell construction, so this is
  not that class of surface. The real risk is the arbitrary-execution
  design itself, which the rails above cover.
- Anything CI already fails on, restated as a review comment. `ruff
  check .` and `ruff format --check .` both gate this repository at a
  pinned version, and `tests/test_smoke_probes.py` already fails the
  build for a registered tool with no probe spec. This does **not**
  extend to that file's estate-specific-literal assertion — a device
  name or address leaking into a public repository is worth catching
  twice.
- Suggestions to *replace* `release-please.yml`'s
  `secrets.RELEASE_PLEASE_TOKEN` with `GITHUB_TOKEN`. Preferring the
  dedicated token is deliberate and explained in that workflow's own
  comment, because a `GITHUB_TOKEN`-authored tag or release does not
  trigger downstream workflows. (The line falls back to `GITHUB_TOKEN`
  when the secret is unset, so a finding about the fallback arm itself
  is still fair game.)
