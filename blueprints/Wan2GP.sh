### AIKORE-METADATA-START ###
# aikore.name = Wan2GP
# aikore.category = Video Generation
# aikore.description = A fast AI Video Generator using PyTorch 2.9 (ComfyUI Stack).
# aikore.venv_type = conda
# aikore.venv_path = ./env
### AIKORE-METADATA-END ###

#!/bin/bash
set -e

source /opt/sd-install/functions.sh

export PATH="/home/abc/miniconda3/bin:$PATH"

# Force logs to appear immediately
export PYTHONUNBUFFERED=1

echo "--- Starting Blueprint: Wan2GP (Port Fixed) for Instance: ${INSTANCE_NAME} ---"

mkdir -p "${INSTANCE_CONF_DIR}"
mkdir -p "${INSTANCE_OUTPUT_DIR}"

APP_DIR="${INSTANCE_CONF_DIR}/Wan2GP"
VENV_DIR="${INSTANCE_CONF_DIR}/env"

# --- 1. Git Clone ---
if [ ! -d "${APP_DIR}/.git" ]; then
    echo "Cloning Wan2GP repository..."
    git clone https://github.com/deepbeepmeep/Wan2GP.git "${APP_DIR}"
else
    echo "Existing Wan2GP repository found. Synchronizing..."
    cd "${APP_DIR}"
    check_remote "GIT_REF"
fi

# --- 2. Environment Setup ---
echo "--- Setting up Conda environment ---"
if [ ! -d "${VENV_DIR}" ]; then
    echo "Creating Conda environment with Python 3.12..."
    conda create -p "${VENV_DIR}" python=3.12 -y
fi

source activate "${VENV_DIR}"

# --- 3. Dependency Installation ---
echo "--- Installing dependencies ---"

conda install -c conda-forge ffmpeg -y

# 1. Install PyTorch (ComfyUI Stack: 2.9.1 + cu130)
echo "--- Installing PyTorch 2.9.1 ---"
pip install torch==2.9.1 torchvision==0.24.1 torchaudio==2.9.1 --index-url https://download.pytorch.org/whl/cu130

# 2. Install Pre-built Wheels (YOUR CUSTOM BUILD)
WHEELS_DIR="${INSTANCE_CONF_DIR}/wheels"
if [ -d "${WHEELS_DIR}" ] && ls "${WHEELS_DIR}"/*.whl 1> /dev/null 2>&1; then
    echo "--- Installing pre-built wheels from ${WHEELS_DIR} ---"
    pip install "${WHEELS_DIR}"/*.whl
else
    echo "WARNING: No custom wheels found via Tool. Verify 'Manage Wheels' in UI."
fi

# 3. Install App Requirements (STRICT FILTER)
if [ -f "${APP_DIR}/requirements.txt" ]; then
    echo "--- Filtering requirements ---"
    
    # WE STRICTLY EXCLUDE:
    # - torch stuff (installed manually)
    # - flash-attn & sageattention (provided by YOUR wheels)
    # - xformers/bitsandbytes (often provided by wheels too)
    PACKAGES_TO_EXCLUDE="torch|torchvision|torchaudio|flash-attn|sageattention|xformers|bitsandbytes"
    
    grep -v -i -E "^(${PACKAGES_TO_EXCLUDE})" "${APP_DIR}/requirements.txt" > "${APP_DIR}/requirements-filtered.txt"
    
    echo "--- Installing filtered requirements ---"
    pip install -r "${APP_DIR}/requirements-filtered.txt"
fi

if [ -f "${INSTANCE_CONF_DIR}/requirements.txt" ]; then
    pip install -r "${INSTANCE_CONF_DIR}/requirements.txt"
fi

echo "--- Dependency installation complete ---"

# --- 4. Configuration & Symlinks ---

# Output Directory
if [ -d "${APP_DIR}/outputs" ] && [ ! -L "${APP_DIR}/outputs" ]; then
    rm -rf "${APP_DIR}/outputs"
fi
ln -sfn "${INSTANCE_OUTPUT_DIR}" "${APP_DIR}/outputs"

# HuggingFace Cache Persistence
export HF_HOME="${INSTANCE_CONF_DIR}/hf_cache"
mkdir -p "${HF_HOME}"

# --- 5. Launch ---
cd "${APP_DIR}"

echo "--- Launching Wan2GP ---"

# According to documentation:
# --listen makes server accessible on network (0.0.0.0)
# --server-port defines the port
CMD="python wgp.py --listen --server-port ${WEBUI_PORT}"

if [ -f "${INSTANCE_CONF_DIR}/launch_args.txt" ]; then
    USER_ARGS=$(cat "${INSTANCE_CONF_DIR}/launch_args.txt")
    CMD+=" ${USER_ARGS}"
fi

echo "Executing: ${CMD}"
echo "HF_HOME: ${HF_HOME}"

eval $CMD
sleep infinity