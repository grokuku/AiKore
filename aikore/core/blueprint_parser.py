import os
from ..core.process_manager import BLUEPRINTS_DIR, CUSTOM_BLUEPRINTS_DIR

def get_blueprint_venv_path(blueprint_name: str) -> str:
    """
    Parses a blueprint file to find the 'aikore.venv_path' metadata.

    Args:
        blueprint_name: The filename of the blueprint (e.g., "ComfyUI.sh").

    Returns:
        The relative path of the venv dir (e.g., "./env") or a default
        of "./env" if not found or specified.
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
        with open(blueprint_path, 'r', encoding='utf-8') as f:
            in_metadata_block = False
            for line in f:
                line = line.strip()
                if line == '### AIKORE-METADATA-START ###':
                    in_metadata_block = True
                    continue
                if line == '### AIKORE-METADATA-END ###':
                    break
                
                if in_metadata_block and line.startswith('#'):
                    # Remove '#' and leading/trailing whitespace
                    cleaned_line = line.lstrip('#').strip()
                    if '=' in cleaned_line:
                        key, value = cleaned_line.split('=', 1)
                        key = key.strip()
                        value = value.strip()
                        if key == 'aikore.venv_path':
                            # Return the found value immediately
                            return value
    except (IOError, FileNotFoundError):
        # In case of read errors, fall back to default
        return "./env"

    # If loop finishes without finding the key, return default
    return "./env"
