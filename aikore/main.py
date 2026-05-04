import os
import time as _time
_t_import_start = _time.time()
print("[Import] Starting AiKore module imports...")
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
print(f"[Import] FastAPI loaded. ({_time.time() - _t_import_start:.2f}s)")

_t_nvml = _time.time()
from pynvml import nvmlInit, nvmlShutdown, NVMLError
print(f"[Import] pynvml loaded. ({_time.time() - _t_nvml:.2f}s)")

_t_db = _time.time()
from .database import models, crud, migration
from .database.session import SessionLocal
print(f"[Import] Database modules loaded. ({_time.time() - _t_db:.2f}s)")

_t_api = _time.time()
from .api import instances, system, builder
print(f"[Import] API routers loaded. ({_time.time() - _t_api:.2f}s)")

_t_pm = _time.time()
from .core import process_manager
print(f"[Import] Process manager loaded. ({_time.time() - _t_pm:.2f}s)")

print(f"[Import] Total import time: {_time.time() - _t_import_start:.2f}s")

# --- Run Database Migration Check ---
migration.run_db_migration()

from .config import INSTANCES_DIR

# --- Request Size Limit Middleware ---
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Rejects request bodies larger than 10 MB to prevent resource exhaustion."""
    MAX_BODY_SIZE = 10 * 1024 * 1024  # 10 MB

    async def dispatch(self, request: Request, call_next):
        if request.method in ("POST", "PUT", "PATCH"):
            content_length = request.headers.get("content-length")
            if content_length and int(content_length) > self.MAX_BODY_SIZE:
                return Response("Request body too large", status_code=413)
        return await call_next(request)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Modern lifespan handler for startup/shutdown events (replaces deprecated on_event).
    """
    # === STARTUP ===
    # 0. Initialize NVML
    _t0 = __import__('time').time()
    print("[Startup] Step 0: Initializing NVML...")
    try:
        nvmlInit()
        print(f"[Startup] NVML initialized successfully. ({__import__('time').time() - _t0:.2f}s)")
    except NVMLError as error:
        print(f"[Startup] [Warning] NVML could not be initialized: {error}. ({__import__('time').time() - _t0:.2f}s)")
    except Exception as error:
        print(f"[Startup] [Warning] NVML unexpected error: {error}. ({__import__('time').time() - _t0:.2f}s)")

    # 1. Open database
    _t1 = __import__('time').time()
    print("[Startup] Step 1: Opening database...")
    db = SessionLocal()
    print(f"[Startup] Database session opened. ({__import__('time').time() - _t1:.2f}s)")
    try:
        # 2. Reset instance statuses
        print("[Startup] Step 2: Resetting instance statuses...")
        num_rows_updated = db.query(models.Instance).update({"status": "stopped", "pid": None})
        db.commit()
        print(f"[Startup] Reset status for {num_rows_updated} instances. ({__import__('time').time() - _t1:.2f}s)")

        # 3. Clear old log files (only check direct instance dirs, not deep subtree)
        _t2 = __import__('time').time()
        print("[Startup] Step 3: Clearing old log files...")
        cleared_count = 0
        for entry in os.scandir(INSTANCES_DIR):
            if entry.is_dir():
                log_path = os.path.join(entry.path, "output.log")
                if os.path.exists(log_path):
                    try:
                        os.remove(log_path)
                        cleared_count += 1
                    except OSError as e:
                        print(f"[Startup] Error removing log file {log_path}: {e}")
        if cleared_count > 0:
            print(f"[Startup] Cleared {cleared_count} old log files. ({__import__('time').time() - _t2:.2f}s)")
        else:
            print(f"[Startup] No log files to clear. ({__import__('time').time() - _t2:.2f}s)")

        # 4. Autostart instances
        _t3 = __import__('time').time()
        print("[Startup] Step 4: Checking for instances to autostart...")
        autostart_instances = crud.get_autostart_instances(db)
        if not autostart_instances:
            print(f"[Startup] No instances marked for autostart. ({__import__('time').time() - _t3:.2f}s)")
        else:
            print(f"[Startup] Found {len(autostart_instances)} instance(s) to start.")
            for instance in autostart_instances:
                _ti = __import__('time').time()
                try:
                    db.refresh(instance)
                    print(f"[Startup] Starting instance '{instance.name}' (ID: {instance.id})...")
                    process_manager.start_instance_process(db, instance)
                    print(f"[Startup] Instance '{instance.name}' started. ({__import__('time').time() - _ti:.2f}s)")
                except Exception as e:
                    print(f"[Startup] [ERROR] Failed to autostart '{instance.name}': {e} ({__import__('time').time() - _ti:.2f}s)")
                    instance.status = "error"
                    db.commit()
    finally:
        db.close()
        print("[Startup] Database session closed.")

    print(f"[Startup] ✓ Application startup complete. Total: {__import__('time').time() - _t0:.2f}s")

    yield  # <-- Application runs here

    # === SHUTDOWN ===
    try:
        nvmlShutdown()
        print("[Shutdown] NVML shut down successfully.")
    except NVMLError:
        pass # Ignore if it was never initialized or already shut down

app = FastAPI(
    title="AiKore API",
    description="Backend API for managing AI WebUI instances.",
    version="0.1.0",
    lifespan=lifespan,
)

# Apply request size limit (10 MB) to prevent resource exhaustion
app.add_middleware(RequestSizeLimitMiddleware)

# Include the API routers
app.include_router(instances.router)
app.include_router(system.router)
app.include_router(builder.router)

# Mount the static directory to serve frontend files
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/api/status", tags=["System"])
def get_status():
    """A simple endpoint to check if the API is running."""
    return {"status": "ok", "message": "AiKore is running!"}

@app.get("/", include_in_schema=False)
def read_root():
    """Serve the main index.html file."""
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))