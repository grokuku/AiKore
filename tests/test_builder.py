"""
tests/test_builder.py — BUILDER version-detection & GPU auto-detection coverage.

Locks the fixes from the 2026 library-version audit:

  * F1/F4 — NUMERIC sorting of CUDA folders ('cu92' must never outrank
    'cu134') and of torch/python version strings ('2.9.1' must not outrank
    '2.14.1'); the UI advertises index 0 as "(Latest)", so the order matters.
  * F2 — offline fallbacks contain only folders that actually exist
    (no cu131; torch up to 2.14.1).
  * F3 — python filter keeps stable CPython >= 3.10 and drops pre-releases
    (3.9.x/3.15.0a1 rejected, 3.14.8 accepted).
  * F6 — an offline fallback gets the SHORT TTL, not the full 24h/6h cache.
  * F7 — /versions/torch/{cu} validates 'cuNNN' before fetching/caching, and
    the per-CUDA cache is bounded.
  * F8 — GPU detection enumerates EVERY GPU, can target a specific index and
    reports failure explicitly instead of silently defaulting to 8.9.

There is NO GPU in this environment, so the NVML paths are exercised through a
fake pynvml module (never a real driver).

Runnable standalone (``python3 tests/test_builder.py``) and
pytest-compatible (``test_*`` functions using asserts).
"""

import asyncio
import os
import sys
import types

# Bootstrap: make the `tests` package importable when run standalone.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests._stubs import Suite, run_suite, load_aikore_module

builder = load_aikore_module("aikore.api.builder")

_suite = Suite("builder")


def check(cond, label):
    _suite.check(cond, label)


# --- Patching helpers (save/restore) -----------------------------------------

class _Patch:
    def __init__(self):
        self._saved = []

    def set(self, obj, name, value):
        self._saved.append((obj, name, getattr(obj, name, None)))
        setattr(obj, name, value)

    def restore(self):
        for obj, name, old in reversed(self._saved):
            setattr(obj, name, old)


class _FakeResponse:
    """Minimal urlopen() context manager returning a fixed body."""

    def __init__(self, body):
        self._body = body.encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _patch_urlopen(patch, html):
    patch.set(builder.urllib.request, "urlopen",
              lambda req, timeout=None: _FakeResponse(html))


def _make_fake_nvml(gpus, init_error=None, count_error=None):
    """A pynvml-shaped module driven by a list of {cap, name} dicts."""
    mod = types.ModuleType("pynvml")

    def nvmlInit():
        if init_error is not None:
            raise init_error

    def nvmlShutdown():
        pass

    def count():
        if count_error is not None:
            raise count_error
        return len(gpus)

    def handle(i):
        return i

    def capability(h):
        return gpus[h]["cap"]

    def name(h):
        return gpus[h]["name"]

    mod.nvmlInit = nvmlInit
    mod.nvmlShutdown = nvmlShutdown
    mod.nvmlDeviceGetCount = count
    mod.nvmlDeviceGetHandleByIndex = handle
    mod.nvmlDeviceGetCudaComputeCapability = capability
    mod.nvmlDeviceGetName = name
    return mod


# --- F1: CUDA numeric sorting -------------------------------------------------

def test_cuda_sort_key_is_numeric():
    check(builder._cuda_sort_key("cu134") == 134, "cu134 -> 134")
    check(builder._cuda_sort_key("cu92") == 92, "cu92 -> 92")
    check(builder._cuda_sort_key("cu92") < builder._cuda_sort_key("cu130"),
          "cu92 ranks BELOW cu130 (not lexicographic)")
    order = sorted(["cu92", "cu130", "cu134", "cu118"], key=builder._cuda_sort_key, reverse=True)
    check(order == ["cu134", "cu130", "cu118", "cu92"], f"numeric desc order: {order}")


def test_cuda_version_string_mapping():
    check(builder._cuda_to_version("cu92") == "9.2", "cu92 -> 9.2")
    check(builder._cuda_to_version("cu118") == "11.8", "cu118 -> 11.8")
    check(builder._cuda_to_version("cu130") == "13.0", "cu130 -> 13.0")
    check(builder._cuda_to_version("cu134") == "13.4", "cu134 -> 13.4")


def test_fetch_cuda_versions_orders_numerically():
    """The scraped listing must come out newest-first, cu92 last."""
    patch = _Patch()
    try:
        html = ('<a href="cu92">x</a><a href="cu130">y</a>'
                '<a href="cu134">z</a><a href="cu118">w</a>')
        _patch_urlopen(patch, html)
        result = builder._fetch_cuda_versions([{"cu": "cu118", "version": "11.8"}])
        cus = [r["cu"] for r in result]
        check(cus == ["cu134", "cu130", "cu118", "cu92"], f"scraped order: {cus}")
        check(result[0]["version"] == "13.4" and result[-1]["version"] == "9.2",
              "version strings follow the numeric order")
        check("cu92" not in cus[:2], "cu92 is not at the top")
    finally:
        patch.restore()


# --- F2: honest offline fallbacks --------------------------------------------

