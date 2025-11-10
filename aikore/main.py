import os
import glob
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pynvml import nvmlInit, nvmlShutdown, NVMLError

from .database import models, crud, migration
from .database.session import SessionLocal
from .api import instances, system
from .core import process_manager

# --- Run Database Migration Check ---
migration.run_db_migration()

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
INSTANCES_DIR = "/config/instances" # Define instances dir for log cleanup

app = FastAPI(
    title="AiKore API",
    description="Backend API for managing AI WebUI instances.",
    version="0.1.0",
)

@app.on_event("startup")
def startup_event():
    """
    Actions to perform on application startup.
    - Initializes NVML for GPU monitoring.
    - Resets the status of all instances to 'stopped'.
    - Clears all old log files.
    - Autostarts instances marked for it.
    """
    # 0. Initialize NVML
    try:
        nvmlInit()
        print("[Startup] NVML initialized successfully.")
    except NVMLError as error:
        print(f"[Startup] [Warning] NVML could not be initialized: {error}. GPU features will be disabled.")

    db = SessionLocal()
    try:
        # 1. Reset all instance statuses
        num_rows_updated = db.query(models.Instance).update({"status": "stopped", "pid": None})
        db.commit()
        print(f"[Startup] Reset status for {num_rows_updated} instances.")

        # 2. Clear old log files
        log_files = glob.glob(os.path.join(INSTANCES_DIR, "**", "output.log"), recursive=True)
        cleared_count = 0
        for log_file in log_files:
            try:
                os.remove(log_file)
                cleared_count += 1
            except OSError as e:
                print(f"[Startup] Error removing log file {log_file}: {e}")
        if cleared_count > 0:
            print(f"[Startup] Cleared {cleared_count} old log files.")

        # 3. Autostart instances
        print("[Startup] Checking for instances to autostart...")
        autostart_instances = crud.get_autostart_instances(db)
        if not autostart_instances:
            print("[Startup] No instances marked for autostart.")
        else:
            print(f"[Startup] Found {len(autostart_instances)} instance(s) to start.")
            for instance in autostart_instances:
                print(f"[Startup] Autostarting instance '{instance.name}' (ID: {instance.id})...")
                try:
                    process_manager.start_instance_process(db, instance)
                except Exception as e:
                    print(f"[Startup] [ERROR] Failed to autostart instance '{instance.name}': {e}")
                    # Mark instance as 'error' so the UI can reflect the failure
                    instance.status = "error"
                    db.commit()
    finally:
        db.close()

@app.on_event("shutdown")
def shutdown_event():
    """
    Actions to perform on application shutdown.
    - Shuts down NVML.
    """
    try:
        nvmlShutdown()
        print("[Shutdown] NVML shut down successfully.")
    except NVMLError:
        pass # Ignore if it was never initialized or already shut down

# Include the API routers
app.include_router(instances.router)
app.include_router(system.router)

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