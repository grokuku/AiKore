#!/bin/bash

### AIKORE-METADATA-START ###
# aikore.name = Ultimate TTS
# aikore.category = Audio / TTS
# aikore.description = All-in-one Voice Cloning & TTS (Tortoise, RVC, AudioLDM).
# aikore.venv_type = conda
# aikore.venv_path = ./env
### AIKORE-METADATA-END ###

set -e

source /opt/sd-install/functions.sh
source /opt/sd-install/versions.env

# --- Load custom instance versions if they exist ---
if [ -f "${INSTANCE_CONF_DIR}/aikore_vars.env" ]; then
    echo "--- Loading custom environment variables ---"
    source "${INSTANCE_CONF_DIR}/aikore_vars.env"
fi

export PATH="/home/abc/miniconda3/bin:$PATH"

echo "--- Starting Blueprint: Ultimate TTS Studio for Instance: ${INSTANCE_NAME} ---"

mkdir -p "${INSTANCE_CONF_DIR}"
mkdir -p "${INSTANCE_OUTPUT_DIR}"

APP_DIR="${INSTANCE_CONF_DIR}/UltimateTTS"
VENV_DIR="${INSTANCE_CONF_DIR}/env"

# --- 1. Git Clone ---
if [ ! -d "${APP_DIR}/.git" ]; then
    echo "Cloning Ultimate-TTS-Studio-SUP3R-Edition..."
    git clone https://github.com/SUP3RMASS1VE/Ultimate-TTS-Studio-SUP3R-Edition.git "${APP_DIR}"
else
    echo "Existing repository found. Synchronizing..."
    cd "${APP_DIR}"
    check_remote "ULTIMATE_TTS_GIT_REF"
fi

# --- 2. Environment Setup ---
echo "--- Setting up Conda environment ---"

# Clean conda cache to prevent metadata errors (same as ComfyUI)
conda clean -ya

# Clean environment if rebuild is requested
clean_env "${VENV_DIR}"

if [ ! -d "${VENV_DIR}" ]; then
    echo "Creating Conda environment with Python 3.10..."
    # Python 3.10 is required because:
    # - numba 0.58.1 (pinned in requirements.txt) requires Python >=3.8,<3.12
    # - misaki requires Python >=3.8,<3.13
    # - torch 2.10.0 supports Python 3.8-3.11
    conda create -p "${VENV_DIR}" python=3.10 portaudio pyaudio -c conda-forge -y
fi

# Use the venv's pip/python directly to avoid picking up the system Python 3.13
PIP="${VENV_DIR}/bin/pip"
PYTHON="${VENV_DIR}/bin/python"

# Install ffmpeg via conda only if not already present
if ! conda list -p "${VENV_DIR}" ffmpeg &>/dev/null | grep -q ffmpeg; then
    conda install -p "${VENV_DIR}" -c conda-forge ffmpeg -y
fi

# --- 3. Dependency Installation ---
echo "--- Installing dependencies ---"

# 1. PyTorch (using venv pip to avoid system Python 3.13)
echo "--- Installing PyTorch ---"
"${PIP}" install torch=="${TORCH_VERSION}" torchvision torchaudio --index-url "${PYTORCH_INDEX_URL}"

# 2. Custom Wheels
WHEELS_DIR="${INSTANCE_CONF_DIR}/wheels"
if [ -d "${WHEELS_DIR}" ] && ls "${WHEELS_DIR}"/*.whl 1> /dev/null 2>&1; then
    echo "--- Installing pre-built wheels from ${WHEELS_DIR} ---"
    "${PIP}" install "${WHEELS_DIR}"/*.whl
fi

# 3. Requirements with Filters
if [ -f "${APP_DIR}/requirements.txt" ]; then
    echo "--- Filtering and installing requirements ---"

    PACKAGES_TO_EXCLUDE="torch|torchvision|torchaudio|numpy|ffmpeg|pyaudio"

    grep -v -i -E "^(${PACKAGES_TO_EXCLUDE})" "${APP_DIR}/requirements.txt" > "${APP_DIR}/requirements-filtered.txt"
    "${PIP}" install -r "${APP_DIR}/requirements-filtered.txt"
fi

# --- 4. Configuration & Symlinks ---
mkdir -p "${APP_DIR}/results"

OUTPUT_FOLDER_NAME=$(basename "${INSTANCE_OUTPUT_DIR}")
sl_folder "${APP_DIR}" "results" "$(dirname "${INSTANCE_OUTPUT_DIR}")" "${OUTPUT_FOLDER_NAME}"

# --- 5. Launch ---
echo "--- Launching Ultimate TTS Studio ---"
cd "${APP_DIR}"

ENTRY_SCRIPT="${APP_DIR}/UltimateTTS.py"
if [ ! -f "${ENTRY_SCRIPT}" ]; then
    ENTRY_SCRIPT="${APP_DIR}/app.py"
fi
if [ ! -f "${ENTRY_SCRIPT}" ]; then
    ENTRY_SCRIPT="${APP_DIR}/main.py"
fi
if [ ! -f "${ENTRY_SCRIPT}" ]; then
    echo "FATAL: Could not find entry script (tried UltimateTTS.py, app.py, main.py)."
    echo "Available .py files:"
    ls -1 "${APP_DIR}"/*.py 2>/dev/null || echo "  (none found)"
    exit 1
fi

echo "Entry Script: ${ENTRY_SCRIPT}"

export GRADIO_SERVER_NAME="0.0.0.0"
export GRADIO_SERVER_PORT="${WEBUI_PORT}"

CMD="${PYTHON} \"${ENTRY_SCRIPT}\""

if [ -f "${INSTANCE_CONF_DIR}/launch_args.txt" ]; then
    USER_ARGS=$(cat "${INSTANCE_CONF_DIR}/launch_args.txt")
    CMD+=" ${USER_ARGS}"
fi

echo "Executing: ${CMD}"
eval ${CMD}
sleep infinity