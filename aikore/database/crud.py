from sqlalchemy.orm import Session
import os
import shutil
import subprocess
import traceback
from pathlib import Path
from . import models
from ..schemas import instance as schemas
from ..core.process_manager import INSTANCES_DIR, BLUEPRINTS_DIR, CUSTOM_BLUEPRINTS_DIR
from ..core.blueprint_parser import get_blueprint_venv_path
from ..database.session import SessionLocal
import stat

# --- LOT3 shared helpers (audit M10 / M7) --------------------------------
# Single implementations live in aikore/core/filesystem.py and
# aikore/core/metadata_parser.py. The try/except keeps THIS module importable
# inside stripped-down unit-test harnesses that assemble a partial package
# tree; each fallback below replicates the FIXED behaviour locally.
try:
    from ..core.filesystem import rm_error_handler as _shared_rm_error_handler
except ImportError:  # pragma: no cover - partial test harness only
    _shared_rm_error_handler = None

try:
    from ..core.metadata_parser import (
        normalize_venv_dir_name as _shared_normalize_venv_dir_name,
    )
except ImportError:  # pragma: no cover - partial test harness only
    _shared_normalize_venv_dir_name = None

def _on_rm_error(func, path, exc):
    """
    Error handler for shutil.rmtree (Python 3.12+ signature).
    LOT3 (M10): canonical implementation in aikore/core/filesystem.py
    (logging ERROR instead of silent prints); kept here as a thin delegation
    for backward-compatible monkeypatching.
    """
    if _shared_rm_error_handler is not None:
        _shared_rm_error_handler(func, path, exc)
        return
    # Fallback (harness only): same logic, legacy print.
    try:
        if not os.access(path, os.W_OK):
            os.chmod(path, stat.S_IWUSR)
            func(path)
        else:
            raise exc
    except Exception as e:
        print(f"[Deletion-Error] Failed to force delete '{path}': {e}")

