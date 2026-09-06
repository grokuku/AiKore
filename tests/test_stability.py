"""
tests/test_stability.py — STABILITY coverage.

Covers:
  * monitor: dead process (poll) -> entry removed + no infinite loop;
    conditional starting->started promotion
  * double-start concurrent -> only one starts
  * stop with ProcessLookupError -> no exception + cleanup in finally
  * concurrent port allocation -> distinct ports
  * migration: DatabaseVersionError (no silent fallback to 1); backup before ALTER
  * metadata parser: dots preserved, dequoting
  * delete during installing -> 409
  * invalid port range -> 400

Runnable standalone (``python3 tests/test_stability.py``) and pytest-compatible.
"""

import os
import sqlite3
import sys
import threading
import time

# Bootstrap: make the `tests` package importable when run standalone.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests._stubs import Suite, run_suite, load_aikore_module

pm = load_aikore_module("aikore.core.process_manager")
migration = load_aikore_module("aikore.database.migration")
metadata = load_aikore_module("aikore.core.metadata_parser")
instances = load_aikore_module("aikore.api.instances")

_suite = Suite("stability")


def check(cond, label):
    _suite.check(cond, label)


# --- Fake DB / process doubles ----------------------------------------------

class _RecQuery:
    def __init__(self, rec):
        self.rec = rec

    def filter(self, *a, **k):
        self.rec["filter"] = (a, k)
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


class _DeadMain:
    def poll(self):
        return 1  # dead

    def wait(self, timeout=None):
        return None


class _LiveMain:
    def __init__(self):
        self.alive = True

    def poll(self):
        return None if self.alive else 1

    def wait(self, timeout=None):
        return None


class _FakeResp:
    def __init__(self, status_code=200):
        self.status_code = status_code


def _reset_pm():
    pm.running_instances.clear()
    pm.firefox_processes.clear()
    pm.MONITOR_POLL_INTERVAL = 0.01


# --- Monitor: dead process ---------------------------------------------------

def test_monitor_dead_process_removes_entry():
    _reset_pm()
    rec = {}
    pm.SessionLocal = _RecSessionMaker(rec)
    main = _DeadMain()
    pm.running_instances[1] = {"process": main, "monitor_thread": None}
    t = threading.Thread(
        target=pm.monitor_instance_thread,
        args=(1, 1000, 9001, 9001, None, "slug", 9001),
        kwargs={"popen": main}, daemon=True,
    )
    t.start()
    t.join(timeout=5)
    check(not t.is_alive(), "monitor exits after process death (no infinite loop)")
    check(1 not in pm.running_instances, "dead entry removed from running_instances")
    check(rec.get("update") is not None, "teardown ran a DB update")


# --- Monitor: conditional starting->started promotion ------------------------

def test_monitor_promotes_starting_to_started():
    _reset_pm()
    rec = {}
    pm.SessionLocal = _RecSessionMaker(rec)
    orig_get = pm.requests.get
    pm.requests.get = lambda url, timeout=None: _FakeResp(200)
    main = _LiveMain()
    pm.running_instances[1] = {"process": main, "monitor_thread": None}
    try:
        t = threading.Thread(
            target=pm.monitor_instance_thread,
            args=(1, 1000, 9001, 9001, None, "slug", 9001),
            kwargs={"popen": main}, daemon=True,
        )
        t.start()
        deadline = time.time() + 5
        while "update" not in rec and time.time() < deadline:
            time.sleep(0.01)
        check("update" in rec, "starting->started promotion update recorded")
        if "update" in rec:
            check(rec["update"][0][0].get("status") == "started", "promotion sets status=started")
        main.alive = False
        t.join(timeout=5)
        check(not t.is_alive(), "monitor exits after death")
    finally:
        pm.requests.get = orig_get


# --- Double-start guard ------------------------------------------------------

def test_double_start_raises():
    _reset_pm()
    pm.running_instances[1] = {"process": object(), "monitor_thread": None}

    class _Inst:
        id = 1

    try:
        pm.start_instance_process(None, _Inst())
        check(False, "double start should raise")
    except Exception as e:
        check("already running" in str(e), "double start raises 'already running'")


# --- Stop with ProcessLookupError -------------------------------------------

def test_stop_process_lookup_error_cleanup():
    _reset_pm()

    class _Proc:
        pid = 9999

    pm.running_instances[1] = {"process": _Proc(), "monitor_thread": None}

    class _Inst:
        id = 1
        name = "test_inst"
        status = "starting"
        pid = 9999

    orig_killpg = pm.os.killpg
    orig_cleanup = pm._cleanup_instance_files
    pm.os.killpg = lambda *a, **k: (_ for _ in ()).throw(ProcessLookupError())
    cleaned = []
    pm._cleanup_instance_files = lambda slug: cleaned.append(slug)
    try:
        try:
            pm.stop_instance_process(None, _Inst())
            check(True, "stop does not raise on ProcessLookupError")
        except Exception as e:
            check(False, f"stop raised: {e}")
    finally:
        pm.os.killpg = orig_killpg
        pm._cleanup_instance_files = orig_cleanup
    check(1 not in pm.running_instances, "entry removed in finally")
    check(len(cleaned) == 1 and cleaned[0] == "test-inst", "file cleanup ran in finally")


