from sqlalchemy.orm import Session
import os
import shutil
from . import models
from ..schemas import instance as schemas
from ..core.process_manager import INSTANCES_DIR, BLUEPRINTS_DIR, CUSTOM_BLUEPRINTS_DIR

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

    # Filesystem operations
    if instance.source_instance_id:
        # This is a copy operation
        source_instance = get_instance(db, instance_id=instance.source_instance_id)
        if not source_instance:
            raise FileNotFoundError(f"Source instance with ID {instance.source_instance_id} not found.")
        
        source_path = os.path.join(INSTANCES_DIR, source_instance.name)
        if not os.path.isdir(source_path):
            raise FileNotFoundError(f"Source instance directory not found at {source_path}.")

        # Copy the directory, ignoring the virtual environment
        shutil.copytree(source_path, instance_conf_dir, ignore=shutil.ignore_patterns('env'))

    else:
        # This is a standard creation from a blueprint
        os.makedirs(instance_conf_dir, exist_ok=True)
        
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