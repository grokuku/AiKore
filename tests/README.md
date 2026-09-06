# AiKore — Persistent Test Suites

Reconstruction, in `tests/`, of the test suites that previously lived in `/tmp`
(ephemeral, lost). Everything lives **only** under `tests/` — nothing in the
production code is modified.

## Quick start

```bash
# Run every suite (recommended)
python3 tests/run_tests.py

# Run a single suite
python3 tests/run_tests.py --suite auth
python3 tests/run_tests.py --suite validation
python3 tests/run_tests.py --suite stability
python3 tests/run_tests.py --suite monitor

# Or run a suite standalone (same harness, own PASS/FAIL counter + exit code)
python3 tests/test_auth.py
```

`run_tests.py` runs each suite in a fresh interpreter, times every suite with
`time.perf_counter` (plus the total), prints a summary table
(`suite | checks | pass | fail | time`) and exits non-zero if anything failed.

## Dual-mode principle

AiKore's runtime container ships `fastapi` / `pydantic` / `sqlalchemy` /
`psutil` / `requests`, but the dev environment where these tests are validated
does **not**. `tests/_stubs.py` centralises the stub-injection pattern:

* If a third-party dependency is importable, the **real** module is used.
* Otherwise a minimal stub is installed into `sys.modules` so the **real**
  `aikore.*` modules can be imported and exercised.

`tests/_stubs.py` also wires up the `aikore` namespace package (pointing at the
real source tree) and pre-installs stubs for the modules that would otherwise
touch `/config` or the real database (`aikore.config`, `aikore.database.session`,
`aikore.database.crud`). No test touches `/config`, the real DB, the network,
or requires a GPU.

Each suite is:
* **standalone** — `python3 tests/test_*.py` with its own PASS/FAIL counter and
  exit code;
* **pytest-compatible** — `test_*` functions using plain `assert`s (the shared
  `Suite.check()` both records and asserts), ready for a future pytest run;
* **offline / no GPU / no real DB** — stubs only.

## What each suite covers

### `test_auth.py` — `aikore/core/auth.py` (pure ASGI middleware)
* Disabled without `AIKORE_API_KEY` → pass-through.
* Enabled → 401 without credential; pass with `Bearer` / `X-API-Key`; 401 on
  wrong key.
* Public paths `/`, `/favicon.ico`, `/static/*` + `AIKORE_AUTH_PUBLIC_PATHS`.
* WebSocket Origin: same-origin with non-default port passes; cross-origin
  blocked; `X-Forwarded-Host` fallback; `AIKORE_WS_ALLOWED_ORIGINS`.
* Subprotocol `['aikore-auth', key]` selected without echoing the key.
* `OPTIONS` pass-through.
* Symmetric stripping of default ports 80/443.

### `test_validation.py` — `aikore/schemas/instance.py` + `aikore/api/builder.py`
* Instance name regex: valid, `../../etc/x` refused, absolute refused,
  65 chars refused, trailing space refused.
* `base_blueprint`: `ok.sh` vs `../../../etc/passwd`.
* `output_path`: relative ok, absolute / `..` refused.
* `Copy` / `Instantiate` `new_name`.
* Builder `git_url`: `https` OK, `; curl` refused, newline refused (fullmatch).
* `cuda_arch`: `8.6` ok, `8.6; touch /tmp/x` refused.
* Wheel filename: `.`, `..`, NUL, `/` refused.
* Containment guard `is_relative_to`.

### `test_stability.py` — `process_manager`, `migration`, `metadata_parser`, `instances`
* Monitor: dead process (`poll`) → entry removed + no infinite loop;
  conditional `starting`→`started` promotion.
* Double-start concurrent → only one starts.
* Stop with `ProcessLookupError` → no exception + cleanup in `finally`.
* Concurrent port allocation → distinct ports.
* Migration: `DatabaseVersionError` (no silent fallback to 1); backup before
  `ALTER`.
* Metadata parser: dots preserved, dequoting.
* Delete during `installing` → 409.
* Invalid port range → 400.

### `test_monitor.py` — historical bug + sticky fix
Adapted from the original `test_monitor_teardown_mock.py`:
* Reproduces the historical bug: after a successful readiness poll the monitor
  `break`s and tears down (drops the entry + kills the kiosk Firefox) even
  though the process is still alive.
* Validates the applied sticky fix: while the process lives the entry and the
  Firefox survive; teardown only runs on real death.

## Files

| File | Purpose |
|------|---------|
| `tests/_stubs.py` | Dual-mode stub injection + shared `Suite`/`run_suite` harness |
| `tests/test_auth.py` | AUTH coverage |
| `tests/test_validation.py` | VALIDATION coverage |
| `tests/test_stability.py` | STABILITY coverage |
| `tests/test_monitor.py` | MONITOR bug + fix coverage |
| `tests/run_tests.py` | Local runner (timing + summary table) |
| `tests/README.md` | This file |
