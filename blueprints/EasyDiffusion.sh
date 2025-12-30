### AIKORE-METADATA-START ###
# aikore.name = EasyDiffusion
# aikore.category = Image Generation
# aikore.description = The easiest way to install and use Stable Diffusion on your computer (formerly UI by cmdr2).
# aikore.venv_type = conda
# aikore.venv_path = ./env
### AIKORE-METADATA-END ###

#!/bin/bash
# Exit immediately if a command exits with a non-zero status.
set -e

source /opt/sd-install/functions.sh

export PATH="/home/abc/miniconda3/bin:$PATH"

# Variables provided by process manager:
# INSTANCE_NAME, INSTANCE_CONF_DIR, INSTANCE_OUTPUT_DIR, WEBUI_PORT

echo "--- Starting Blueprint: EasyDiffusion for Instance: ${INSTANCE_NAME} ---"

# Ensure directories
mkdir -p "${INSTANCE_CONF_DIR}"
mkdir -p "${INSTANCE_OUTPUT_DIR}"

APP_DIR="${INSTANCE_CONF_DIR}/easy-diffusion"
VENV_DIR="${INSTANCE_CONF_DIR}/env"

# --- 1. Git Clone ---
if [ ! -d "${APP_DIR}/.git" ]; then
    echo "Cloning Easy Diffusion repository..."
    git clone https://github.com/easydiffusion/easydiffusion.git "${APP_DIR}"
else
    echo "Existing repository found. Synchronizing..."
    cd "${APP_DIR}"
    check_remote "GIT_REF"
fi

# --- 2. Environment Setup ---
echo "--- Setting up Conda environment ---"
conda clean -ya
clean_env "${VENV_DIR}"

# Easy Diffusion works best with Python 3.10 stable
if [ ! -d "${VENV_DIR}" ]; then
    echo "Creating Conda environment (Python 3.10)..."
    conda create -p "${VENV_DIR}" python=3.10 -y
fi

source activate "${VENV_DIR}"

# --- 3. Dependency Installation ---
echo "--- Installing dependencies ---"

# Install PyTorch manually (CUDA 12.1)
echo "--- Installing PyTorch 2.1.2 ---"
pip install torch==2.1.2 torchvision==0.16.2 torchaudio==2.1.2 --index-url https://download.pytorch.org/whl/cu121

# Install Pre-built Wheels (Custom Modules)
WHEELS_DIR="${INSTANCE_CONF_DIR}/wheels"
if [ -d "${WHEELS_DIR}" ] && ls "${WHEELS_DIR}"/*.whl 1> /dev/null 2>&1; then
    echo "--- Installing pre-built wheels from ${WHEELS_DIR} ---"
    pip install "${WHEELS_DIR}"/*.whl
else
    echo "No custom wheels found in ${WHEELS_DIR}."
fi

# Install App Requirements with Filtering
if [ -f "${APP_DIR}/requirements.txt" ]; then
    echo "--- Filtering and installing app requirements ---"
    # Exclude torch and potentially custom compiled packages to avoid overwrites
    PACKAGES_TO_EXCLUDE="torch|torchvision|torchaudio|xformers|bitsandbytes|flash-attn|sageattention"
    
    grep -v -i -E "^(${PACKAGES_TO_EXCLUDE})" "${APP_DIR}/requirements.txt" > "${APP_DIR}/requirements-filtered.txt"
    pip install -r "${APP_DIR}/requirements-filtered.txt"
fi

# Easy Diffusion relies on 'sdkit'. If not present in requirements, ensure it's installed.
pip install sdkit

# Install custom user requirements
if [ -f "${INSTANCE_CONF_DIR}/requirements.txt" ]; then
    pip install -r "${INSTANCE_CONF_DIR}/requirements.txt"
fi

echo "--- Dependency installation complete ---"

# --- 4. Symlinks & Configuration ---
echo "--- Setting up symlinks ---"

# Output folder
# Easy Diffusion typically saves to 'outputs' inside its folder.
# We back it up if it exists and create a symlink to the AiKore output dir.
if [ -d "${APP_DIR}/outputs" ] && [ ! -L "${APP_DIR}/outputs" ]; then
    mv "${APP_DIR}/outputs" "${APP_DIR}/outputs_backup_$(date +%s)"
fi
ln -sfn "${INSTANCE_OUTPUT_DIR}" "${APP_DIR}/outputs"

# Models (Link Global AiKore Models)
mkdir -p "${APP_DIR}/models"
sl_folder "${APP_DIR}/models" "stable-diffusion" "/config/models" "stable-diffusion"
sl_folder "${APP_DIR}/models" "vae" "/config/models" "vae"
sl_folder "${APP_DIR}/models" "lora" "/config/models" "lora"
sl_folder "${APP_DIR}/models" "embeddings" "/config/models" "embeddings"
# Easy Diffusion specific model structure might differ slightly, but this covers basics.

# --- 5. Launch ---
cd "${APP_DIR}"

echo "--- Launching Easy Diffusion ---"

# We bypass 'start.sh' to use our Conda env and control parameters directly.
# The main entry point is scripts/main.py (or similar depending on version, sometimes just main.py in root or inside ui folder).
# Checking typical structure:
LAUNCH_SCRIPT="scripts/main.py"
if [ ! -f "$LAUNCH_SCRIPT" ]; then
    # Fallback search
    LAUNCH_SCRIPT=$(find . -name "main.py" | grep "scripts" | head -n 1)
fi

# Command construction
# --port and --host for Docker networking
CMD="python ${LAUNCH_SCRIPT} --port ${WEBUI_PORT} --host 0.0.0.0"

# Add user-defined arguments
if [ -f "${INSTANCE_CONF_DIR}/launch_args.txt" ]; then
    USER_ARGS=$(cat "${INSTANCE_CONF_DIR}/launch_args.txt")
    CMD+=" ${USER_ARGS}"
fi

echo "Executing: ${CMD}"
eval $CMD
sleep infinity