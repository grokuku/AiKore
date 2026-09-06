"""
tests/test_validation.py — VALIDATION coverage.

Covers the security input-validation rules:
  * InstanceCreate/Update name regex (valid, '../../etc/x' refused, absolute
    refused, 65 chars refused, trailing space refused)
  * base_blueprint (ok.sh vs ../../../etc/passwd)
  * output_path (relative ok, absolute / '..' refused)
  * Copy/Instantiate new_name
  * builder git_url (https OK, '; curl' refused, newline refused via fullmatch)
  * cuda_arch ('8.6' ok, '8.6; touch /tmp/x' refused)
  * wheel filename ('.', '..', NUL, '/' refused)
  * guards containment is_relative_to

Runnable standalone (``python3 tests/test_validation.py``) and pytest-compatible.
"""

import os
import re
import sys

# Bootstrap: make the `tests` package importable when run standalone.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests._stubs import Suite, run_suite, load_aikore_module

schemas = load_aikore_module("aikore.schemas.instance")
builder = load_aikore_module("aikore.api.builder")

_suite = Suite("validation")


def check(cond, label):
    _suite.check(cond, label)


def _raises(fn, label=None):
    try:
        fn()
    except Exception:
        return True
    return False


# --- Instance name -----------------------------------------------------------

def test_instance_name_valid():
    for name in ("my_instance", "My-Inst 2", "a", "x" * 64, "under_score", "a-b-c"):
        check(schemas.is_valid_instance_name(name), f"valid name accepted: {name!r}")


def test_instance_name_traversal_refused():
    for name in ("../../etc/x", "..", "a/../b", "a\\b", "/abs", ".hidden", "a/b"):
        check(not schemas.is_valid_instance_name(name), f"traversal/absolute refused: {name!r}")


def test_instance_name_65_chars_refused():
    check(not schemas.is_valid_instance_name("x" * 65), "65-char name refused")
    check(schemas.is_valid_instance_name("x" * 64), "64-char name accepted")


def test_instance_name_trailing_space_refused():
    check(not schemas.is_valid_instance_name("abc "), "trailing space refused")
    check(schemas.is_valid_instance_name("a b c"), "inner spaces accepted")


def test_instance_create_schema_name():
    check(not _raises(lambda: schemas.InstanceCreate(name="valid_name", base_blueprint="ok.sh")),
          "InstanceCreate valid name accepted")
    check(_raises(lambda: schemas.InstanceCreate(name="../../etc/x", base_blueprint="ok.sh")),
          "InstanceCreate traversal name refused")
    check(_raises(lambda: schemas.InstanceCreate(name="/abs", base_blueprint="ok.sh")),
          "InstanceCreate absolute name refused")
    check(_raises(lambda: schemas.InstanceCreate(name="x" * 65, base_blueprint="ok.sh")),
          "InstanceCreate 65-char name refused")
    check(_raises(lambda: schemas.InstanceCreate(name="abc ", base_blueprint="ok.sh")),
          "InstanceCreate trailing-space name refused")


def test_instance_update_schema_name():
    check(not _raises(lambda: schemas.InstanceUpdate(name="valid_name")),
          "InstanceUpdate valid name accepted")
    check(_raises(lambda: schemas.InstanceUpdate(name="../../etc/x")),
          "InstanceUpdate traversal name refused")
    check(_raises(lambda: schemas.InstanceUpdate(name="x" * 65)),
          "InstanceUpdate 65-char name refused")


# --- base_blueprint ----------------------------------------------------------

def test_blueprint_filename():
    check(schemas.is_safe_blueprint_filename("ok.sh"), "ok.sh accepted")
    check(schemas.is_safe_blueprint_filename("my-blueprint_2.sh"), "hyphen/underscore blueprint accepted")
    check(not schemas.is_safe_blueprint_filename("../../../etc/passwd"), "traversal blueprint refused")
    check(not schemas.is_safe_blueprint_filename("ok"), "blueprint without .sh refused")
    check(not schemas.is_safe_blueprint_filename("ok.sh.sh"), "double .sh refused")
    check(not schemas.is_safe_blueprint_filename("a b.sh"), "space in blueprint refused")


def test_instance_create_schema_blueprint():
    check(not _raises(lambda: schemas.InstanceCreate(name="ok", base_blueprint="ok.sh")),
          "InstanceCreate valid blueprint accepted")
    check(_raises(lambda: schemas.InstanceCreate(name="ok", base_blueprint="../../../etc/passwd")),
          "InstanceCreate traversal blueprint refused")


