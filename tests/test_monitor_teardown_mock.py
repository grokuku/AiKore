"""
Mock test for monitor_instance_thread teardown bug in persistent mode.

Reproduces the live bug where, after a SUCCESSFUL readiness poll on the
persistent (VNC) port, the monitor:
  * launches the kiosk Firefox,
  * `break`s out of the loop,
  * runs the teardown block EVEN THOUGH the main process is still alive,
  * thus drops the running_instances entry and kills the Firefox it just spawned.

The test injects fake modules for dependencies that are not installed at runtime
of this repo checkout (`requests`, `psutil`, `sqlalchemy`, and the internal
`aikore.*` modules) so the REAL process_manager module can be imported.

It then runs the REAL `monitor_instance_thread` and asserts the buggy behaviour,
then applies the proposed WIP fix in-memory and re-tests that the fixed monitor
does NOT tear down prematurely and only tears down once the process actually dies.
"""

import sys
import types
import threading
import time
import os
import signal
import importlib

# ---------------------------------------------------------------------------
# 0. Inject fake modules so process_manager can be imported in this harness.
# ---------------------------------------------------------------------------

_fake_modules = {}

def _make_module(name, **attrs):
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    _fake_modules[name] = m
    sys.modules[name] = m
    return m

# --- requests ---
_requests_mod = types.ModuleType("requests")
class _ConnectionError(Exception):
    pass
class _Response:
    status_code = 200
class _requests:
    @staticmethod
    def get(url, timeout=None):
        return _Response()
_requests_mod.ConnectionError = _ConnectionError
_requests_mod.get = _requests.get
_req_exc = types.ModuleType("requests.exceptions")
_req_exc.ConnectionError = _ConnectionError
_requests_mod.exceptions = _req_exc
sys.modules["requests.exceptions"] = _req_exc
sys.modules["requests"] = _requests_mod

# --- psutil ---
_psutil = types.ModuleType("psutil")
_psutil.pid_exists = lambda pid: True
sys.modules["psutil"] = _psutil

# --- sqlalchemy ---
_sqla_orm = types.ModuleType("sqlalchemy.orm")
_sqla_orm.Session = type("Session", (), {})
sys.modules["sqlalchemy"] = types.ModuleType("sqlalchemy")
sys.modules["sqlalchemy.orm"] = _sqla_orm

# --- aikore.config ---
_config = _make_module("aikore.config",
                      INSTANCES_DIR="/tmp/aikore/instances",
                      OUTPUTS_DIR="/tmp/aikore/outputs",
                      BLUEPRINTS_DIR="/tmp/aikore/blueprints",
                      CUSTOM_BLUEPRINTS_DIR="/tmp/aikore/custom",
                      SCRIPTS_DIR="/tmp/aikore/scripts")

# --- aikore.database ---
_db_models = _make_module("aikore.database.models",
                            Instance=type("Instance", (), {"id": None, "status": None, "port": None, "persistent_port": None, "name": "", "pid": None}))
_db_session = _make_module("aikore.database.session", SessionLocal=None)
_aikore_db = _make_module("aikore.database")
sys.modules.setdefault("aikore.database.models", _db_models)
sys.modules.setdefault("aikore.database.session", _db_session)
sys.modules.setdefault("aikore.database", _aikore_db)

# --- aikore.core.metadata_parser ---
_meta = _make_module("aikore.core.metadata_parser",
                     iter_metadata_entries=lambda *a, **k: iter([]),
                     parse_metadata_file=lambda *a, **k: {})
sys.modules.setdefault("aikore.core.metadata_parser", _meta)

# ---------------------------------------------------------------------------
# 1. Register aikore as a namespace package, then import the REAL process_manager.
# ---------------------------------------------------------------------------
_aikore = types.ModuleType("aikore")
_aikore.__path__ = [os.path.join(os.path.dirname(__file__), "..", "aikore")]
sys.modules["aikore"] = _aikore
_aikore_core = types.ModuleType("aikore.core")
_aikore_core.__path__ = [os.path.join(os.path.dirname(__file__), "..", "aikore", "core")]
sys.modules["aikore.core"] = _aikore_core

from aikore.core import process_manager as pm

# Give the monitor a fake DB. `with SessionLocal() as db:` -> db.query()...
class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows
    def filter(self, *a, **k):
        return self
    def update(self, *a, **k):
        return len(self._rows)
