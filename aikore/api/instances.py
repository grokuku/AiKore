from fastapi import APIRouter, Depends, HTTPException, Body, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Any
import os
import shutil
import asyncio
import psutil
import json

from ..database import crud
from ..database.session import SessionLocal
from ..schemas import instance as schemas
from ..core import process_manager
from ..core.process_manager import INSTANCES_DIR, BLUEPRINTS_DIR, _find_free_port, _find_free_display, parse_blueprint_metadata, running_instances

router = APIRouter(
    prefix="/api/instances",
    tags=["Instances"]
)

class FileContent(BaseModel):
    content: str
    
class AccessPatternUpdate(BaseModel):
    access_pattern: str

class ActivationResult(BaseModel):
    success: bool
    message: str
    conflict: bool = False
    conflicting_instance_name: str | None = None

# Custom response model to include the 'is_active' status
class InstanceResponse(schemas.Instance):
    is_active: bool

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

@router.post("/", response_model=schemas.Instance)
def create_new_instance(instance: schemas.InstanceCreate, db: Session = Depends(get_db)):
    # Check for name conflict
    if crud.get_instance_by_name(db, name=instance.name):
        raise HTTPException(status_code=400, detail="Instance with this name already exists")
    
    # Check for port conflict
    if crud.get_instance_by_port(db, port=instance.port):
        raise HTTPException(status_code=400, detail=f"Public port {instance.port} is already assigned to another instance.")

    vnc_port = _find_free_port() if instance.persistent_mode else None
    vnc_display = _find_free_display() if instance.persistent_mode else None
    
    return crud.create_instance(
        db=db, 
        instance=instance,
        vnc_port=vnc_port,
        vnc_display=vnc_display
    )

