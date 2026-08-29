from fastapi import APIRouter, Depends, HTTPException, Body, WebSocket, WebSocketDisconnect, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import List
import os
import shutil
import stat  # NEW: Needed for permission handling
import asyncio
import psutil
import json
import glob 
import re # NEW: For regex
import threading
import time
import traceback
from pathlib import Path
from pydantic import BaseModel

from ..database import crud, models
from ..database.session import SessionLocal, get_db
from ..schemas import instance as schemas
from ..core import process_manager
from ..core.process_manager import INSTANCES_DIR, BLUEPRINTS_DIR, CUSTOM_BLUEPRINTS_DIR, _find_free_port, _find_free_display

# LOT3 (M10): shared rmtree error handler (logging ERROR). The guarded import
# keeps this module loadable in stripped-down unit-test harnesses.
try:
    from ..core.filesystem import rm_error_handler as _shared_rm_error_handler
except ImportError:  # pragma: no cover - partial test harness only
    _shared_rm_error_handler = None

# --- CONSTANTS ---
GLOBAL_WHEELS_DIR = os.path.join(INSTANCES_DIR, ".wheels")

# LOT3 (M1): serializes port/display allocation across concurrent API threads,
# closing the read-DB-then-insert TOCTOU window in _allocate_ports.
_port_allocation_lock = threading.Lock()

# LOT3 (M8): per-instance lifecycle locks so start/delete cannot interleave
# (a start racing a delete used to resurrect an instance mid-purge).
_lifecycle_locks_guard = threading.Lock()
_instance_lifecycle_locks = {}

def _get_lifecycle_lock(instance):
    """Returns the lifecycle Lock for an instance (keyed by DB id when known).

    Falls back to an object-identity key when the row carries no usable 'id'
    (legacy/test stand-ins); production rows always have one.
    """
    instance_id = getattr(instance, "id", None)
    key = ("id", instance_id) if isinstance(instance_id, int) else ("obj", id(instance))
    with _lifecycle_locks_guard:
        if key not in _instance_lifecycle_locks:
            _instance_lifecycle_locks[key] = threading.Lock()
        return _instance_lifecycle_locks[key]

def _parse_instance_port_range(status_code: int = 500):
    """LOT3 (M9): single validated parse of AIKORE_INSTANCE_PORT_RANGE.

    Returns (start, end, range_str); raises a clean HTTPException instead of a
    raw ValueError/500 traceback when the environment variable is malformed.
    """
    port_range_str = os.environ.get("AIKORE_INSTANCE_PORT_RANGE", "19001-19020")
    try:
        start_port, end_port = map(int, port_range_str.split('-'))
        if start_port > end_port:
            raise ValueError("start port must be <= end port")
        return start_port, end_port, port_range_str
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status_code,
            detail=f"Invalid AIKORE_INSTANCE_PORT_RANGE format: '{port_range_str}'. Expected 'start-end'.",
        )

class DeleteOptions(BaseModel):
    mode: str = "trash"
    overwrite: bool = False

router = APIRouter(
    prefix="/api", # UPDATED: Common prefix for system info
    tags=["Instances"]
)

class FileContent(BaseModel):
    content: str

def _ensure_path_within_dir(path_str: str, root_str: str, label: str):
    """SECURITY (audit C-4): defense in depth against path traversal.
    Resolves `path_str` and refuses (403) anything that does not live STRICTLY
    inside `root_str`. Used before any destructive filesystem operation."""
    root = Path(root_str).resolve()
    resolved = Path(path_str).resolve()
    if resolved == root or not resolved.is_relative_to(root):
        raise HTTPException(
            status_code=403,
            detail=f"Refusing to operate on '{label}': resolved path escapes the allowed directory."
        )

def _ensure_no_traversal_component(value, label: str):
    """SECURITY (audit H-1): refuses any value that could escape its base
    directory when joined with os.path.join (absolute path, separators or '..').
    Works on legacy DB rows too, without requiring the stricter create-time regex."""
    if not isinstance(value, str) or not value or "/" in value or "\\" in value or ".." in value:
        raise HTTPException(status_code=400, detail=f"Invalid {label}: path separators and '..' are not allowed.")


def _ensure_instance_dir_contained(path_str: str, label: str):
    """SECURITY (lot 2 review, H-1): legacy/tampered DB rows may hold an instance
    name written before the strict schema validators existed, which escapes
    INSTANCES_DIR once joined (e.g. '/tmp/x'). Resolve the joined path and refuse
    (400) anything that is not strictly inside the instances root — protects the
    read/write file endpoints, the logs endpoint and the rename flow."""
    root = Path(INSTANCES_DIR).resolve()
    resolved = Path(path_str).resolve()
    if resolved == root or not resolved.is_relative_to(root):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid instance name in database. '{label}' resolves outside the instances directory."
        )


def _ensure_legacy_runtime_values_safe(instance):
    """SECURITY (lot 2 review, M-2): rows created before the strict schema
    validators may still carry dangerous values in the database. process_manager
    derives filesystem paths (os.path.join + os.makedirs under OUTPUTS_DIR /
    INSTANCES_DIR) from output_path and name, so refuse (400) to start or rebuild
    an instance whose stored values no longer conform to the schema validators.
    Sane legacy rows (conforming values) keep working unchanged."""
    if instance.output_path is not None and not schemas.is_valid_output_path(instance.output_path):
        raise HTTPException(
            status_code=400,
            detail=(
                "Legacy value rejected: output_path "
                f"'{instance.output_path}' does not conform to the current validation rules "
                "(relative folder name, no absolute path, no '..' segment). Update the "
                "instance configuration before starting it."
            ),
        )
    if not schemas.is_valid_instance_name(instance.name):
        raise HTTPException(
            status_code=400,
            detail=(
                "Legacy value rejected: instance name "
                f"'{instance.name}' does not conform to the current validation rules. "
                "Rename the instance before starting it."
            ),
        )

