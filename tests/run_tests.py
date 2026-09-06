"""
tests/run_tests.py — Local runner for the persistent AiKore test suites.

Runs each suite in a fresh interpreter (isolation of stubs / module state),
times every suite with ``time.perf_counter`` plus the total, and prints a
summary table (suite | checks | pass | fail | time). Exits non-zero if any
suite failed.

Usage:
    python3 tests/run_tests.py                 # run all suites
    python3 tests/run_tests.py --suite auth    # run a single suite
"""

import os
import subprocess
import sys
import time

SUITES = ["test_auth", "test_validation", "test_stability", "test_monitor"]

_HERE = os.path.dirname(os.path.abspath(__file__))


def run_one(name):
    path = os.path.join(_HERE, name + ".py")
    t0 = time.perf_counter()
    proc = subprocess.run([sys.executable, path], capture_output=True, text=True)
    dt = time.perf_counter() - t0
    passed = failed = 0
    for line in proc.stdout.splitlines():
        if line.startswith("RESULT "):
            parts = line.split()
            if len(parts) >= 4:
                passed = int(parts[2])
                failed = int(parts[3])
    return proc.returncode, dt, passed, failed, proc.stdout, proc.stderr


def main():
    args = sys.argv[1:]
    suites = SUITES
    if args and args[0] == "--suite":
        if len(args) < 2:
            print("usage: run_tests.py [--suite <name>]")
            return 2
        name = args[1]
        if not name.startswith("test_"):
            name = "test_" + name
        suites = [name]

    print("=" * 60)
    print("AiKore persistent test runner")
    print("=" * 60)

    rows = []
    total_passed = total_failed = 0
    total_time = 0.0
    for name in suites:
        rc, dt, passed, failed, out, err = run_one(name)
        total_passed += passed
        total_failed += failed
        total_time += dt
        rows.append((name, passed + failed, passed, failed, dt))
        print(out)
        if err:
            print(err)

    print()
    print(f"{'suite':<18}{'checks':>8}{'pass':>8}{'fail':>8}{'time(s)':>10}")
    print("-" * 52)
    for name, checks, passed, failed, dt in rows:
        print(f"{name:<18}{checks:>8}{passed:>8}{failed:>8}{dt:>10.3f}")
    print("-" * 52)
    print(f"{'TOTAL':<18}{total_passed + total_failed:>8}{total_passed:>8}{total_failed:>8}{total_time:>10.3f}")
    print()

    if total_failed:
        print(f"RESULT: {total_failed} FAILURE(S)")
        return 1
    print("ALL SUITES PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
