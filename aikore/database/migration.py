import os
import sys
import shutil
import time
import sqlite3
from sqlalchemy import create_engine, inspect, Column, Integer, String, Boolean, text
from sqlalchemy.orm import sessionmaker, Session, DeclarativeBase
from . import models
# LOT3 (H2): import the GLOBAL engine — the destructive rebuild steps
# (os.remove + recreate) leave the global engine's QueuePool holding
# connections attached to the deleted inode; the pool must be disposed.
from .session import SessionLocal, DATABASE_URL, connect_args, engine as _global_engine

# --- AUTOMATED DATABASE MIGRATION LOGIC ---

EXPECTED_DB_VERSION = 6


def _backup_database_before_step(db_path: str, backup_path: str, log_prefix: str = "0."):
    """LOT3 (M6): WAL-checkpoint-then-copy backup used by every step.

    The app DB runs in WAL mode (PRAGMA journal_mode=WAL in session.py), so
    the latest committed writes may still live in the '-wal' side file;
    shutil.copy2 of the main file alone would snapshot a stale state.
    PRAGMA wal_checkpoint(TRUNCATE) folds the WAL back into the main file
    immediately before the copy.
    """
    print(f"[DB Migration] {log_prefix} Backing up current database to: {backup_path}")
    try:
        checkpoint_con = sqlite3.connect(db_path)
        try:
            checkpoint_con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            checkpoint_con.close()
    except Exception as checkpoint_err:
        # Best-effort: a failed checkpoint degrades backup freshness, it must
        # not abort the migration itself.
        print(f"[DB Migration] WARNING: WAL checkpoint before backup failed: {checkpoint_err}", file=sys.stderr)
    try:
        shutil.copy2(db_path, backup_path)
    except Exception as e:
        print(f"[DB Migration] FATAL: Could not back up database. Aborting. Error: {e}", file=sys.stderr)
        sys.exit(1)

class DatabaseVersionError(RuntimeError):
    """LOT3 (M5): raised when the DB state cannot be trusted for a safe decision.

    Aborting startup (instead of silently assuming v1) is critical: the v1->v2
    migration is DESTRUCTIVE (it deletes and recreates the database file), so a
    transient access error on a v4/v5/v6 database must never be mistaken for a
    legacy v1 database.
    """

# Columns introduced AFTER schema v1. Their presence together with a missing
# meta table means the meta table was lost/corrupted — NOT a legitimate v1.
_POST_V1_COLUMNS = {
    "hostname", "use_custom_hostname", "output_path",
    "parent_instance_id", "python_version", "cuda_version", "torch_version",
}

def _get_db_version(db_session):
    """Checks the version of the database.

    LOT3 (M5): the historical implementation returned 1 on ANY exception, so a
    transient error (locked file, permission problem, corrupted page...) on a
    v4/v5/v6 database silently triggered the destructive v1->v2 migration.
    Now:
      - no meta table AND instances table looks genuinely v1 -> legitimate v1;
      - no meta table BUT post-v1 columns present -> hard abort (corrupted);
      - meta table present but no/invalid version row -> hard abort;
      - any other error -> CRITICAL log + raise (no silent fallback to 1).
    """
    try:
        inspector = inspect(db_session.bind)
        if not inspector.has_table(models.AikoreMeta.__tablename__):
            # No meta table: could be a legitimate v1 database... verify it.
            if inspector.has_table("instances"):
                columns = {col['name'] for col in inspector.get_columns('instances')}
                suspicious = sorted(columns & _POST_V1_COLUMNS)
                if suspicious:
                    raise DatabaseVersionError(
                        "The 'aikore_meta' table is missing but the 'instances' table "
                        f"contains post-v1 column(s) {suspicious}. The metadata table "
                        "was likely lost or the database is corrupted. Refusing to "
                        "run migrations (the v1->v2 step would DESTROY this data). "
                        "Restore 'aikore_meta' or restore from backup."
                    )
            return 1
        
        version_entry = db_session.query(models.AikoreMeta).filter_by(key="schema_version").first()
        if not version_entry:
            raise DatabaseVersionError(
                "Table 'aikore_meta' exists but has no 'schema_version' entry. "
                "Refusing to guess the schema version (a wrong guess would run "
                "destructive migrations)."
            )
        
        try:
            return int(version_entry.value)
        except (TypeError, ValueError) as e:
            raise DatabaseVersionError(
                f"Invalid 'schema_version' value {version_entry.value!r}: {e}"
            )
    except DatabaseVersionError:
        raise
    except Exception as e:
        print(
            f"[DB Migration] CRITICAL: could not determine the database version: {e}\n"
            f"[DB Migration] Refusing to migrate: falling back to version 1 would "
            f"trigger the DESTRUCTIVE v1->v2 rebuild on a possibly recent database.",
            file=sys.stderr,
        )
        raise

