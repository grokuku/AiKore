from sqlalchemy.orm import Session
import os
import shutil
import subprocess
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

def copy_instance(db: Session, source_instance_id: int, new_name: str):
    """
    Creates a complete clone of an existing instance, including its Conda environment.
    """
    # 1. Validation
    if get_instance_by_name(db, name=new_name):
        raise ValueError(f"Instance with name '{new_name}' already exists.")
    
    source_instance = get_instance(db, instance_id=source_instance_id)
    if not source_instance:
        raise ValueError(f"Source instance with ID {source_instance_id} not found.")

    source_dir = os.path.join(INSTANCES_DIR, source_instance.name)
    clone_dir = os.path.join(INSTANCES_DIR, new_name)
    
    if not os.path.isdir(source_dir):
        raise FileNotFoundError(f"Source instance directory not found at {source_dir}")

    # 2. Database Entry
    db_instance = models.Instance(
        name=new_name,
        base_blueprint=source_instance.base_blueprint,
        gpu_ids=source_instance.gpu_ids,
        autostart=source_instance.autostart,
        persistent_mode=source_instance.persistent_mode,
        output_path=source_instance.output_path,
        hostname=source_instance.hostname,
        use_custom_hostname=False, # As per requirement
        status="stopped"
    )
    db.add(db_instance)
    db.commit()
    db.refresh(db_instance)

    # 3. Filesystem and Environment Cloning
    try:
        # Copy the entire source directory first
        shutil.copytree(source_dir, clone_dir)

        # Clone the conda environment
        source_env_path = os.path.join(source_dir, "env")
        clone_env_path = os.path.join(clone_dir, "env")

        if os.path.isdir(source_env_path):
            # Remove the copied 'env' and clone it properly
            shutil.rmtree(clone_env_path)
            
            print(f"Cloning Conda environment from {source_env_path} to {clone_env_path}...")
            # Using --prefix for non-activated env creation
            result = subprocess.run(
                ["conda", "create", "--prefix", clone_env_path, "--clone", source_env_path, "-y"],
                capture_output=True, text=True
            )
            if result.returncode != 0:
                raise Exception(f"Conda clone failed: {result.stderr}")
            print("Conda environment cloned successfully.")

        # Update the launch.sh to point to the new env
        launch_script_path = os.path.join(clone_dir, "launch.sh")
        if os.path.exists(launch_script_path):
            with open(launch_script_path, 'r') as f:
                script_content = f.read()
            
            # Replace the old instance name in the env path with the new one
            updated_content = script_content.replace(
                f"/config/instances/{source_instance.name}/env",
                f"/config/instances/{new_name}/env"
            )
            
            with open(launch_script_path, 'w') as f:
                f.write(updated_content)
            print(f"Updated launch.sh for instance '{new_name}'.")

    except Exception as e:
        # Cleanup on failure
        db.delete(db_instance)
        db.commit()
        if os.path.isdir(clone_dir):
            shutil.rmtree(clone_dir)
        raise e

    return db_instance

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
    instance_dir = os.path.join(INSTANCES_DIR, new_name)
    os.makedirs(instance_dir, exist_ok=True)

    # 3. Database Entry
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
        status="stopped"
        # port, pid, etc., are left as None until started
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