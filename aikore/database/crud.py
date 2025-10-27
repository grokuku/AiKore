import os
from sqlalchemy.orm import Session
from . import models
from ..schemas import instance as schemas

def get_instance_by_name(db: Session, name: str):
    """
    Retrieve a single instance from the database by its unique name.
    """
    return db.query(models.Instance).filter(models.Instance.name == name).first()

def get_instance_by_port(db: Session, port: int):
    """
    Retrieve a single instance from the database by its assigned public port.
    """
    return db.query(models.Instance).filter(models.Instance.port == port).first()

def get_instances(db: Session, skip: int = 0, limit: int = 100):
    """
    Retrieve a list of all instances from the database, with pagination.
    """
    return db.query(models.Instance).offset(skip).limit(limit).all()

def get_autostart_instances(db: Session):
    """
    Retrieve all instances that are marked for autostart.
    """
    return db.query(models.Instance).filter(models.Instance.autostart == True).all()

def get_active_comfyui_slot(db: Session):
    """
    Retrieve the instance currently marked as the active ComfyUI slot.
    """
    return db.query(models.Instance).filter(models.Instance.is_comfyui_active_slot == True).first()

def unset_all_active_comfyui_slots(db: Session):
    """
    Sets is_comfyui_active_slot to False for all instances.
    """
    db.query(models.Instance).filter(models.Instance.is_comfyui_active_slot == True).update({"is_comfyui_active_slot": False})
    db.commit()

def set_active_comfyui_slot(db: Session, instance_to_activate: models.Instance):
    """
    Sets a specific instance as the active ComfyUI slot, deactivating any other.
    """
    # First, deactivate any currently active slot
    unset_all_active_comfyui_slots(db)
    
    # Then, activate the new one
    instance_to_activate.is_comfyui_active_slot = True
    db.commit()
    db.refresh(instance_to_activate)
    return instance_to_activate

def create_instance(
    db: Session, 
    instance: schemas.InstanceCreate,
    vnc_port: int | None,
    vnc_display: int | None
):
    """
    Create a new instance record in the database using user-provided data.
    """
    instance_data = instance.model_dump()
    db_instance = models.Instance(
        **instance_data,
        vnc_port=vnc_port,
        vnc_display=vnc_display,
        is_comfyui_active_slot=False # Explicitly set to false on creation
    )
    db.add(db_instance)
    db.commit()
    db.refresh(db_instance)
    return db_instance

def update_instance_access_pattern(db: Session, instance_id: int, access_pattern: str):
    """
    Updates the access_pattern for a specific instance.
    """
    db_instance = db.query(models.Instance).filter(models.Instance.id == instance_id).first()
    if db_instance:
        db_instance.access_pattern = access_pattern
        db.commit()
        db.refresh(db_instance)
    return db_instance

def update_instance_status(
    db: Session,
    instance_id: int,
    status: str,
    pid: int | None = None,
    port: int | None = None,
    vnc_port: int | None = None,
    vnc_display: int | None = None
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
        db_instance.vnc_port = vnc_port
        db_instance.vnc_display = vnc_display
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