def _perform_v1_to_v2_migration():
    """
    Migrates the database from schema V1 to V2.
    V1 -> V2 Change: Adds the `hostname` column to the `instances` table.
    """
    print("[DB Migration] Starting migration from V1 to V2...")
    
    db_path = DATABASE_URL.split("///")[1]
    backup_path = f"{db_path}.bak.v1_to_v2.{int(time.time())}"
    
    # LOT3 (M6): WAL checkpoint before copying (see _backup_database_before_step).
    _backup_database_before_step(db_path, backup_path, "1.")

    # --- Old Schema (V1) ---
    class _BaseV1(DeclarativeBase):
        pass

    class Instance_v1(_BaseV1):
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

    # --- New Schema (V2) ---
    class _BaseV2(DeclarativeBase):
        pass

    class Instance_v2(_BaseV2):
        __tablename__ = "instances"
        id = Column(Integer, primary_key=True, index=True)
        name = Column(String, unique=True, index=True, nullable=False)
        base_blueprint = Column(String, nullable=False)
        gpu_ids = Column(String, nullable=True)
        autostart = Column(Boolean, default=False, nullable=False)
        persistent_mode = Column(Boolean, default=False, nullable=False)
        hostname = Column(String, nullable=True)
        status = Column(String, default="stopped", nullable=False)
        pid = Column(Integer, nullable=True)
        port = Column(Integer, nullable=True)
        persistent_port = Column(Integer, nullable=True)
        persistent_display = Column(Integer, nullable=True)
    
    class AikoreMeta_v2(_BaseV2):
        __tablename__ = "aikore_meta"
        key = Column(String, primary_key=True, index=True)
        value = Column(String, nullable=False)

    _BaseV2.metadata.create_all(bind=temp_new_engine)
    NewSession = sessionmaker(autocommit=False, autoflush=False, bind=temp_new_engine)
    
    try:
        print("[DB Migration] 3. Transferring data...")
        with OldSession() as old_db, NewSession() as new_db:
            old_instances = old_db.query(Instance_v1).all()
            for old_inst in old_instances:
                new_inst = Instance_v2(
                    id=old_inst.id, name=old_inst.name, base_blueprint=old_inst.base_blueprint,
                    gpu_ids=old_inst.gpu_ids, autostart=old_inst.autostart,
                    persistent_mode=old_inst.persistent_mode, hostname=None,
                    status="stopped", pid=None,
                    port=old_inst.port, persistent_port=old_inst.persistent_port,
                    persistent_display=old_inst.persistent_display,
                )
                new_db.add(new_inst)
            new_db.add(AikoreMeta_v2(key="schema_version", value="2"))
            new_db.commit()
            print(f"[DB Migration]    - Transferred {len(old_instances)} records. Commit successful.")

        print("[DB Migration] 4. Verifying data integrity...")
        with OldSession() as old_db_verify, NewSession() as new_db_verify:
            old_count = old_db_verify.query(Instance_v1).count()
            new_count = new_db_verify.query(Instance_v2).count()
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
        # LOT3 (H2): os.remove()+recreate replaced the DB file underneath the
        # global engine; its QueuePool (WAL active — session.py) still holds a
        # connection to the GHOST inode. Dispose the pool so nothing reuses a
        # stale handle; new connections re-open the real file (the WAL pragma
        # listener re-applies on fresh connections).
        _global_engine.dispose()
        
    print("[DB Migration] 5. Migration from V1 to V2 complete.")
    # LOT3 (M6): no sys.exit here anymore — run_db_migration() chains all steps
    # in a single run, so an upgrade from v1 no longer requires 5 restarts.

