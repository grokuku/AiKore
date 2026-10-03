"""
tests/_stubs.py — Dual-mode test helper for AiKore.

AiKore's runtime container ships fastapi / pydantic / sqlalchemy / psutil /
requests, but the dev environment where these tests are validated does NOT.
This module centralises the "stub injection" pattern used by earlier sessions:

  * If a third-party dependency is importable, the REAL module is used.
  * Otherwise a minimal stub is installed into ``sys.modules`` so the REAL
    ``aikore.*`` modules can be imported and exercised.

It also wires up the ``aikore`` namespace package (pointing at the real source
tree) and pre-installs stubs for the modules that would otherwise touch
``/config`` or the real database (``aikore.config``, ``aikore.database.session``,
``aikore.database.crud``).

Usage from a test suite::

    from tests._stubs import load_aikore_module, Suite, run_suite
    auth = load_aikore_module("aikore.core.auth")
"""

import importlib
import os
import sys
import tempfile
import types

# ---------------------------------------------------------------------------
# 0. Project root on sys.path so the REAL aikore.* source tree is importable.
# ---------------------------------------------------------------------------
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def _install_stub(name, module):
    sys.modules.setdefault(name, module)
    return module


def _try_import(name):
    try:
        return importlib.import_module(name)
    except ImportError:
        return None


# ---------------------------------------------------------------------------
# 1. Third-party dependency stubs (only installed when the real lib is absent).
# ---------------------------------------------------------------------------

def _make_pydantic_stub():
    """Minimal pydantic: BaseModel + field_validator + ValidationError.

    Supports the subset used by aikore/schemas/instance.py (classmethod
    field validators that raise ValueError). Real pydantic is used when
    available.
    """
    mod = types.ModuleType("pydantic")

    class ValidationError(Exception):
        def __init__(self, errors):
            self.errors = errors
            super().__init__(f"Validation error: {errors}")

    def field_validator(*fields):
        def deco(func):
            target = getattr(func, "__func__", func)
            target._aikore_fields = fields
            return func
        return deco

    class BaseModel:
        def __init_subclass__(cls, **kwargs):
            super().__init_subclass__(**kwargs)
            validators = {}
            for attr in cls.__dict__.values():
                target = getattr(attr, "__func__", attr)
                fields = getattr(target, "_aikore_fields", None)
                if fields:
                    for f in fields:
                        validators[f] = target
            cls.__field_validators__ = validators

        def __init__(self, **data):
            data = dict(data)
            for name, validator in self.__field_validators__.items():
                if name in data:
                    try:
                        data[name] = validator(self.__class__, data[name])
                    except ValueError as e:
                        raise ValidationError([{"loc": (name,), "msg": str(e)}])
            for k, v in data.items():
                setattr(self, k, v)

        @classmethod
        def model_validate(cls, obj):
            if isinstance(obj, dict):
                return cls(**obj)
            data = {}
            for name in getattr(cls, "__annotations__", {}):
                if hasattr(obj, name):
                    data[name] = getattr(obj, name)
            return cls(**data)

        def model_dump(self):
            return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}

    mod.ValidationError = ValidationError
    mod.field_validator = field_validator
    mod.BaseModel = BaseModel
    return mod


def _make_fastapi_stub():
    """Minimal fastapi: APIRouter, HTTPException, Depends, Body, WebSocket,
    BackgroundTasks, responses.FileResponse. Real fastapi is used when present.
    """
    mod = types.ModuleType("fastapi")

    class HTTPException(Exception):
        def __init__(self, status_code=500, detail=None):
            self.status_code = status_code
            self.detail = detail
            super().__init__(detail)

    class APIRouter:
        def __init__(self, *a, **k):
            self.routes = []

        def _route(self, *a, **k):
            def deco(f):
                return f
            return deco

        get = _route
        post = _route
        put = _route
        delete = _route
        patch = _route
        websocket = _route

    def Depends(x=None):
        return x

    def Body(x=None):
        return x

    class WebSocket:
        pass

    class WebSocketDisconnect(Exception):
        pass

    class BackgroundTasks:
        def add_task(self, *a, **k):
            pass

    mod.APIRouter = APIRouter
    mod.HTTPException = HTTPException
    mod.Depends = Depends
    mod.Body = Body
    mod.WebSocket = WebSocket
    mod.WebSocketDisconnect = WebSocketDisconnect
    mod.BackgroundTasks = BackgroundTasks

    responses = types.ModuleType("fastapi.responses")

    class FileResponse:
        def __init__(self, *a, **k):
            pass

    responses.FileResponse = FileResponse
    mod.responses = responses
    sys.modules["fastapi.responses"] = responses
    return mod


