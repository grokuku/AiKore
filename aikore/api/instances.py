from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from typing import List
import os

from ..database import crud
from ..database.session import SessionLocal
from ..schemas import instance as schemas
from ..core import process_manager
from ..core.process_manager import INSTANCES_DIR, BLUEPRINTS_DIR, _find_free_port, _find_free_display

router = APIRouter(
    prefix="/api/instances",
    tags=["Instances"]
)

class FileContent(schemas.BaseModel):
    content: str

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
    db_instance = crud.get_instance_by_name(db, name=instance.name)
    if db_instance:
        raise HTTPException(status_code=400, detail="Instance with this name already exists")
    
    # Pre-allocate ports and display number
    app_port = _find_free_port()
    vnc_port = _find_free_port() if instance.persistent_mode else None
    vnc_display = _find_free_display() if instance.persistent_mode else None
    
    return crud.create_instance(
        db=db, 
        instance=instance,
        port=app_port,
        vnc_port=vnc_port,
        vnc_display=vnc_display
    )

@router.get("/", response_model=List[schemas.Instance])
def read_all_instances(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    instances = crud.get_instances(db, skip=skip, limit=limit)
    return instances

@router.post("/{instance_id}/start", response_model=schemas.Instance, tags=["Instance Actions"])
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

@router.post("/{instance_id}/stop", response_model=schemas.Instance, tags=["Instance Actions"])
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

@router.delete("/{instance_id}", status_code=200, tags=["Instance Actions"])
def delete_instance(instance_id: int, db: Session = Depends(get_db)):
    db_instance = crud.get_instance(db, instance_id=instance_id)
    if not db_instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    if db_instance.status != "stopped":
        raise HTTPException(status_code=400, detail="Cannot delete an active instance. Please stop it first.")
    
    # Cleanup is now part of stop, but we call it here just in case of leftover files
    process_manager._cleanup_instance_files(process_manager._slugify(db_instance.name))
    
    crud.delete_instance(db, instance_id=instance_id)
    return {"ok": True, "detail": "Instance deleted successfully"}

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