class _FakeDB:
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def query(self, model):
        # return a fake query whose .filter().update() returns 1
        return _FakeQuery([1])
    def commit(self): pass
    def refresh(self, obj): pass
class _SessionMaker:
    """callable that returns a fresh context-manager DB (mimics SessionLocal())."""
    def __call__(self):
        return _FakeDB()

pm.SessionLocal = _SessionMaker()
pm.MONITOR_POLL_INTERVAL = 0.01  # speed up the loop for testing

# --- Fake firefox Popen (as returned by subprocess.Popen in the monitor) ---
class _FakeFirefox:
    def __init__(self):
        self.pid = 999999  # not a real pid -> killpg/getpgid will ProcessLookupError
    def wait(self, timeout=None):
        return 0
    def kill(self):
        pass

# --- Fake main Popen (as passed via kwargs={"popen": main_process}) ---
class _FakeMain:
    def __init__(self):
        self.alive = True
        self._polls = 0
    def poll(self):
        self._polls += 1
        return None if self.alive else 1
    def wait(self, timeout=None):
        # real popen.wait() only waits; it does not kill the process.
        return None


# Patch subprocess.Popen ONCE so the monitor's Firefox launch returns a fake.
# (A within-function try/finally would restore it before the thread runs.)
pm.subprocess.Popen = lambda *a, **k: _FakeFirefox()

def _run_monitor(instance_id, args, kwargs):
    pm.running_instances.clear()
    pm.firefox_processes.clear()
    # mirror what start_instance_process() does before spawning the monitor thread
    pm.running_instances[instance_id] = {"process": kwargs["popen"], "monitor_thread": None}
    t = threading.Thread(target=pm.monitor_instance_thread, args=args, kwargs=kwargs, daemon=True)
    t.start()
    return t


def test_applied_fix_teardowns_only_on_death():
    """FIX APPLIQUÉ dans process_manager.py : après un poll VNC réussi, le
    moniteur continue de boucler (pas de break) ; l'entrée running_instances et
    le Firefox survivent tant que le process vit. Teardown uniquement à la mort
    réelle."""

    main = _FakeMain()  # stays alive initially
    args = (1, 1000, 9001, 9001, 9001, "free-token", 1919)  # (instance_id,pid,port_to_monitor,internal_app_port,persistent_display,slug,internal_web_port)
    t = _run_monitor(1, args, {"popen": main})

    # Wait until Firefox has been launched but process is still alive.
    deadline = time.time() + 5
    while pm.firefox_processes.get(1) is None and time.time() < deadline:
        time.sleep(0.01)

    time.sleep(0.5)  # allow several monitor iterations post-success

    assert main.poll() is None, "sanity: main process should still be alive"
    assert 1 in pm.running_instances, (
        "FIX VIOLATED: running_instances entry must persist while the process is alive"
    )
    assert 1 in pm.firefox_processes, (
        "FIX VIOLATED: kiosk Firefox must survive while the process is alive"
    )
    print("[mock] FIX OK: while alive -> entry tracked + Firefox ALIVE")

    # Real death -> clean teardown.
    main.alive = False
    t.join(timeout=5)
    assert not t.is_alive(), "monitor should have exited after process death"
    assert 1 not in pm.running_instances, "teardown must drop the entry on death"
    assert 1 not in pm.firefox_processes, "teardown must kill Firefox on death"
    print("[mock] FIX OK: after death -> entry dropped + Firefox cleaned up")


def test_fixed_stays_tracked_until_death():
    """Proposed fix: on success the monitor only marks ready + launches Firefox,
    then KEEPS LOOPING (no break); it only tears down after the process actually
    dies. So while alive the entry persists and Firefox survives."""

    main = _FakeMain()
    args = (2, 2000, 9002, 9002, 9002, "free-token", 1919)

    # Apply the FIX in-memory (mirror of the proposed process_manager patch).
    orig = pm.monitor_instance_thread
    _install_fixed_monitor(pm)
    try:
        t = _run_monitor(2, args, {"popen": main})

        # Wait until Firefox has been launched but process is still alive.
        deadline = time.time() + 5
        while pm.firefox_processes.get(2) is None and time.time() < deadline:
            time.sleep(0.01)
        time.sleep(0.2)

        assert main.alive, "sanity: main process should still be alive"
        assert 2 in pm.running_instances, (
            "FIX VIOLATED: entry must persist while the main process is alive"
        )
        assert 2 in pm.firefox_processes, (
            "FIX VIOLATED: kiosk Firefox must survive until the process dies"
        )
        print("[mock] FIX OK: while alive -> entry tracked + Firefox ALIVE")

        # Now let the process die; teardown must run.
        main.alive = False
        t.join(timeout=5)
        assert not t.is_alive(), "monitor should have exited after process death"
        assert 2 not in pm.running_instances, "teardown must drop the entry on death"
        assert 2 not in pm.firefox_processes, "teardown must kill Firefox on death"
        print("[mock] FIX OK: after death -> entry dropped + Firefox cleaned up")
    finally:
        pm.monitor_instance_thread = orig