def _normalize_venv_dir_name(venv_path_str) -> str:
    """
    LOT3 (M7): normalizes a blueprint 'venv_path' into a bare directory name.

    Fixes './my.env' -> 'myenv' (the historical normpath().replace('.','')
    destroyed EVERY dot, so ignore_patterns no longer matched and whole
    multi-GB venvs were copied). Dequotes '"./env"' -> 'env' too.
    """
    if _shared_normalize_venv_dir_name is not None:
        return _shared_normalize_venv_dir_name(venv_path_str)
    # Fallback (harness only): same semantics as metadata_parser.normalize_venv_dir_name.
    value = str(venv_path_str or "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1]
    value = value.strip()
    if not value:
        return "env"
    if "\x00" in value or os.path.isabs(value) or ".." in value.replace("\\", "/").split("/"):
        raise ValueError(f"Invalid venv_path {venv_path_str!r}")
    base = os.path.basename(os.path.normpath(value))
    if not base or base in (".", ".."):
        raise ValueError(f"Invalid venv_path {venv_path_str!r}")
    return base

def _ensure_dir_within(path_str: str, root_str: str, label: str):
    """SECURITY (audit C-4): defense in depth against path traversal.
    Raises ValueError if `path_str` does not resolve STRICTLY inside `root_str`."""
    root = Path(root_str).resolve()
    resolved = Path(path_str).resolve()
    if resolved == root or not resolved.is_relative_to(root):
        raise ValueError(
            f"Refusing {label} '{path_str}': resolved path escapes '{root_str}'."
        )

def get_instance_by_name(db: Session, name: str):
    """
    Retrieve a single instance from the database by its unique name.
    """
    return db.query(models.Instance).filter(models.Instance.name == name).first()

def get_instances(db: Session, skip: int = 0, limit: int = 100):
    """
    Retrieve a list of all instances from the database, with pagination.
    """
    return db.query(models.Instance).offset(skip).limit(limit).all()

def get_used_ports(db: Session, exclude_instance_id: int | None = None):
    """
    LOT3 (#13/M1): targeted projection of the allocated ports.

    Returns (id, port, persistent_port) rows WITHOUT pagination so no port can
    be missed when the instance count grows past an arbitrary LIMIT (the old
    `get_instances(limit=1000)` callers reported false-free ports beyond 1000).
    Tolerates db=None (stripped-down unit-test harnesses) by returning [].
    """
    if db is None:
        return []
    query = db.query(models.Instance.id, models.Instance.port, models.Instance.persistent_port)
    if exclude_instance_id is not None:
        query = query.filter(models.Instance.id != exclude_instance_id)
    return query.all()

def get_autostart_instances(db: Session):
    """
    Retrieve all instances that are marked for autostart.
    """
    return db.query(models.Instance).filter(models.Instance.autostart == True).all()

def create_instance(
    db: Session, 
    instance: schemas.InstanceCreate,
    port: int,
    persistent_port: int | None,
    persistent_display: int | None
):
    """
    Create a new instance record in the database and prepare its directory and files.
    """
    instance_conf_dir = os.path.join(INSTANCES_DIR, instance.name)

    # --- SECURITY (audit C-4): the target directory must stay under INSTANCES_DIR,
    # even if an unvalidated name somehow reached this layer.
    _ensure_dir_within(instance_conf_dir, INSTANCES_DIR, "instance directory")

    # Filesystem operations
    # LOT3 (#15): track whether WE created the directory, so a failed DB commit
    # can roll it back without ever deleting pre-existing user data.
    created_conf_dir = False
    if instance.source_instance_id:
        # This is a copy operation
        source_instance = get_instance(db, instance_id=instance.source_instance_id)
        if not source_instance:
            raise FileNotFoundError(f"Source instance with ID {instance.source_instance_id} not found.")
        
        source_path = os.path.join(INSTANCES_DIR, source_instance.name)
        _ensure_dir_within(source_path, INSTANCES_DIR, "source instance directory")
        if not os.path.isdir(source_path):
            raise FileNotFoundError(f"Source instance directory not found at {source_path}.")

        # Copy the directory, ignoring the virtual environment
        # FIX: symlinks=True prevents copying the content of huge model folders.
        shutil.copytree(source_path, instance_conf_dir, ignore=shutil.ignore_patterns('env'), symlinks=True)
        created_conf_dir = True  # copytree refuses an existing target

    else:
        # This is a standard creation from a blueprint
        if not os.path.isdir(instance_conf_dir):
            os.makedirs(instance_conf_dir, exist_ok=True)
            created_conf_dir = True
        
        # Find the correct blueprint file path
        custom_blueprint_path = os.path.join(CUSTOM_BLUEPRINTS_DIR, instance.base_blueprint)
        stock_blueprint_path = os.path.join(BLUEPRINTS_DIR, instance.base_blueprint)
        
        if os.path.exists(custom_blueprint_path):
            blueprint_file_path = custom_blueprint_path
        elif os.path.exists(stock_blueprint_path):
            blueprint_file_path = stock_blueprint_path
        else:
            raise FileNotFoundError(f"Blueprint '{instance.base_blueprint}' not found.")
            
        # Copy the blueprint to the instance's launch.sh
        shutil.copy(blueprint_file_path, os.path.join(instance_conf_dir, "launch.sh"))

    # Database operation
    instance_data = instance.model_dump()
    instance_data.pop('port', None)
    instance_data.pop('source_instance_id', None) # Don't save this to the DB
    db_instance = models.Instance(
        **instance_data,
        port=port,
        persistent_port=persistent_port,
        persistent_display=persistent_display
    )
    db.add(db_instance)
    try:
        db.commit()
    except Exception:
        # LOT3 (#15): the filesystem work happened BEFORE the commit; if it
        # fails (e.g. IntegrityError on the unique name), remove the directory
        # we just created instead of leaving an orphan on disk.
        db.rollback()
        if created_conf_dir and os.path.isdir(instance_conf_dir):
            try:
                shutil.rmtree(instance_conf_dir, ignore_errors=True)
                print(f"[CRUD] Rolled back instance directory '{instance_conf_dir}' after failed commit.")
            except Exception as cleanup_err:
                print(f"[CRUD-ERROR] Could not clean up '{instance_conf_dir}' after failed commit: {cleanup_err}")
        raise
    db.refresh(db_instance)
    return db_instance

def create_copy_placeholder(db: Session, source_instance_id: int, new_name: str):
    """
    STEP 1: Creates the DB entry immediately with 'installing' status.
    """
    # 1. Validation
    if get_instance_by_name(db, name=new_name):
        raise ValueError(f"Instance with name '{new_name}' already exists.")
    
    source_instance = get_instance(db, instance_id=source_instance_id)
    if not source_instance:
        raise ValueError(f"Source instance with ID {source_instance_id} not found.")

    # 2. Create Database Entry immediately
    # explicitly set ports to None so they get allocated on first start (Self-Healing)
    db_instance = models.Instance(
        name=new_name,
        base_blueprint=source_instance.base_blueprint,
        gpu_ids=source_instance.gpu_ids,
        autostart=source_instance.autostart,
        persistent_mode=source_instance.persistent_mode,
        output_path=source_instance.output_path,
        hostname=source_instance.hostname,
        use_custom_hostname=False,
        # --- NEW: Copy custom versions ---
        python_version=source_instance.python_version,
        cuda_version=source_instance.cuda_version,
        torch_version=source_instance.torch_version,
        status="installing", # <--- NEW STATUS indicating background work
        port=None,
        persistent_port=None,
        persistent_display=None
    )
    db.add(db_instance)
    db.commit()
    db.refresh(db_instance)
    
    return db_instance

def process_background_copy(new_instance_id: int, source_instance_id: int):
    """
    STEP 2: Heavy lifting (Filesystem & Conda) running in background.
    Creates its own DB session to avoid DetachedInstanceError.
    """
    print(f"[Background] Starting copy process for instance ID {new_instance_id}...")
    
    with SessionLocal() as db:
        new_instance = get_instance(db, new_instance_id)
        source_instance = get_instance(db, source_instance_id)
        
        if not new_instance or not source_instance:
            print("[Background] Error: Instance record missing.")
            return

        source_dir = os.path.join(INSTANCES_DIR, source_instance.name)
        clone_dir = os.path.join(INSTANCES_DIR, new_instance.name)

        # --- SECURITY (audit C-4): refuse any path resolving outside INSTANCES_DIR
        # BEFORE touching the filesystem (checked here so the exception-based
        # cleanup below can never rmtree a path outside the storage area).
        try:
            _ensure_dir_within(source_dir, INSTANCES_DIR, "source instance directory")
            _ensure_dir_within(clone_dir, INSTANCES_DIR, "clone instance directory")
        except ValueError as e:
            print(f"[Background-CRITICAL] Path traversal blocked during copy: {e}")
            new_instance.status = "error"
            db.commit()
            return
        
        try:
            # 1. Get venv path info
            venv_path_str = get_blueprint_venv_path(source_instance.base_blueprint)
            # LOT3 (M7): shared normalization — keeps dots ('./my.env' ->
            # 'my.env') and dequotes ('"./env"' -> 'env'), so ignore_patterns
            # matches again and multi-GB venvs are no longer copied.
            venv_dir_name = _normalize_venv_dir_name(venv_path_str)

            # 2. Filesystem Copy (Symlinks preserved!)
            print(f"[Background] Copying files from {source_dir} to {clone_dir}...")
            if os.path.exists(clone_dir):
                 shutil.rmtree(clone_dir, onexc=_on_rm_error) # Safety cleanup if retrying
                 
            shutil.copytree(
                source_dir, 
                clone_dir, 
                ignore=shutil.ignore_patterns(venv_dir_name), 
                symlinks=True
            )

            # 3. Clone Conda Environment
            source_env_path = os.path.join(source_dir, venv_dir_name)
            clone_env_path = os.path.join(clone_dir, venv_dir_name)

            if os.path.isdir(source_env_path):
                print(f"[Background] Cloning Conda environment...")
                subprocess.run(["/home/abc/miniconda3/bin/conda", "create", "--prefix", clone_env_path, "--clone", source_env_path, "-y"],
                    capture_output=True, text=True, check=True
                )

            # 4. Update launch.sh
            launch_script_path = os.path.join(clone_dir, "launch.sh")
            if os.path.exists(launch_script_path):
                with open(launch_script_path, 'r') as f:
                    script_content = f.read()
                
                old_base_path = f"/config/instances/{source_instance.name}"
                new_base_path = f"/config/instances/{new_instance.name}"
                updated_content = script_content.replace(old_base_path, new_base_path)
                
                with open(launch_script_path, 'w') as f:
                    f.write(updated_content)

            # SUCCESS: Update status to 'stopped'
            # LOT3 (M8): re-fetch the row instead of committing on the stale
            # ORM object — the instance may have been deleted or altered while
            # the long copy was running.
            fresh = get_instance(db, new_instance_id)
            if fresh is None:
                print(f"[Background] Instance row {new_instance_id} disappeared during copy "
                      f"(deleted concurrently). Leaving files in place, no status write.")
                return
            if fresh.status != "installing":
                print(f"[Background] Instance {new_instance_id} left 'installing' during copy "
                      f"(now '{fresh.status}'); not overwriting its status.")
                return
            fresh.status = "stopped"
            db.commit()
            print(f"[Background] Clone successful for '{new_instance.name}'.")

        except Exception as e:
            print(f"[Background] CRITICAL ERROR cloning instance: {e}")
            traceback.print_exc()
            
            # FAILURE: Update status to 'error'
            # LOT3 (M8): same stale-object guard on the failure path.
            fresh = get_instance(db, new_instance_id)
            if fresh is not None and fresh.status == "installing":
                fresh.status = "error"
                db.commit()
            elif fresh is None:
                print(f"[Background] Instance row {new_instance_id} already deleted; skipping error-status write.")
            
            # Cleanup partial files
            if os.path.isdir(clone_dir):
                shutil.rmtree(clone_dir, onexc=_on_rm_error)

def instantiate_instance(db: Session, source_instance_id: int, new_name: str):
    """
    Creates a new 'satellite' instance linked to a parent.
    It shares the parent's environment and script but has its own DB entry.
    """
    # 1. Validation
    if get_instance_by_name(db, name=new_name):
        raise ValueError(f"Instance with name '{new_name}' already exists.")
    
    source_instance = get_instance(db, instance_id=source_instance_id)
    if not source_instance:
        raise ValueError(f"Source instance with ID {source_instance_id} not found.")

    # Cannot instantiate a satellite from another satellite
    if source_instance.parent_instance_id is not None:
        raise ValueError("Cannot create an instance from another satellite instance. Please use the original parent.")

    # 2. Filesystem
    # UPDATED: We do NOT create the directory here eagerly.
    # The process_manager will create it on first launch to store logs/pid.
    # This keeps the filesystem clean until the instance is actually used.
    
    # 3. Database Entry
    # Explicitly clear ports so they get allocated on start
    db_instance = models.Instance(
        name=new_name,
        parent_instance_id=source_instance.id,
        base_blueprint=source_instance.base_blueprint, # Copied for reference
        gpu_ids=source_instance.gpu_ids,
        autostart=False, # Satellites should not autostart
        persistent_mode=source_instance.persistent_mode,
        output_path=source_instance.output_path,
        hostname=None, # Satellites get their own hostname/port when started
        use_custom_hostname=False,
        # --- NEW: Copy custom versions ---
        python_version=source_instance.python_version,
        cuda_version=source_instance.cuda_version,
        torch_version=source_instance.torch_version,
        status="stopped",
        port=None,
        persistent_port=None,
        persistent_display=None
    )
    db.add(db_instance)
    db.commit()
    db.refresh(db_instance)

    return db_instance

def update_instance_status(
    db: Session,
    instance_id: int,
    status: str,
    pid: int | None = None,
    port: int | None = None,
    persistent_port: int | None = None,
    persistent_display: int | None = None
):
    """
    Update the status, PID, port, and VNC details of an instance.
    NOTE: This is legacy and no longer used by the primary start/stop flow.
    """
    db_instance = db.query(models.Instance).filter(models.Instance.id == instance_id).first()
    if db_instance:
        db_instance.status = status
        db_instance.pid = pid
        db_instance.port = port
        db_instance.persistent_port = persistent_port
        db_instance.persistent_display = persistent_display
        db.commit()
        db.refresh(db_instance)
    return db_instance

# NEW: Function to update an instance's configurable fields
def update_instance(db: Session, instance_id: int, instance_update: schemas.InstanceUpdate):
    """
    Update an instance's details in the database.
    """
    db_instance = db.query(models.Instance).filter(models.Instance.id == instance_id).first()
    if db_instance:
        update_data = instance_update.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(db_instance, key, value)
        db.commit()
        db.refresh(db_instance)
    return db_instance

def get_instance(db: Session, instance_id: int):
    """
    Retrieve a single instance by its ID.
    """
    return db.query(models.Instance).filter(models.Instance.id == instance_id).first()

def delete_instance(db: Session, instance_id: int):
    """
    Delete an instance from the database by its ID.
    """
    db_instance = db.query(models.Instance).filter(models.Instance.id == instance_id).first()
    if db_instance:
        db.delete(db_instance)
        db.commit()
    return db_instance