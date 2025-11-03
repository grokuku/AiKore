from fastapi import APIRouter, HTTPException, Depends
import os
import psutil
from pynvml import *
from sqlalchemy.orm import Session

from ..core.process_manager import BLUEPRINTS_DIR
from ..database import crud
from ..database.session import SessionLocal

router = APIRouter(
    prefix="/api/system",
    tags=["System"]
)

@router.get("/blueprints")
def get_available_blueprints():
    """
    Scans the blueprints directory and returns a list of available .sh scripts.
    """
    try:
        files = os.listdir(BLUEPRINTS_DIR)
        # Filter for .sh files and sort them
        sh_files = sorted([f for f in files if f.endswith('.sh')])
        return {"blueprints": sh_files}
    except FileNotFoundError:
        return {"blueprints": []}
    except Exception as e:
        # In a real app, you'd want to log this error.
        return {"blueprints": [], "error": str(e)}

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
        nvmlInit()
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
        nvmlShutdown()
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