def _make_sqlalchemy_stub():
    """Minimal sqlalchemy + sqlalchemy.orm stubs sufficient to import the
    aikore modules under test. Real sqlalchemy is used when present.
    """
    mod = types.ModuleType("sqlalchemy")

    class Column:
        def __init__(self, *a, **k):
            pass

    class Integer:
        pass

    class String:
        pass

    class Boolean:
        pass

    class Text:
        pass

    class Float:
        pass

    class _FakeEngine:
        def connect(self):
            raise NotImplementedError("stub engine: no real DB")

        def dispose(self):
            pass

    def create_engine(*a, **k):
        return _FakeEngine()

    def inspect(*a, **k):
        raise NotImplementedError("stub inspect")

    def text(s):
        return s

    def or_(*a):
        return a

    class event:
        @staticmethod
        def listens_for(*a, **k):
            def deco(f):
                return f
            return deco

    mod.Column = Column
    mod.Integer = Integer
    mod.String = String
    mod.Boolean = Boolean
    mod.Text = Text
    mod.Float = Float
    mod.create_engine = create_engine
    mod.inspect = inspect
    mod.text = text
    mod.or_ = or_
    mod.event = event

    # --- sqlalchemy.orm ---
    orm = types.ModuleType("sqlalchemy.orm")

    class _Meta:
        def create_all(self, bind=None):
            pass

    class DeclarativeBase:
        metadata = _Meta()

    class Session:
        pass

    class _FakeQuery:
        def filter(self, *a, **k):
            return self

        def filter_by(self, *a, **k):
            return self

        def first(self):
            return None

        def all(self):
            return []

        def update(self, *a, **k):
            return 0

        def count(self):
            return 0

    class _FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def query(self, *a, **k):
            return _FakeQuery()

        def commit(self):
            pass

        def add(self, *a):
            pass

    class _FakeSessionMaker:
        def __call__(self, *a, **k):
            return _FakeSession()

    def sessionmaker(*a, **k):
        return _FakeSessionMaker()

    orm.Session = Session
    orm.sessionmaker = sessionmaker
    orm.DeclarativeBase = DeclarativeBase
    mod.orm = orm
    sys.modules["sqlalchemy.orm"] = orm
    return mod


def _make_psutil_stub():
    mod = types.ModuleType("psutil")

    def pid_exists(pid):
        return True

    def cpu_percent(interval=None):
        return 0.0

    def virtual_memory():
        return types.SimpleNamespace(total=16 * 1024**3, used=8 * 1024**3, percent=50.0)

    # sensors_temperatures() is a dict keyed by chip name (coretemp, k10temp,
    # acpitz, ...) whose entries expose label/current/high/critical. The empty
    # dict is the graceful default: /api/system/stats then reports cpu_temp
    # as None instead of crashing. Tests monkeypatch this (or the pynvml
    # getters) to cover the enriched payload.
    def sensors_temperatures():
        return {}

    def cpu_freq():
        return None

    mod.pid_exists = pid_exists
    mod.cpu_percent = cpu_percent
    mod.virtual_memory = virtual_memory
    mod.sensors_temperatures = sensors_temperatures
    mod.cpu_freq = cpu_freq
    return mod


def _make_pynvml_stub():
    """Minimal pynvml (nvidia-ml-py) stub: error classes + getters.

    The default getters raise NVMLError_NotSupported; tests patch the names
    imported by aikore.api.system (nvmlDeviceGetCount, ...GetTemperature,
    ...GetFanSpeed, ...GetPowerUsage, ...PowerManagementLimit/DefaultLimit)
    to exercise the enriched /api/system/stats payload.
    """
    mod = types.ModuleType("pynvml")

    class NVMLError(Exception):
        def __init__(self, value=None):
            self.value = value
            super().__init__(f"NVML error {value}")

    class NVMLError_NotSupported(NVMLError):
        pass

    def _unavailable(*a, **k):
        raise NVMLError_NotSupported()

    mod.NVMLError = NVMLError
    mod.NVMLError_NotSupported = NVMLError_NotSupported
    mod.NVML_TEMPERATURE_GPU = 0
    mod.nvmlDeviceGetCount = lambda: 0
    mod.nvmlDeviceGetHandleByIndex = lambda i: i
    for _name in (
        "nvmlDeviceGetMemoryInfo",
        "nvmlDeviceGetUtilizationRates",
        "nvmlDeviceGetName",
        "nvmlDeviceGetTemperature",
        "nvmlDeviceGetFanSpeed",
        "nvmlDeviceGetPowerUsage",
        "nvmlDeviceGetPowerManagementLimit",
        "nvmlDeviceGetPowerManagementDefaultLimit",
        "nvmlDeviceGetEnforcedPowerLimit",
    ):
        setattr(mod, _name, _unavailable)
    return mod


def _make_requests_stub():
    mod = types.ModuleType("requests")

    class _ConnectionError(Exception):
        pass

    class _Response:
        status_code = 200

    def get(url, timeout=None):
        return _Response()

    mod.ConnectionError = _ConnectionError
    mod.get = get

    exc = types.ModuleType("requests.exceptions")
    exc.ConnectionError = _ConnectionError
    mod.exceptions = exc
    sys.modules["requests.exceptions"] = exc
    return mod


