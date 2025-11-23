from sqlalchemy.orm import Session
import os
import shutil
import subprocess
import traceback
from . import models
from ..schemas import instance as schemas
from ..core.process_manager import INSTANCES_DIR, BLUEPRINTS_DIR, CUSTOM_BLUEPRINTS_DIR
from ..core.blueprint_parser import get_blueprint_venv_path

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
        # FIX: symlinks=True prevents copying the content of huge model folders.
        shutil.copytree(source_path, instance_conf_dir, ignore=shutil.ignore_patterns('env'), symlinks=True)

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

def create_copy_placeholder(db: Session, source_instance_id: int, new_name: str):
    """
    STEP 1: Creates the DB entry immediately with 'installing' status.
    """
    # 1. Validation
    if get_instance_by_name(db, name=new_name):
        raise ValueError(f"Instance with name '{new_name}' already exists.")
    
    source_instance = get_instance(db, instance_id=source_instance_id)
    if not source_instance:
        raise ValueError(f"Source instance with ID {source_instance_id} not found.")

    # 2. Create Database Entry immediately
    # explicitly set ports to None so they get allocated on first start (Self-Healing)
    db_instance = models.Instance(
        name=new_name,
        base_blueprint=source_instance.base_blueprint,
        gpu_ids=source_instance.gpu_ids,
        autostart=source_instance.autostart,
        persistent_mode=source_instance.persistent_mode,
        output_path=source_instance.output_path,
        hostname=source_instance.hostname,
        use_custom_hostname=False,
        status="installing", # <--- NEW STATUS indicating background work
        port=None,
        persistent_port=None,
        persistent_display=None
    )
    db.add(db_instance)
    db.commit()
    db.refresh(db_instance)
    
    return db_instance

def process_background_copy(db: Session, new_instance_id: int, source_instance_id: int):
    """
    STEP 2: Heavy lifting (Filesystem & Conda) running in background.
    """
    print(f"[Background] Starting copy process for instance ID {new_instance_id}...")
    
    new_instance = get_instance(db, new_instance_id)
    source_instance = get_instance(db, source_instance_id)
    
    if not new_instance or not source_instance:
        print("[Background] Error: Instance record missing.")
        return

    source_dir = os.path.join(INSTANCES_DIR, source_instance.name)
    clone_dir = os.path.join(INSTANCES_DIR, new_instance.name)
    
    try:
        # 1. Get venv path info
        venv_path_str = get_blueprint_venv_path(source_instance.base_blueprint)
        venv_dir_name = os.path.normpath(venv_path_str).replace('.', '').strip(os.sep)

        # 2. Filesystem Copy (Symlinks preserved!)
        print(f"[Background] Copying files from {source_dir} to {clone_dir}...")
        if os.path.exists(clone_dir):
             shutil.rmtree(clone_dir) # Safety cleanup if retrying
             
        shutil.copytree(
            source_dir, 
            clone_dir, 
            ignore=shutil.ignore_patterns(venv_dir_name), 
            symlinks=True
        )

        # 3. Clone Conda Environment
        source_env_path = os.path.join(source_dir, venv_dir_name)
        clone_env_path = os.path.join(clone_dir, venv_dir_name)

        if os.path.isdir(source_env_path):
            print(f"[Background] Cloning Conda environment...")
            subprocess.run(
                ["conda", "create", "--prefix", clone_env_path, "--clone", source_env_path, "-y"],
                capture_output=True, text=True, check=True
            )

        # 4. Update launch.sh
        launch_script_path = os.path.join(clone_dir, "launch.sh")
        if os.path.exists(launch_script_path):
            with open(launch_script_path, 'r') as f:
                script_content = f.read()
            
            old_base_path = f"/config/instances/{source_instance.name}"
            new_base_path = f"/config/instances/{new_instance.name}"
            updated_content = script_content.replace(old_base_path, new_base_path)
            
            with open(launch_script_path, 'w') as f:
                f.write(updated_content)

        # SUCCESS: Update status to 'stopped'
        new_instance.status = "stopped"
        db.commit()
        print(f"[Background] Clone successful for '{new_instance.name}'.")

    except Exception as e:
        print(f"[Background] CRITICAL ERROR cloning instance: {e}")
        traceback.print_exc()
        
        # FAILURE: Update status to 'error'
        new_instance.status = "error"
        db.commit()
        
        # Cleanup partial files
        if os.path.isdir(clone_dir):
            shutil.rmtree(clone_dir, ignore_errors=True)

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
    # Explicitly clear ports so they get allocated on start
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
        status="stopped",
        port=None,
        persistent_port=None,
        persistent_display=None
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