@router.get("/", response_model=List[InstanceResponse])
def read_all_instances(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    instances = crud.get_instances(db, skip=skip, limit=limit)
    response_data = []
    for inst in instances:
        # Convert SQLAlchemy model to Pydantic model
        inst_data = schemas.Instance.model_validate(inst)
        # Add our custom field
        is_active = (
            inst.id in running_instances and
            running_instances[inst.id].get("activation_process") is not None
        )
        response_data.append(InstanceResponse(**inst_data.model_dump(), is_active=is_active))
    return response_data

@router.put("/{instance_id}/access-pattern", response_model=schemas.Instance, tags=["Instance Actions"])
def update_access_pattern(instance_id: int, payload: AccessPatternUpdate, db: Session = Depends(get_db)):
    db_instance = crud.get_instance(db, instance_id=instance_id)
    if not db_instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    if payload.access_pattern not in ["port", "subdomain"]:
        raise HTTPException(status_code=400, detail="Invalid access pattern. Must be 'port' or 'subdomain'.")
        
    return crud.update_instance_access_pattern(db, instance_id, payload.access_pattern)

@router.post("/{instance_id}/activate", response_model=ActivationResult, tags=["Instance Actions"])
def activate_port(instance_id: int, force: bool = False, db: Session = Depends(get_db)):
    db_instance = crud.get_instance(db, instance_id=instance_id)
    if not db_instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    if db_instance.status != "started":
        raise HTTPException(status_code=400, detail="Instance must be in 'started' status to be activated.")
    if db_instance.persistent_mode:
        raise HTTPException(status_code=400, detail="Port activation is not applicable for persistent mode instances.")

    # Find if another instance is currently active on this port
    conflicting_instance = None
    for inst_id, state in running_instances.items():
        if state.get("activation_process") is not None:
            # This instance is active. Is its public port the same as ours?
            other_instance = crud.get_instance(db, inst_id)
            if other_instance and other_instance.port == db_instance.port:
                conflicting_instance = other_instance
                break
    
    if conflicting_instance and not force:
        return ActivationResult(
            success=False,
            message=f"Port {db_instance.port} is already in use.",
            conflict=True,
            conflicting_instance_name=conflicting_instance.name
        )
    
    if conflicting_instance and force:
        print(f"Force activation: deactivating instance '{conflicting_instance.name}'...")
        process_manager.deactivate_instance_port(conflicting_instance.id)

    try:
        process_manager.activate_instance_port(db_instance)
        return ActivationResult(success=True, message="Instance activated successfully.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to activate instance: {e}")

@router.post("/{instance_id}/deactivate", response_model=ActivationResult, tags=["Instance Actions"])
def deactivate_port(instance_id: int, db: Session = Depends(get_db)):
    db_instance = crud.get_instance(db, instance_id=instance_id)
    if not db_instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    
    try:
        process_manager.deactivate_instance_port(instance_id)
        return ActivationResult(success=True, message="Instance deactivated successfully.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to deactivate instance: {e}")

@router.post("/{instance_id}/start", response_model=schemas.Instance, tags=["Instance Actions"])
def start_instance(instance_id: int, db: Session = Depends(get_db)):
    db_instance = crud.get_instance(db, instance_id=instance_id)
    if not db_instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    if db_instance.status != "stopped":
        raise HTTPException(status_code=400, detail=f"Instance cannot be started from status '{db_instance.status}'")

    try:
        process_manager.start_instance_process(db=db, instance=db_instance)
        return db_instance
    except Exception as e:
        db_instance.status = "stopped"
        db.commit()
        raise HTTPException(status_code=500, detail=f"Failed to start instance: {str(e)}")

@router.post("/{instance_id}/stop", response_model=schemas.Instance, tags=["Instance Actions"])
def stop_instance(instance_id: int, db: Session = Depends(get_db)):
    db_instance = crud.get_instance(db, instance_id=instance_id)
    if not db_instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    if db_instance.status == "stopped":
        raise HTTPException(status_code=400, detail="Instance is already stopped")

    try:
        is_active_slot = db_instance.is_comfyui_active_slot
        process_manager.stop_instance_process(db=db, instance=db_instance)
        if is_active_slot:
            crud.unset_all_active_comfyui_slots(db)
            process_manager.update_comfyui_proxy(db)
        return db_instance
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to stop instance: {str(e)}")

@router.post("/{instance_id}/activate-comfyui", response_model=schemas.Instance, tags=["Instance Actions"])
def activate_comfyui_slot(instance_id: int, db: Session = Depends(get_db)):
    db_instance = crud.get_instance(db, instance_id=instance_id)
    if not db_instance:
        raise HTTPException(status_code=404, detail="Instance not found")

    metadata = parse_blueprint_metadata(db_instance.base_blueprint)
    if metadata.get('app_id') != 'comfyui':
        raise HTTPException(status_code=400, detail="This action is only for ComfyUI instances.")
    if db_instance.persistent_mode:
        raise HTTPException(status_code=400, detail="Cannot activate UI slot for an instance in persistent mode.")
    if db_instance.status != "started":
        raise HTTPException(status_code=400, detail="Instance must be in 'started' status to be activated.")

    crud.set_active_comfyui_slot(db, db_instance)
    process_manager.update_comfyui_proxy(db)

    return db_instance

@router.delete("/{instance_id}", status_code=200, tags=["Instance Actions"])
def delete_instance(instance_id: int, db: Session = Depends(get_db)):
    db_instance = crud.get_instance(db, instance_id=instance_id)
    if not db_instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    if db_instance.status != "stopped":
        raise HTTPException(status_code=400, detail="Cannot delete an active instance. Please stop it first.")

    if db_instance.is_comfyui_active_slot:
        crud.unset_all_active_comfyui_slots(db)
        process_manager.update_comfyui_proxy(db)

    instance_dir = os.path.join(INSTANCES_DIR, db_instance.name)
    TRASH_DIR = os.path.join(os.path.dirname(INSTANCES_DIR), "trashcan")

    if os.path.isdir(instance_dir):
        os.makedirs(TRASH_DIR, exist_ok=True)
        try:
            shutil.move(instance_dir, TRASH_DIR)
        except shutil.Error as e:
            raise HTTPException(status_code=500, detail=f"Could not move instance to trashcan: {e}")

    crud.delete_instance(db, instance_id=instance_id)
    return {"ok": True, "detail": "Instance deleted and moved to trashcan."}

@router.get("/{instance_id}/logs", tags=["Instance Actions"])
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

@router.get("/{instance_id}/file", response_model=FileContent, tags=["Instance Actions"])
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
        
@router.put("/{instance_id}/file", status_code=200, tags=["Instance Actions"])
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

@router.websocket("/{instance_id}/terminal", name="Instance Terminal")
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
                if message.strip().startswith('{'):
                    try:
                        data = json.loads(message)
                        if isinstance(data, dict) and data.get("type") == "resize" and "rows" in data and "cols" in data:
                            process_manager.resize_terminal_process(master_fd, data['rows'], data['cols'])
                            continue
                    except (json.JSONDecodeError, TypeError):
                        pass
                
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
            await websocket.close()