# NEW: Wheel Management Schemas
class InstanceWheel(BaseModel):
    filename: str
    size_mb: float
    installed: bool # Present in instance/wheels/
    
class WheelsSyncRequest(BaseModel):
    filenames: List[str] # List of filenames to KEEP/INSTALL

def get_instance_file_path(db: Session, db_instance: models.Instance):
    """
    Gets the correct launch script path for an instance.
    For satellite instances, this resolves to the parent's script path.
    """
    # If the instance is a satellite, we need to operate on the parent's directory.
    if db_instance.parent_instance_id is not None:
        parent_instance = crud.get_instance(db, instance_id=db_instance.parent_instance_id)
        if not parent_instance:
            # This is a critical data integrity issue if it happens.
            raise HTTPException(status_code=404, detail=f"Parent instance for satellite '{db_instance.name}' not found.")
        effective_instance_name = parent_instance.name
    else:
        effective_instance_name = db_instance.name

    base_script_name = db_instance.base_blueprint

    # --- SECURITY (audit H-1): the blueprint name is joined into blueprint
    # directories and the resulting file can be exfiltrated via GET /file.
    # Refuse any traversal-capable value, whatever code path calls us.
    _ensure_no_traversal_component(base_script_name, "base_blueprint")

    instance_conf_dir = os.path.join(INSTANCES_DIR, effective_instance_name)

    # --- SECURITY (lot 2 review, H-1): legacy/tampered rows may hold a name that
    # escapes INSTANCES_DIR once joined (e.g. '/tmp/x'); launch.sh would then be
    # read/written OUTSIDE the instances root via GET/PUT /file.
    _ensure_instance_dir_contained(instance_conf_dir, f"instance '{effective_instance_name}'")

    instance_file_path = os.path.join(instance_conf_dir, "launch.sh")
    
    # The logic for finding the fallback blueprint remains the same.
    custom_blueprint_path = os.path.join(CUSTOM_BLUEPRINTS_DIR, base_script_name)
    stock_blueprint_path = os.path.join(BLUEPRINTS_DIR, base_script_name)
    
    blueprint_file_path = custom_blueprint_path if os.path.exists(custom_blueprint_path) else stock_blueprint_path
        
    return instance_file_path, blueprint_file_path

def _allocate_ports(db: Session, persistent_mode: bool, requested_port: int | None, instance_to_exclude_id: int | None = None) -> dict:
    """
    Allocates application and persistent ports based on availability and instance mode.
    Returns a dictionary with 'port', 'persistent_port', and 'persistent_display'.
    If instance_to_exclude_id is provided, its ports are ignored during conflict checks.

    LOT3 (M1):
      - the whole read-then-decide sequence runs under a process-wide lock so
        two concurrent creations can no longer observe the same port as free;
      - used ports come from a targeted DB projection (no LIMIT 1000), fixing
        false "free" results beyond 1000 instances;
      - the final safety net is the bind re-verification in
        process_manager.start_instance_process() right before Popen.
    """
    start_port, end_port, port_range_str = _parse_instance_port_range(status_code=500)
    all_possible_ports = set(range(start_port, end_port + 1))

    with _port_allocation_lock:
        used_pool_ports = set()
        # LOT3 (#13): targeted projection instead of loading up to 1000 full
        # rows; the exclusion of the current instance stays SQL-side.
        for _row_id, used_port, used_persistent_port in crud.get_used_ports(
            db, exclude_instance_id=instance_to_exclude_id
        ):
            if used_port in all_possible_ports:
                # If an instance is in persistent mode, its 'port' is internal/ephemeral and doesn't block the public pool.
                # BUT: The current logic might have assigned a pool port to 'port' even in persistent mode in the past.
                # To be safe: we block it if it falls in the range.
                used_pool_ports.add(used_port)
            if used_persistent_port in all_possible_ports:
                used_pool_ports.add(used_persistent_port)

    app_port = None
    persistent_port = None
    persistent_display = None

    if persistent_mode:
        if requested_port:
            if requested_port not in all_possible_ports:
                raise HTTPException(status_code=400, detail=f"Selected port {requested_port} is not within the allowed range {port_range_str}.")
            if requested_port in used_pool_ports:
                raise HTTPException(status_code=400, detail=f"Selected port {requested_port} is already in use.")
            persistent_port = requested_port
        else:
            available_ports = sorted(list(all_possible_ports - used_pool_ports))
            if not available_ports:
                raise HTTPException(status_code=503, detail="No available ports for new persistent instances.")
            persistent_port = available_ports[0]
        
        app_port = _find_free_port()
        persistent_display = _find_free_display()
    else:
        if requested_port:
            if requested_port not in all_possible_ports:
                raise HTTPException(status_code=400, detail=f"Selected port {requested_port} is not within the allowed range {port_range_str}.")
            if requested_port in used_pool_ports:
                raise HTTPException(status_code=400, detail=f"Selected port {requested_port} is already in use.")
            app_port = requested_port
        else:
            available_ports = sorted(list(all_possible_ports - used_pool_ports))
            if not available_ports:
                raise HTTPException(status_code=503, detail="No available ports for new normal instances.")
            app_port = available_ports[0]
        
        persistent_port = None
        persistent_display = None

    return {
        "port": app_port,
        "persistent_port": persistent_port,
        "persistent_display": persistent_display
    }

@router.post("/instances/", response_model=schemas.Instance)
def create_new_instance(instance: schemas.InstanceCreate, db: Session = Depends(get_db)):
    db_instance = crud.get_instance_by_name(db, name=instance.name)
    if db_instance:
        raise HTTPException(status_code=400, detail="Instance with this name already exists")

    port_allocations = _allocate_ports(db, instance.persistent_mode, instance.port)

    try:
        return crud.create_instance(
            db=db, 
            instance=instance,
            port=port_allocations["port"],
            persistent_port=port_allocations["persistent_port"],
            persistent_display=port_allocations["persistent_display"]
        )
    except ValueError as e:
        # SECURITY (audit C-4): path-containment guard in crud layer.
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        # LOT 2 REVIEW (L-3a): a missing blueprint or source directory is a
        # client-visible 404, not an opaque 500.
        raise HTTPException(status_code=404, detail=str(e))