def _perform_v2_to_v3_migration():
    """
    Migrates the database from schema V2 to V3.
    V2 -> V3 Change: Adds the `use_custom_hostname` column to the `instances` table.
    """
    print("[DB Migration] Starting migration from V2 to V3...")
    
    db_path = DATABASE_URL.split("///")[1]
    backup_path = f"{db_path}.bak.v2_to_v3.{int(time.time())}"
    
    # LOT3 (M6): WAL checkpoint before copy (see _backup_database_before_step).
    _backup_database_before_step(db_path, backup_path, "1.")

    # --- Old Schema (V2) ---
    class _BaseV2_Old(DeclarativeBase):
        pass

    class Instance_v2(_BaseV2_Old):
        __tablename__ = "instances"
        id = Column(Integer, primary_key=True, index=True)
        name = Column(String, unique=True, index=True, nullable=False)
        base_blueprint = Column(String, nullable=False)
        gpu_ids = Column(String, nullable=True)
        autostart = Column(Boolean, default=False, nullable=False)
        persistent_mode = Column(Boolean, default=False, nullable=False)
        hostname = Column(String, nullable=True)
        status = Column(String, default="stopped", nullable=False)
        pid = Column(Integer, nullable=True)
        port = Column(Integer, nullable=True)
        persistent_port = Column(Integer, nullable=True)
        persistent_display = Column(Integer, nullable=True)

    old_engine = create_engine(f"sqlite:///{backup_path}")
    OldSession = sessionmaker(autocommit=False, autoflush=False, bind=old_engine)
    
    print("[DB Migration] 2. Creating new empty database with V3 schema...")
    if os.path.exists(db_path):
        os.remove(db_path)
    
    temp_new_engine = create_engine(DATABASE_URL, connect_args=connect_args)

    # --- New Schema (V3) ---
    class _BaseV3(DeclarativeBase):
        pass

    class Instance_v3(_BaseV3):
        __tablename__ = "instances"
        id = Column(Integer, primary_key=True, index=True)
        name = Column(String, unique=True, index=True, nullable=False)
        base_blueprint = Column(String, nullable=False)
        gpu_ids = Column(String, nullable=True)
        autostart = Column(Boolean, default=False, nullable=False)
        persistent_mode = Column(Boolean, default=False, nullable=False)
        hostname = Column(String, nullable=True)
        use_custom_hostname = Column(Boolean, default=False, nullable=False, server_default='0')
        status = Column(String, default="stopped", nullable=False)
        pid = Column(Integer, nullable=True)
        port = Column(Integer, nullable=True)
        persistent_port = Column(Integer, nullable=True)
        persistent_display = Column(Integer, nullable=True)

    class AikoreMeta_v3(_BaseV3):
        __tablename__ = "aikore_meta"
        key = Column(String, primary_key=True, index=True)
        value = Column(String, nullable=False)

    _BaseV3.metadata.create_all(bind=temp_new_engine)
    NewSession = sessionmaker(autocommit=False, autoflush=False, bind=temp_new_engine)
    
    try:
        print("[DB Migration] 3. Transferring data...")
        with OldSession() as old_db, NewSession() as new_db:
            old_instances = old_db.query(Instance_v2).all()
            for old_inst in old_instances:
                new_inst = Instance_v3(
                    id=old_inst.id, name=old_inst.name, base_blueprint=old_inst.base_blueprint,
                    gpu_ids=old_inst.gpu_ids, autostart=old_inst.autostart,
                    persistent_mode=old_inst.persistent_mode, hostname=old_inst.hostname,
                    use_custom_hostname=False, # New field default
                    status="stopped", pid=None,
                    port=old_inst.port, persistent_port=old_inst.persistent_port,
                    persistent_display=old_inst.persistent_display,
                )
                new_db.add(new_inst)
            new_db.add(AikoreMeta_v3(key="schema_version", value="3"))
            new_db.commit()
            print(f"[DB Migration]    - Transferred {len(old_instances)} records. Commit successful.")

        print("[DB Migration] 4. Verifying data integrity...")
        with OldSession() as old_db_verify, NewSession() as new_db_verify:
            old_count = old_db_verify.query(Instance_v2).count()
            new_count = new_db_verify.query(Instance_v3).count()
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
        # LOT3 (H2): same ghost-inode cleanup as the v1->v2 step.
        _global_engine.dispose()
        
    print("[DB Migration] 5. Migration from V2 to V3 complete.")
    # LOT3 (M6): chained by run_db_migration(), see note above.