# ---------------------------------------------------------------------------
# 2. aikore submodule stubs (always stubbed -> never touch /config or the DB).
# ---------------------------------------------------------------------------

def _make_aikore_config_stub():
    """aikore.config with temp dirs so no test ever touches /config."""
    base = tempfile.mkdtemp(prefix="aikore_test_")
    mod = types.ModuleType("aikore.config")
    mod.INSTANCES_DIR = os.path.join(base, "instances")
    mod.OUTPUTS_DIR = os.path.join(base, "outputs")
    mod.BLUEPRINTS_DIR = os.path.join(base, "blueprints")
    mod.CUSTOM_BLUEPRINTS_DIR = os.path.join(base, "custom_blueprints")
    mod.SCRIPTS_DIR = os.path.join(base, "scripts")
    return mod


def _get_orm_declarative_base():
    orm = sys.modules.get("sqlalchemy.orm")
    if orm is not None and hasattr(orm, "DeclarativeBase"):
        return orm.DeclarativeBase

    class _Base:
        pass

    return _Base


def _make_aikore_session_stub():
    """aikore.database.session stub — never opens the real /config DB."""
    mod = types.ModuleType("aikore.database.session")
    mod.DATABASE_URL = "sqlite:////tmp/aikore_test.db"
    mod.connect_args = {"check_same_thread": False}
    mod.engine = None
    mod.SessionLocal = None
    mod.Base = _get_orm_declarative_base()

    def get_db():
        yield None

    mod.get_db = get_db
    return mod


def _make_aikore_crud_stub():
    """aikore.database.crud stub — keeps instances.py importable without the
    heavy real crud module. Tests monkeypatch get_instance as needed."""
    mod = types.ModuleType("aikore.database.crud")

    def get_instance(db, instance_id=None, **k):
        return None

    mod.get_instance = get_instance
    return mod


# ---------------------------------------------------------------------------
# 3. Public entry points.
# ---------------------------------------------------------------------------

def ensure_stubs():
    """Install stubs for missing third-party deps and the aikore submodules
    that would touch /config or the real DB.

    Returns True if any third-party stub was installed (i.e. we are NOT in the
    full runtime container), False if everything real is available.
    """
    stubbed = False

    if _try_import("pydantic") is None:
        _install_stub("pydantic", _make_pydantic_stub())
        stubbed = True

    if _try_import("fastapi") is None:
        _install_stub("fastapi", _make_fastapi_stub())
        stubbed = True

    if _try_import("sqlalchemy") is None:
        _install_stub("sqlalchemy", _make_sqlalchemy_stub())
        stubbed = True

    if _try_import("psutil") is None:
        _install_stub("psutil", _make_psutil_stub())
        stubbed = True

    if _try_import("pynvml") is None:
        _install_stub("pynvml", _make_pynvml_stub())
        stubbed = True

    if _try_import("requests") is None:
        _install_stub("requests", _make_requests_stub())
        stubbed = True

    # Always stub these so no test ever touches /config or the real DB.
    _install_stub("aikore.config", _make_aikore_config_stub())
    _install_stub("aikore.database.session", _make_aikore_session_stub())
    _install_stub("aikore.database.crud", _make_aikore_crud_stub())

    return stubbed


def load_aikore_module(name):
    """Import a REAL aikore.* module with the stubs in place."""
    ensure_stubs()
    return importlib.import_module(name)


# ---------------------------------------------------------------------------
# 4. Standalone + pytest-compatible harness.
# ---------------------------------------------------------------------------

class Suite:
    """Counts PASS/FAIL checks. ``check()`` both records the result and
    asserts, so the same test_* functions work under pytest (asserts) and in
    the standalone runner (counter + exit code)."""

    def __init__(self, name):
        self.name = name
        self.passed = 0
        self.failed = 0
        self.failures = []

    def check(self, cond, label):
        if cond:
            self.passed += 1
            print(f"    [PASS] {label}")
        else:
            self.failed += 1
            self.failures.append(label)
            print(f"    [FAIL] {label}")
        assert cond, label

    def summary(self):
        return f"{self.name}: {self.passed} passed, {self.failed} failed"


def run_suite(suite, module_globals):
    """Run every ``test_*`` callable in ``module_globals`` and report.

    Returns the process exit code (0 = all green). Prints a machine-readable
    ``RESULT <name> <passed> <failed>`` line for the runner to parse.
    """
    funcs = [
        obj for name, obj in module_globals.items()
        if name.startswith("test_") and callable(obj)
    ]
    funcs.sort(key=lambda f: f.__name__)
    for f in funcs:
        before = suite.failed
        try:
            f()
        except Exception as e:  # noqa: BLE001 - harness must catch everything
            if suite.failed == before:
                suite.failed += 1
                suite.failures.append(f"{f.__name__}: {e}")
            print(f"    [FAIL] {f.__name__}: {e}")
    print()
    print(suite.summary())
    print(f"RESULT {suite.name} {suite.passed} {suite.failed}")
    return 0 if suite.failed == 0 else 1
