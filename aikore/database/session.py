import os
import shutil
import logging
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import OperationalError

# --- CONSTANTS ---
LATEST_DB_VERSION = 3
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

def _migrate_v2_to_v3():
    """
    Performs the migration from database version 2 to 3.
    - Adds the 'access_pattern' column to the 'instances' table with a default value.
    """
    log.info("Performing database migration from v2 to v3...")
    try:
        with engine.connect() as connection:
            # Use a transaction to ensure atomicity
            with connection.begin():
                # Add the new column with a default value of 'port'
                add_column_sql = text("""
                    ALTER TABLE instances
                    ADD COLUMN access_pattern VARCHAR NOT NULL DEFAULT 'port'
                """)
                connection.execute(add_column_sql)
                
                # Update the database version number
                update_version_sql = text("""
                    UPDATE aikore_meta
                    SET value = :version
                    WHERE key = 'database_version'
                """)
                connection.execute(update_version_sql, {"version": "3"})
            
            log.info("Successfully added 'access_pattern' column and updated DB version to 3.")
    except Exception as e:
        log.error(f"FATAL: Database migration from v2 to v3 failed: {e}")
        raise

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
        
        # Set the new database version (to 2, as this is the v1->v2 migration)
        meta_version = models.AikoreMeta(key="database_version", value="2")
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
        # The v1->v2 migration creates the table and sets version to 2.
        _migrate_v1_to_v2()
        # After this, the DB is at v2. We can proceed with other migrations.
    
    try:
        with SessionLocal() as db:
            from . import models
            version_entry = db.query(models.AikoreMeta).filter_by(key="database_version").first()
            if not version_entry:
                log.warning("aikore_meta table exists but is empty. Assuming v1 and migrating.")
                _migrate_v1_to_v2()
                version_entry = db.query(models.AikoreMeta).filter_by(key="database_version").first()
            
            current_version = int(version_entry.value)
            
            if current_version < LATEST_DB_VERSION:
                log.info(f"Database version {current_version} detected. Latest is {LATEST_DB_VERSION}. Starting migration...")
                
                if current_version == 1:
                    # This should be handled by the check above, but as a safeguard:
                    _migrate_v1_to_v2()
                    current_version = 2 # Manually update for the next step in the chain
                
                if current_version == 2:
                    _migrate_v2_to_v3()
                    current_version = 3 # Manually update for future migrations

                # Add 'if current_version == 3:' for the next migration, etc.
                
            else:
                log.info(f"Database is up to date (version {current_version}).")
    
    except OperationalError as e:
        # This can happen if the DB is corrupt or from a future version with unknown columns
        log.error(f"A database operational error occurred: {e}. Manual check might be needed.")
        raise
    except Exception as e:
        log.error(f"An unexpected error occurred during database version check: {e}")
        raise