def test_cuda_fallback_has_no_bogus_folder():
    cus = [v["cu"] for v in builder._FALLBACK_CUDA_VERSIONS]
    check("cu131" not in cus, "cu131 (non-existent folder) is purged")
    check("cu134" in cus and "cu132" in cus, "real folders cu134/cu132 present")
    numeric = sorted(cus, key=builder._cuda_sort_key, reverse=True)
    check(cus == numeric, f"fallback already numerically sorted: {cus}")


def test_python_fallback_drops_prerelease():
    check("3.15" not in builder._FALLBACK_PYTHON_VERSIONS,
          "3.15 (pre-release) not advertised offline")
    check("3.14" in builder._FALLBACK_PYTHON_VERSIONS, "3.14 stable present")


def test_torch_fallback_reaches_2_14_1():
    fb = builder._FALLBACK_TORCH_VERSIONS
    check("2.14.1" in fb, "torch fallback includes 2.14.1")
    check(fb[0] == "2.14.1", "torch fallback is newest-first (2.14.1 at index 0)")
    check("2.10.0" in fb, "2.10.0 kept for versions.env coherence")


# --- F4: torch numeric sorting -----------------------------------------------

def test_version_key_numeric_not_lexicographic():
    check(builder._parse_version_key("2.14.1") > builder._parse_version_key("2.9.1"),
          "2.14.1 ranks above 2.9.1")
    order = sorted(["2.9.1", "2.11.0", "2.14.1"], key=builder._parse_version_key, reverse=True)
    check(order == ["2.14.1", "2.11.0", "2.9.1"], f"torch desc order: {order}")


def test_fetch_torch_versions_orders_and_flags_fallback():
    patch = _Patch()
    try:
        html = "torch-2.14.1%2Bcu130-cp312.whl torch-2.9.1%2Bcu130-cp312.whl torch-2.11.0%2Bcu130-cp312.whl"
        _patch_urlopen(patch, html)
        versions, is_fallback = builder._fetch_torch_versions("cu130", ["2.9.1"])
        check(versions == ["2.14.1", "2.11.0", "2.9.1"], f"live order: {versions}")
        check(is_fallback is False, "live result is not flagged as fallback")

        # Empty listing -> fallback list, numerically sorted, flagged.
        _patch_urlopen(patch, "")
        versions, is_fallback = builder._fetch_torch_versions("cu130", ["2.9.1", "2.11.0", "2.14.1"])
        check(versions == ["2.14.1", "2.11.0", "2.9.1"], f"fallback order: {versions}")
        check(is_fallback is True, "empty listing is flagged as fallback")
    finally:
        patch.restore()


# --- F3: python >= 3.10, stable only -----------------------------------------

def test_clean_python_versions_filters_and_sorts():
    raw = ["3.9.23", "3.15.0a1", "3.14.8", "3.12.7", "2.7.18", "3.13.0rc1", "3.10.14"]
    result = builder._clean_python_versions(raw)
    check("3.9" not in result, "3.9.23 rejected (>= 3.10 required)")
    check("3.15" not in result, "3.15.0a1 rejected (pre-release)")
    check("3.13" not in result, "3.13.0rc1 rejected (pre-release)")
    check("2.7" not in result, "python 2 rejected")
    check("3.14" in result, "3.14.8 accepted as stable")
    check(result == ["3.14", "3.12", "3.10"], f"cleaned/sorted: {result}")


def test_clean_python_versions_parses_minor_as_integer():
    # '3.20' must be read as minor 20 (>= 10), never as '3.2'.
    result = builder._clean_python_versions(["3.20.1"])
    check(result == ["3.20"], f"3.20 kept as 3.20: {result}")


# --- F6: short TTL for offline fallbacks -------------------------------------

def test_fallback_ttl_is_shorter_than_full_ttl():
    check(builder._FALLBACK_CACHE_TTL < builder._PYTHON_CACHE_TTL, "python fallback TTL < 24h")
    check(builder._FALLBACK_CACHE_TTL < builder._CUDA_CACHE_TTL, "cuda fallback TTL < 6h")
    check(builder._FALLBACK_CACHE_TTL < builder._TORCH_CACHE_TTL, "torch fallback TTL < 24h")

    builder._cache_python_fallback()
    check(builder._cached_python_versions_is_fallback is True, "python fallback flagged")
    check(builder._python_cache_ttl() == builder._FALLBACK_CACHE_TTL,
          "flagged fallback uses the short TTL")


# --- F7: cuda_ver validation + bounded cache ---------------------------------

def test_torch_endpoint_rejects_invalid_cuda_ver():
    before = dict(builder._cached_torch_versions)
    for bad in ["../evil", "cu", "12.8", "cu12x", "cu;rm -rf", ""]:
        raised = False
        try:
            asyncio.run(builder.get_torch_versions_for_cuda(bad))
        except builder.HTTPException:
            raised = True
        check(raised, f"invalid cuda_ver {bad!r} rejected with HTTPException")
    check(builder._cached_torch_versions == before,
          "invalid cuda_ver does not create a cache entry")