def _perform_v3_to_v4_migration():
    """
    Migrates the database from schema V3 to V4.
    V3 -> V4 Change: Adds the `output_path` column to the `instances` table.
    """
    print("[DB Migration] Starting migration from V3 to V4...")
    
    db_path = DATABASE_URL.split("///")[1]
    backup_path = f"{db_path}.bak.v3_to_v4.{int(time.time())}"
    
    # LOT3 (M6): WAL checkpoint before copy (see _backup_database_before_step).
    _backup_database_before_step(db_path, backup_path, "1.")

    # --- Old Schema (V3) ---
    class _BaseV3_Old(DeclarativeBase):
        pass

    class Instance_v3(_BaseV3_Old):
        __tablename__ = "instances"
        id = Column(Integer, primary_key=True, index=True)
        name = Column(String, unique=True, index=True, nullable=False)
        base_blueprint = Column(String, nullable=False)
        gpu_ids = Column(String, nullable=True)
        autostart = Column(Boolean, default=False, nullable=False)
        persistent_mode = Column(Boolean, default=False, nullable=False)
        hostname = Column(String, nullable=True)
        use_custom_hostname = Column(Boolean, default=False, nullable=False, server_default='0')
        status = Column(String, default="stopped", nullable=False)
        pid = Column(Integer, nullable=True)
        port = Column(Integer, nullable=True)
        persistent_port = Column(Integer, nullable=True)
        persistent_display = Column(Integer, nullable=True)

    old_engine = create_engine(f"sqlite:///{backup_path}")
    OldSession = sessionmaker(autocommit=False, autoflush=False, bind=old_engine)
    
    print("[DB Migration] 2. Creating new empty database with V4 schema...")
    if os.path.exists(db_path):
        os.remove(db_path)
    
    # The main `models` module now represents the V4 schema
    temp_new_engine = create_engine(DATABASE_URL, connect_args=connect_args)
    models.Base.metadata.create_all(bind=temp_new_engine)
    NewSession = sessionmaker(autocommit=False, autoflush=False, bind=temp_new_engine)
    
    try:
        print("[DB Migration] 3. Transferring data...")
        with OldSession() as old_db, NewSession() as new_db:
            old_instances = old_db.query(Instance_v3).all()
            for old_inst in old_instances:
                new_inst = models.Instance(
                    id=old_inst.id, name=old_inst.name, base_blueprint=old_inst.base_blueprint,
                    gpu_ids=old_inst.gpu_ids, autostart=old_inst.autostart,
                    persistent_mode=old_inst.persistent_mode, hostname=old_inst.hostname,
                    use_custom_hostname=old_inst.use_custom_hostname,
                    output_path=None, # New field default
                    status="stopped", pid=None,
                    port=old_inst.port, persistent_port=old_inst.persistent_port,
                    persistent_display=old_inst.persistent_display,
                )
                new_db.add(new_inst)
            new_db.add(models.AikoreMeta(key="schema_version", value="4"))
            new_db.commit()
            print(f"[DB Migration]    - Transferred {len(old_instances)} records. Commit successful.")

        print("[DB Migration] 4. Verifying data integrity...")
        with OldSession() as old_db_verify, NewSession() as new_db_verify:
            old_count = old_db_verify.query(Instance_v3).count()
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
        # LOT3 (H2): last of the three destructive os.remove+recreate steps.
        _global_engine.dispose()
        
    print("[DB Migration] 5. Migration from V3 to V4 complete.")
    # LOT3 (M6): chained by run_db_migration(), see note above.

