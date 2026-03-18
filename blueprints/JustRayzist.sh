### AIKORE-METADATA-START ###
# aikore.name = JustRayzist
# aikore.category = Image Generation
# aikore.description = A lightweight implementation for Rayzist.
# aikore.venv_type = conda
# aikore.venv_path = ./env
### AIKORE-METADATA-END ###

#!/bin/bash
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

echo "--- Starting Blueprint: ${BLUEPRINT_ID} for Instance: ${INSTANCE_NAME} ---"

# Ensure instance-specific directories exist
mkdir -p "${INSTANCE_CONF_DIR}"
mkdir -p "${INSTANCE_OUTPUT_DIR}"

RAYZIST_DIR="${INSTANCE_CONF_DIR}/JustRayzist"
VENV_DIR="${INSTANCE_CONF_DIR}/env"

# Install or update the main JustRayzist repository
if [ ! -d "${RAYZIST_DIR}/.git" ]; then
    echo "Cloning JustRayzist repository..."
    git clone https://github.com/MutantSparrow/JustRayzist.git "${RAYZIST_DIR}"
else
    echo "Existing JustRayzist repository found. Synchronizing..."
    cd "${RAYZIST_DIR}"
    check_remote "GIT_REF"
fi

# --- Environment Setup ---
echo "--- Setting up Conda environment ---"

conda clean -ya
clean_env "${VENV_DIR}"

if [ ! -d "${VENV_DIR}" ]; then
    echo "Creating Conda environment with Python ${PYTHON_VERSION:-3.12}..."
    conda create -p "${VENV_DIR}" python="${PYTHON_VERSION:-3.12}" -y
fi

source activate "${VENV_DIR}"

# --- Dependency Installation ---
echo "--- Installing dependencies ---"

echo "--- Installing PyTorch ---"
pip install torch==${TORCH_VERSION} torchvision torchaudio --index-url ${PYTORCH_INDEX_URL}

echo "--- Installing JustRayzist package ---"
cd "${RAYZIST_DIR}"
pip install -e . --extra-index-url ${PYTORCH_INDEX_URL}

WHEELS_DIR="${INSTANCE_CONF_DIR}/wheels"
echo "--- Checking for pre-built libraries in ${WHEELS_DIR} ---"
if [ -d "${WHEELS_DIR}" ] && ls "${WHEELS_DIR}"/*.whl 1> /dev/null 2>&1; then
    echo "Wheel files found, installing optimized libraries..."
    pip install "${WHEELS_DIR}"/*.whl
else
    echo "No wheel files found in ${WHEELS_DIR}, skipping."
fi

if [ -f "${INSTANCE_CONF_DIR}/requirements.txt" ]; then
    echo "--- Installing custom user requirements ---"
    pip install -r "${INSTANCE_CONF_DIR}/requirements.txt"
fi

echo "--- Dependency installation complete ---"

# --- Model & Assets Fetching ---
echo "--- Ensuring required models and runtime assets exist ---"

# 1. Fetch SeedVR2 Runtime
SEEDVR2_RUNTIME_DIR="${RAYZIST_DIR}/models/seedvr2/runtime/ComfyUI-SeedVR2_VideoUpscaler"
if [ ! -d "${SEEDVR2_RUNTIME_DIR}/.git" ]; then
    echo "Cloning SeedVR2 runtime..."
    mkdir -p "${RAYZIST_DIR}/models/seedvr2/runtime"
    git clone --depth 1 https://github.com/numz/ComfyUI-SeedVR2_VideoUpscaler.git "${SEEDVR2_RUNTIME_DIR}"
else
    echo "SeedVR2 runtime exists. Pulling latest..."
    cd "${SEEDVR2_RUNTIME_DIR}"
    git pull origin main || true
    cd "${RAYZIST_DIR}"
fi

# Apply allocator patch
INFERENCE_CLI="${SEEDVR2_RUNTIME_DIR}/inference_cli.py"
if [ -f "${INFERENCE_CLI}" ]; then
    sed -i 's/PYTORCH_CUDA_ALLOC_CONF/PYTORCH_ALLOC_CONF/g' "${INFERENCE_CLI}"
fi

# 2. Fetch Models via direct download (wget)
download_model() {
    local repo_id=$1
    local filename=$2
    local output_path=$3
    local full_path="${RAYZIST_DIR}/${output_path}"
    
    if [ ! -f "${full_path}" ]; then
        echo "--> Downloading ${filename}..."
        mkdir -p "$(dirname "${full_path}")"
        local url="https://huggingface.co/${repo_id}/resolve/main/${filename}"
        wget -q --show-progress -O "${full_path}" "${url}"
    else
        echo "--> Asset already exists: ${full_path}"
    fi
}

echo "--- Downloading Models (This may take a while but progress will be shown) ---"
download_model "MutantSparrow/Ray" "Z-IMAGE-TURBO/Rayzist.v1.0.safetensors" "models/packs/Rayzist_bf16/weights/Rayzist.v1.0.safetensors"
download_model "Tongyi-MAI/Z-Image-Turbo" "vae/diffusion_pytorch_model.safetensors" "models/packs/Rayzist_bf16/weights/diffusion_pytorch_model.safetensors"
download_model "Comfy-Org/z_image_turbo" "split_files/text_encoders/qwen_3_4b.safetensors" "models/packs/Rayzist_bf16/config/text_encoder/model.safetensors"
download_model "themindstudio/SeedVR2-3B-FP8-e4m3fn" "seedvr2_ema_3b_fp8_e4m3fn.safetensors" "models/seedvr2/seedvr2_ema_3b_fp8_e4m3fn.safetensors"
download_model "themindstudio/SeedVR2-3B-FP8-e4m3fn" "ema_vae_fp16.safetensors" "models/seedvr2/ema_vae_fp16.safetensors"
download_model "imagepipeline/superresolution" "RealESRGAN_x2plus.pth" "models/upscaler/2x_RealESRGAN_x2plus.pth"

# --- Output Symlink Setup ---
TARGET_PARENT=$(dirname "$INSTANCE_OUTPUT_DIR")
TARGET_FOLDER=$(basename "$INSTANCE_OUTPUT_DIR")
sl_folder "${RAYZIST_DIR}" "outputs" "${TARGET_PARENT}" "${TARGET_FOLDER}"

# --- Launch ---
cd "${RAYZIST_DIR}"

# Use 'constrained' for 12GB VRAM, 'balanced' for 16GB, 'high' for 24GB+
PROFILE="constrained"

# PyTorch VRAM optimization to prevent fragmentation OOM errors
export PYTORCH_ALLOC_CONF=expandable_segments:True

CMD="python -m app.cli.main serve --host 0.0.0.0 --port ${WEBUI_PORT} --profile ${PROFILE}"

if [ -f "${INSTANCE_CONF_DIR}/launch_args.txt" ]; then
    USER_ARGS=$(cat "${INSTANCE_CONF_DIR}/launch_args.txt")
    CMD+=" ${USER_ARGS}"
fi

echo "---"
echo "Launching JustRayzist with command:"
echo "${CMD}"
echo "---"

eval $CMD
sleep infinity