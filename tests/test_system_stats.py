"""
tests/test_system_stats.py — SYSTEM STATS coverage for GET /api/system/stats.

Covers the monitoring enrichment (2026-10):
  * nominal payload: historical contract intact + cpu_temp / cpu_freq_mhz /
    gpus[].temperature_c / fan_percent / power_w / power_limit_w
  * REGRESSION LOCK: a per-metric NVML failure (fan speed NotSupported on
    A100/H100-class GPUs) must null ONLY that metric — never drop the GPU or
    the other metrics/GPUs (the endpoint used to wrap the whole GPU loop in a
    single try/except)
  * CPU sensor absent / raising -> cpu_temp None, endpoint still healthy
  * NVML unavailable (device count raises) -> gpus [] + CPU metrics kept
  * power limit fallback on nvmlDeviceGetPowerManagementDefaultLimit
  * k10temp/Tctl (AMD) and coretemp-without-Package-id-0 selection

Runnable standalone (``python3 tests/test_system_stats.py``) and
pytest-compatible (``test_*`` functions using asserts).
"""

import os
import sys
import types

# Bootstrap: make the `tests` package importable when run standalone.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests._stubs import Suite, run_suite, load_aikore_module

system = load_aikore_module("aikore.api.system")

psutil_mod = sys.modules["psutil"]
pynvml_mod = sys.modules["pynvml"]

_suite = Suite("system_stats")


def check(cond, label):
    _suite.check(cond, label)


# --- Patching helpers (save/restore, shared by every test) --------------------

class _Patch:
    """Collects (obj, name, old_value) so a test can restore everything."""

    def __init__(self):
        self._saved = []

    def set(self, obj, name, value):
        self._saved.append((obj, name, getattr(obj, name, None)))
        setattr(obj, name, value)

    def restore(self):
        for obj, name, old in reversed(self._saved):
            setattr(obj, name, old)


RAM = {"total": 16 * 1024**3, "used": 8 * 1024**3, "percent": 50.0}

# Defaults applied when a GPU dict omits a field.
_GPU_DEFAULTS = {
    "name": "Fake GPU",
    "vram_total": 8 * 1024**3,
    "vram_used": 2 * 1024**3,
    "util": 0,
    "temp": 40,
    "fan": 30,
    "power_mw": 10000,
}


def _value(gpu, key, default=None):
    """Field value, or raise the bundled exception (per-metric failure sim)."""
    if key not in gpu:
        if default is None:
            raise pynvml_mod.NVMLError_NotSupported()
        return default
    value = gpu[key]
    if isinstance(value, BaseException):
        raise value
    return value


def _install_fake_nvml(patch, gpus, count_error=None):
    """Patch the NVML getters imported by aikore.api.system.

    `gpus` is a list of field dicts (see _GPU_DEFAULTS); a field may hold an
    exception instance to simulate NVMLError_NotSupported for that metric.
    `count_error` simulates NVML being unavailable altogether.
    """

    def count():
        if count_error is not None:
            raise count_error
        return len(gpus)

    def memory_info(handle):
        gpu = gpus[handle]
        return types.SimpleNamespace(
            total=_value(gpu, "vram_total", _GPU_DEFAULTS["vram_total"]),
            used=_value(gpu, "vram_used", _GPU_DEFAULTS["vram_used"]),
        )

    def utilization(handle):
        return types.SimpleNamespace(gpu=_value(gpus[handle], "util", _GPU_DEFAULTS["util"]))

    def name(handle):
        return _value(gpus[handle], "name", _GPU_DEFAULTS["name"])

    def temperature(handle, sensor):
        return _value(gpus[handle], "temp", _GPU_DEFAULTS["temp"])

    def fan(handle):
        return _value(gpus[handle], "fan", _GPU_DEFAULTS["fan"])

    def power(handle):
        return _value(gpus[handle], "power_mw", _GPU_DEFAULTS["power_mw"])

    def limit(handle):
        return _value(gpus[handle], "limit_mw")

    def default_limit(handle):
        return _value(gpus[handle], "default_limit_mw")

    patch.set(system, "nvmlDeviceGetCount", count)
    patch.set(system, "nvmlDeviceGetHandleByIndex", lambda i: i)
    patch.set(system, "nvmlDeviceGetMemoryInfo", memory_info)
    patch.set(system, "nvmlDeviceGetUtilizationRates", utilization)
    patch.set(system, "nvmlDeviceGetName", name)
    patch.set(system, "nvmlDeviceGetTemperature", temperature)
    patch.set(system, "nvmlDeviceGetFanSpeed", fan)
    patch.set(system, "nvmlDeviceGetPowerUsage", power)
    patch.set(system, "nvmlDeviceGetPowerManagementLimit", limit)
    patch.set(system, "nvmlDeviceGetPowerManagementDefaultLimit", default_limit)


