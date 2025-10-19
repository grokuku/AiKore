from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
import os
import signal

from ..database import crud
from ..database.session import SessionLocal
from ..schemas import instance as schemas
from ..core import process_manager
from ..core.process_manager import INSTANCES_DIR # Import the constant

router = APIRouter(
    prefix="/api/instances",
    tags=["Instances"]
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

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
        pid, port = process_manager.start_instance_process(
            instance_name=db_instance.name,
            blueprint_script=db_instance.base_blueprint,
            gpu_ids=db_instance.gpu_ids
        )
        updated_instance = crud.update_instance_status(db, instance_id=instance_id, status="running", pid=pid, port=port)
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
    
    updated_instance = crud.update_instance_status(db, instance_id=instance_id, status="stopped", pid=None, port=None)
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
def get_instance_logs(instance_id: int, db: Session = Depends(get_db)):
    db_instance = crud.get_instance(db, instance_id=instance_id)
    if not db_instance:
        raise HTTPException(status_code=404, detail="Instance not found")

    instance_conf_dir = os.path.join(INSTANCES_DIR, db_instance.name)
    stdout_log_path = os.path.join(instance_conf_dir, "stdout.log")
    stderr_log_path = os.path.join(instance_conf_dir, "stderr.log")

    logs = []
    if os.path.exists(stdout_log_path):
        with open(stdout_log_path, 'r') as f:
            logs.append("--- STDOUT ---")
            logs.append(f.read())
    
    if os.path.exists(stderr_log_path):
        with open(stderr_log_path, 'r') as f:
            logs.append("\n--- STDERR ---")
            logs.append(f.read())

    if not logs:
        return {"logs": "No log files found for this instance. It might have never been started."}

    return {"logs": "\n".join(logs)}