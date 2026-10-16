"""
tests/test_process_manager.py — Process-manager hardening coverage.

Covers the two linked production bugs fixed in this session:

  * BUG 1 — the stop escalation never fired because it waited on the HEAD
    process, which dies instantly, instead of on the whole process GROUP.
  * BUG 2 — the normal-mode port reallocation accepted an out-of-range
    ephemeral port and persisted it.

Runnable standalone (``python3 tests/test_process_manager.py``) and
pytest-compatible.
"""

import os
import shutil
import signal
import subprocess
import sys
import tempfile

# Bootstrap: make the `tests` package importable when run standalone.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests._stubs import Suite, run_suite, load_aikore_module

pm = load_aikore_module("aikore.core.process_manager")

_suite = Suite("process_manager")


def check(cond, label):
    _suite.check(cond, label)


# --- Fake doubles ------------------------------------------------------------

class _FakeDB:
    """Minimal stand-in for the query()/commit()/refresh() surface used by
    _ensure_runtime_ports_free()."""

    def __init__(self, rows=None):
        self.committed = False
        self.refreshed = None

    def query(self, *a, **k):
        return self

    def filter(self, *a, **k):
        return self

    def all(self):
        return []

    def commit(self):
        self.committed = True

    def refresh(self, obj):
        self.refreshed = obj


class _FakeInstance:
    def __init__(self, **kw):
        self.id = 1
        self.name = "strata"
        self.base_blueprint = "StrataLLM.sh"
        self.persistent_mode = False
        self.port = None
        self.persistent_port = None
        self.persistent_display = None
        self.output_path = None
        self.pgid = None
        self.pid = None
        self.__dict__.update(kw)


class _DeadHead:
    """A Popen-like head that has ALREADY exited (poll() != None)."""

    def poll(self):
        return 0

    def wait(self, timeout=None):
        return 0


def _make_killpg(survives_after_term):
    """Build a fake os.killpg backed by an in-memory group.

    Returns (state, fake). ``state["alive"]`` models the survival of the group;
    ``state["calls"]`` records every signal sent.
    """
    state = {"alive": True, "calls": []}

    def fake_killpg(pgid, sig):
        state["calls"].append(sig)
        if sig == 0:
            if state["alive"]:
                return None
            raise ProcessLookupError(3, "No such process")
        if sig == signal.SIGTERM:
            # The head always dies, but a descendant may keep the group alive.
            if not survives_after_term:
                state["alive"] = False
            return None
        if sig == signal.SIGKILL:
            state["alive"] = False
            return None
        return None

    return state, fake_killpg


def _patch_killpg(fake):
    original = pm.os.killpg
    pm.os.killpg = fake
    return original


# --- C1: escalation driven by the GROUP, not the head ------------------------

def test_sigkill_sent_when_group_survives_sigterm():
    state, fake = _make_killpg(survives_after_term=True)
    original = _patch_killpg(fake)
    try:
        dead = pm._terminate_process_group(
            4242, "test", term_grace=0.1, kill_grace=0.2, poll_interval=0.01
        )
    finally:
        pm.os.killpg = original

    check(dead is True, "group reported dead after SIGKILL")
    check(signal.SIGTERM in state["calls"], "SIGTERM was sent to the group")
    check(signal.SIGKILL in state["calls"], "SIGKILL WAS sent because the group survived SIGTERM")
    check(
        state["calls"].index(signal.SIGTERM) < state["calls"].index(signal.SIGKILL),
        "SIGTERM precedes SIGKILL",
    )
    check(state["calls"].count(signal.SIGKILL) == 1, "SIGKILL sent exactly once")


def test_no_sigkill_when_group_dies_immediately():
    state, fake = _make_killpg(survives_after_term=False)
    original = _patch_killpg(fake)
    try:
        dead = pm._terminate_process_group(
            4343, "test", term_grace=0.2, kill_grace=0.2, poll_interval=0.01
        )
    finally:
        pm.os.killpg = original

    check(dead is True, "group reported dead after graceful exit")
    check(signal.SIGTERM in state["calls"], "SIGTERM was sent")
    check(signal.SIGKILL not in state["calls"], "no useless SIGKILL when the group died on SIGTERM")


