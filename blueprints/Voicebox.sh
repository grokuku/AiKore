#!/bin/bash

### AIKORE-METADATA-START ###
# aikore.name = Voicebox
# aikore.category = Audio / TTS
# aikore.description = The open-source AI voice studio. Clone any voice, generate speech, dictate into any app.
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

# The following variables are provided by the process manager:
# - INSTANCE_NAME: The unique user-defined name for this instance.
# - INSTANCE_CONF_DIR: The dedicated directory for this instance's configuration.
# - INSTANCE_OUTPUT_DIR: The dedicated directory for this instance's generated outputs.
# - WEBUI_PORT: The internal port assigned to this instance.
# - BLUEPRINT_ID: The base name of this blueprint script.

echo "--- Starting Blueprint: ${BLUEPRINT_ID} for Instance: ${INSTANCE_NAME} ---"

# Ensure instance-specific directories exist
mkdir -p "${INSTANCE_CONF_DIR}"
mkdir -p "${INSTANCE_OUTPUT_DIR}"

VOICEBOX_DIR="${INSTANCE_CONF_DIR}/voicebox"
VENV_DIR="${INSTANCE_CONF_DIR}/env"
DATA_DIR="${INSTANCE_CONF_DIR}/data"

# ============================================================
# 1. CLONE / UPDATE REPOSITORY
# ============================================================
if [ ! -d "${VOICEBOX_DIR}/.git" ]; then
    echo "Cloning Voicebox repository..."
    git clone https://github.com/jamiepine/voicebox.git "${VOICEBOX_DIR}"
else
    echo "Existing Voicebox repository found. Synchronizing..."
    cd "${VOICEBOX_DIR}"
    check_remote "VOICEBOX_GIT_REF"
fi

# ============================================================
# 2. BUILD FRONTEND (one-time operation)
# ============================================================
FRONTEND_DIR="${VOICEBOX_DIR}/frontend"
if [ ! -d "${FRONTEND_DIR}" ]; then
    echo "--- Building web frontend (first run only) ---"

    # Install bun (fast JavaScript runtime needed for Vite build)
    BUN_DIR="${INSTANCE_CONF_DIR}/.bun"
    BUN_BIN="${BUN_DIR}/bin/bun"
    if [ ! -f "${BUN_BIN}" ]; then
        echo "Installing bun..."
        mkdir -p "${BUN_DIR}/bin"
        BUN_ZIP="$(mktemp /tmp/bun-XXXXXX.zip)"
        curl -fsSL -o "${BUN_ZIP}" https://github.com/oven-sh/bun/releases/latest/download/bun-linux-x64.zip
        unzip -o "${BUN_ZIP}" -d /tmp/bun-extract-$$ 1>/dev/null
        # The zip contains a directory 'bun-linux-x64/' with the binary inside
        find /tmp/bun-extract-$$ -name 'bun' -type f -exec mv {} "${BUN_BIN}" \;
        chmod +x "${BUN_BIN}"
        rm -rf /tmp/bun-extract-$$ "${BUN_ZIP}"
        echo "Bun installed to ${BUN_BIN}"
    fi
    export PATH="${BUN_DIR}/bin:$PATH"

    cd "${VOICEBOX_DIR}"

    # Strip workspaces not needed for web build (tauri = desktop app, landing = marketing page)
    # This matches the official Dockerfile build steps
    python3 -c "
import json
with open('package.json') as f:
    data = json.load(f)
data['workspaces'] = [w for w in data['workspaces'] if w not in ('tauri', 'landing')]
with open('package.json', 'w') as f:
    json.dump(data, f, indent=2)
"

    echo "Installing frontend dependencies..."
    bun install --no-save

    echo "Building frontend with Vite..."
    cd web && bun x vite build

    # Copy built frontend to where the backend expects it (../frontend/ relative to backend/)
    cp -r "${VOICEBOX_DIR}/web/dist" "${FRONTEND_DIR}"

    echo "Frontend build complete."
else
    echo "Frontend already built, skipping."
fi

# ============================================================
# 3. CONDA ENVIRONMENT SETUP
# ============================================================
echo "--- Setting up Conda environment ---"

conda clean -ya

# Clean the Conda environment if required by user (rebuild trigger)
clean_env "${VENV_DIR}"

# Create the Conda environment if it doesn't exist
# Voicebox requires Python 3.11 (as specified in their Dockerfile)
if [ ! -d "${VENV_DIR}" ]; then
    echo "Creating Conda environment with Python ${PYTHON_VERSION:-3.11}..."
    conda create -p "${VENV_DIR}" python="${PYTHON_VERSION:-3.11}" pip -y
fi

source activate "${VENV_DIR}"

# Ensure pip is available inside the environment
if [ ! -f "${VENV_DIR}/bin/pip" ]; then
    echo "--- pip not found in environment, installing via conda ---"
    conda install -p "${VENV_DIR}" pip -y
fi

# ============================================================
# 4. INSTALL ALL BACKEND DEPENDENCIES
# ============================================================
echo "--- Installing backend dependencies ---"