def _perform_v4_to_v5_migration():
    """
    Migrates the database from schema V4 to V5.
    V4 -> V5 Change: Adds the `parent_instance_id` column to the `instances` table.
    This migration uses a direct ALTER TABLE statement for simplicity.
    """
    print("[DB Migration] Starting migration from V4 to V5...")
    engine = create_engine(DATABASE_URL, connect_args=connect_args)
    
    # LOT3 (M6): back up the database BEFORE the ALTER TABLE (after a WAL
    # checkpoint — see _backup_database_before_step), like the rebuild-based
    # v1->v4 steps already do. An ALTER on SQLite is safer than a
    # full rebuild but a backup still turns any mid-flight failure into a
    # restore instead of data loss.
    db_path = DATABASE_URL.split("///")[1]
    backup_path = f"{db_path}.bak.v4_to_v5.{int(time.time())}"
    _backup_database_before_step(db_path, backup_path, "0.")
    
    try:
        with engine.connect() as connection:
            with connection.begin():
                inspector = inspect(engine)
                columns = [col['name'] for col in inspector.get_columns('instances')]
                
                if 'parent_instance_id' not in columns:
                    print("[DB Migration] 1. Adding column 'parent_instance_id' to 'instances' table...")
                    connection.execute(text('ALTER TABLE instances ADD COLUMN parent_instance_id INTEGER'))
                    # Add index separately for compatibility
                    connection.execute(text('CREATE INDEX ix_instances_parent_instance_id ON instances (parent_instance_id)'))
                else:
                    print("[DB Migration] 1. Column 'parent_instance_id' already exists.")

                print("[DB Migration] 2. Updating schema version to 5...")
                # Use a session to update the meta table
                with Session(bind=connection) as db:
                    version_entry = db.query(models.AikoreMeta).filter_by(key="schema_version").first()
                    if version_entry:
                        version_entry.value = "5"
                    else:
                        db.add(models.AikoreMeta(key="schema_version", value="5"))
                    db.commit()

        print("[DB Migration] Migration from V4 to V5 complete.")
    except Exception as e:
        print(f"[DB Migration] FATAL: Error during V4 to V5 migration: {e}", file=sys.stderr)
        print(f"[DB Migration] A pre-migration backup exists at: {backup_path}", file=sys.stderr)
        print("[DB Migration] Manual inspection of the database is required.", file=sys.stderr)
        sys.exit(1)
        
