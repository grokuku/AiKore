from fastapi import APIRouter, HTTPException, Depends, Body
from pydantic import BaseModel
import os
import psutil
from pynvml import (
    NVMLError,
    nvmlDeviceGetCount,
    nvmlDeviceGetHandleByIndex,
    nvmlDeviceGetMemoryInfo,
    nvmlDeviceGetName,
    nvmlDeviceGetUtilizationRates
)
from sqlalchemy.orm import Session
import re

from ..core.process_manager import BLUEPRINTS_DIR, CUSTOM_BLUEPRINTS_DIR
from ..database import crud
from ..database.session import SessionLocal

router = APIRouter(
    prefix="/api/system",
    tags=["System"]
)

class CustomBlueprint(BaseModel):
    filename: str
    content: str

@router.get("/blueprints")
def get_available_blueprints():
    """
    Scans stock and custom blueprint directories and returns a categorized list of available .sh scripts.
    """
    stock_blueprints = []
    custom_blueprints = []
    
    try:
        # Scan stock blueprints
        if os.path.isdir(BLUEPRINTS_DIR):
            stock_files = os.listdir(BLUEPRINTS_DIR)
            stock_blueprints = sorted([f for f in stock_files if f.endswith('.sh')])
        
        # Scan custom blueprints
        os.makedirs(CUSTOM_BLUEPRINTS_DIR, exist_ok=True) # Ensure it exists
        if os.path.isdir(CUSTOM_BLUEPRINTS_DIR):
            custom_files = os.listdir(CUSTOM_BLUEPRINTS_DIR)
            custom_blueprints = sorted([f for f in custom_files if f.endswith('.sh')])
            
        return {"stock": stock_blueprints, "custom": custom_blueprints}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read blueprints: {str(e)}")

@router.post("/blueprints/custom", status_code=201)
def create_custom_blueprint(blueprint: CustomBlueprint):
    """
    Creates a new custom blueprint file from user-provided content.
    """
    # Validate filename to prevent directory traversal and ensure it's a .sh file
    filename = blueprint.filename
    if not filename.endswith(".sh"):
        raise HTTPException(status_code=400, detail="Filename must end with .sh")
    if "/" in filename or ".." in filename or not re.match(r"^[a-zA-Z0-9_\-]+\.sh$", filename):
        raise HTTPException(status_code=400, detail="Invalid filename. Use only alphanumeric characters, underscores, and hyphens.")

    filepath = os.path.join(CUSTOM_BLUEPRINTS_DIR, filename)

    if os.path.exists(filepath):
        raise HTTPException(status_code=409, detail=f"A custom blueprint with the name '{filename}' already exists.")

    try:
        os.makedirs(CUSTOM_BLUEPRINTS_DIR, exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(blueprint.content)
        return {"detail": "Custom blueprint created successfully.", "filename": filename}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write blueprint file: {str(e)}")


@router.get("/info")
def get_system_info():
    """
    Retrieves basic system information, like GPU count.
    """
    info = {}
    try:
        info["gpu_count"] = nvmlDeviceGetCount()
    except NVMLError:
        info["gpu_count"] = 0
    return info

@router.get("/stats")
def get_system_stats():
    """
    Retrieves system and GPU statistics.
    """
    stats = {
        "cpu_percent": psutil.cpu_percent(interval=None),
        "ram": {
            "total": psutil.virtual_memory().total,
            "used": psutil.virtual_memory().used,
            "percent": psutil.virtual_memory().percent
        },
        "gpus": []
    }

    try:
        device_count = nvmlDeviceGetCount()
        for i in range(device_count):
            handle = nvmlDeviceGetHandleByIndex(i)
            
            # Get memory info
            mem_info = nvmlDeviceGetMemoryInfo(handle)
            
            # Get utilization rates
            util_rates = nvmlDeviceGetUtilizationRates(handle)
            
            gpu_info = {
                "id": i,
                "name": nvmlDeviceGetName(handle),
                "vram": {
                    "total": mem_info.total,
                    "used": mem_info.used,
                    "percent": round((mem_info.used / mem_info.total) * 100, 2) if mem_info.total > 0 else 0
                },
                "utilization_percent": util_rates.gpu
            }
            stats["gpus"].append(gpu_info)
    except NVMLError as error:
        # This can happen if NVIDIA drivers are not installed or no GPU is found.
        # We'll just return the stats without GPU info.
        print(f"NVMLError: {error}. Proceeding without GPU stats.")
    except Exception as e:
        # Catch other potential errors to prevent the endpoint from crashing.
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred while fetching system stats: {str(e)}")
        
    return stats

@router.get("/debug-nginx")
def debug_nginx():
    nginx_log_path = "/var/log/nginx/debug.log"
    locations_dir = "/etc/nginx/locations.d"
    log_content = ""
    locations_content = {}

    try:
        if os.path.exists(nginx_log_path):
            with open(nginx_log_path, "r", encoding='utf-8', errors='ignore') as f:
                log_content = f.read()
        else:
            log_content = "NGINX debug log not found at " + nginx_log_path
    except Exception as e:
        log_content = f"Error reading log file: {e}"

    try:
        if os.path.isdir(locations_dir):
            for filename in os.listdir(locations_dir):
                filepath = os.path.join(locations_dir, filename)
                if os.path.isfile(filepath):
                    with open(filepath, "r", encoding='utf-8', errors='ignore') as f:
                        locations_content[filename] = f.read()
        else:
            locations_content["error"] = "locations.d directory not found at " + locations_dir
    except Exception as e:
        locations_content["error"] = f"Error reading locations dir: {e}"

    return {
        "nginx_debug_log": log_content,
        "locations_d": locations_content,
    }

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("/available-ports")
def get_available_ports(db: Session = Depends(get_db)):
    """
    Returns a list of available ports for new instances based on the configured range.
    """
    port_range_str = os.environ.get("AIKORE_INSTANCE_PORT_RANGE", "19001-19020")
    try:
        start_port, end_port = map(int, port_range_str.split('-'))
        if start_port > end_port:
            raise ValueError("Start port must be less than or equal to end port.")
        all_possible_ports = set(range(start_port, end_port + 1))
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=500,
            detail=f"Invalid AIKORE_INSTANCE_PORT_RANGE format: '{port_range_str}'. Expected 'start-end'."
        )

    instances = crud.get_instances(db, limit=1000) # Get all instances
    used_ports = {instance.port for instance in instances if instance.port is not None}
    
    available_ports = sorted(list(all_possible_ports - used_ports))
    
    return {"available_ports": available_ports}