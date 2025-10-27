import os
import shutil
import logging
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import OperationalError

# --- CONSTANTS ---
LATEST_DB_VERSION = 2
DATABASE_PATH = "/config/aikore.db"
SQLALCHEMY_DATABASE_URL = f"sqlite:///{DATABASE_PATH}"

# Configure logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# --- DATABASE ENGINE AND SESSION ---
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- MIGRATION LOGIC ---

def _migrate_v1_to_v2():
    """
    Performs the migration from database version 1 to 2.
    - Adds the 'is_comfyui_active_slot' column to the 'instances' table.
    - Adds the 'aikore_meta' table and sets the database version.
    """
    old_db_path = f"{DATABASE_PATH}.old_v1"
    log.info(f"Backing up old database to {old_db_path}...")
    shutil.move(DATABASE_PATH, old_db_path)

    # Create a new engine for the old database to read from it
    old_engine = create_engine(f"sqlite:///{old_db_path}")
    OldSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=old_engine)
    old_db = OldSessionLocal()

    # Create the new database with the latest schema
    from . import models  # Import here to avoid circular dependency
    log.info("Creating new database with the latest schema (v2)...")
    Base.metadata.create_all(bind=engine)
    new_db = SessionLocal()

    try:
        # Read all instances from the old database
        log.info("Migrating data from old database...")
        # Using text() for raw query as the old models are not defined
        old_instances = old_db.execute(text("SELECT * FROM instances")).fetchall()
        
        migrated_count = 0
        for row in old_instances:
            new_instance = models.Instance(
                id=row.id,
                name=row.name,
                base_blueprint=row.base_blueprint,
                gpu_ids=row.gpu_ids,
                autostart=row.autostart,
                persistent_mode=row.persistent_mode,
                status=row.status,
                pid=row.pid,
                port=row.port,
                vnc_port=row.vnc_port,
                vnc_display=row.vnc_display,
                is_comfyui_active_slot=False  # New field with default value
            )
            new_db.add(new_instance)
            migrated_count += 1
        
        # Set the new database version
        meta_version = models.AikoreMeta(key="database_version", value=str(LATEST_DB_VERSION))
        new_db.add(meta_version)
        
        new_db.commit()
        log.info(f"Successfully migrated {migrated_count} instances.")

        # Verification step
        new_count = new_db.query(models.Instance).count()
        if new_count != len(old_instances):
            raise Exception(f"Migration verification failed: Old DB had {len(old_instances)} instances, new DB has {new_count}.")

        log.info("Migration successful. Removing backup file.")
        os.remove(old_db_path)

    except Exception as e:
        log.error(f"FATAL: Database migration failed: {e}")
        log.error("The new database has been created, but the old one is preserved as "
                    f"'{old_db_path}'. Manual intervention is required.")
        # Restore the backup
        if os.path.exists(DATABASE_PATH):
            os.remove(DATABASE_PATH)
        shutil.move(old_db_path, DATABASE_PATH)
        raise  # Re-raise the exception to stop the application
    finally:
        old_db.close()
        new_db.close()

def check_and_migrate_db():
    """
    Checks the database version and performs migration if necessary.
    This is the main entry point for the migration process.
    """
    if not os.path.exists(DATABASE_PATH):
        log.info("No database found. Creating a new one at the latest version.")
        from . import models
        Base.metadata.create_all(bind=engine)
        with SessionLocal() as db:
            meta_version = models.AikoreMeta(key="database_version", value=str(LATEST_DB_VERSION))
            db.add(meta_version)
            db.commit()
        return

    inspector = inspect(engine)
    
    # Check if this is a v1 database (aikore_meta table does not exist)
    if not inspector.has_table("aikore_meta"):
        log.info("Database version 1 detected (no 'aikore_meta' table). Starting migration to v2...")
        _migrate_v1_to_v2()
        return

    # For future migrations, we'll check the version number
    try:
        with SessionLocal() as db:
            from . import models
            version_entry = db.query(models.AikoreMeta).filter_by(key="database_version").first()
            if not version_entry:
                # This case should be rare, but handle it.
                log.warning("aikore_meta table exists but is empty. Assuming v1 and migrating.")
                _migrate_v1_to_v2()
                return
            
            current_version = int(version_entry.value)
            if current_version < LATEST_DB_VERSION:
                log.info(f"Database version {current_version} detected. Latest is {LATEST_DB_VERSION}.")
                # Here you would add a loop or if/elif chain for future migrations
                # For now, we only have one migration path.
                if current_version == 1:
                    _migrate_v1_to_v2()
                else:
                    log.error(f"Unknown database version {current_version}. No migration path available.")
                    raise Exception(f"Cannot migrate from unknown database version {current_version}")
            else:
                log.info(f"Database is up to date (version {current_version}).")
    
    except OperationalError:
        # This can happen if the DB exists but is empty/corrupt
        log.warning("Could not inspect database, assuming it's a fresh v1. Attempting migration.")
        _migrate_v1_to_v2()
    except Exception as e:
        log.error(f"An unexpected error occurred during database version check: {e}")
        raise