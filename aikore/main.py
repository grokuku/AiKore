from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os

from .database import models
from .database.session import engine
from .api import instances, system # <-- Import the new router

# Define the path to the static directory
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

# Create the database tables on startup, if they don't exist
models.Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="AiKore API",
    description="Backend API for managing AI WebUI instances.",
    version="0.1.0",
)

# Include the API routers
app.include_router(instances.router)
app.include_router(system.router) # <-- Add the new router to the app

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