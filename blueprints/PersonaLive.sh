#!/bin/bash
# Exit immediately if a command exits with a non-zero status.
set -e

### AIKORE-METADATA-START ###
# aikore.name = PersonaLive
# aikore.category = Digital Avatar
# aikore.description = Real-time Digital Human generation and interaction.
# aikore.venv_type = conda
# aikore.venv_path = ./env
### AIKORE-METADATA-END ###

source /opt/sd-install/functions.sh

export PATH="/home/abc/miniconda3/bin:$PATH"

echo "--- Starting Blueprint: ${BLUEPRINT_ID} for Instance: ${INSTANCE_NAME} ---"

# Ensure instance-specific directories exist
mkdir -p "${INSTANCE_CONF_DIR}"
mkdir -p "${INSTANCE_OUTPUT_DIR}"

APP_DIR="${INSTANCE_CONF_DIR}/PersonaLive"
VENV_DIR="${INSTANCE_CONF_DIR}/env"

# --- 1. Git Clone ---
if [ ! -d "${APP_DIR}/.git" ]; then
    echo "Cloning PersonaLive repository..."
    git clone https://github.com/GVCLab/PersonaLive.git "${APP_DIR}"
else
    echo "Existing PersonaLive repository found. Synchronizing..."
    cd "${APP_DIR}"
    sync_repo
fi

# --- 2. Environment Setup ---
echo "--- Setting up Conda environment ---"

# Clean the Conda environment if required by user
clean_env "${VENV_DIR}"

# Create the Conda environment if it doesn't exist
# Using Python 3.10 as it is generally the most compatible for audio/video AI tools currently.
if [ ! -d "${VENV_DIR}" ]; then
    conda create -p "${VENV_DIR}" python=3.10 -y
fi

# Activate the environment
source activate "${VENV_DIR}"

# --- 3. Dependency Installation ---
echo "--- Installing dependencies ---"

# Install FFmpeg, PyAV (av) and pycuda via conda to avoid compilation issues
conda install -c conda-forge ffmpeg av pycuda nodejs=18 -y

# Install PyTorch 2.1.0
echo "--- Installing PyTorch 2.1.0 (Strict Requirement) ---"
pip install torch==2.1.0 torchvision==0.16.0 torchaudio==2.1.0 --index-url https://download.pytorch.org/whl/cu121

# Install TensorRT python bindings
echo "--- Installing TensorRT ---"
pip install tensorrt

# Install Requirements
if [ -f "${APP_DIR}/requirements_base.txt" ]; then
    echo "--- Installing dependencies from requirements_base.txt ---"
    # Exclude torch/vision (installed manually), av, pycuda and tensorrt (installed via conda/pip manually)
    grep -vE "torch|torchvision|torchaudio|av|pycuda|tensorrt" "${APP_DIR}/requirements_base.txt" > "${APP_DIR}/requirements-filtered.txt"
    pip install -r "${APP_DIR}/requirements-filtered.txt"
fi

# 4. Download Weights
echo "--- Downloading pre-trained weights ---"
cd "${APP_DIR}"
python tools/download_weights.py

echo "--- Dependency installation complete ---"

# --- 5. Symlinks ---
echo "--- Setting up symlinks ---"
sl_folder "${APP_DIR}" "output" "$(dirname "${INSTANCE_OUTPUT_DIR}")" "$(basename "${INSTANCE_OUTPUT_DIR}")"


# --- 6. Launch ---
cd "${APP_DIR}"

echo "--- Launching PersonaLive Backend (inference_online.py) ---"

# The app uses Gradio. We set the port.
export GRADIO_SERVER_PORT="${WEBUI_PORT}"
export GRADIO_SERVER_NAME="0.0.0.0"

# Note: The README mentions --acceleration none/xformers/tensorrt. 
# We default to none for compatibility, user can add xformers in launch_args.txt
CMD="python inference_online.py --port ${WEBUI_PORT}"

# User override via launch_args.txt
if [ -f "${INSTANCE_CONF_DIR}/launch_args.txt" ]; then
    USER_ARGS=$(cat "${INSTANCE_CONF_DIR}/launch_args.txt")
    CMD+=" ${USER_ARGS}"
fi

echo "Executing: ${CMD}"
eval $CMD
sleep infinity