def _install_fake_psutil(patch, cpu_percent=12.5, temps=None, freq=4200.0,
                         ram=None, temps_error=None):
    patch.set(psutil_mod, "cpu_percent", lambda interval=None: cpu_percent)
    ram = ram or RAM
    patch.set(psutil_mod, "virtual_memory", lambda: types.SimpleNamespace(**ram))
    if temps_error is not None:
        patch.set(psutil_mod, "sensors_temperatures",
                  lambda: (_ for _ in ()).throw(temps_error))
    else:
        patch.set(psutil_mod, "sensors_temperatures", lambda: temps if temps is not None else {})
    patch.set(psutil_mod, "cpu_freq",
              lambda: types.SimpleNamespace(current=freq) if freq is not None else None)


def _stats(gpus=None, count_error=None, **psutil_kwargs):
    """Call the endpoint with fake psutil/NVML, restoring everything after."""
    patch = _Patch()
    try:
        _install_fake_psutil(patch, **psutil_kwargs)
        _install_fake_nvml(patch, gpus if gpus is not None else [{}], count_error=count_error)
        return system.get_system_stats()
    finally:
        patch.restore()


def _temp(label, current, high=None, critical=None):
    return types.SimpleNamespace(label=label, current=current, high=high, critical=critical)


# --- Tests --------------------------------------------------------------------

def test_nominal_payload_contract_and_enrichment():
    """RTX 4070-like values: historical fields identical, new fields present."""
    gpu = {
        "name": "NVIDIA GeForce RTX 4070",
        "vram_total": 12 * 1024**3,
        "vram_used": 7 * 1024**3,
        "util": 62,
        "temp": 47,
        "fan": 30,
        "power_mw": 12770,       # 12.77 W
        "limit_mw": 200000,      # 200 W
    }
    temps = {"coretemp": [
        _temp("Package id 0", 62.0, 92.0, 102.0),
        _temp("Core 0", 58.0, 92.0, 102.0),
    ]}
    stats = _stats(gpus=[gpu], temps=temps)

    # Historical contract — unchanged.
    check(stats["cpu_percent"] == 12.5, "cpu_percent kept")
    check(stats["ram"] == {"total": RAM["total"], "used": RAM["used"], "percent": RAM["percent"]},
          "ram payload kept identical")
    check(len(stats["gpus"]) == 1, "one GPU reported")
    g = stats["gpus"][0]
    check(g["id"] == 0 and g["name"] == "NVIDIA GeForce RTX 4070", "gpu id/name kept")
    check(g["vram"] == {"total": gpu["vram_total"], "used": gpu["vram_used"],
                        "percent": round((gpu["vram_used"] / gpu["vram_total"]) * 100, 2)},
          "vram kept identical (total/used/percent)")
    check(g["utilization_percent"] == 62, "utilization_percent kept")

    # Enrichment.
    check(stats["cpu_temp"] == {"current": 62.0, "high": 92.0, "critical": 102.0},
          "cpu_temp from coretemp Package id 0 with sensor thresholds")
    check(stats["cpu_freq_mhz"] == 4200.0, "cpu_freq_mhz reported")
    check(g["temperature_c"] == 47, "gpu temperature_c")
    check(g["fan_percent"] == 30, "gpu fan_percent")
    check(g["power_w"] == 12.77, "gpu power_w converted mW -> W")
    check(g["power_limit_w"] == 200.0, "gpu power_limit_w converted mW -> W")


def test_fan_not_supported_is_isolated_per_metric():
    """REGRESSION: fan NotSupported on GPU 0 nulls only fan_percent.

    The historical single try/except around the whole GPU loop made ALL GPUs
    disappear; this test pins the per-metric isolation.
    """
    gpu0 = {
        "name": "NVIDIA A100-SXM4-80GB",
        "temp": 51,
        "fan": pynvml_mod.NVMLError_NotSupported(),  # datacenter GPU: no fan
        "power_mw": 120000,
        "limit_mw": 400000,
    }
    gpu1 = {
        "name": "NVIDIA GeForce RTX 4070",
        "temp": 47,
        "fan": 30,
        "power_mw": 12770,
        "limit_mw": 200000,
    }
    stats = _stats(gpus=[gpu0, gpu1])

    check(len(stats["gpus"]) == 2, "both GPUs survive a per-metric failure")
    check(stats["gpus"][0]["fan_percent"] is None, "failed metric is null")
    check(stats["gpus"][0]["temperature_c"] == 51, "GPU 0 temperature still reported")
    check(stats["gpus"][0]["power_w"] == 120.0, "GPU 0 power still reported")
    check(stats["gpus"][0]["utilization_percent"] == 0, "GPU 0 utilization still reported")
    check(stats["gpus"][1]["fan_percent"] == 30, "GPU 1 fan still reported")
    check(stats["gpus"][1]["temperature_c"] == 47, "GPU 1 temperature still reported")
    check(stats["cpu_temp"] is None, "CPU temp independently absent (no sensor stubbed)")
    check(stats["cpu_freq_mhz"] == 4200.0, "CPU freq independently reported")


