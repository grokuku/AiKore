### AIKORE-METADATA-START ###
# aikore.name = IOPaint
# aikore.category = Image Editing
# aikore.description = A free and open-source inpainting/outpainting tool powered by SOTA AI models (LaMa, MAT, etc.).
# aikore.venv_type = conda
# aikore.venv_path = ./env
### AIKORE-METADATA-END ###

#!/bin/bash
# Exit immediately if a command exits with a non-zero status.
set -e

source /opt/sd-install/functions.sh

export PATH="/home/abc/miniconda3/bin:$PATH"

# The following variables are provided by the process manager:
# - INSTANCE_NAME: The unique user-defined name for this instance.
# - INSTANCE_CONF_DIR: The dedicated directory for this instance's configuration.
# - INSTANCE_OUTPUT_DIR: The dedicated directory for this instance's generated outputs.
# - WEBUI_PORT: The internal port assigned to this instance.

echo "--- Starting Blueprint: IOPaint for Instance: ${INSTANCE_NAME} ---"

# Ensure instance-specific directories exist
mkdir -p "${INSTANCE_CONF_DIR}"
mkdir -p "${INSTANCE_OUTPUT_DIR}"

# IOPaint is a PIP package, but we create a working directory for it
WORK_DIR="${INSTANCE_CONF_DIR}/iopaint_work"
mkdir -p "${WORK_DIR}"

VENV_DIR="${INSTANCE_CONF_DIR}/env"

# --- Environment Setup ---
echo "--- Setting up Conda environment ---"

# Clean up conda cache
conda clean -ya

# Clean the Conda environment if required by user
clean_env "${VENV_DIR}"

# Create the Conda environment if it doesn't exist
# Using Python 3.11 (Recommended for IOPaint)
if [ ! -d "${VENV_DIR}" ]; then
    echo "Creating Conda environment with Python 3.11..."
    conda create -p "${VENV_DIR}" python=3.11 -y
fi

# Activate the environment
source activate "${VENV_DIR}"

# --- Dependency Installation ---
echo "--- Installing dependencies ---"

# 1. Install PyTorch manually to ensure CUDA support
# IOPaint might try to pull CPU versions otherwise.
echo "--- Installing PyTorch (CUDA 12.1 compatible) ---"
pip install torch==2.1.2 torchvision==0.16.2 --index-url https://download.pytorch.org/whl/cu121

# 2. Install Pre-built Wheels (Custom Modules)
# Standard AiKore block to use local compiled wheels if available
WHEELS_DIR="${INSTANCE_CONF_DIR}/wheels"
if [ -d "${WHEELS_DIR}" ] && ls "${WHEELS_DIR}"/*.whl 1> /dev/null 2>&1; then
    echo "--- Installing pre-built wheels from ${WHEELS_DIR} ---"
    pip install "${WHEELS_DIR}"/*.whl
else
    echo "No custom wheels found in ${WHEELS_DIR}."
fi

# 3. Install IOPaint
echo "--- Installing IOPaint ---"
# We exclude torch from requirements if present in pip dependencies to avoid overwrite
pip install --upgrade iopaint

# 4. Install custom user requirements if specified
if [ -f "${INSTANCE_CONF_DIR}/requirements.txt" ]; then
    echo "--- Installing user requirements ---"
    pip install -r "${INSTANCE_CONF_DIR}/requirements.txt"
fi

echo "--- Dependency installation complete ---"

# --- Configuration & Symlinks ---
# IOPaint stores models in ~/.cache/iopaint by default. 
# We should redirect this to the config folder to make it persistent.
export XDG_CACHE_HOME="${INSTANCE_CONF_DIR}/cache"
mkdir -p "${XDG_CACHE_HOME}"

# --- Launch ---
cd "${WORK_DIR}"

echo "--- Launching IOPaint ---"

# Construct command
# --host 0.0.0.0 is required for Docker networking
# --port is assigned by AiKore
# --model-dir allows storing models in the persistent config folder
# --output-dir sends generated images to the correct output folder
CMD="iopaint start --host 0.0.0.0 --port ${WEBUI_PORT} --model-dir ${INSTANCE_CONF_DIR}/models --output-dir ${INSTANCE_OUTPUT_DIR}"

# Add user-defined arguments from launch_args.txt (AiKore Standard)
if [ -f "${INSTANCE_CONF_DIR}/launch_args.txt" ]; then
    USER_ARGS=$(cat "${INSTANCE_CONF_DIR}/launch_args.txt")
    CMD+=" ${USER_ARGS}"
fi

# Fallback for legacy parameters.txt support (from the ancestor script)
if [ -f "${INSTANCE_CONF_DIR}/parameters.txt" ] && [ ! -f "${INSTANCE_CONF_DIR}/launch_args.txt" ]; then
    echo "Legacy parameters.txt found. Appending arguments..."
    while IFS= read -r param; do
        if [[ $param != \#* ]]; then
            CMD+=" ${param}"
        fi
    done < "${INSTANCE_CONF_DIR}/parameters.txt"
fi

echo "Executing: ${CMD}"
eval $CMD
sleep infinity