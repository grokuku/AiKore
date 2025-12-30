from fastapi import APIRouter, Depends, HTTPException, Body, WebSocket, WebSocketDisconnect, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List
import os
import shutil
import stat  # NEW: Needed for permission handling
import asyncio
import psutil
import json
import subprocess
import glob 
from pydantic import BaseModel

from ..database import crud, models
from ..database.session import SessionLocal
from ..schemas import instance as schemas
from ..core import process_manager
from ..core.process_manager import INSTANCES_DIR, BLUEPRINTS_DIR, CUSTOM_BLUEPRINTS_DIR, _find_free_port, _find_free_display

# --- CONSTANTS ---
GLOBAL_WHEELS_DIR = os.path.join(INSTANCES_DIR, ".wheels")

class DeleteOptions(BaseModel):
    mode: str = "trash"
    overwrite: bool = False

router = APIRouter(
    prefix="/api", # UPDATED: Common prefix for system info
    tags=["Instances"]
)

class FileContent(BaseModel):
    content: str

# NEW: System Information Schema
class SystemInfo(BaseModel):
    gpu_count: int
    gpus: List[dict] = [] # To provide more details if needed

# NEW: Wheel Management Schemas
class InstanceWheel(BaseModel):
    filename: str
    size_mb: float
    installed: bool # Present in instance/wheels/
    
class WheelsSyncRequest(BaseModel):
    filenames: List[str] # List of filenames to KEEP/INSTALL

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

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
    instance_conf_dir = os.path.join(INSTANCES_DIR, effective_instance_name)
    instance_file_path = os.path.join(instance_conf_dir, "launch.sh")
    
    # The logic for finding the fallback blueprint remains the same.
    custom_blueprint_path = os.path.join(CUSTOM_BLUEPRINTS_DIR, base_script_name)
    stock_blueprint_path = os.path.join(BLUEPRINTS_DIR, base_script_name)
    
    blueprint_file_path = custom_blueprint_path if os.path.exists(custom_blueprint_path) else stock_blueprint_path
        
    return instance_file_path, blueprint_file_path

# NEW: Endpoint to provide system information like GPU count
@router.get("/system/info", response_model=SystemInfo, tags=["System"])
def get_system_info():
    """
    Provides general system information, such as the number and details of available GPUs.
    """
    gpus_info = []
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,name", "--format=csv,noheader"],
            capture_output=True, text=True, check=True
        )
        for line in result.stdout.strip().split('\n'):
            if not line: continue
            parts = line.split(', ')
            gpus_info.append({"id": int(parts[0]), "name": parts[1]})
    except (FileNotFoundError, subprocess.CalledProcessError, ValueError):
        pass # Handles cases where nvidia-smi is not found or fails
    
    return {"gpu_count": len(gpus_info), "gpus": gpus_info}

