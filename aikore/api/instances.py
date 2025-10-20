from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from typing import List
import os
import signal

from ..database import crud
from ..database.session import SessionLocal
from ..schemas import instance as schemas
from ..core import process_manager
from ..core.process_manager import INSTANCES_DIR, BLUEPRINTS_DIR # Import constants

router = APIRouter(
    prefix="/api/instances",
    tags=["Instances"]
)

# Define a simple Pydantic model for the request body of the file update
class FileContent(schemas.BaseModel):
    content: str

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Helper function to resolve file paths
def get_instance_file_path(db_instance):
    """
    Gets the path for an instance's file.
    The instance-specific script is ALWAYS named 'launch.sh'.
    The blueprint path is the original script name.
    """
    base_script_name = db_instance.base_blueprint
    instance_conf_dir = os.path.join(INSTANCES_DIR, db_instance.name)
    
    # The customized script for an instance is ALWAYS saved as launch.sh
    instance_file_path = os.path.join(instance_conf_dir, "launch.sh")
    
    # The original blueprint file path keeps its original name
    blueprint_file_path = os.path.join(BLUEPRINTS_DIR, base_script_name)

    return instance_file_path, blueprint_file_path

@router.post("/", response_model=schemas.Instance)
def create_new_instance(instance: schemas.InstanceCreate, db: Session = Depends(get_db)):
    db_instance = crud.get_instance_by_name(db, name=instance.name)
    if db_instance:
        raise HTTPException(status_code=400, detail="Instance with this name already exists")
    return crud.create_instance(db=db, instance=instance)

@router.get("/", response_model=List[schemas.Instance])
def read_all_instances(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    instances = crud.get_instances(db, skip=skip, limit=limit)
    return instances

@router.post("/{instance_id}/start", response_model=schemas.Instance, tags=["Instance Actions"])
def start_instance(instance_id: int, db: Session = Depends(get_db)):
    db_instance = crud.get_instance(db, instance_id=instance_id)
    if not db_instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    if db_instance.status == "running":
        raise HTTPException(status_code=400, detail="Instance is already running")

    crud.update_instance_status(db, instance_id=instance_id, status="starting")
    try:
        pid, app_port, vnc_port, vnc_display = process_manager.start_instance_process(
            instance_name=db_instance.name,
            blueprint_script=db_instance.base_blueprint,
            gpu_ids=db_instance.gpu_ids,
            persistent_mode=db_instance.persistent_mode
        )
        updated_instance = crud.update_instance_status(
            db, instance_id=instance_id, status="running", 
            pid=pid, port=app_port, vnc_port=vnc_port, vnc_display=vnc_display
        )
        return updated_instance
    except Exception as e:
        crud.update_instance_status(db, instance_id=instance_id, status="error")
        raise HTTPException(status_code=500, detail=f"Failed to start instance: {str(e)}")

@router.post("/{instance_id}/stop", response_model=schemas.Instance, tags=["Instance Actions"])
def stop_instance(instance_id: int, db: Session = Depends(get_db)):
    db_instance = crud.get_instance(db, instance_id=instance_id)
    if not db_instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    if db_instance.status != "running" or not db_instance.pid:
        raise HTTPException(status_code=400, detail="Instance is not running")

    try:
        os.killpg(os.getpgid(db_instance.pid), signal.SIGTERM)
    except ProcessLookupError:
        pass # Process already dead
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to stop process: {str(e)}")
    
    # Clean up NGINX config
    process_manager.cleanup_instance_process(instance_name=db_instance.name)
    
    updated_instance = crud.update_instance_status(
        db, instance_id=instance_id, status="stopped", 
        pid=None, port=None, vnc_port=None, vnc_display=None
    )
    return updated_instance

@router.delete("/{instance_id}", status_code=200, tags=["Instance Actions"])
def delete_instance(instance_id: int, db: Session = Depends(get_db)):
    db_instance = crud.get_instance(db, instance_id=instance_id)
    if not db_instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    if db_instance.status == "running":
        raise HTTPException(status_code=400, detail="Cannot delete a running instance. Please stop it first.")
    
    # In case a config is left over from an errored state
    process_manager.cleanup_instance_process(instance_name=db_instance.name)
    
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
        # This can happen in a race condition if the file is deleted after os.path.exists
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
        # Ensure the instance config directory exists
        os.makedirs(os.path.dirname(instance_file_path), exist_ok=True)
        
        with open(instance_file_path, 'w', encoding='utf-8') as f:
            f.write(file_content.content)
        
        return {"ok": True, "detail": "File updated successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error writing file: {str(e)}")