# Install everything from Voicebox's requirements.txt first.
# This resolves all sub-dependencies (linacodec, Zipvoice, etc.) with compatible versions.
pip install -r "${VOICEBOX_DIR}/backend/requirements.txt"

# ============================================================
# 5. OVERWRITE TORCH ECOSYSTEM WITH AIKORE'S CUDA VERSIONS
# ============================================================
echo "--- Installing AiKore's CUDA-optimized PyTorch ---"

# Voicebox pins torch==2.7.0, torchaudio==2.7.0 from PyPI (CPU or CUDA 12.x).
# We overwrite with AiKore's CUDA 13.0 builds so torch uses the installed GPU toolkit.
# All three packages must come from the same index at matching versions for ABI compat.
pip install --upgrade --force-reinstall \
    torch==${TORCH_VERSION} \
    torchvision==${TORCHVISION_VERSION} \
    torchaudio==${TORCHAUDIO_VERSION} \
    --index-url ${PYTORCH_INDEX_URL}

# Force-reinstalling torch may pull in newer numpy (e.g. 2.x) which breaks
# numba (pinned to <2.0 in requirements.txt). Re-constrain numpy here.
echo "--- Pinning numpy<2.0 for numba compatibility ---"
pip install "numpy>=1.24.0,<2.0"

# ============================================================
# 6. INSTALL PRE-BUILT WHEELS (if any custom compiled modules exist)
# ============================================================
WHEELS_DIR="${INSTANCE_CONF_DIR}/wheels"
if [ -d "${WHEELS_DIR}" ] && ls "${WHEELS_DIR}"/*.whl 1> /dev/null 2>&1; then
    echo "--- Installing pre-built wheels from ${WHEELS_DIR} ---"
    pip install "${WHEELS_DIR}"/*.whl
else
    echo "No custom wheels found in ${WHEELS_DIR}."
fi

# ============================================================
# 7. INSTALL CUSTOM TTS ENGINES (--no-deps to avoid version conflicts)
# ============================================================
# chatterbox-tts pins numpy<1.26 and torch==2.6 which are incompatible with
# Python 3.12+ and our CUDA-specific torch. We install it --no-deps and let
# the sub-dependencies (already in requirements.txt) handle the real deps.
# hume-tada pins torch>=2.7,<2.8 which would overwrite our CUDA-specific build.
echo "--- Installing custom TTS engines (no-deps) ---"
pip install --no-deps chatterbox-tts
pip install --no-deps hume-tada

# ============================================================
# 8. INSTALL USER REQUIREMENTS (if specified)
# ============================================================
if [ -f "${INSTANCE_CONF_DIR}/requirements.txt" ]; then
    echo "--- Installing user requirements ---"
    pip install -r "${INSTANCE_CONF_DIR}/requirements.txt"
fi

echo "--- Dependency installation complete ---"

# ============================================================
# 9. DATA DIRECTORY SETUP
# ============================================================
echo "--- Setting up data directories ---"

# Voicebox stores everything (DB, profiles, captures, cache, models) under a
# single data directory. We set it to the instance's config dir for persistence.
mkdir -p "${DATA_DIR}"
mkdir -p "${DATA_DIR}/profiles"
mkdir -p "${DATA_DIR}/captures"
mkdir -p "${DATA_DIR}/cache"
mkdir -p "${DATA_DIR}/models"

# Symlink generations directory to AiKore's shared output folder
# so generated audio is accessible alongside other instances' outputs
rm -rf "${DATA_DIR}/generations"
ln -sfn "${INSTANCE_OUTPUT_DIR}" "${DATA_DIR}/generations"

# ============================================================
# 10. LAUNCH
# ============================================================
cd "${VOICEBOX_DIR}"

# --- Environment Variables ---
# Redirect HuggingFace model downloads to the instance's models directory
export VOICEBOX_MODELS_DIR="${DATA_DIR}/models"
# Numba needs a writable cache dir (per-instance to avoid conflicts)
export NUMBA_CACHE_DIR="/tmp/numba_cache_${INSTANCE_NAME}"
mkdir -p "${NUMBA_CACHE_DIR}"

# Use python -m backend.main (not bare uvicorn) so we can pass --data-dir
# The --data-dir flag is only parsed when running as __main__, not when
# uvicorn imports the app module directly.
CMD="python -m backend.main --host 0.0.0.0 --port ${WEBUI_PORT} --data-dir ${DATA_DIR}"

# Add user-defined launch arguments from launch_args.txt (AiKore standard)
if [ -f "${INSTANCE_CONF_DIR}/launch_args.txt" ]; then
    USER_ARGS=$(cat "${INSTANCE_CONF_DIR}/launch_args.txt")
    CMD+=" ${USER_ARGS}"
fi

echo "---"
echo "Launching Voicebox with command:"
echo "${CMD}"
echo "Data directory: ${DATA_DIR}"
echo "Models directory: ${DATA_DIR}/models}"
echo "---"

eval $CMD
sleep infinity