# --- Concurrent port allocation ---------------------------------------------

def test_concurrent_port_allocation_distinct():
    results = []
    lock = threading.Lock()

    def worker():
        p = pm._find_free_port()
        with lock:
            results.append(p)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    check(len(results) == 8, "8 ports allocated")
    check(len(set(results)) == 8, "all ports distinct")


# --- Migration: DatabaseVersionError (no silent fallback to 1) --------------

def test_get_db_version_raises_on_error():
    class _Inspector:
        def has_table(self, name):
            raise sqlite3.OperationalError("database is locked")

    class _DB:
        bind = object()

    orig_inspect = migration.inspect
    migration.inspect = lambda bind: _Inspector()
    try:
        try:
            migration._get_db_version(_DB())
            check(False, "should raise, not silently fall back to 1")
        except Exception:
            check(True, "raises instead of silent fallback to 1")
    finally:
        migration.inspect = orig_inspect


def test_get_db_version_legit_v1():
    class _Inspector:
        def has_table(self, name):
            return name == "instances"

        def get_columns(self, name):
            return [{"name": "id"}, {"name": "name"}]

    class _DB:
        bind = object()

    orig_inspect = migration.inspect
    migration.inspect = lambda bind: _Inspector()
    try:
        check(migration._get_db_version(_DB()) == 1, "legit v1 returns 1")
    finally:
        migration.inspect = orig_inspect


def test_get_db_version_corrupted_raises():
    class _Inspector:
        def has_table(self, name):
            return name == "instances"

        def get_columns(self, name):
            return [{"name": "id"}, {"name": "hostname"}]

    class _DB:
        bind = object()

    orig_inspect = migration.inspect
    migration.inspect = lambda bind: _Inspector()
    try:
        try:
            migration._get_db_version(_DB())
            check(False, "corrupted DB should raise DatabaseVersionError")
        except migration.DatabaseVersionError:
            check(True, "corrupted DB raises DatabaseVersionError")
    finally:
        migration.inspect = orig_inspect


# --- Migration: backup before ALTER ------------------------------------------

def test_backup_before_alter():
    calls = []
    orig_backup = migration._backup_database_before_step
    migration._backup_database_before_step = lambda db_path, backup_path, log_prefix="0.": calls.append(backup_path)

    class _FakeEngine:
        def connect(self):
            raise RuntimeError("boom")

    orig_create_engine = migration.create_engine
    migration.create_engine = lambda *a, **k: _FakeEngine()
    try:
        try:
            migration._perform_v4_to_v5_migration()
        except SystemExit:
            pass
        check(len(calls) == 1, "backup called before ALTER")
    finally:
        migration._backup_database_before_step = orig_backup
        migration.create_engine = orig_create_engine


# --- Metadata parser ---------------------------------------------------------

def test_metadata_parser_dots_preserved():
    check(metadata.normalize_venv_dir_name("./my.env") == "my.env", "dots preserved in venv dir name")
    check(metadata.normalize_venv_dir_name("env") == "env", "plain venv dir name")
    check(metadata.normalize_venv_dir_name('"./env"') == "env", "dequoted venv dir name")


def test_metadata_parser_dequote():
    check(metadata.dequote('"./env"') == "./env", "double quotes removed")
    check(metadata.dequote("'x'") == "x", "single quotes removed")
    check(metadata.dequote("plain") == "plain", "unquoted value unchanged")
    entries = list(metadata.iter_metadata_entries([
        "### AIKORE-METADATA-START ###",
        '# aikore.venv_path = "./env"',
        "# aikore.category = ComfyUI",
        "### AIKORE-METADATA-END ###",
    ]))
    d = dict(entries)
    check(d.get("venv_path") == "./env", "iter_metadata_entries dequotes venv_path")
    check(d.get("category") == "ComfyUI", "iter_metadata_entries parses category")


# --- Delete during installing -> 409 -----------------------------------------

def test_delete_during_installing_409():
    class _FakeInst:
        id = 1
        name = "x"
        status = "installing"

    orig_get = instances.crud.get_instance
    instances.crud.get_instance = lambda db, instance_id=None, **k: _FakeInst()
    try:
        try:
            instances.delete_instance(1, instances.DeleteOptions(), instances.BackgroundTasks())
            check(False, "delete during installing should raise 409")
        except instances.HTTPException as e:
            check(e.status_code == 409, "delete during installing returns 409")
    finally:
        instances.crud.get_instance = orig_get


# --- Invalid port range -> 400 -----------------------------------------------

def test_port_range_invalid_400():
    os.environ["AIKORE_INSTANCE_PORT_RANGE"] = "not-a-range"
    try:
        try:
            instances._parse_instance_port_range(status_code=400)
            check(False, "invalid port range should raise 400")
        except instances.HTTPException as e:
            check(e.status_code == 400, "invalid port range returns 400")
    finally:
        os.environ.pop("AIKORE_INSTANCE_PORT_RANGE", None)


if __name__ == "__main__":
    sys.exit(run_suite(_suite, globals()))
