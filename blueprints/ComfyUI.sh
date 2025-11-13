### AIKORE-METADATA-START ###
# aikore.name = ComfyUI
# aikore.category = Image Generation
# aikore.description = A powerful and modular GUI for Stable Diffusion.
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
# - BLUEPRINT_ID: The base name of this blueprint script.

echo "--- Starting Blueprint: ${BLUEPRINT_ID} for Instance: ${INSTANCE_NAME} ---"

# Ensure instance-specific directories exist
mkdir -p "${INSTANCE_CONF_DIR}"
mkdir -p "${INSTANCE_OUTPUT_DIR}"

COMFYUI_DIR="${INSTANCE_CONF_DIR}/ComfyUI"
MANAGER_DIR="${COMFYUI_DIR}/custom_nodes/ComfyUI-Manager"
VENV_DIR="${INSTANCE_CONF_DIR}/env"

# Install or update the main ComfyUI repository
if [ ! -d "${COMFYUI_DIR}/.git" ]; then
    echo "Cloning ComfyUI repository..."
    git clone https://github.com/comfyanonymous/ComfyUI.git "${COMFYUI_DIR}"
else
    echo "Existing ComfyUI repository found. Synchronizing..."
    cd "${COMFYUI_DIR}"
    check_remote "GIT_REF"
fi

# Install or update the ComfyUI-Manager custom node
if [ ! -d "${MANAGER_DIR}/.git" ]; then
    echo "Cloning ComfyUI-Manager repository..."
    git clone https://github.com/ltdrdata/ComfyUI-Manager.git "${MANAGER_DIR}"
else
    echo "Existing ComfyUI-Manager repository found. Synchronizing..."
    cd "${MANAGER_DIR}"
    check_remote "GIT_REF"
fi

# --- Environment Setup ---
echo "--- Setting up Conda environment ---"

# Clean up conda cache to prevent metadata errors
conda clean -ya

# Clean the Conda environment if required by user
clean_env "${VENV_DIR}"

# Create the Conda environment if it doesn't exist
if [ ! -d "${VENV_DIR}" ]; then
    conda create -p "${VENV_DIR}" python=3.12 -y
fi

# Activate the environment
source activate "${VENV_DIR}"

# --- Dependency Installation ---
echo "--- Installing dependencies ---"

# 1. Install pre-built performance and utility libraries from wheels first.
# This ensures our GPU-optimized versions are used.
echo "--- Installing pre-built libraries from /wheels/ ---"
pip install /wheels/*.whl

# 2. Prepare a filtered requirements file for ComfyUI
# We remove packages that we just installed from wheels to avoid conflicts.
echo "--- Filtering ComfyUI requirements ---"
# Create a pattern for grep. Note that some packages might be specified with '=='
# so we match the package name at the beginning of the line.
# The list should include all packages that are built into wheels.
PACKAGES_TO_EXCLUDE="torch|torchvision|torchaudio|xformers|bitsandbytes|flash-attn|sageattention|diso|nvdiffrast|kaolin|diff-gaussian-rasterization|vox2seq"

grep -v -i -E "^(${PACKAGES_TO_EXCLUDE})" "${COMFYUI_DIR}/requirements.txt" > "${COMFYUI_DIR}/requirements-filtered.txt"

echo "--- Installing dependencies from filtered requirements.txt ---"
pip install -r "${COMFYUI_DIR}/requirements-filtered.txt"

# 3. Install dependencies for ComfyUI-Manager.
pip install -r "${MANAGER_DIR}/requirements.txt"

# 4. Find and install dependencies for all other custom nodes
echo "--- Installing dependencies for other custom nodes ---"
CUSTOM_NODES_DIR="${COMFYUI_DIR}/custom_nodes"
PACKAGES_TO_EXCLUDE="torch|torchvision|torchaudio|xformers|bitsandbytes|flash-attn|sageattention|diso|nvdiffrast|kaolin|diff-gaussian-rasterization|vox2seq"

find "${CUSTOM_NODES_DIR}" -name "requirements.txt" -print0 | while IFS= read -r -d $'\0' req_file; do
    # Exclude the ComfyUI-Manager's requirements file as we've already installed it
    if [ "$req_file" != "${MANAGER_DIR}/requirements.txt" ]; then
        echo "--- Processing custom node requirements: $req_file ---"
        
        TEMP_REQ_FILE=$(mktemp)
        
        grep -v -i -E "^(${PACKAGES_TO_EXCLUDE})" "$req_file" > "$TEMP_REQ_FILE"
        
        # Only run pip if the filtered file is not empty
        if [ -s "$TEMP_REQ_FILE" ]; then
            echo "Installing filtered dependencies from $req_file"
            pip install -r "$TEMP_REQ_FILE"
        else
            echo "No dependencies to install from $req_file after filtering."
        fi
        
        rm "$TEMP_REQ_FILE"
    fi
done

# 5. Install other packages
pip install peft opencv-python nunchaku

# 6. Install custom user requirements if specified
if [ -f "${INSTANCE_CONF_DIR}/requirements.txt" ]; then
    pip install -r "${INSTANCE_CONF_DIR}/requirements.txt"
fi

echo "--- Dependency installation complete ---"

# --- Symlink Setup ---
echo "--- Setting up model and output symlinks ---"
# Symlink shared models folders into the ComfyUI directory
sl_folder "${COMFYUI_DIR}/models" "checkpoints" "/config/models" "stable-diffusion"
sl_folder "${COMFYUI_DIR}/models" "hypernetworks" "/config/models" "hypernetwork"
sl_folder "${COMFYUI_DIR}/models" "loras" "/config/models" "lora"
sl_folder "${COMFYUI_DIR}/models" "vae" "/config/models" "vae"
sl_folder "${COMFYUI_DIR}/models" "vae_approx" "/config/models" "vae_approx"
sl_folder "${COMFYUI_DIR}/models" "embeddings" "/config/models" "embeddings"
sl_folder "${COMFYUI_DIR}/models" "upscale_models" "/config/models" "upscale"
sl_folder "${COMFYUI_DIR}/models" "clip_vision" "/config/models" "clip_vision"
sl_folder "${COMFYUI_DIR}/models" "clip" "/config/models" "clip"
sl_folder "${COMFYUI_DIR}/models" "controlnet" "/config/models" "controlnet"
sl_folder "${COMFYUI_DIR}/models" "t5" "/config/models" "t5"
sl_folder "${COMFYUI_DIR}/models" "unet" "/config/models" "unet"

# Symlink the output directory to the instance-specific output folder
TARGET_PARENT=$(dirname "$INSTANCE_OUTPUT_DIR")
TARGET_FOLDER=$(basename "$INSTANCE_OUTPUT_DIR")
sl_folder "${COMFYUI_DIR}" "output" "${TARGET_PARENT}" "${TARGET_FOLDER}"

# --- Launch ---
cd "${COMFYUI_DIR}"

CMD="python main.py --listen --port ${WEBUI_PORT}"

# Add any user-defined launch arguments
if [ -f "${INSTANCE_CONF_DIR}/launch_args.txt" ]; then
    USER_ARGS=$(cat "${INSTANCE_CONF_DIR}/launch_args.txt")
    CMD+=" ${USER_ARGS}"
fi

echo "---"
echo "Launching ComfyUI with command:"
echo "${CMD}"
echo "---"

eval $CMD
sleep infinity