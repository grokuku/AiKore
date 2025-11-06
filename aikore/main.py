import os
import glob
import sys
import time
import shutil
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy import create_engine, inspect, Column, Integer, String, Boolean
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base

from .database import models, crud
from .database.session import engine, SessionLocal, DATABASE_URL, connect_args
from .api import instances, system
from .core import process_manager

# --- AUTOMATED DATABASE MIGRATION LOGIC ---

EXPECTED_DB_VERSION = 2

def _get_db_version(db_session):
    """Checks the version of the database."""
    try:
        inspector = inspect(db_session.bind)
        if not inspector.has_table(models.AikoreMeta.__tablename__):
            return 1
        
        version_entry = db_session.query(models.AikoreMeta).filter_by(key="schema_version").first()
        if not version_entry:
            return 1
        
        return int(version_entry.value)
    except Exception as e:
        print(f"[DB Migration] Error checking DB version: {e}", file=sys.stderr)
        return 1

def _perform_v1_to_v2_migration():
    """
    Migrates the database from schema V1 to V2.
    V1 -> V2 Change: Adds the `hostname` column to the `instances` table.
    """
    print("[DB Migration] Starting migration from V1 to V2...")
    
    db_path = DATABASE_URL.split("///")[1]
    backup_path = f"{db_path}.bak.{int(time.time())}"
    
    print(f"[DB Migration] 1. Backing up current database to: {backup_path}")
    try:
        shutil.copy2(db_path, backup_path)
    except Exception as e:
        print(f"[DB Migration] FATAL: Could not back up database. Aborting. Error: {e}", file=sys.stderr)
        sys.exit(1)
        
    Base_v1 = declarative_base()
    class Instance_v1(Base_v1):
        __tablename__ = "instances"
        id = Column(Integer, primary_key=True, index=True)
        name = Column(String, unique=True, index=True, nullable=False)
        base_blueprint = Column(String, nullable=False)
        gpu_ids = Column(String, nullable=True)
        autostart = Column(Boolean, default=False, nullable=False)
        persistent_mode = Column(Boolean, default=False, nullable=False)
        status = Column(String, default="stopped", nullable=False)
        pid = Column(Integer, nullable=True)
        port = Column(Integer, nullable=True)
        persistent_port = Column(Integer, nullable=True)
        persistent_display = Column(Integer, nullable=True)

    old_engine = create_engine(f"sqlite:///{backup_path}")
    OldSession = sessionmaker(autocommit=False, autoflush=False, bind=old_engine)
    
    print("[DB Migration] 2. Creating new empty database with V2 schema...")
    if os.path.exists(db_path):
        os.remove(db_path)
    
    temp_new_engine = create_engine(DATABASE_URL, connect_args=connect_args)
    models.Base.metadata.create_all(bind=temp_new_engine)
    NewSession = sessionmaker(autocommit=False, autoflush=False, bind=temp_new_engine)
    
    try:
        print("[DB Migration] 3. Transferring data...")
        with OldSession() as old_db, NewSession() as new_db:
            old_instances = old_db.query(Instance_v1).all()
            for old_inst in old_instances:
                new_inst = models.Instance(
                    id=old_inst.id, name=old_inst.name, base_blueprint=old_inst.base_blueprint,
                    gpu_ids=old_inst.gpu_ids, autostart=old_inst.autostart,
                    persistent_mode=old_inst.persistent_mode, hostname=None,
                    status="stopped", pid=None,
                    port=old_inst.port, persistent_port=old_inst.persistent_port,
                    persistent_display=old_inst.persistent_display,
                )
                new_db.add(new_inst)
            new_db.add(models.AikoreMeta(key="schema_version", value=str(EXPECTED_DB_VERSION)))
            new_db.commit()
            print(f"[DB Migration]    - Transferred {len(old_instances)} records. Commit successful.")

        print("[DB Migration] 4. Verifying data integrity...")
        with OldSession() as old_db_verify, NewSession() as new_db_verify:
            old_count = old_db_verify.query(Instance_v1).count()
            new_count = new_db_verify.query(models.Instance).count()
            if old_count != new_count:
                raise ValueError(f"Verification failed: Row count mismatch. Old={old_count}, New={new_count}")
            print("[DB Migration]    - Verification successful!")

    except Exception as e:
        print(f"[DB Migration] FATAL: Error during migration.", file=sys.stderr)
        print(f"[DB Migration] Original database is safe at: {backup_path}", file=sys.stderr)
        print(f"[DB Migration] Error details: {e}", file=sys.stderr)
        if os.path.exists(db_path): os.remove(db_path)
        shutil.copy2(backup_path, db_path)
        print(f"[DB Migration] Restored backup to {db_path}.")
        sys.exit(1)
    finally:
        temp_new_engine.dispose()
        
    print("[DB Migration] 5. Migration complete. Requesting application restart for changes to take effect.")
    sys.exit(0)

def run_db_migration():
    db_path = DATABASE_URL.split("///")[1]
    if not os.path.exists(db_path) or os.path.getsize(db_path) == 0:
        print("[DB Init] No database found or DB is empty. Creating new one.")
        if os.path.exists(db_path): os.remove(db_path)
        models.Base.metadata.create_all(bind=engine)
        with SessionLocal() as db:
            db.add(models.AikoreMeta(key="schema_version", value=str(EXPECTED_DB_VERSION)))
            db.commit()
        print(f"[DB Init] Database created with schema version {EXPECTED_DB_VERSION}.")
        return

    with SessionLocal() as db:
        current_version = _get_db_version(db)
        print(f"[DB Check] Current DB version: {current_version}. Expected version: {EXPECTED_DB_VERSION}.")
    
        if current_version < EXPECTED_DB_VERSION:
            if current_version == 1 and EXPECTED_DB_VERSION == 2:
                _perform_v1_to_v2_migration()
            else:
                print(f"[DB Migration] FATAL: Unsupported migration path from v{current_version} to v{EXPECTED_DB_VERSION}.", file=sys.stderr)
                sys.exit(1)
        elif current_version > EXPECTED_DB_VERSION:
            print(f"[DB Migration] WARNING: Database version ({current_version}) is newer than the application's expected version.", file=sys.stderr)

# --- END OF MIGRATION LOGIC ---

run_db_migration()

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
    - Resets the status of all instances to 'stopped'.
    - Clears all old log files.
    - Autostarts instances marked for it.
    """
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