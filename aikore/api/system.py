from fastapi import APIRouter
import os

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