from fastapi import APIRouter, Depends, HTTPException, Body, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from typing import List
import os
import shutil
import asyncio
import psutil
import json
import subprocess # NEW
from pydantic import BaseModel

from ..database import crud
from ..database.session import SessionLocal
from ..schemas import instance as schemas
from ..core import process_manager
from ..core.process_manager import INSTANCES_DIR, BLUEPRINTS_DIR, _find_free_port, _find_free_display

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

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_instance_file_path(db_instance):
    base_script_name = db_instance.base_blueprint
    instance_conf_dir = os.path.join(INSTANCES_DIR, db_instance.name)
    instance_file_path = os.path.join(instance_conf_dir, "launch.sh")
    blueprint_file_path = os.path.join(BLUEPRINTS_DIR, base_script_name)
    return instance_file_path, blueprint_file_path

# NEW: Endpoint to provide system information like GPU count
@router.get("/system/info", response_model=SystemInfo, tags=["System"])
def get_system_info():
    """
    Provides general system information, such as the number of available GPUs.
    """
    gpu_count = 0
    try:
        # Using nvidia-smi to get the count of GPUs
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=count", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            check=True
        )
        gpu_count = int(result.stdout.strip())
    except (FileNotFoundError, subprocess.CalledProcessError, ValueError):
        # Handle cases where nvidia-smi is not found or fails
        gpu_count = 0
    return {"gpu_count": gpu_count}

@router.post("/instances/", response_model=schemas.Instance)
def create_new_instance(instance: schemas.InstanceCreate, db: Session = Depends(get_db)):
    db_instance = crud.get_instance_by_name(db, name=instance.name)
    if db_instance:
        raise HTTPException(status_code=400, detail="Instance with this name already exists")

    # --- RE-ARCHITECTED PORT LOGIC ---
    
    # Define ports to be assigned
    app_port = None
    persistent_port = None
    persistent_display = None

    # Get the pool of available, user-facing ports
    port_range_str = os.environ.get("AIKORE_INSTANCE_PORT_RANGE", "19001-19020")
    try:
        start_port, end_port = map(int, port_range_str.split('-'))
        all_possible_ports = set(range(start_port, end_port + 1))
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=500,
            detail=f"Invalid AIKORE_INSTANCE_PORT_RANGE format: '{port_range_str}'. Expected 'start-end'."
        )

    # Find which ports from the pool are already in use
    instances = crud.get_instances(db, limit=1000)
    # Check both port and persistent_port to see what's used from the main pool
    used_pool_ports = {inst.port for inst in instances if inst.port in all_possible_ports}
    used_pool_ports.update({inst.persistent_port for inst in instances if inst.persistent_port in all_possible_ports})

    if instance.persistent_mode:
        # For persistent mode, the USER-FACING port is the persistent_port, chosen from the pool.
        user_selected_port = instance.port # The UI sends the choice in the 'port' field
        
        if user_selected_port:
            # User provided a port, validate it
            if user_selected_port not in all_possible_ports:
                raise HTTPException(status_code=400, detail=f"Selected port {user_selected_port} is not within the allowed range {port_range_str}.")
            if user_selected_port in used_pool_ports:
                raise HTTPException(status_code=400, detail=f"Selected port {user_selected_port} is already in use.")
            persistent_port = user_selected_port
        else:
            # User did not provide a port, find the first available one from the pool
            available_ports = sorted(list(all_possible_ports - used_pool_ports))
            if not available_ports:
                raise HTTPException(status_code=503, detail="No available ports for new instances.")
            persistent_port = available_ports[0]
        
        # The application port is a random internal port
        app_port = _find_free_port()
        persistent_display = _find_free_display()

    else:
        # For normal mode, the USER-FACING port is the app_port, chosen from the pool.
        user_selected_port = instance.port

        if user_selected_port:
            if user_selected_port not in all_possible_ports:
                raise HTTPException(status_code=400, detail=f"Selected port {user_selected_port} is not within the allowed range {port_range_str}.")
            if user_selected_port in used_pool_ports:
                raise HTTPException(status_code=400, detail=f"Selected port {user_selected_port} is already in use.")
            app_port = user_selected_port
        else:
            available_ports = sorted(list(all_possible_ports - used_pool_ports))
            if not available_ports:
                raise HTTPException(status_code=503, detail="No available ports for new instances.")
            app_port = available_ports[0]
        
        # No persistent resources for normal mode
        persistent_port = None
        persistent_display = None

    return crud.create_instance(
        db=db, 
        instance=instance,
        port=app_port,
        persistent_port=persistent_port,
        persistent_display=persistent_display
    )

