import os
import glob
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .database import models, crud
from .database.session import engine, SessionLocal
from .api import instances, system

# Define the path to the static directory
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
INSTANCES_DIR = "/config/instances" # Define instances dir for log cleanup

# Create the database tables on startup, if they don't exist
models.Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="AiKore API",
    description="Backend API for managing AI WebUI instances.",
    version="0.1.0",
)

@app.on_event("startup")
def startup_event():
    """
    Actions to perform on application startup.
    - Resets the status of all instances to 'stopped'.
    - Clears all old log files.
    """
    # Reset all instance statuses
    db = SessionLocal()
    try:
        num_rows_updated = db.query(models.Instance).update({"status": "stopped", "pid": None})
        db.commit()
        print(f"[Startup] Reset status for {num_rows_updated} instances.")
    finally:
        db.close()

    # Clear old log files
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