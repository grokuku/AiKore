import os
import sys
import shutil
import time
from sqlalchemy import create_engine, inspect, Column, Integer, String, Boolean
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base

from . import models
from .session import SessionLocal, DATABASE_URL, connect_args

# --- AUTOMATED DATABASE MIGRATION LOGIC ---

EXPECTED_DB_VERSION = 4

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
    backup_path = f"{db_path}.bak.v1_to_v2.{int(time.time())}"
    
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
    # Create tables for a temporary V2 schema
    Base_v2 = declarative_base()
    class Instance_v2(Base_v2):
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
    
    class AikoreMeta_v2(Base_v2):
        __tablename__ = "aikore_meta"
        key = Column(String, primary_key=True, index=True)
        value = Column(String, nullable=False)

    Base_v2.metadata.create_all(bind=temp_new_engine)
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
        
    print("[DB Migration] 5. Migration from V1 to V2 complete. Please restart the application.")
    sys.exit(0)

def _perform_v2_to_v3_migration():
    """
    Migrates the database from schema V2 to V3.
    V2 -> V3 Change: Adds the `use_custom_hostname` column to the `instances` table.
    """
    print("[DB Migration] Starting migration from V2 to V3...")
    
    db_path = DATABASE_URL.split("///")[1]
    backup_path = f"{db_path}.bak.v2_to_v3.{int(time.time())}"
    
    print(f"[DB Migration] 1. Backing up current database to: {backup_path}")
    try:
        shutil.copy2(db_path, backup_path)
    except Exception as e:
        print(f"[DB Migration] FATAL: Could not back up database. Aborting. Error: {e}", file=sys.stderr)
        sys.exit(1)
        
    Base_v2 = declarative_base()
    class Instance_v2(Base_v2):
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
    
    # We use the main `models` module here because it represents the target schema (V3)
    # at the time this migration was written.
    temp_new_engine = create_engine(DATABASE_URL, connect_args=connect_args)
    
    Base_v3 = declarative_base()
    class Instance_v3(Base_v3):
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

    class AikoreMeta_v3(Base_v3):
        __tablename__ = "aikore_meta"
        key = Column(String, primary_key=True, index=True)
        value = Column(String, nullable=False)

    Base_v3.metadata.create_all(bind=temp_new_engine)
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
        
    print("[DB Migration] 5. Migration from V2 to V3 complete. Please restart the application.")
    sys.exit(0)

def _perform_v3_to_v4_migration():
    """
    Migrates the database from schema V3 to V4.
    V3 -> V4 Change: Adds the `output_path` column to the `instances` table.
    """
    print("[DB Migration] Starting migration from V3 to V4...")
    
    db_path = DATABASE_URL.split("///")[1]
    backup_path = f"{db_path}.bak.v3_to_v4.{int(time.time())}"
    
    print(f"[DB Migration] 1. Backing up current database to: {backup_path}")
    try:
        shutil.copy2(db_path, backup_path)
    except Exception as e:
        print(f"[DB Migration] FATAL: Could not back up database. Aborting. Error: {e}", file=sys.stderr)
        sys.exit(1)
        
    Base_v3 = declarative_base()
    class Instance_v3(Base_v3):
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
        
    print("[DB Migration] 5. Migration from V3 to V4 complete. Please restart the application.")
    sys.exit(0)


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
    
        if current_version < EXPECTED_DB_VERSION:
            if current_version == 1:
                _perform_v1_to_v2_migration()
            elif current_version == 2:
                _perform_v2_to_v3_migration()
            elif current_version == 3:
                _perform_v3_to_v4_migration()
            else:
                print(f"[DB Migration] FATAL: Unsupported migration path from v{current_version} to v{EXPECTED_DB_VERSION}.", file=sys.stderr)
                sys.exit(1)
        elif current_version > EXPECTED_DB_VERSION:
            print(f"[DB Migration] WARNING: Database version ({current_version}) is newer than the application's expected version.", file=sys.stderr)
