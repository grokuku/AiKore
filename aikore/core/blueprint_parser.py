import os
from ..core.process_manager import BLUEPRINTS_DIR, CUSTOM_BLUEPRINTS_DIR

# LOT3 (M7): single shared metadata parser (dequoted values, one implementation).
from ..core.metadata_parser import parse_metadata_file


def get_blueprint_venv_path(blueprint_name: str) -> str:
    """
    Parses a blueprint file to find the 'aikore.venv_path' metadata.

    Args:
        blueprint_name: The filename of the blueprint (e.g., "ComfyUI.sh").

    Returns:
        The relative path of the venv dir (e.g., "./env") or a default
        of "./env" if not found or specified. The value is dequoted by the
        shared parser ('"#./env"'-style metadata no longer keeps its quotes).
    """
    if not blueprint_name:
        return "./env"

    # Check custom blueprints first, then stock blueprints
    custom_path = os.path.join(CUSTOM_BLUEPRINTS_DIR, blueprint_name)
    stock_path = os.path.join(BLUEPRINTS_DIR, blueprint_name)

    blueprint_path = None
    if os.path.exists(custom_path):
        blueprint_path = custom_path
    elif os.path.exists(stock_path):
        blueprint_path = stock_path

    if not blueprint_path:
        # If blueprint file doesn't exist, return default and let other parts
        # of the system handle the FileNotFoundError.
        return "./env"

    try:
        value = parse_metadata_file(blueprint_path).get("venv_path")
    except (IOError, OSError):
        # In case of read errors, fall back to default
        return "./env"

    # If the key is absent/empty, return default
    return value if value else "./env"
