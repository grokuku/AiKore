#!/bin/bash

### AIKORE-METADATA-START ###
# aikore.name = EasyDiffusion
# aikore.category = Image Generation
# aikore.description = The easiest way to install and use Stable Diffusion on your computer (formerly UI by cmdr2).
# aikore.venv_type = conda
# aikore.venv_path = ./env
### AIKORE-METADATA-END ###

# Exit immediately if a command exits with a non-zero status.
set -e

source /opt/sd-install/functions.sh
source /opt/sd-install/versions.env

# --- Load custom instance versions if they exist ---
if [ -f "${INSTANCE_CONF_DIR}/aikore_vars.env" ]; then
    echo "--- Loading custom environment variables ---"
    source "${INSTANCE_CONF_DIR}/aikore_vars.env"
fi

export PATH="/home/abc/miniconda3/bin:$PATH"

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

# Easy Diffusion works well with Python 3.10
if [ ! -d "${VENV_DIR}" ]; then
    echo "Creating Conda environment (Python ${PYTHON_VERSION:-3.10})..."
    conda create -p "${VENV_DIR}" python="${PYTHON_VERSION:-3.10}" -y
fi

source activate "${VENV_DIR}"

# --- 3. Dependency Installation ---
echo "--- Installing dependencies ---"

echo "--- Installing PyTorch ---"
pip install torch==${TORCH_VERSION} torchvision torchaudio --index-url ${PYTORCH_INDEX_URL}

WHEELS_DIR="${INSTANCE_CONF_DIR}/wheels"
if [ -d "${WHEELS_DIR}" ] && [ "$(ls -A "${WHEELS_DIR}"/*.whl 2>/dev/null)" ]; then
    echo "--- Installing pre-built wheels from ${WHEELS_DIR} ---"
    pip install "${WHEELS_DIR}"/*.whl
else
    echo "No custom wheels found in ${WHEELS_DIR}."
fi

# Filter requirements to protect PyTorch and custom Wheels
if [ -f "${APP_DIR}/requirements.txt" ]; then
    echo "--- Filtering and installing app requirements ---"
    PACKAGES_TO_EXCLUDE="torch|torchvision|torchaudio|xformers|bitsandbytes|flash-attn|sageattention"
    
    # Use || true to prevent set -e from killing the script if grep finds nothing
    grep -v -i -E "^(${PACKAGES_TO_EXCLUDE})" "${APP_DIR}/requirements.txt" > "${APP_DIR}/requirements-filtered.txt" || true
    
    if [ -s "${APP_DIR}/requirements-filtered.txt" ]; then
        pip install -r "${APP_DIR}/requirements-filtered.txt"
    fi
fi

# Easy Diffusion doesn't use a standard requirements.txt for the UI engine.
# We install the core dependencies manually to bypass their check_modules.py
pip install sdkit uvicorn fastapi ruamel.yaml rich python-multipart pycloudflared sqlalchemy onnxruntime huggingface-hub wandb torchsde basicsr gfpgan stable-diffusion-sdkit diffusers

# Install custom user requirements
if [ -f "${INSTANCE_CONF_DIR}/requirements.txt" ]; then
    pip install -r "${INSTANCE_CONF_DIR}/requirements.txt"
fi

echo "--- Dependency installation complete ---"

# --- 4. Configuration & Symlinks ---
echo "--- Setting up configuration and symlinks ---"

# Generate config.yaml to force Easy Diffusion to use the AiKore port and network settings
cat <<EOF > "${APP_DIR}/config.yaml"
net:
    listen_port: ${WEBUI_PORT}
    listen_to_network: true
ui:
    open_browser_on_start: false
EOF

# Patch hardcoded IP binds in their codebase as a fallback measure
if [ -f "${APP_DIR}/scripts/check_modules.py" ]; then
    sed -i 's/bind_ip = "127.0.0.1"/bind_ip = "0.0.0.0"/g' "${APP_DIR}/scripts/check_modules.py" || true
fi
if [ -f "${APP_DIR}/ui/easydiffusion/server.py" ]; then
    sed -i 's/127.0.0.1/0.0.0.0/g' "${APP_DIR}/ui/easydiffusion/server.py" || true
fi

# Link Outputs folder
if [ -d "${APP_DIR}/outputs" ] && [ ! -L "${APP_DIR}/outputs" ]; then
    mv "${APP_DIR}/outputs" "${APP_DIR}/outputs_backup_$(date +%s)"
fi
ln -sfn "${INSTANCE_OUTPUT_DIR}" "${APP_DIR}/outputs"

# Link Global AiKore Models
mkdir -p "${APP_DIR}/models"
sl_folder "${APP_DIR}/models" "stable-diffusion" "/config/models" "stable-diffusion"
sl_folder "${APP_DIR}/models" "vae" "/config/models" "vae"
sl_folder "${APP_DIR}/models" "lora" "/config/models" "lora"
sl_folder "${APP_DIR}/models" "embeddings" "/config/models" "embeddings"

# --- 5. Launch ---
echo "--- Launching Easy Diffusion ---"

cd "${APP_DIR}"

# CRITICAL: We bypass start.sh and check_modules.py to run the Uvicorn ASGI directly.
# We must provide the correct paths and environments variables that are usually injected by their scripts.
export SD_UI_PATH="${APP_DIR}/ui"
export PYTHONPATH="${APP_DIR}/ui:${PYTHONPATH}"
export SD_UI_BIND_PORT=${WEBUI_PORT}
export SD_UI_BIND_IP=0.0.0.0

# uvicorn target is 'server_api' from 'ui/main.py'
CMD="python -m uvicorn ui.main:server_api --host 0.0.0.0 --port ${WEBUI_PORT}"

# Add user-defined arguments
if [ -f "${INSTANCE_CONF_DIR}/launch_args.txt" ]; then
    USER_ARGS=$(cat "${INSTANCE_CONF_DIR}/launch_args.txt")
    CMD+=" ${USER_ARGS}"
fi

echo "Executing: ${CMD}"
eval $CMD
sleep infinity