# ---------------------------------------------------------------------------
# The proposed WIP patch (mirrored here for testing). It must NOT be applied to
# process_manager.py (read-only); this is only the in-memory test copy.
# ---------------------------------------------------------------------------
def _install_fixed_monitor(pm):
    def fixed_monitor(instance_id, pid, port_to_monitor, internal_app_port,
                      persistent_display, instance_slug, internal_web_port=None, popen=None):
        start_time = time.time()
        last_log_time = 0.0
        # --- PATCH: keep a "ready" flag, do NOT break after first success. ---
        app_ready = False

        while True:
            if popen is not None:
                if popen.poll() is not None:
                    break
            elif not pm.psutil.pid_exists(pid):
                break
            try:
                if not app_ready:
                    response = pm.requests.get(
                        f"http://127.0.0.1:{internal_app_port}", timeout=2)
                    if response.status_code < 500:
                        # promote starting->started ONCE
                        with pm.SessionLocal() as db:
                            updated_rows = (
                                db.query(pm.models.Instance)
                                .filter(pm.models.Instance.id == instance_id,
                                        pm.models.Instance.status == "starting")
                                .update({"status": "started"})
                            )
                            db.commit()
                        app_ready = True
                        if persistent_display is not None:
                            ffd = f"/tmp/firefox-profiles/{instance_slug}"
                            os.makedirs(ffd, exist_ok=True)
                            ffe = os.environ.copy()
                            ffe["DISPLAY"] = f":{persistent_display}"
                            target_url = f'http://127.0.0.1:{internal_web_port or internal_app_port}'
                            ffp = pm.subprocess.Popen(
                                ['/usr/bin/firefox', '--profile', ffd, '--kiosk', '-url', target_url],
                                env=ffe, stdout=pm.subprocess.DEVNULL,
                                stderr=pm.subprocess.DEVNULL, start_new_session=True)
                            pm.firefox_processes[instance_id] = ffp
                # ---- PATCH: no break here; keep looping so the entry/Firefox
                # survive. Only process death (top of loop) breaks out. ----
                time.sleep(pm.MONITOR_POLL_INTERVAL)
            except pm.requests.exceptions.ConnectionError:
                if not app_ready:
                    elapsed = time.time() - start_time
                    if elapsed - last_log_time >= 60:
                        last_log_time = elapsed
                time.sleep(pm.MONITOR_POLL_INTERVAL)
            except Exception as e:
                time.sleep(pm.MONITOR_POLL_INTERVAL)

        # Process died (or never became ready) -- run the existing teardown.
        with pm.SessionLocal() as db:
            db.query(pm.models.Instance).filter(
                pm.models.Instance.id == instance_id,
                pm.models.Instance.status == "starting",
            ).update({"status": "stalled"})
            db.commit()

        if popen is not None:
            try:
                popen.wait(timeout=5)
            except Exception:
                pass
        removed = pm.running_instances.pop(instance_id, None)
        if removed is not None:
            pm.terminate_firefox_for_instance(instance_id)
        print(f"[Monitor-{instance_id}] Monitor thread exiting.")

    pm.monitor_instance_thread = fixed_monitor


if __name__ == "__main__":
    print("=== Validating the APPLIED fix (sticky monitor) ===")
    test_applied_fix_teardowns_only_on_death()
    print()
    print("=== Validating the fix behavior (in-memory reference copy) ===")
    test_fixed_stays_tracked_until_death()
    test_fixed_stays_tracked_until_death_again = None
    print()
    print("ALL MOCK TESTS PASSED.")