@router.post("/instances/{instance_id}/copy", response_model=schemas.Instance, tags=["Instance Actions"])
def copy_instance(
    instance_id: int,
    instance_copy: schemas.InstanceCopy,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Creates a new instance by copying an existing one (Asynchronous).
    """
    source_instance = crud.get_instance(db, instance_id=instance_id)
    if not source_instance:
        raise HTTPException(status_code=404, detail="Source instance not found")

    try:
        # 1. Create the DB entry immediately (Status: installing)
        new_instance = crud.create_copy_placeholder(
            db=db,
            source_instance_id=instance_id,
            new_name=instance_copy.new_name
        )
        
        # 2. Launch the heavy work in background
        # We pass IDs only, NOT the db session, to avoid DetachedInstanceError
        background_tasks.add_task(crud.process_background_copy, new_instance.id, instance_id)
        
        return new_instance
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/instances/{instance_id}/instantiate", response_model=schemas.Instance, tags=["Instance Actions"])
def instantiate_instance(
    instance_id: int,
    instance_instantiate: schemas.InstanceInstantiate,
    db: Session = Depends(get_db)
):
    """
    Creates a new instance by instantiating an existing one (linked).
    """
    source_instance = crud.get_instance(db, instance_id=instance_id)
    if not source_instance:
        raise HTTPException(status_code=404, detail="Source instance not found")

    # The actual logic is in crud.instantiate_instance
    try:
        new_instance = crud.instantiate_instance(
            db=db,
            source_instance_id=instance_id,
            new_name=instance_instantiate.new_name
        )
        return new_instance
    except ValueError as e:
        # Client errors from crud (name conflict, satellite-of-satellite...)
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        # LOT3 (M9): unexpected errors are SERVER errors — no longer masked as
        # a blanket 400; log loudly and return a structured 500.
        print(f"[API-ERROR] Unexpected error while instantiating from instance {instance_id}: "
              f"{type(e).__name__}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Internal error while instantiating the instance.")

@router.get("/instances/", response_model=List[schemas.Instance])
def read_all_instances(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    instances = crud.get_instances(db, skip=skip, limit=limit)
    return instances

@router.put("/instances/{instance_id}", response_model=schemas.Instance)
def update_instance_details(
    instance_id: int,
    instance_update: schemas.InstanceUpdate,
    db: Session = Depends(get_db)
):
    db_instance = crud.get_instance(db, instance_id=instance_id)
    if not db_instance:
        raise HTTPException(status_code=404, detail="Instance not found")

    update_data = instance_update.model_dump(exclude_unset=True)
    if not update_data:
        return db_instance

    # LOT3 (H3): the whole update path (hot-swap AND disruptive stop/
    # update/start) runs under the per-instance lifecycle lock so a
    # concurrent start/stop/delete cannot interleave with it.
    with _get_lifecycle_lock(db_instance):
            # --- HOT-SWAP / SMART UPDATE LOGIC ---
            # Define fields that require a full stop/start cycle if they are present
            restart_fields = {
                'name', 'base_blueprint', 'output_path', 'gpu_ids', 'persistent_mode', 'port',
                'python_version', 'cuda_version', 'torch_version' # <--- NOUVEAU ICI
            }

            requires_restart = any(field in restart_fields for field in update_data.keys())

            if not requires_restart:
                # Handle safe updates (autostart, hostname, use_custom_hostname) without restart
                print(f"[API] Performing hot-swap update for instance '{db_instance.name}'. No restart needed.")
        
                # 1. Update DB
                updated_instance = crud.update_instance(db, instance_id=db_instance.id, instance_update=instance_update)
        
                # 2. Refresh NGINX config if routing details changed
                if 'hostname' in update_data or 'use_custom_hostname' in update_data:
                    print("[API] Hostname-related change detected. Updating NGINX configuration.")
                    try:
                        process_manager.update_nginx_config(db)
                    except Exception as e:
                        print(f"[API-WARNING] Could not dynamically update NGINX config: {e}. Change will apply on next restart.")
        
                db.refresh(updated_instance)
                return updated_instance

            # --- For all other updates, handle stop/start (original logic) ---
            was_running = db_instance.status != "stopped"
            if was_running:
                print(f"Instance '{db_instance.name}' is running. Stopping it before disruptive update.")
                process_manager.stop_instance_process(db=db, instance=db_instance)
                db.refresh(db_instance)

            # --- Apply changes ---
            original_name = db_instance.name
            final_update_data = update_data.copy()

            # 1. Name Change
            if "name" in update_data and update_data["name"] != original_name:
                new_name = update_data["name"]
                if crud.get_instance_by_name(db, name=new_name):
                    raise HTTPException(status_code=400, detail=f"An instance with the name '{new_name}' already exists.")
                # --- SECURITY (audit C-4): same policy as creation, enforced again right
                # before the filesystem rename (defense in depth on top of the schema).
                if not schemas.is_valid_instance_name(new_name):
                    raise HTTPException(status_code=400, detail=(
                        "Invalid instance name: 1-64 characters required, must start with a letter, "
                        "digit or underscore; only letters, digits, underscores, hyphens and inner "
                        "spaces are allowed (no trailing space). Path separators and '..' are forbidden."
                    ))
                try:
                    old_dir = os.path.join(INSTANCES_DIR, original_name)
                    new_dir = os.path.join(INSTANCES_DIR, new_name)
                    # --- SECURITY (lot 2 review, H-1): BOTH sides of the rename must
                    # resolve strictly inside INSTANCES_DIR before os.rename runs —
                    # new_name is validated above, but the legacy old name may escape.
                    _ensure_instance_dir_contained(old_dir, f"current instance directory '{original_name}'")
                    _ensure_instance_dir_contained(new_dir, f"target instance directory '{new_name}'")
                    if os.path.isdir(old_dir):
                        os.rename(old_dir, new_dir)
                        rebuild_trigger_path = os.path.join(new_dir, ".rebuild-env")
                        with open(rebuild_trigger_path, 'w') as f: f.write('')
                        # LOT3 (M9): remove the stale '{old_slug}.conf' right away;
                        # it used to linger until the next stop/start cycle. Best-effort
                        # and getattr-guarded for stripped-down test harnesses.
                        try:
                            _slugify_fn = getattr(process_manager, "_slugify", None)
                            _remove_conf_fn = getattr(process_manager, "remove_nginx_config", None)
                            old_slug = _slugify_fn(original_name) if callable(_slugify_fn) else original_name
                            if callable(_remove_conf_fn):
                                _remove_conf_fn(old_slug)
                        except Exception as nginx_err:
                            print(f"[API-WARNING] Could not clean up NGINX config after rename of '{original_name}': {nginx_err}")
                except OSError as e:
                    # Rollback: only if rename succeeded but something else failed,
                    # or if the rename partially moved the directory.
                    try:
                        if os.path.isdir(new_dir) and not os.path.isdir(old_dir):
                            os.rename(new_dir, old_dir)
                            print(f"[API] Rolled back directory rename for '{original_name}'.")
                    except OSError as rollback_err:
                        print(f"[API-CRITICAL] Rollback failed for '{original_name}': {rollback_err}")
                    raise HTTPException(status_code=500, detail=f"Failed to rename instance directory: {e}")

            # 2. Blueprint Change
            if "base_blueprint" in update_data and update_data["base_blueprint"] != db_instance.base_blueprint:
                new_blueprint = update_data["base_blueprint"]
                # --- SECURITY (audit H-1): same traversal guard as get_instance_file_path.
                _ensure_no_traversal_component(new_blueprint, "base_blueprint")
                current_name = update_data.get("name", original_name)
                instance_conf_dir = os.path.join(INSTANCES_DIR, current_name)
                os.makedirs(instance_conf_dir, exist_ok=True)
                instance_file_path = os.path.join(instance_conf_dir, "launch.sh")
                custom_bp_path = os.path.join(CUSTOM_BLUEPRINTS_DIR, new_blueprint)
                stock_bp_path = os.path.join(BLUEPRINTS_DIR, new_blueprint)
                blueprint_to_copy = custom_bp_path if os.path.exists(custom_bp_path) else stock_bp_path if os.path.exists(stock_bp_path) else None
                if blueprint_to_copy:
                    try:
                        shutil.copy(blueprint_to_copy, instance_file_path)
                    except Exception as e:
                        raise HTTPException(status_code=500, detail=f"Failed to update launch script: {e}")

            # 3. Port & Mode Logic
            persistent_mode_changed = "persistent_mode" in update_data and update_data["persistent_mode"] != db_instance.persistent_mode
    
            # Identify the current publicly exposed port
            current_exposed_port = db_instance.persistent_port if db_instance.persistent_mode else db_instance.port
    
            # Identify if the user requested a NEW port
            requested_port_val = update_data.get("port")
            user_changed_port = False
    
            if requested_port_val is not None:
                # User sent a port value. Is it different from what we have?
                if str(requested_port_val) != str(current_exposed_port):
                    user_changed_port = True

            if persistent_mode_changed or user_changed_port:
        
                # A. Determine the Target Public Port
                if user_changed_port and requested_port_val:
                    target_public_port = int(requested_port_val)
                else:
                    # If user didn't change port explicitly, we want to KEEP the current public port
                    target_public_port = current_exposed_port

                # B. Determine the Target Mode
                target_mode = update_data.get("persistent_mode", db_instance.persistent_mode)

                # C. Conflict Check
                # LOT3 (M9): validated parse — an invalid AIKORE_INSTANCE_PORT_RANGE
                # produced a raw ValueError/500 traceback here.
                start_port, end_port, port_range_str = _parse_instance_port_range(status_code=400)
        
                # Only check range if we have a valid port. If it's None (orphaned/new), we skip range check but will allocate below.
                if target_public_port is not None and start_port <= target_public_port <= end_port:
                    conflict = db.query(models.Instance).filter(
                        models.Instance.id != db_instance.id,
                        or_(models.Instance.port == target_public_port, models.Instance.persistent_port == target_public_port)
                    ).first()
                    if conflict:
                         raise HTTPException(status_code=400, detail=f"Port {target_public_port} is already in use by instance '{conflict.name}'.")
        
                # Fallback allocation if we somehow ended up with None (e.g. invalid state)
                if target_public_port is None:
                     alloc = _allocate_ports(db, target_mode, None, instance_to_exclude_id=db_instance.id)
                     target_public_port = alloc['persistent_port'] if target_mode else alloc['port']

                # D. Apply Logic based on Target Mode
                if target_mode: # Persistent Mode
                    # Public port goes to VNC
                    final_update_data['persistent_port'] = target_public_port
                    # Application gets a new internal ephemeral port
                    final_update_data['port'] = _find_free_port()
            
                    if not db_instance.persistent_display:
                        final_update_data['persistent_display'] = _find_free_display()
                
                    # Install dependencies if switching to persistent for the first time
                    if not db_instance.persistent_mode:
                        temp_instance_for_cmd = schemas.Instance.model_validate(db_instance)
                        temp_instance_for_cmd.name = update_data.get("name", original_name)
                        success, output = process_manager.run_command_in_instance_venv(temp_instance_for_cmd, "pip install websockify numpy")
                        if not success:
                             print(f"WARNING: Failed to install persistent mode dependencies for '{db_instance.name}': {output}")

                else: # Normal Mode
                    # Public port goes to Application
                    final_update_data['port'] = target_public_port
                    # VNC ports are cleared
                    final_update_data['persistent_port'] = None
                    final_update_data['persistent_display'] = None

            # --- Finalize ---
            final_instance_update = schemas.InstanceUpdate(**final_update_data)
    
            # Use crud.update_instance as the single source of truth for the commit
            # It uses model_dump(exclude_unset=True), which now correctly includes
            # port, persistent_port, and persistent_display since they were added to InstanceUpdate.
            updated_instance = crud.update_instance(db, instance_id=db_instance.id, instance_update=final_instance_update)
            db.refresh(updated_instance)

            if was_running:
                print(f"Restarting instance '{updated_instance.name}' after disruptive update.")
                try:
                    process_manager.start_instance_process(db=db, instance=updated_instance)
                except Exception as e:
                    print(f"CRITICAL: Failed to restart instance after update: {e}")

            return updated_instance

@router.post("/instances/{instance_id}/rebuild", response_model=schemas.Instance, tags=["Instance Actions"])
def rebuild_instance_environment(instance_id: int, db: Session = Depends(get_db)):
    db_instance = crud.get_instance(db, instance_id=instance_id)
    if not db_instance:
        raise HTTPException(status_code=404, detail="Instance not found")

    # --- SECURITY (lot 2 review, M-2): refuse dangerous legacy values BEFORE
    # process_manager derives directories (os.makedirs) from them.
    _ensure_legacy_runtime_values_safe(db_instance)

    # LOT3 (H3): the rebuild's stop/restart cycle runs under the per-instance
    # lifecycle lock (same critical section contract as start/stop/delete).
    with _get_lifecycle_lock(db_instance):
        try:
            process_manager.rebuild_instance_env(db=db, instance=db_instance)
            # The process manager handles status updates, so we just return the instance
            return db_instance
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to rebuild instance environment: {str(e)}")

@router.post("/instances/{instance_id}/start", response_model=schemas.Instance, tags=["Instance Actions"])
def start_instance(instance_id: int, db: Session = Depends(get_db)):
    db_instance = crud.get_instance(db, instance_id=instance_id)
    if not db_instance:
        raise HTTPException(status_code=404, detail="Instance not found")

    # LOT3 (M8): the whole start critical section (status check -> spawn) runs
    # under the per-instance lifecycle lock so a concurrent delete/stop/start
    # cannot interleave with it.
    with _get_lifecycle_lock(db_instance):
        if db_instance.status != "stopped":
            raise HTTPException(status_code=400, detail=f"Instance cannot be started from status '{db_instance.status}'")

        # --- SECURITY (lot 2 review, M-2): refuse dangerous legacy values BEFORE
        # process_manager derives directories (os.makedirs) from them.
        _ensure_legacy_runtime_values_safe(db_instance)

        # --- SELF-HEALING (CORRECTION AUTO) ---
        # Si une instance est en mode persistant mais n'a pas de ports définis, on les alloue maintenant.
        needs_repair = False
        if db_instance.persistent_mode:
            if db_instance.persistent_port is None or db_instance.persistent_display is None:
                needs_repair = True
        else:
            if db_instance.port is None:
                needs_repair = True
            
        if needs_repair:
            print(f"[API] Auto-healing instance '{db_instance.name}' configuration before start.")
            # Force reallocation
            alloc = _allocate_ports(db, db_instance.persistent_mode, None, instance_to_exclude_id=db_instance.id)
            
            db_instance.port = alloc['port']
            db_instance.persistent_port = alloc['persistent_port']
            db_instance.persistent_display = alloc['persistent_display']
            
            db.commit()
            db.refresh(db_instance)

        try:
            process_manager.start_instance_process(db=db, instance=db_instance)
            # The process manager handles status updates, so we just return the instance
            return db_instance
        except Exception as e:
            # If start fails catastrophically, revert status and raise error
            db_instance.status = "stopped"
            db.commit()
            raise HTTPException(status_code=500, detail=f"Failed to start instance: {str(e)}")

@router.post("/instances/{instance_id}/stop", response_model=schemas.Instance, tags=["Instance Actions"])
def stop_instance(instance_id: int, db: Session = Depends(get_db)):
    db_instance = crud.get_instance(db, instance_id=instance_id)
    if not db_instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    if db_instance.status == "stopped":
        # Can be useful to force-stop a stuck instance ('starting' or 'stalled')
        # So we allow stopping unless it's already definitively stopped.
        raise HTTPException(status_code=400, detail="Instance is already stopped")

    # LOT3 (H3): the whole stop critical section (status check -> kill sequence)
    # runs under the per-instance lifecycle lock, so a concurrent start/restart
    # cannot interleave with it.
    with _get_lifecycle_lock(db_instance):
        try:
            process_manager.stop_instance_process(db=db, instance=db_instance)
            return db_instance
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to stop instance: {str(e)}")

@router.post("/instances/{instance_id}/version-check", tags=["Instance Actions"])
def version_check(instance_id: int, db: Session = Depends(get_db)):
    db_instance = crud.get_instance(db, instance_id=instance_id)
    if not db_instance:
        raise HTTPException(status_code=404, detail="Instance not found")

    # The version check can run whether the instance is running or not,
    # as long as the environment exists.

    try:
        output = process_manager.run_version_check(instance=db_instance)
        
        parts = output.split("---AIKORE-SEPARATOR---", 1)
        versions = parts[0].strip()
        conflicts = parts[1].strip() if len(parts) > 1 else "No conflict check output."
        
        # Check if pip check found issues. "No broken requirements found." is the success message.
        if "No broken requirements found." in conflicts:
            conflicts = "No dependency conflicts found."

        return {"versions": versions, "conflicts": conflicts}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to run version check: {str(e)}")

# --- HELPER FUNCTION FOR BACKGROUND DELETION ---
def _on_rm_error(func, path, exc):
    """
    Error handler for shutil.rmtree (Python 3.12+ signature).
    LOT3 (M10): canonical implementation in aikore/core/filesystem.py
    (logging.ERROR instead of silent prints); thin delegation kept for
    backward-compatible monkeypatching.
    """
    if _shared_rm_error_handler is not None:
        _shared_rm_error_handler(func, path, exc)
        return
    # Fallback (stripped-down harness only): same logic, legacy print.
    try:
        # Check if the file is read-only
        if not os.access(path, os.W_OK):
            os.chmod(path, stat.S_IWUSR)
            func(path)
        else:
            # Re-raise the original exception if it wasn't a permission issue
            raise exc
    except Exception as e:
        print(f"[Deletion-Error] Failed to force delete '{path}': {e}")

def _background_file_deletion(instance_name: str, mode: str, overwrite: bool):
    """
    Deletes or moves instance files in the background to avoid blocking the API response.
    """
    instance_dir = os.path.join(INSTANCES_DIR, instance_name)
    TRASH_DIR = os.path.join(os.path.dirname(INSTANCES_DIR), "trashcan")
    trash_path = os.path.join(TRASH_DIR, instance_name)

    try:
        if mode == "permanent":
            if os.path.isdir(instance_dir):
                print(f"[Background-Delete] Permanently deleting '{instance_name}'...")
                # Use the new robust error handler
                shutil.rmtree(instance_dir, onexc=_on_rm_error)
        elif mode == "trash":
            if os.path.isdir(instance_dir):
                os.makedirs(TRASH_DIR, exist_ok=True)
                if os.path.exists(trash_path) and overwrite:
                    print(f"[Background-Delete] Overwriting trashcan entry for '{instance_name}'...")
                    shutil.rmtree(trash_path, onexc=_on_rm_error)
                
                # Check again if destination exists
                if not os.path.exists(trash_path):
                     print(f"[Background-Delete] Moving '{instance_name}' to trashcan...")
                     shutil.move(instance_dir, TRASH_DIR)
        
        print(f"[Background-Delete] Cleanup for '{instance_name}' completed.")
        
    except Exception as e:
        # LOT3 (M8): failures used to be swallowed by a single print. Log the
        # full traceback AND drop a visible marker file so a failed background
        # deletion can be spotted and retried instead of silently leaking
        # instance directories.
        print(f"[Background-Delete-ERROR] Failed to process files for '{instance_name}': {e}")
        traceback.print_exc()
        try:
            marker_dir = os.path.join(TRASH_DIR, ".failed-deletions")
            os.makedirs(marker_dir, exist_ok=True)
            safe_stem = re.sub(r"[^A-Za-z0-9._-]", "_", instance_name)[:100] or "instance"
            marker_path = os.path.join(marker_dir, f"{safe_stem}.{int(time.time())}.err")
            with open(marker_path, "w", encoding="utf-8") as mf:
                mf.write(
                    f"instance_name={instance_name!r}\n"
                    f"mode={mode!r} overwrite={overwrite!r}\n"
                    f"error={type(e).__name__}: {e}\n"
                )
            print(f"[Background-Delete-ERROR] Failure marker written to '{marker_path}'.")
        except Exception as marker_err:
            print(f"[Background-Delete-ERROR] Could not write failure marker: {marker_err}")


@router.delete("/instances/{instance_id}", status_code=200, tags=["Instance Actions"])
def delete_instance(
    instance_id: int, 
    options: DeleteOptions, 
    background_tasks: BackgroundTasks, # <--- Added for background processing
    db: Session = Depends(get_db)
):
    db_instance = crud.get_instance(db, instance_id=instance_id)
    if not db_instance:
        raise HTTPException(status_code=404, detail="Instance not found")

    # LOT3 (M8): the status check -> DB purge -> file-op scheduling sequence is
    # atomic under the per-instance lifecycle lock; a concurrent start can no
    # longer resurrect the instance between the check and the purge.
    with _get_lifecycle_lock(db_instance):
        if db_instance.status == "installing":
            # LOT3 (M8): a background copy (process_background_copy) may still
            # be writing files and would commit on a stale object afterwards.
            raise HTTPException(
                status_code=409,
                detail="Cannot delete an instance that is still installing. Wait for the background copy to finish (or clean it up once it reaches 'error').",
            )
        if db_instance.status not in ("stopped", "error"):
            raise HTTPException(status_code=400, detail=f"Cannot delete an instance in '{db_instance.status}' status. Please stop it first.")

        # --- Orphaned Satellite Protection ---
        children_count = db.query(models.Instance).filter(models.Instance.parent_instance_id == db_instance.id).count()
        if children_count > 0:
            raise HTTPException(
                status_code=409, 
                detail=f"Cannot delete instance '{db_instance.name}' because it is a parent to {children_count} satellite instance(s). Please delete them first."
            )

        instance_name = db_instance.name
        TRASH_DIR = os.path.join(os.path.dirname(INSTANCES_DIR), "trashcan")
        trash_path = os.path.join(TRASH_DIR, instance_name)
        instance_dir = os.path.join(INSTANCES_DIR, instance_name)

        # --- SECURITY (audit C-4): defense in depth before scheduling destructive
        # background operations — both targets must resolve strictly inside their root.
        _ensure_path_within_dir(instance_dir, INSTANCES_DIR, f"instance directory '{instance_name}'")
        _ensure_path_within_dir(trash_path, TRASH_DIR, f"trashcan entry '{instance_name}'")

        # Pre-check for trash conflicts to return error immediately (if not overwriting)
        if options.mode == "trash" and not options.overwrite and os.path.exists(trash_path) and os.path.isdir(os.path.join(INSTANCES_DIR, instance_name)):
             raise HTTPException(status_code=409, detail=f"Destination path '{instance_name}' already exists in trashcan. Use 'overwrite=true' to replace it.")

        # 1. DELETE FROM DB FIRST (Instant UI update)
        try:
            crud.delete_instance(db, instance_id=instance_id)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Database deletion failed: {e}")

        # 2. SCHEDULE FILE OPS IN BACKGROUND (No blocking)
        background_tasks.add_task(_background_file_deletion, instance_name, options.mode, options.overwrite)
    
    return {"ok": True, "detail": "Instance deleted successfully."}

@router.get("/instances/{instance_id}/logs", tags=["Instance Actions"])
def get_instance_logs(
    instance_id: int, 
    db: Session = Depends(get_db),
    offset: int = 0
):
    db_instance = crud.get_instance(db, instance_id=instance_id)
    if not db_instance:
        raise HTTPException(status_code=404, detail="Instance not found")

    # LOT3 (#14): a negative offset used to reach f.seek(offset) and explode
    # into a ValueError/raw 500.
    if offset < 0:
        raise HTTPException(status_code=400, detail="offset must be >= 0")

    instance_conf_dir = os.path.join(INSTANCES_DIR, db_instance.name)

    # --- SECURITY (lot 2 review, H-1): same containment guard as GET/PUT file —
    # a legacy/tampered name must not let us read logs outside INSTANCES_DIR.
    _ensure_instance_dir_contained(instance_conf_dir, f"instance '{db_instance.name}'")

    output_log_path = os.path.join(instance_conf_dir, "output.log")

    content = ""
    size = offset

    try:
        if os.path.exists(output_log_path):
            current_size = os.path.getsize(output_log_path)
            if current_size > offset:
                with open(output_log_path, 'r', encoding='utf-8', errors='ignore') as f:
                    f.seek(offset)
                    content = f.read()
                size = current_size
    except FileNotFoundError:
        pass

    return {
        "content": content,
        "size": size,
    }

@router.get("/instances/{instance_id}/file", response_model=FileContent, tags=["Instance Actions"])
def get_instance_file(instance_id: int, file_type: str, db: Session = Depends(get_db)):
    db_instance = crud.get_instance(db, instance_id=instance_id)
    if not db_instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    if file_type != "script":
        raise HTTPException(status_code=400, detail="Invalid file type specified")

    instance_file_path, blueprint_file_path = get_instance_file_path(db, db_instance)
    read_path = instance_file_path if os.path.exists(instance_file_path) else blueprint_file_path

    try:
        with open(read_path, 'r', encoding='utf-8') as f:
            content = f.read()
        return FileContent(content=content)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Source file '{os.path.basename(blueprint_file_path)}' not found in blueprints.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading file: {str(e)}")
        
@router.put("/instances/{instance_id}/file", status_code=200, tags=["Instance Actions"])
def update_instance_file(instance_id: int, file_type: str, file_content: FileContent, restart: bool = False, db: Session = Depends(get_db)):
    db_instance = crud.get_instance(db, instance_id=instance_id)
    if not db_instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    if file_type != "script":
        raise HTTPException(status_code=400, detail="Invalid file type specified")

    # --- NEW: Enforce rule for satellite instances ---
    if db_instance.parent_instance_id is not None:
        raise HTTPException(
            status_code=403, 
            detail="Satellite instances share their parent's script. It cannot be edited directly. Please edit the parent instance's script."
        )

    instance_file_path, _ = get_instance_file_path(db, db_instance)

    try:
        os.makedirs(os.path.dirname(instance_file_path), exist_ok=True)
        with open(instance_file_path, 'w', encoding='utf-8') as f:
            f.write(file_content.content)
        
        # --- NEW: Restart logic ---
        # LOT3 (H3): the scripted restart-after-edit whole stop/start cycle
        # runs under the per-instance lifecycle lock.
        if restart and db_instance.status != "stopped":
            with _get_lifecycle_lock(db_instance):
                try:
                    print(f"[API] Restarting instance {db_instance.name} after script update.")
                    # Stop the process. This updates status to 'stopped' in the DB.
                    process_manager.stop_instance_process(db=db, instance=db_instance)
                    
                    # The instance object in memory might be stale after stopping.
                    # Refresh it to get the latest state before starting again.
                    db.refresh(db_instance)

                    # Start the process again. This will update status to 'starting'.
                    process_manager.start_instance_process(db=db, instance=db_instance)
                    print(f"[API] Instance {db_instance.name} restart initiated.")
                except Exception as e:
                    # Log the error but don't fail the request, as the file was saved.
                    # The UI will reflect that the instance is stopped or stalled.
                    print(f"[API-ERROR] Failed to auto-restart instance {db_instance.name} after script update: {e}")

        return {"ok": True, "detail": "File updated successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error writing file: {str(e)}")

@router.websocket("/instances/{instance_id}/terminal", name="Instance Terminal")
async def instance_terminal_endpoint(instance_id: int, websocket: WebSocket, db: Session = Depends(get_db)):
    db_instance = crud.get_instance(db, instance_id=instance_id)
    if not db_instance:
        await websocket.close(code=4004, reason="Instance not found")
        return
    
    # Close the DB session immediately — we don't need it for the WebSocket lifetime
    # Holding it open would lock SQLite writes for the entire connection duration
    db.close()
    
    await websocket.accept()

    try:
        pid, master_fd = process_manager.start_terminal_process(db_instance)
    except Exception as e:
        error_message = f"Failed to start terminal: {e}"
        print(f"[ERROR] {error_message}")
        await websocket.send_text(f"\x1b[31m[ERROR] {error_message}\x1b[0m\r\n")
        await websocket.close(code=1011)
        return

    os.set_blocking(master_fd, False)

    async def read_from_pty():
        while True:
            try:
                await asyncio.sleep(0.01)
                data = os.read(master_fd, 1024)
                if data:
                    await websocket.send_bytes(data)
                else:
                    break # EOF
            except BlockingIOError:
                pass
            except Exception:
                break

    async def write_to_pty():
        while True:
            try:
                message = await websocket.receive_text()
                # Robustly check if the message is a control command
                if message.strip().startswith('{'):
                    try:
                        data = json.loads(message)
                        if isinstance(data, dict) and data.get("type") == "resize" and "rows" in data and "cols" in data:
                            process_manager.resize_terminal_process(master_fd, data['rows'], data['cols'])
                            continue # Skip writing this message to PTY
                    except (json.JSONDecodeError, TypeError):
                        # It looked like JSON but wasn't valid, treat as normal input
                        pass
                
                # If it's not a valid control message, write it to the PTY
                os.write(master_fd, message.encode('utf-8'))

            except Exception:
                break

    read_task = asyncio.create_task(read_from_pty())
    write_task = asyncio.create_task(write_to_pty())

    try:
        done, pending = await asyncio.wait([read_task, write_task], return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
    finally:
        print(f"[Terminal-{pid}] Connection closed. Cleaning up PTY process.")
        if not read_task.done(): read_task.cancel()
        if not write_task.done(): write_task.cancel()
        await asyncio.gather(read_task, write_task, return_exceptions=True)
        
        os.close(master_fd)
        
        try:
            parent = psutil.Process(pid)
            children = parent.children(recursive=True)
            for child in children:
                child.terminate()
            parent.terminate()
            _, alive = psutil.wait_procs([parent] + children, timeout=3)
            for p in alive:
                p.kill()
        except psutil.NoSuchProcess:
            pass
        
        if websocket.client_state != "DISCONNECTED":
            try:
                await websocket.close()
            except RuntimeError:
                # This can happen if the socket is already in the process of closing, which is fine.
                pass

# --- NEW ENDPOINTS FOR WHEELS MANAGEMENT ---

def _clean_wheel_name(filename: str) -> str:
    """
    Removes the internal architecture suffix (+archX.Y) from the filename
    to restore PEP 425 compatibility for pip.
    Example: sage..._x86_64+arch8.9.whl -> sage..._x86_64.whl
    """
    return re.sub(r'\+arch[\d\.]+(?=\.whl)', '', filename)

@router.get("/instances/{instance_id}/wheels", response_model=List[InstanceWheel], tags=["Instance Assets"])
def get_instance_wheels(instance_id: int, db: Session = Depends(get_db)):
    db_instance = crud.get_instance(db, instance_id=instance_id)
    if not db_instance:
        raise HTTPException(status_code=404, detail="Instance not found")

    # Determine paths
    instance_dir = os.path.join(INSTANCES_DIR, db_instance.name)
    local_wheels_dir = os.path.join(instance_dir, "wheels")
    
    # 1. List Global Wheels (Source of Truth - with suffix)
    global_files = glob.glob(os.path.join(GLOBAL_WHEELS_DIR, "*.whl"))
    
    # 2. List Local Wheels (Current State - cleaned names)
    local_filenames = set()
    if os.path.exists(local_wheels_dir):
        local_filenames = set(os.path.basename(f) for f in glob.glob(os.path.join(local_wheels_dir, "*.whl")))

    result = []
    
    for p in global_files:
        fname = os.path.basename(p) # This has +arch suffix
        try:
            size_mb = round(os.path.getsize(p) / (1024 * 1024), 2)
        except OSError:
            size_mb = 0.0
            
        # Check if the CLEAN version exists locally
        clean_name = _clean_wheel_name(fname)
        is_installed = clean_name in local_filenames
            
        result.append({
            "filename": fname,
            "size_mb": size_mb,
            "installed": is_installed
        })
        
    # Sort: Installed first, then by name
    result.sort(key=lambda x: (not x['installed'], x['filename']))
    return result

@router.post("/instances/{instance_id}/wheels", tags=["Instance Assets"])
def sync_instance_wheels(
    instance_id: int, 
    sync_request: WheelsSyncRequest,
    db: Session = Depends(get_db)
):
    db_instance = crud.get_instance(db, instance_id=instance_id)
    if not db_instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    
    instance_dir = os.path.join(INSTANCES_DIR, db_instance.name)
    local_wheels_dir = os.path.join(instance_dir, "wheels")

    # --- SECURITY (lot 2 review, L-2a/L-3c): validate EVERY requested filename
    # BEFORE touching the filesystem (no mkdir/copy/delete on invalid input).
    # NUL bytes are refused too, and ALL invalid names are reported in one
    # aggregated 400 instead of being silently skipped.
    invalid_names = [
        repr(fname) for fname in sync_request.filenames
        if not isinstance(fname, str) or not fname
        or ".." in fname or "/" in fname or "\\" in fname or "\x00" in fname
    ]
    if invalid_names:
        raise HTTPException(
            status_code=400,
            detail="Invalid wheel filename(s) refused (empty, path separators, '..' or NUL byte): "
                   + ", ".join(invalid_names)
        )

    os.makedirs(local_wheels_dir, exist_ok=True)
    
    # These are the requested global filenames (with suffix)
    # We compute what their local names SHOULD be (cleaned)
    target_clean_names = set(_clean_wheel_name(f) for f in sync_request.filenames)
    
    # 1. Clean up: Remove files locally that are NOT in target list
    current_local_files = glob.glob(os.path.join(local_wheels_dir, "*.whl"))
    for fpath in current_local_files:
        local_fname = os.path.basename(fpath)
        if local_fname not in target_clean_names:
            try:
                os.remove(fpath)
            except OSError as e:
                print(f"[Wheels-Sync] Failed to remove {local_fname}: {e}")

    # 2. Install: Copy files from global, renaming them on the fly
    for fname in sync_request.filenames:
        # (Every filename was validated upfront — no silent skip here anymore.)
        src_path = os.path.join(GLOBAL_WHEELS_DIR, fname)
        
        # Determine clean destination name
        clean_name = _clean_wheel_name(fname)
        dst_path = os.path.join(local_wheels_dir, clean_name)
        
        if os.path.exists(src_path):
            if not os.path.exists(dst_path):
                try:
                    shutil.copy2(src_path, dst_path)
                except OSError as e:
                     raise HTTPException(status_code=500, detail=f"Failed to copy {fname}: {e}")
            else:
                # File exists locally. Should we update it?
                # Simple logic: if global is newer/different size?
                # For now, assume immutable unless deleted. 
                # To force update, user can uncheck -> apply -> check -> apply.
                pass
            
    return {"ok": True, "detail": "Wheels synchronized successfully."}