#!/bin/bash
# Exit immediately if a command exits with a non-zero status.
set -e

### AIKORE-METADATA-START ###
# aikore.name = DPGui
# aikore.category = Training
# aikore.description = A web UI for managing and launching diffusion-pipe training jobs. The blueprint prepares a minimal Conda environment and runs the app's native launcher.
# aikore.venv_type = conda
# aikore.venv_path = ./env
### AIKORE-METADATA-END ###

# Source the global helper functions
source /opt/sd-install/functions.sh

echo "--- Starting Blueprint: DPGui (Minimal Launcher) for Instance: ${INSTANCE_NAME} ---"

# --- Variable Definitions ---
# The root instance directory provided by AiKore
INSTANCE_ROOT_DIR="${INSTANCE_CONF_DIR}"
# The application code will be cloned into this subdirectory
DPGUI_DIR="${INSTANCE_ROOT_DIR}/dpgui"
VENV_DIR="${INSTANCE_ROOT_DIR}/env"

# --- Git Repository Setup ---
# The blueprint MUST clone the application code itself.
if [ ! -d "${DPGUI_DIR}/.git" ]; then
    echo "Cloning DPGui repository into ${DPGUI_DIR}..."
    git clone https://github.com/grokuku/dpgui.git "${DPGUI_DIR}"
else
    echo "DPGui repository found. Skipping clone."
    # Optional: Add logic here to pull latest changes if needed
fi

# Ensure other instance directories exist
mkdir -p "${INSTANCE_ROOT_DIR}"
mkdir -p "${INSTANCE_OUTPUT_DIR}"

# --- Conda Environment Setup ---
echo "--- Setting up Conda environment ---"
clean_env "${VENV_DIR}"

if [ ! -d "${VENV_DIR}" ]; then
    echo "Creating Conda environment with Python 3.11 and Node.js..."
    conda create -p "${VENV_DIR}" python=3.11 nodejs -c conda-forge -y
fi

# Activate the environment for the rest of the script
source activate "${VENV_DIR}"
echo "--- Conda environment activated. ---"


# --- Configuration & Symlinks ---
echo "--- Applying configurations ---"
# Symlink the instance's output directory to the app's 'output' folder
sl_folder "${DPGUI_DIR}" "output" "$(dirname "${INSTANCE_OUTPUT_DIR}")" "$(basename "${INSTANCE_OUTPUT_DIR}")"


# --- Launch Application ---
echo "--- Handing over to the application's native launcher ---"

# The native launcher.sh script uses DPGUI_PORT to set the public-facing port.
export DPGUI_PORT="${WEBUI_PORT}"

# Execute the project's own launcher script.
# It will handle cloning vendor repos, installing pip/npm packages, and starting the services.
echo "Changing directory to ${DPGUI_DIR}"
cd "${DPGUI_DIR}"

LAUNCH_SCRIPT_PATH="./scripts/launcher.sh"
if [ -f "$LAUNCH_SCRIPT_PATH" ]; then
    bash "$LAUNCH_SCRIPT_PATH"
else
    echo "FATAL: Launcher script not found at ${LAUNCH_SCRIPT_PATH}"
    exit 1
fi


echo "--- DPGui Blueprint Finished ---"