@router.get("/instances/", response_model=List[schemas.Instance])
def read_all_instances(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    instances = crud.get_instances(db, skip=skip, limit=limit)
    return instances

# NEW: Endpoint to update an instance's details
@router.put("/instances/{instance_id}", response_model=schemas.Instance)
def update_instance_details(
    instance_id: int, 
    instance_update: schemas.InstanceUpdate, 
    db: Session = Depends(get_db)
):
    db_instance = crud.get_instance(db, instance_id=instance_id)
    if not db_instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    
    # Proactive check: Disallow updates on a running instance to prevent inconsistencies
    if db_instance.status != "stopped":
        raise HTTPException(status_code=400, detail="Instance must be stopped to be updated.")

    # Check if the name is being changed and if the new name already exists
    if instance_update.name and instance_update.name != db_instance.name:
        existing_instance = crud.get_instance_by_name(db, name=instance_update.name)
        if existing_instance:
            raise HTTPException(status_code=400, detail="An instance with the new name already exists.")
        # NOTE: Renaming the instance directory is a side-effect that needs careful handling.
        # For now, we focus on DB change. Frontend should be aware.
        # A more robust solution would handle the rename in a transaction.
        try:
            old_dir = os.path.join(INSTANCES_DIR, db_instance.name)
            new_dir = os.path.join(INSTANCES_DIR, instance_update.name)
            if os.path.isdir(old_dir):
                os.rename(old_dir, new_dir)
        except OSError as e:
            raise HTTPException(status_code=500, detail=f"Failed to rename instance directory: {e}")

    updated_instance = crud.update_instance(db, instance_id, instance_update)
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

@router.delete("/instances/{instance_id}", status_code=200, tags=["Instance Actions"])
def delete_instance(instance_id: int, options: DeleteOptions, db: Session = Depends(get_db)):
    db_instance = crud.get_instance(db, instance_id=instance_id)
    if not db_instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    if db_instance.status != "stopped":
        raise HTTPException(status_code=400, detail="Cannot delete an active instance. Please stop it first.")

    instance_dir = os.path.join(INSTANCES_DIR, db_instance.name)
    TRASH_DIR = os.path.join(os.path.dirname(INSTANCES_DIR), "trashcan")
    trash_path = os.path.join(TRASH_DIR, db_instance.name)

    if options.mode == "permanent":
        if os.path.isdir(instance_dir):
            try:
                shutil.rmtree(instance_dir)
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Could not permanently delete instance folder: {e}")
        crud.delete_instance(db, instance_id=instance_id)
        return {"ok": True, "detail": "Instance permanently deleted."}

    elif options.mode == "trash":
        if not os.path.isdir(instance_dir):
            # If there's no folder, just delete from DB
            crud.delete_instance(db, instance_id=instance_id)
            return {"ok": True, "detail": "Instance record deleted (no folder found)."}

        os.makedirs(TRASH_DIR, exist_ok=True)

        if os.path.exists(trash_path):
            if options.overwrite:
                try:
                    shutil.rmtree(trash_path) # Remove existing in trash
                    shutil.move(instance_dir, TRASH_DIR)
                except Exception as e:
                    raise HTTPException(status_code=500, detail=f"Could not overwrite destination in trashcan: {e}")
            else:
                # This is the case that needs the second modal.
                # The backend should report the conflict.
                raise HTTPException(status_code=409, detail=f"Destination path '{os.path.basename(trash_path)}' already exists in trashcan. Use 'overwrite=true' to replace it.")
        else:
            # Destination does not exist, just move it
            try:
                shutil.move(instance_dir, TRASH_DIR)
            except shutil.Error as e:
                raise HTTPException(status_code=500, detail=f"Could not move instance to trashcan: {e}")

        crud.delete_instance(db, instance_id=instance_id)
        return {"ok": True, "detail": "Instance deleted and moved to trashcan."}

    else:
        raise HTTPException(status_code=400, detail=f"Invalid delete mode: {options.mode}")
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

    instance_file_path, blueprint_file_path = get_instance_file_path(db_instance)
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
def update_instance_file(instance_id: int, file_type: str, file_content: FileContent, db: Session = Depends(get_db)):
    db_instance = crud.get_instance(db, instance_id=instance_id)
    if not db_instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    if file_type != "script":
        raise HTTPException(status_code=400, detail="Invalid file type specified")

    instance_file_path, _ = get_instance_file_path(db_instance)

    try:
        os.makedirs(os.path.dirname(instance_file_path), exist_ok=True)
        with open(instance_file_path, 'w', encoding='utf-8') as f:
            f.write(file_content.content)
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