def test_torch_endpoint_accepts_and_sorts_valid_cuda_ver():
    patch = _Patch()
    saved = dict(builder._cached_torch_versions)
    try:
        builder._cached_torch_versions.clear()
        html = "torch-2.14.1%2Bcu130.whl torch-2.9.1%2Bcu130.whl"
        _patch_urlopen(patch, html)
        result = asyncio.run(builder.get_torch_versions_for_cuda("cu130"))
        check(result == ["2.14.1", "2.9.1"], f"endpoint order: {result}")
        check("cu130" in builder._cached_torch_versions, "valid cuda_ver cached")
    finally:
        patch.restore()
        builder._cached_torch_versions.clear()
        builder._cached_torch_versions.update(saved)


def test_torch_cache_is_bounded():
    patch = _Patch()
    saved = dict(builder._cached_torch_versions)
    try:
        builder._cached_torch_versions.clear()
        for i in range(builder._MAX_TORCH_CACHE_ENTRIES):
            builder._cached_torch_versions[f"cu{100 + i}"] = (float(i), ["2.14.1"], False)
        html = "torch-2.14.1%2Bcu999.whl"
        _patch_urlopen(patch, html)
        asyncio.run(builder.get_torch_versions_for_cuda("cu999"))
        check(len(builder._cached_torch_versions) <= builder._MAX_TORCH_CACHE_ENTRIES,
              f"cache size bounded (<= {builder._MAX_TORCH_CACHE_ENTRIES})")
        check("cu100" not in builder._cached_torch_versions,
              "oldest entry evicted first")
    finally:
        patch.restore()
        builder._cached_torch_versions.clear()
        builder._cached_torch_versions.update(saved)


# --- F8: GPU auto-detection ---------------------------------------------------

_GPUS = [
    {"cap": (8, 6), "name": "NVIDIA GeForce RTX 3090"},
    {"cap": (8, 9), "name": "NVIDIA GeForce RTX 4090"},
]


def test_detect_gpus_enumerates_all():
    patch = _Patch()
    try:
        patch.set(builder, "pynvml", _make_fake_nvml(_GPUS))
        gpus, error = builder._detect_gpus()
        check(error is None, "detection succeeds")
        check([g["arch"] for g in gpus] == ["8.6", "8.9"], f"all archs: {gpus}")
        check(gpus[1]["name"] == "NVIDIA GeForce RTX 4090", "GPU 1 name exposed")
    finally:
        patch.restore()


def test_mixed_machine_defaults_to_gpu0_but_exposes_gpu1():
    patch = _Patch()
    try:
        patch.set(builder, "pynvml", _make_fake_nvml(_GPUS))
        info = builder.get_builder_info()
        check(info["detected_arch"] == "8.6", "default detection = GPU 0 (8.6)")
        check(info["gpu_name"].endswith("3090"), "GPU 0 name reported")
        check(info["detection"]["ok"] is True, "detection flagged ok")
        check(len(info["gpus"]) == 2, "both GPUs exposed for the UI")

        info1 = builder.get_builder_info(gpu_index=1)
        check(info1["detected_arch"] == "8.9", "targeting GPU 1 -> 8.9 (the 4090)")
        check(info1["gpu_name"].endswith("4090"), "GPU 1 name reported")
    finally:
        patch.restore()


def test_explicit_missing_gpu_index_is_visible_error():
    patch = _Patch()
    try:
        patch.set(builder, "pynvml", _make_fake_nvml(_GPUS))
        info = builder.get_builder_info(gpu_index=7)
        check(info["detection"]["ok"] is False, "missing explicit index -> ok False")
        check("not found" in (info["detection"]["error"] or ""),
              f"explicit error message: {info['detection']['error']}")
        check(info["detected_arch"] == "8.9", "arch falls back to the 8.9 default")
    finally:
        patch.restore()


def test_nvml_unavailable_is_explicit_not_silent():
    patch = _Patch()
    try:
        patch.set(builder, "pynvml", None)
        gpus, error = builder._detect_gpus()
        check(gpus == [], "no GPU when pynvml missing")
        check(bool(error), f"error is surfaced: {error}")

        info = builder.get_builder_info()
        check(info["detection"]["ok"] is False, "detection flagged NOT ok")
        check(bool(info["detection"]["error"]), "error string present")
        check(info["detected_arch"] == "8.9", "still returns the 8.9 default")
        check(info["gpus"] == [], "empty gpus list")
    finally:
        patch.restore()


def test_nvml_init_failure_is_explicit():
    patch = _Patch()
    try:
        patch.set(builder, "pynvml", _make_fake_nvml([], init_error=RuntimeError("no driver")))
        gpus, error = builder._detect_gpus()
        check(gpus == [] and "NVML init failed" in (error or ""),
              f"init failure surfaced: {error}")
    finally:
        patch.restore()


def test_nvml_count_failure_is_explicit():
    patch = _Patch()
    try:
        patch.set(builder, "pynvml",
                  _make_fake_nvml(_GPUS, count_error=RuntimeError("device count boom")))
        gpus, error = builder._detect_gpus()
        check(gpus == [] and "enumeration failed" in (error or ""),
              f"count failure surfaced: {error}")
    finally:
        patch.restore()


if __name__ == "__main__":
    sys.exit(run_suite(_suite, globals()))
