### AIKORE-METADATA-START ###
# aikore.name = AIToolkit
# aikore.category = Training
# aikore.description = Ostris AI Toolkit for training LoRAs and Flux models.
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

echo "--- Starting Blueprint: AIToolkit for Instance: ${INSTANCE_NAME} ---"

# Ensure instance-specific directories exist
mkdir -p "${INSTANCE_CONF_DIR}"
mkdir -p "${INSTANCE_OUTPUT_DIR}"

TOOLKIT_DIR="${INSTANCE_CONF_DIR}/ai-toolkit"
VENV_DIR="${INSTANCE_CONF_DIR}/env"

# Install or update the ai-toolkit repository
if [ ! -d "${TOOLKIT_DIR}/.git" ]; then
    echo "Cloning ai-toolkit repository..."
    git clone https://github.com/ostris/ai-toolkit.git "${TOOLKIT_DIR}"
else
    echo "Existing ai-toolkit repository found. Synchronizing..."
    cd "${TOOLKIT_DIR}"
    check_remote "GIT_REF"
fi

# --- Environment Setup ---
echo "--- Setting up Conda environment ---"

# Clean up conda cache
conda clean -ya

# Clean the Conda environment if required by user
clean_env "${VENV_DIR}"

# Create the Conda environment if it doesn't exist
# Using Python 3.12 and Node.js
if [ ! -d "${VENV_DIR}" ]; then
    echo "Creating Conda environment with Python 3.12 and Node.js..."
    conda create -p "${VENV_DIR}" python=3.12 nodejs -c conda-forge -y
fi

# Activate the environment
source activate "${VENV_DIR}"

# --- Dependency Installation ---
echo "--- Installing dependencies ---"

# 1. Install specific PyTorch version (Torch 2.8 + CUDA 12.8)
echo "--- Installing PyTorch 2.8.0 (CUDA 12.8) ---"
pip install torch==2.8.0 torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128

# 2. Install torchao manually
echo "--- Installing torchao 0.10.0 ---"
pip install torchao==0.10.0

# 3. Install Pre-built Wheels (Custom Modules)
# This step installs your custom compiled wheels (e.g. SageAttention, FlashAttn)
WHEELS_DIR="${INSTANCE_CONF_DIR}/wheels"
if [ -d "${WHEELS_DIR}" ] && ls "${WHEELS_DIR}"/*.whl 1> /dev/null 2>&1; then
    echo "--- Installing pre-built wheels from ${WHEELS_DIR} ---"
    pip install "${WHEELS_DIR}"/*.whl
else
    echo "No custom wheels found in ${WHEELS_DIR}."
fi

# 4. Filter and install requirements
echo "--- Filtering and installing requirements ---"
# We exclude torch packages AND packages we might have installed via wheels
PACKAGES_TO_EXCLUDE="torch|torchvision|torchaudio|flash-attn|sageattention|xformers|bitsandbytes"

grep -v -i -E "^(${PACKAGES_TO_EXCLUDE})" "${TOOLKIT_DIR}/requirements.txt" > "${TOOLKIT_DIR}/requirements-filtered.txt"
pip install -r "${TOOLKIT_DIR}/requirements-filtered.txt"

# Install custom user requirements if specified
if [ -f "${INSTANCE_CONF_DIR}/requirements.txt" ]; then
    pip install -r "${INSTANCE_CONF_DIR}/requirements.txt"
fi

echo "--- Dependency installation complete ---"

# --- Configuration & Symlinks ---

# Symlink the output directory
TARGET_PARENT=$(dirname "${INSTANCE_OUTPUT_DIR}")
TARGET_FOLDER=$(basename "${INSTANCE_OUTPUT_DIR}")
sl_folder "${TOOLKIT_DIR}" "output" "${TARGET_PARENT}" "${TARGET_FOLDER}"

# Symlink datasets (Global shared folder)
mkdir -p "/config/datasets"
sl_folder "${TOOLKIT_DIR}" "datasets" "/config" "datasets"

# --- UI Port Configuration ---
# The UI is in a subdirectory 'ui'. It uses a package.json script to start.
# We need to inject the AiKore assigned port (${WEBUI_PORT}) into this file.

UI_PACKAGE_JSON="${TOOLKIT_DIR}/ui/package.json"
if [ -f "$UI_PACKAGE_JSON" ]; then
    echo "Configuring UI port to ${WEBUI_PORT} in package.json..."
    # Replaces any existing --port generic definition with the assigned port
    sed -i "s/--port [0-9]*/--port ${WEBUI_PORT}/g" "$UI_PACKAGE_JSON"
else
    echo "WARNING: package.json not found in ${TOOLKIT_DIR}/ui. Port configuration might fail."
fi

# --- Launch ---
echo "--- Starting AI-Toolkit UI ---"
cd "${TOOLKIT_DIR}/ui"

# Ensure node dependencies are installed
if [ ! -d "node_modules" ]; then
    echo "Installing Node modules..."
    npm install
fi

# Build and Start
echo "Launching via npm..."
npm run build_and_start