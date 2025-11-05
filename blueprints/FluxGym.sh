#!/bin/bash
source /opt/sd-install/functions.sh

export PATH="/home/abc/miniconda3/bin:$PATH"

# Clean up conda cache and packages to prevent metadata errors
conda clean -ya

# The following variables are provided by the process manager:
# - INSTANCE_NAME: The unique user-defined name for this instance.
# - INSTANCE_CONF_DIR: The dedicated directory for this instance's configuration.
# - INSTANCE_OUTPUT_DIR: The dedicated directory for this instance's generated outputs.
# - BLUEPRINT_ID: The base name of this blueprint script.

echo "--- Starting Blueprint: ${BLUEPRINT_ID} for Instance: ${INSTANCE_NAME} ---"

mkdir -p "${INSTANCE_CONF_DIR}"
mkdir -p "${INSTANCE_OUTPUT_DIR}"

APP_DIR="${INSTANCE_CONF_DIR}/fluxgym"

# Install or update the main fluxgym repository
if [ ! -d "${APP_DIR}/.git" ]; then
    echo "Cloning fluxgym repository..."
    git clone https://github.com/cocktailpeanut/fluxgym.git "${APP_DIR}"
    cd "${APP_DIR}"
    echo "Cloning sd-scripts sub-repository for fluxgym..."
    git clone -b sd3 https://github.com/kohya-ss/sd-scripts
else
    echo "Existing fluxgym repository found. Synchronizing..."
    cd "${APP_DIR}"
    check_remote "GIT_REF"
    if [ -d "sd-scripts/.git" ]; then
    echo "Synchronizing sd-scripts sub-repository to 'sd3' branch..."
    cd sd-scripts
    git fetch
    git checkout sd3
    git reset --hard origin/sd3
    cd ..
    else
    echo "sd-scripts sub-repository not found or not a git repo, attempting to clone..."
    rm -rf sd-scripts
    git clone -b sd3 https://github.com/kohya-ss/sd-scripts
    fi
fi

# Clean and setup Conda environment
clean_env "${INSTANCE_CONF_DIR}/env"
if [ ! -d "${INSTANCE_CONF_DIR}/env" ]; then
    conda create -p "${INSTANCE_CONF_DIR}/env" -y
fi
source activate "${INSTANCE_CONF_DIR}/env"

echo "--- Updating Conda and installing base packages ---"
conda update -n base conda -y
conda install -n base conda-libmamba-solver -y
conda install -c conda-forge python=3.10 pip gfortran --solver=libmamba -y

# Install Python requirements
echo "--- Installing Python dependencies ---"
pip install --upgrade pip
pip install python-slugify
pip install gradio==3.50.2
cd "${APP_DIR}/sd-scripts"
pip install -r requirements.txt
cd "${APP_DIR}"
pip install -r requirements.txt
pip install --pre torch torchvision torchaudio --index-url https://download.pytorch.org/whl/nightly/cu121

if [ -f "${INSTANCE_CONF_DIR}/requirements.txt" ]; then
    pip install -r "${INSTANCE_CONF_DIR}/requirements.txt"
fi

# Symlink models and outputs
sl_folder "${APP_DIR}/models" "vae" "/config/models/vae"
sl_folder "${APP_DIR}/models" "clip" "/config/models/clip"
sl_folder "${APP_DIR}/models" "unet" "/config/models/unet"
ln -sfn "${INSTANCE_OUTPUT_DIR}" "${APP_DIR}/outputs"

# Launch fluxgym
cd "${APP_DIR}"

# Set Gradio environment variables for server configuration
export GRADIO_SERVER_NAME="0.0.0.0"
export GRADIO_SERVER_PORT="${WEBUI_PORT}"
# Use the environment variable for root_path, which can be more reliable.
export GRADIO_ROOT_PATH="/app/${INSTANCE_NAME}"

# The command is now clean, relying only on environment variables.
CMD="python app.py"

echo "---"
echo "Launching fluxgym on port ${GRADIO_SERVER_PORT} with root path ${GRADIO_ROOT_PATH}"
echo "Command: ${CMD}"
echo "---"

eval $CMD
sleep infinity