def test_all_gpu_metrics_nullable_without_losing_gpu():
    """Every enriched metric failing still yields a GPU entry (all nulls)."""
    broken = {
        "name": pynvml_mod.NVMLError_NotSupported(),
        "vram_total": pynvml_mod.NVMLError_NotSupported(),
        "util": pynvml_mod.NVMLError_NotSupported(),
        "temp": pynvml_mod.NVMLError_NotSupported(),
        "fan": pynvml_mod.NVMLError_NotSupported(),
        "power_mw": pynvml_mod.NVMLError_NotSupported(),
        "limit_mw": pynvml_mod.NVMLError_NotSupported(),
    }
    stats = _stats(gpus=[broken])

    check(len(stats["gpus"]) == 1, "GPU entry kept when every metric fails")
    g = stats["gpus"][0]
    check(g["name"] is None, "name null when unavailable")
    check(g["vram"] is None, "vram null when unavailable")
    check(g["utilization_percent"] is None, "utilization null when unavailable")
    check(g["temperature_c"] is None, "temperature null when unavailable")
    check(g["fan_percent"] is None, "fan null when unavailable")
    check(g["power_w"] is None, "power null when unavailable")
    check(g["power_limit_w"] is None, "power limit null when unavailable")
    check(stats["cpu_percent"] == 12.5, "CPU metrics unaffected")


def test_cpu_sensor_absent_or_raising_gives_null():
    stats = _stats(temps={})
    check(stats["cpu_temp"] is None, "empty sensors dict -> cpu_temp null")
    check(stats["cpu_percent"] == 12.5, "cpu_percent kept without sensor")

    stats = _stats(temps_error=OSError("no hwmon"))
    check(stats["cpu_temp"] is None, "raising sensors_temperatures -> cpu_temp null")
    check(stats["cpu_freq_mhz"] == 4200.0, "cpu_freq kept without sensor")


def test_cpu_freq_absent_gives_null():
    stats = _stats(freq=None)
    check(stats["cpu_freq_mhz"] is None, "cpu_freq None -> cpu_freq_mhz null")


def test_nvml_unavailable_keeps_cpu_metrics():
    stats = _stats(gpus=[], count_error=pynvml_mod.NVMLError(1))
    check(stats["gpus"] == [], "no GPU reported when NVML fails")
    check(stats["cpu_percent"] == 12.5, "cpu_percent kept without NVML")
    check(stats["ram"]["percent"] == 50.0, "ram kept without NVML")


def test_power_limit_falls_back_on_default_limit():
    gpu = {
        "limit_mw": pynvml_mod.NVMLError_NotSupported(),
        "default_limit_mw": 250000,
    }
    stats = _stats(gpus=[gpu])
    check(stats["gpus"][0]["power_limit_w"] == 250.0,
          "default power limit used when management limit is unsupported")

    # Both getters unavailable -> null (never a fake 0).
    stats = _stats(gpus=[{"limit_mw": pynvml_mod.NVMLError_NotSupported()}])
    check(stats["gpus"][0]["power_limit_w"] is None,
          "power limit null when neither getter answers")


def test_cpu_temp_amd_k10temp_and_coretemp_without_package_label():
    temps = {"k10temp": [
        _temp("Tccd1", 45.0, None, None),
        _temp("Tctl", 68.5, None, None),
    ]}
    stats = _stats(temps=temps)
    check(stats["cpu_temp"]["current"] == 68.5, "AMD k10temp prefers Tctl")
    check(stats["cpu_temp"]["high"] is None, "k10temp without thresholds -> high null")
    check(stats["cpu_temp"]["critical"] is None, "k10temp without thresholds -> critical null")

    # coretemp present but without "Package id 0": first entry is used.
    temps = {"coretemp": [_temp("Core 0", 55.0, 92.0, 102.0)]}
    stats = _stats(temps=temps)
    check(stats["cpu_temp"] == {"current": 55.0, "high": 92.0, "critical": 102.0},
          "coretemp without Package id 0 falls back to its first entry")


if __name__ == "__main__":
    sys.exit(run_suite(_suite, globals()))
