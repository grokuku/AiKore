"""
tests/test_monitor.py — MONITOR coverage (historical bug + sticky fix).

Adapted from tests/test_monitor_teardown_mock.py. Reproduces the historical
bug where, after a SUCCESSFUL readiness poll, the monitor ``break``s out of
the loop and runs the teardown EVEN THOUGH the main process is still alive
(dropping the running_instances entry and killing the kiosk Firefox it just
spawned). Then validates the applied sticky fix: while the process lives the
entry and Firefox survive; teardown only runs on real death.

Runnable standalone (``python3 tests/test_monitor.py``) and pytest-compatible.
"""

import os
import sys
import threading
import time

# Bootstrap: make the `tests` package importable when run standalone.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests._stubs import Suite, run_suite, load_aikore_module

pm = load_aikore_module("aikore.core.process_manager")

_suite = Suite("monitor")


def check(cond, label):
    _suite.check(cond, label)


# --- Fake doubles ------------------------------------------------------------

class _RecQuery:
    def __init__(self, rec):
        self.rec = rec

    def filter(self, *a, **k):
        return self

    def update(self, *a, **k):
        self.rec["update"] = (a, k)
        return 1


class _RecDB:
    def __init__(self, rec):
        self.rec = rec

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def query(self, model):
        return _RecQuery(self.rec)

    def commit(self):
        pass


class _RecSessionMaker:
    def __init__(self, rec):
        self.rec = rec

    def __call__(self):
        return _RecDB(self.rec)


class _FakeFirefox:
    def __init__(self):
        self.pid = 999999  # not a real pid -> killpg raises ProcessLookupError

    def wait(self, timeout=None):
        return 0

    def kill(self):
        pass


class _FakeMain:
    def __init__(self):
        self.alive = True
        self._polls = 0

    def poll(self):
        self._polls += 1
        return None if self.alive else 1

    def wait(self, timeout=None):
        return None


class _FakeResp:
    def __init__(self, status_code=200):
        self.status_code = status_code


def _run_monitor(instance_id, main):
    pm.running_instances.clear()
    pm.firefox_processes.clear()
    pm.running_instances[instance_id] = {"process": main, "monitor_thread": None}
    t = threading.Thread(
        target=pm.monitor_instance_thread,
        args=(instance_id, 1000, 9001, 9001, 9001, "free-token", 1919),
        kwargs={"popen": main}, daemon=True,
    )
    t.start()
    return t


def _wait_firefox(instance_id, timeout=5):
    deadline = time.time() + timeout
    while pm.firefox_processes.get(instance_id) is None and time.time() < deadline:
        time.sleep(0.01)


# --- Historical bug: break -> teardown after first poll ----------------------

def _install_buggy_monitor(pm):
    """In-memory copy of the OLD monitor that ``break``s after the first
    successful poll, then runs teardown even though the process is alive."""

    def buggy_monitor(instance_id, pid, port_to_monitor, internal_app_port,
                      persistent_display, instance_slug, internal_web_port=None, popen=None):
        start_time = time.time()
        last_log_time = 0.0
        while True:
            if popen is not None:
                if popen.poll() is not None:
                    break
            elif not pm.psutil.pid_exists(pid):
                break
            try:
                response = pm.requests.get(f"http://127.0.0.1:{internal_app_port}", timeout=2)
                if response.status_code < 500:
                    with pm.SessionLocal() as db:
                        db.query(pm.models.Instance).filter(
                            pm.models.Instance.id == instance_id,
                            pm.models.Instance.status == "starting",
                        ).update({"status": "started"})
                        db.commit()
                    if persistent_display is not None:
                        ffp = pm.subprocess.Popen(
                            ['/usr/bin/firefox', '--profile', f"/tmp/firefox-profiles/{instance_slug}",
                             '--kiosk', '-url', f'http://127.0.0.1:{internal_web_port or internal_app_port}'],
                            stdout=pm.subprocess.DEVNULL, stderr=pm.subprocess.DEVNULL,
                            start_new_session=True,
                        )
                        pm.firefox_processes[instance_id] = ffp
                    # ---- BUG: break here -> teardown runs while process alive ----
                    break
                time.sleep(pm.MONITOR_POLL_INTERVAL)
            except pm.requests.exceptions.ConnectionError:
                time.sleep(pm.MONITOR_POLL_INTERVAL)
            except Exception:
                time.sleep(pm.MONITOR_POLL_INTERVAL)

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

    pm.monitor_instance_thread = buggy_monitor


def test_historical_bug_teardowns_after_first_poll():
    """Reproduces the bug: after a successful poll the monitor tears down
    (drops the entry + kills Firefox) even though the process is still alive."""
    pm.MONITOR_POLL_INTERVAL = 0.01
    rec = {}
    pm.SessionLocal = _RecSessionMaker(rec)
    orig_get = pm.requests.get
    orig_popen = pm.subprocess.Popen
    orig_monitor = pm.monitor_instance_thread
    pm.requests.get = lambda url, timeout=None: _FakeResp(200)
    pm.subprocess.Popen = lambda *a, **k: _FakeFirefox()
    try:
        _install_buggy_monitor(pm)
        main = _FakeMain()  # stays alive
        t = _run_monitor(1, main)
        # The buggy monitor breaks after the first successful poll and runs
        # teardown, so the thread exits quickly. Join it (deterministic) rather
        # than racing to observe the short-lived Firefox entry.
        t.join(timeout=5)

        check(not t.is_alive(), "buggy monitor thread exited after first poll")
        check(main.poll() is None, "sanity: main process still alive")
        check(1 not in pm.running_instances, "BUG reproduced: entry dropped while process alive")
        check(1 not in pm.firefox_processes, "BUG reproduced: Firefox killed while process alive")
    finally:
        pm.requests.get = orig_get
        pm.subprocess.Popen = orig_popen
        pm.monitor_instance_thread = orig_monitor


def test_applied_fix_sticky_until_death():
    """Validates the applied fix: while the process lives the entry and the
    kiosk Firefox survive; teardown only runs once the process really dies."""
    pm.MONITOR_POLL_INTERVAL = 0.01
    rec = {}
    pm.SessionLocal = _RecSessionMaker(rec)
    orig_get = pm.requests.get
    orig_popen = pm.subprocess.Popen
    pm.requests.get = lambda url, timeout=None: _FakeResp(200)
    pm.subprocess.Popen = lambda *a, **k: _FakeFirefox()
    try:
        main = _FakeMain()  # stays alive initially
        t = _run_monitor(2, main)
        _wait_firefox(2)
        time.sleep(0.3)  # several monitor iterations post-success

        check(main.poll() is None, "sanity: main process still alive")
        check(2 in pm.running_instances, "FIX OK: entry persists while process alive")
        check(2 in pm.firefox_processes, "FIX OK: kiosk Firefox survives while process alive")

        # Real death -> clean teardown.
        main.alive = False
        t.join(timeout=5)
        check(not t.is_alive(), "monitor exits after process death")
        check(2 not in pm.running_instances, "FIX OK: entry dropped on death")
        check(2 not in pm.firefox_processes, "FIX OK: Firefox cleaned up on death")
    finally:
        pm.requests.get = orig_get
        pm.subprocess.Popen = orig_popen


if __name__ == "__main__":
    sys.exit(run_suite(_suite, globals()))
