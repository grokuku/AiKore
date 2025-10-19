from fastapi import APIRouter, HTTPException
import os
import psutil
from pynvml import *

from ..core.process_manager import BLUEPRINTS_DIR

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