def test_escalation_independent_of_dead_head():
    """The whole point of BUG 1: even when the head is already dead, a
    surviving group still triggers SIGKILL."""
    state, fake = _make_killpg(survives_after_term=True)
    original = _patch_killpg(fake)
    try:
        dead = pm._terminate_process_group(
            4545, "test", process=_DeadHead(), term_grace=0.1, kill_grace=0.2, poll_interval=0.01
        )
    finally:
        pm.os.killpg = original

    check(dead is True, "surviving group reported dead after SIGKILL")
    check(signal.SIGKILL in state["calls"], "SIGKILL sent even though the head was already dead")


def test_missing_group_does_not_crash():
    def fake_killpg(pgid, sig):
        raise ProcessLookupError(3, "No such process")

    original = _patch_killpg(fake_killpg)
    try:
        dead = pm._terminate_process_group(9999, "gone", term_grace=0.05, kill_grace=0.05, poll_interval=0.01)
    finally:
        pm.os.killpg = original

    check(dead is True, "already-gone group reported dead without raising")


def test_group_still_alive_after_sigkill_reports_false():
    def fake_killpg(pgid, sig):
        return None  # group never dies

    original = _patch_killpg(fake_killpg)
    try:
        dead = pm._terminate_process_group(7777, "stuck", term_grace=0.05, kill_grace=0.05, poll_interval=0.01)
    finally:
        pm.os.killpg = original

    check(dead is False, "un-killable group is reported as still alive (no false 'stopped')")


# --- C5: bounded port allocation --------------------------------------------

def test_find_free_port_in_range_bounded():
    original = pm._can_bind_port
    pm._can_bind_port = lambda p: p == 9005
    try:
        check(pm._find_free_port_in_range(9001, 9020) == 9005, "returns the free in-range port")
        check(pm._find_free_port_in_range(9001, 9003) is None, "None when no in-range port is free")
        check(pm._find_free_port_in_range(9001, 9020, exclude=(9005,)) is None, "excluded port not returned")
        check(pm._find_free_port_in_range(9001, 9020, other_used=(9005,)) is None, "used port not returned")
    finally:
        pm._can_bind_port = original


def test_normal_reallocation_rejects_ephemeral_candidate():
    original_range = os.environ.get("AIKORE_INSTANCE_PORT_RANGE")
    os.environ["AIKORE_INSTANCE_PORT_RANGE"] = "9001-9020"
    original_find = pm._find_free_port
    original_bind = pm._can_bind_port
    # The old buggy path drew its candidate from _find_free_port() (bind to
    # port 0 -> ephemeral, out of range). Only 9007 is actually free in range.
    pm._find_free_port = lambda: 32581
    pm._can_bind_port = lambda p: p == 9007
    inst = _FakeInstance(port=9003)
    db = _FakeDB()
    try:
        events = pm._ensure_runtime_ports_free(db, inst)
    finally:
        pm._find_free_port = original_find
        pm._can_bind_port = original_bind
        if original_range is None:
            del os.environ["AIKORE_INSTANCE_PORT_RANGE"]
        else:
            os.environ["AIKORE_INSTANCE_PORT_RANGE"] = original_range

    check(inst.port == 9007, "normal reallocation picks an in-range port")
    check(inst.port != 32581, "ephemeral candidate (32581) is rejected, never persisted")
    check(db.committed, "reallocation is persisted")
    check(any("9007" in e for e in events), "an event mentions the new port (C7)")


def test_normal_reallocation_fails_loudly_when_range_saturated():
    original_range = os.environ.get("AIKORE_INSTANCE_PORT_RANGE")
    os.environ["AIKORE_INSTANCE_PORT_RANGE"] = "9001-9002"
    original_bind = pm._can_bind_port
    pm._can_bind_port = lambda p: False  # every candidate is busy
    inst = _FakeInstance(port=9001)
    db = _FakeDB()
    raised = None
    try:
        pm._ensure_runtime_ports_free(db, inst)
    except RuntimeError as e:
        raised = str(e)
    finally:
        pm._can_bind_port = original_bind
        if original_range is None:
            del os.environ["AIKORE_INSTANCE_PORT_RANGE"]
        else:
            os.environ["AIKORE_INSTANCE_PORT_RANGE"] = original_range

    check(raised is not None, "saturated range raises RuntimeError (start fails loudly)")
    check("9001-9002" in raised, "error message names the published range")
    check("ephemeral" in raised, "error message refuses the ephemeral fallback")
    check(inst.port == 9001, "no out-of-range port was persisted on failure")