def _perform_v5_to_v6_migration():
    """
    Migrates the database from schema V5 to V6.
    V5 -> V6 Change: Adds python_version, cuda_version, torch_version columns.
    """
    print("[DB Migration] Starting migration from V5 to V6...")
    engine = create_engine(DATABASE_URL, connect_args=connect_args)
    
    # LOT3 (M6): same pre-ALTER backup as v4->v5 (WAL checkpoint before copy).
    db_path = DATABASE_URL.split("///")[1]
    backup_path = f"{db_path}.bak.v5_to_v6.{int(time.time())}"
    _backup_database_before_step(db_path, backup_path, "0.")
    
    try:
        with engine.connect() as connection:
            with connection.begin():
                inspector = inspect(engine)
                columns = [col['name'] for col in inspector.get_columns('instances')]
                
                print("[DB Migration] 1. Adding custom version columns to 'instances' table...")
                if 'python_version' not in columns:
                    connection.execute(text('ALTER TABLE instances ADD COLUMN python_version VARCHAR'))
                if 'cuda_version' not in columns:
                    connection.execute(text('ALTER TABLE instances ADD COLUMN cuda_version VARCHAR'))
                if 'torch_version' not in columns:
                    connection.execute(text('ALTER TABLE instances ADD COLUMN torch_version VARCHAR'))
                    
                print("[DB Migration] 2. Updating schema version to 6...")
                with Session(bind=connection) as db:
                    version_entry = db.query(models.AikoreMeta).filter_by(key="schema_version").first()
                    if version_entry:
                        version_entry.value = "6"
                    else:
                        db.add(models.AikoreMeta(key="schema_version", value="6"))
                    db.commit()

        print("[DB Migration] Migration from V5 to V6 complete.")
    except Exception as e:
        print(f"[DB Migration] FATAL: Error during V5 to V6 migration: {e}", file=sys.stderr)
        print(f"[DB Migration] A pre-migration backup exists at: {backup_path}", file=sys.stderr)
        print("[DB Migration] Manual inspection of the database is required.", file=sys.stderr)
        sys.exit(1)

# LOT3 (M6): explicit migration-step table, executed SEQUENTIALLY by
# run_db_migration() so an upgrade from v1 to v6 completes in a single run.
_MIGRATION_STEPS = {
    1: _perform_v1_to_v2_migration,
    2: _perform_v2_to_v3_migration,
    3: _perform_v3_to_v4_migration,
    4: _perform_v4_to_v5_migration,
    5: _perform_v5_to_v6_migration,
}

def run_db_migration():
    # This is a hack to get the correct engine for the migration check
    engine = create_engine(DATABASE_URL, connect_args=connect_args)
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

    if current_version > EXPECTED_DB_VERSION:
        print(f"[DB Migration] WARNING: Database version ({current_version}) is newer than the application's expected version.", file=sys.stderr)
        return

    # LOT3 (H2): the session used to read the version is CLOSED before any
    # step runs — steps delete/recreate the DB file (v1..v4) or ALTER it, and
    # an open session/pooled connection must not ride across those operations.
    # The version is re-read with a FRESH session after every step.

    # LOT3 (M6): run ALL pending steps in one go instead of exiting after a
    # single step (the old behaviour required up to 5 restarts for a
    # v1 -> v6 upgrade). Each step keeps its own backup + failure abort.
    while current_version < EXPECTED_DB_VERSION:
        step = _MIGRATION_STEPS.get(current_version)
        if step is None:
            print(f"[DB Migration] FATAL: Unsupported migration path from v{current_version} to v{EXPECTED_DB_VERSION}.", file=sys.stderr)
            sys.exit(1)

        print(f"[DB Migration] Applying step v{current_version} -> v{current_version + 1}...")
        before_version = current_version
        step()

        # Re-read the version with a FRESH session (the previous one is
        # closed) to confirm the step actually advanced the schema; guards
        # against a silently no-op step looping forever.
        with SessionLocal() as verify_db:
            current_version = _get_db_version(verify_db)
        if current_version <= before_version:
            print(
                f"[DB Migration] FATAL: step from v{before_version} did not advance "
                f"the schema version (still v{current_version}). Aborting.",
                file=sys.stderr,
            )
            sys.exit(1)
        print(f"[DB Migration] Now at schema version {current_version}.")

        print(f"[DB Migration] Database is up to date at schema version {current_version}.")