def _allocate_ports(db: Session, persistent_mode: bool, requested_port: int | None, instance_to_exclude_id: int | None = None) -> dict:
    """
    Allocates application and persistent ports based on availability and instance mode.
    Returns a dictionary with 'port', 'persistent_port', and 'persistent_display'.
    If instance_to_exclude_id is provided, its ports are ignored during conflict checks.
    """
    port_range_str = os.environ.get("AIKORE_INSTANCE_PORT_RANGE", "19001-19020")
    try:
        start_port, end_port = map(int, port_range_str.split('-'))
        all_possible_ports = set(range(start_port, end_port + 1))
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=500,
            detail=f"Invalid AIKORE_INSTANCE_PORT_RANGE format: '{port_range_str}'. Expected 'start-end'."
        )

    instances = crud.get_instances(db, limit=1000)
    used_pool_ports = set()
    for inst in instances:
        if inst.id == instance_to_exclude_id:
            continue
        # Mark ports as used
        if inst.port and inst.port in all_possible_ports:
            # If an instance is in persistent mode, its 'port' is internal/ephemeral and doesn't block the public pool.
            # BUT: The current logic might have assigned a pool port to 'port' even in persistent mode in the past.
            # To be safe: we block it if it falls in the range.
            used_pool_ports.add(inst.port)
        if inst.persistent_port and inst.persistent_port in all_possible_ports:
            used_pool_ports.add(inst.persistent_port)

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

    return crud.create_instance(
        db=db, 
        instance=instance,
        port=port_allocations["port"],
        persistent_port=port_allocations["persistent_port"],
        persistent_display=port_allocations["persistent_display"]
    )

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
        # We pass the ID, not the object, to avoid session detachment issues in threads
        background_tasks.add_task(crud.process_background_copy, db, new_instance.id, instance_id)
        
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
    except Exception as e:
        # Catch potential errors from crud, like name conflict or file system errors
        raise HTTPException(status_code=400, detail=str(e))

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

    # --- HOT-SWAP / SMART UPDATE LOGIC ---
    # Define fields that require a full stop/start cycle if they are present
    restart_fields = {
        'name', 'base_blueprint', 'output_path', 'gpu_ids', 'persistent_mode', 'port'
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
        try:
            old_dir = os.path.join(INSTANCES_DIR, original_name)
            new_dir = os.path.join(INSTANCES_DIR, new_name)
            if os.path.isdir(old_dir):
                os.rename(old_dir, new_dir)
                rebuild_trigger_path = os.path.join(new_dir, ".rebuild-env")
                with open(rebuild_trigger_path, 'w') as f: f.write('')
        except OSError as e:
            if 'new_dir' in locals() and not os.path.isdir(old_dir) and os.path.isdir(new_dir): os.rename(new_dir, old_dir)
            raise HTTPException(status_code=500, detail=f"Failed to rename instance directory: {e}")

    # 2. Blueprint Change
    if "base_blueprint" in update_data and update_data["base_blueprint"] != db_instance.base_blueprint:
        new_blueprint = update_data["base_blueprint"]
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
        port_range_str = os.environ.get("AIKORE_INSTANCE_PORT_RANGE", "19001-19020")
        start_port, end_port = map(int, port_range_str.split('-'))
        
        # Only check range if we have a valid port. If it's None (orphaned/new), we skip range check but will allocate below.
        if target_public_port is not None and start_port <= target_public_port <= end_port:
            conflict = db.query(models.Instance).filter(
                models.Instance.id != db_instance.id,
                ((models.Instance.port == target_public_port) | (models.Instance.persistent_port == target_public_port))
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
    
    # Force direct assignment to ensure fields like persistent_port are updated even if schema filters them
    for field, value in final_update_data.items():
        if hasattr(db_instance, field):
            setattr(db_instance, field, value)
    
    # We still use the update function for standard behavior, but the important part was above
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
    if db_instance.status != "stopped":
        raise HTTPException(status_code=400, detail=f"Instance cannot be started from status '{db_instance.status}'")

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
def _on_rm_error(func, path, exc_info):
    """
    Error handler for shutil.rmtree.
    If the error is due to read-only access, change the file mode and retry.
    """
    try:
        # Check if the file is read-only
        if not os.access(path, os.W_OK):
            os.chmod(path, stat.S_IWRITE)
            func(path)
        else:
            # Re-raise the original exception if it wasn't a permission issue
            raise exc_info[1]
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
                shutil.rmtree(instance_dir, onerror=_on_rm_error)
        elif mode == "trash":
            if os.path.isdir(instance_dir):
                os.makedirs(TRASH_DIR, exist_ok=True)
                if os.path.exists(trash_path) and overwrite:
                    print(f"[Background-Delete] Overwriting trashcan entry for '{instance_name}'...")
                    shutil.rmtree(trash_path, onerror=_on_rm_error)
                
                # Check again if destination exists
                if not os.path.exists(trash_path):
                     print(f"[Background-Delete] Moving '{instance_name}' to trashcan...")
                     shutil.move(instance_dir, TRASH_DIR)
        
        print(f"[Background-Delete] Cleanup for '{instance_name}' completed.")
        
    except Exception as e:
        print(f"[Background-Delete-ERROR] Failed to process files for '{instance_name}': {e}")


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
    if db_instance.status != "stopped":
        raise HTTPException(status_code=400, detail="Cannot delete an active instance. Please stop it first.")

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

    instance_conf_dir = os.path.join(INSTANCES_DIR, db_instance.name)
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
        if restart and db_instance.status != "stopped":
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

@router.get("/instances/{instance_id}/wheels", response_model=List[InstanceWheel], tags=["Instance Assets"])
def get_instance_wheels(instance_id: int, db: Session = Depends(get_db)):
    db_instance = crud.get_instance(db, instance_id=instance_id)
    if not db_instance:
        raise HTTPException(status_code=404, detail="Instance not found")

    # Determine paths
    instance_dir = os.path.join(INSTANCES_DIR, db_instance.name)
    local_wheels_dir = os.path.join(instance_dir, "wheels")
    
    # 1. List Global Wheels (Source of Truth)
    global_files = glob.glob(os.path.join(GLOBAL_WHEELS_DIR, "*.whl"))
    
    # 2. List Local Wheels (Current State)
    local_filenames = set()
    if os.path.exists(local_wheels_dir):
        local_filenames = set(os.path.basename(f) for f in glob.glob(os.path.join(local_wheels_dir, "*.whl")))

    result = []
    
    for p in global_files:
        fname = os.path.basename(p)
        try:
            size_mb = round(os.path.getsize(p) / (1024 * 1024), 2)
        except OSError:
            size_mb = 0.0
            
        result.append({
            "filename": fname,
            "size_mb": size_mb,
            "installed": fname in local_filenames
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

    # Only allow modification if stopped (safer, though technically could be done while running if careful)
    # Allowing it while running to let user prepare next restart.
    
    instance_dir = os.path.join(INSTANCES_DIR, db_instance.name)
    local_wheels_dir = os.path.join(instance_dir, "wheels")
    os.makedirs(local_wheels_dir, exist_ok=True)
    
    target_filenames = set(sync_request.filenames)
    
    # 1. Clean up: Remove files locally that are NOT in target list
    current_local_files = glob.glob(os.path.join(local_wheels_dir, "*.whl"))
    for fpath in current_local_files:
        fname = os.path.basename(fpath)
        if fname not in target_filenames:
            try:
                os.remove(fpath)
            except OSError as e:
                print(f"[Wheels-Sync] Failed to remove {fname}: {e}")

    # 2. Install: Copy files from global that ARE in target list but missing locally
    for fname in target_filenames:
        # Security check: prevent directory traversal
        if ".." in fname or "/" in fname or "\\" in fname:
            continue
            
        src_path = os.path.join(GLOBAL_WHEELS_DIR, fname)
        dst_path = os.path.join(local_wheels_dir, fname)
        
        if os.path.exists(src_path):
            if not os.path.exists(dst_path):
                try:
                    shutil.copy2(src_path, dst_path)
                except OSError as e:
                     raise HTTPException(status_code=500, detail=f"Failed to copy {fname}: {e}")
        else:
            # If global file doesn't exist, we skip it (maybe deleted globally?)
            pass
            
    return {"ok": True, "detail": "Wheels synchronized successfully."}