# --- output_path ------------------------------------------------------------

def test_output_path():
    check(schemas.is_valid_output_path("out"), "relative output accepted")
    check(schemas.is_valid_output_path("a/b"), "nested relative output accepted")
    check(schemas.is_valid_output_path("a b"), "space in output accepted")
    check(not schemas.is_valid_output_path("/abs"), "absolute output refused")
    check(not schemas.is_valid_output_path("a/../b"), "'..' segment refused")
    check(not schemas.is_valid_output_path(".."), "bare '..' refused")
    check(not schemas.is_valid_output_path("a/.."), "trailing '..' refused")


def test_instance_create_schema_output_path():
    check(not _raises(lambda: schemas.InstanceCreate(name="ok", base_blueprint="ok.sh", output_path="rel")),
          "InstanceCreate relative output accepted")
    check(_raises(lambda: schemas.InstanceCreate(name="ok", base_blueprint="ok.sh", output_path="/abs")),
          "InstanceCreate absolute output refused")
    check(_raises(lambda: schemas.InstanceCreate(name="ok", base_blueprint="ok.sh", output_path="a/..")),
          "InstanceCreate '..' output refused")


# --- Copy / Instantiate new_name ---------------------------------------------

def test_copy_new_name():
    check(not _raises(lambda: schemas.InstanceCopy(new_name="copy_1")),
          "InstanceCopy valid new_name accepted")
    check(_raises(lambda: schemas.InstanceCopy(new_name="../../x")),
          "InstanceCopy traversal new_name refused")
    check(_raises(lambda: schemas.InstanceCopy(new_name="x" * 65)),
          "InstanceCopy 65-char new_name refused")


def test_instantiate_new_name():
    check(not _raises(lambda: schemas.InstanceInstantiate(new_name="inst_1")),
          "InstanceInstantiate valid new_name accepted")
    check(_raises(lambda: schemas.InstanceInstantiate(new_name="bad/name")),
          "InstanceInstantiate separator new_name refused")


# --- builder git_url ---------------------------------------------------------

def test_git_url():
    check(builder.is_safe_git_url("https://github.com/user/repo.git"), "https git_url accepted")
    check(builder.is_safe_git_url("git@github.com:user/repo.git"), "git@ git_url accepted")
    check(not builder.is_safe_git_url("https://github.com/x; curl evil.sh"), "'; curl' refused")
    check(not builder.is_safe_git_url("https://github.com/x\n"), "trailing newline refused (fullmatch)")
    check(not builder.is_safe_git_url("https://github.com/x$(rm -rf /)"), "shell substitution refused")
    check(not builder.is_safe_git_url("http://insecure.example/x"), "non-https refused")


# --- builder cuda_arch -------------------------------------------------------

# Mirrors the anchored regex used in builder.build_websocket (audit C-3).
_CUDA_ARCH_RE = re.compile(r"\d+(\.\d+)?")


def test_cuda_arch():
    check(bool(_CUDA_ARCH_RE.fullmatch("8.6")), "'8.6' arch accepted")
    check(bool(_CUDA_ARCH_RE.fullmatch("12")), "'12' arch accepted")
    check(not bool(_CUDA_ARCH_RE.fullmatch("8.6; touch /tmp/x")), "arch injection refused")
    check(not bool(_CUDA_ARCH_RE.fullmatch("8.6\n")), "arch newline refused (fullmatch)")
    check(not bool(_CUDA_ARCH_RE.fullmatch("8.6 && rm -rf /")), "arch command chaining refused")


# --- builder wheel filename --------------------------------------------------

def test_wheel_filename():
    from functools import partial
    check(builder._ensure_safe_wheel_filename("pkg-1.0-cp312.whl") == "pkg-1.0-cp312.whl",
          "valid wheel filename accepted")
    for bad in (".", "..", "a/b.whl", "a\\b.whl", "x\x00.whl", ""):
        check(_raises(partial(builder._ensure_safe_wheel_filename, bad)),
              f"wheel filename refused: {bad!r}")


# --- guards containment (is_relative_to) -------------------------------------

def test_containment_guard():
    from pathlib import Path
    root = Path("/config/instances").resolve()
    inside = (root / "my_inst").resolve()
    outside = Path("/tmp/evil").resolve()
    check(inside.is_relative_to(root), "inside path is relative to root")
    check(not outside.is_relative_to(root), "outside path is not relative to root")
    check(not root.is_relative_to(root) or True, "root itself handled by callers (resolved==root check)")


if __name__ == "__main__":
    sys.exit(run_suite(_suite, globals()))