# --- C6: out-of-range drift is re-normalized --------------------------------

def test_out_of_range_port_normalized_even_when_free():
    original_range = os.environ.get("AIKORE_INSTANCE_PORT_RANGE")
    os.environ["AIKORE_INSTANCE_PORT_RANGE"] = "9001-9020"
    original_bind = pm._can_bind_port
    pm._can_bind_port = lambda p: True  # the drifted 32581 is free, and so is 9001
    inst = _FakeInstance(port=32581)
    db = _FakeDB()
    try:
        pm._ensure_runtime_ports_free(db, inst)
    finally:
        pm._can_bind_port = original_bind
        if original_range is None:
            del os.environ["AIKORE_INSTANCE_PORT_RANGE"]
        else:
            os.environ["AIKORE_INSTANCE_PORT_RANGE"] = original_range

    check(inst.port == 9001, "out-of-range port normalized to the first in-range free port")
    check(db.committed, "normalization persisted")


# --- C2/C3: anti-PID-recycled guard -----------------------------------------

def test_persisted_group_refused_when_not_matching_instance():
    original_belongs = pm._group_belongs_to_instance
    original_term = pm._terminate_process_group
    calls = []
    pm._group_belongs_to_instance = lambda pgid, inst: False
    pm._terminate_process_group = lambda *a, **k: (calls.append(a), True)[1]
    inst = _FakeInstance(pgid=4242, pid=4242)
    try:
        dead, targeted = pm._safe_terminate_persisted_group(inst)
    finally:
        pm._group_belongs_to_instance = original_belongs
        pm._terminate_process_group = original_term

    check(dead is True and targeted is None, "non-matching group is not killed")
    check(calls == [], "no kill attempt for a group that does not look like ours")


def test_persisted_group_killed_when_matching():
    original_belongs = pm._group_belongs_to_instance
    original_term = pm._terminate_process_group
    calls = []
    pm._group_belongs_to_instance = lambda pgid, inst: True
    pm._terminate_process_group = lambda pgid, label, **k: (calls.append(pgid), True)[1]
    inst = _FakeInstance(pgid=5555, pid=5555)
    try:
        dead, targeted = pm._safe_terminate_persisted_group(inst)
    finally:
        pm._group_belongs_to_instance = original_belongs
        pm._terminate_process_group = original_term

    check(dead is True and targeted == 5555, "matching group is targeted")
    check(calls == [5555], "kill attempted exactly once on the persisted pgid")


def test_group_guard_matches_real_cwd():
    """End-to-end guard check on a REAL process group: a member whose cwd
    references the instance is accepted, an unrelated instance name is not."""
    tmp = tempfile.mkdtemp(prefix="aikore_guard_")
    inst_dir = os.path.join(tmp, "strata-inst")
    os.makedirs(inst_dir, exist_ok=True)
    proc = subprocess.Popen(["sleep", "30"], cwd=inst_dir, preexec_fn=os.setsid)
    original_instances_dir = pm.INSTANCES_DIR
    pm.INSTANCES_DIR = tmp
    try:
        matching = _FakeInstance(name="strata-inst", pgid=proc.pid, pid=proc.pid)
        other = _FakeInstance(name="totally-other", pgid=proc.pid, pid=proc.pid)
        check(pm._group_belongs_to_instance(proc.pid, matching) is True,
              "real group accepted via cwd containing the instance name")
        check(pm._group_belongs_to_instance(proc.pid, other) is False,
              "unrelated instance name is NOT matched (anti-PID-recycled)")
    finally:
        pm.INSTANCES_DIR = original_instances_dir
        try:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=5)
        except Exception:
            pass
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(run_suite(_suite, globals()))
