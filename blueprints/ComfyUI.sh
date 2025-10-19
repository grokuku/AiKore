#!/bin/bash
source /functions.sh

export PATH="/home/abc/miniconda3/bin:$PATH"

# The following variables are provided by the process manager:
# - INSTANCE_NAME: The unique user-defined name for this instance (e.g., "MyTestUI").
# - INSTANCE_CONF_DIR: The dedicated directory for this instance's configuration, repos, and venv.
# - INSTANCE_OUTPUT_DIR: The dedicated directory for this instance's generated outputs.
# - BLUEPRINT_ID: The base name of the original blueprint script (e.g., "05-comfyui").

echo "--- Starting Blueprint: ${BLUEPRINT_ID} for Instance: ${INSTANCE_NAME} ---"

# Ensure instance-specific directories exist
mkdir -p "${INSTANCE_CONF_DIR}"
mkdir -p "${INSTANCE_OUTPUT_DIR}"

# Copy default launch parameters if the instance does not have its own
if [ ! -f "${INSTANCE_CONF_DIR}/parameters.txt" ]; then
    source_parameters_file="/opt/sd-install/blueprints/${BLUEPRINT_ID}.parameters.txt"
    if [ -f "$source_parameters_file" ]; then
        echo "Copying default parameters from ${source_parameters_file}..."
        cp -v "$source_parameters_file" "${INSTANCE_CONF_DIR}/parameters.txt"
    else
        echo "Warning: Default parameter file not found at ${source_parameters_file}. Creating an empty one."
        touch "${INSTANCE_CONF_DIR}/parameters.txt"
    fi
fi

# Install or update the main ComfyUI repository
if [ ! -d "${INSTANCE_CONF_DIR}/ComfyUI/.git" ]; then
    echo "Cloning ComfyUI repository..."
    git clone https://github.com/comfyanonymous/ComfyUI.git "${INSTANCE_CONF_DIR}/ComfyUI"
    cd "${INSTANCE_CONF_DIR}/ComfyUI"
else
    echo "Existing ComfyUI repository found. Synchronizing..."
    cd "${INSTANCE_CONF_DIR}/ComfyUI"
    check_remote "GIT_REF"
fi

# Install or update the ComfyUI-Manager custom node
mkdir -p "${INSTANCE_CONF_DIR}/ComfyUI/custom_nodes"
if [ ! -d "${INSTANCE_CONF_DIR}/ComfyUI/custom_nodes/ComfyUI-Manager/.git" ]; then
    echo "Cloning ComfyUI-Manager repository..."
    git clone https://github.com/Comfy-Org/ComfyUI-Manager.git "${INSTANCE_CONF_DIR}/ComfyUI/custom_nodes/ComfyUI-Manager"
    cd "${INSTANCE_CONF_DIR}/ComfyUI/custom_nodes/ComfyUI-Manager"
else
    echo "Existing ComfyUI-Manager repository found. Synchronizing..."
    cd "${INSTANCE_CONF_DIR}/ComfyUI/custom_nodes/ComfyUI-Manager"
    check_remote "GIT_REF"
fi

# Clean the Conda environment if required
clean_env "${INSTANCE_CONF_DIR}/env"

# Create the Conda environment if it doesn't exist
if [ ! -d "${INSTANCE_CONF_DIR}/env" ]; then
    conda create -p "${INSTANCE_CONF_DIR}/env" -y
fi

# Activate the environment and install base packages
source activate "${INSTANCE_CONF_DIR}/env"
conda install -n base conda-libmamba-solver -y
conda install -c python=3.12 pip --solver=libmamba -y 
pip install --upgrade pip
pip install torch==2.8.0 torchvision torchaudio --extra-index-url https://download.pytorch.org/whl/cu128
conda install -c conda-forge git gxx libcurand --solver=libmamba -y
conda install -c nvidia cuda-cudart --solver=libmamba -y
pip install --force-reinstall --no-cache-dir --no-deps flash-attn

# Install ComfyUI's Python requirements
cd "${INSTANCE_CONF_DIR}/ComfyUI"
pip install -r requirements.txt
cd "${INSTANCE_CONF_DIR}/ComfyUI/custom_nodes/ComfyUI-Manager"
pip install -r requirements.txt

# Install custom user requirements if specified
if [ -f "${INSTANCE_CONF_DIR}/requirements.txt" ]; then
    pip install -r "${INSTANCE_CONF_DIR}/requirements.txt"
fi

# Install pre-compiled wheels and other specific packages
pip install /wheels/*.whl
pip install plyfile \
    tqdm \
    spconv-cu124 \
    llama-cpp-python \
    logger \
    sageattention
pip install --upgrade diffusers[torch]

# Install dependencies for custom nodes if a full clean was performed
if [ "$active_clean" = "1" ]; then
    echo "-------------------------------------"
    echo "Install Custom Nodes Dependencies"
    install_requirements "${INSTANCE_CONF_DIR}/ComfyUI/custom_nodes"
    echo "Done!"
    echo -e "-------------------------------------\n"
fi

# Symlink shared models folders into the ComfyUI directory
sl_folder "${INSTANCE_CONF_DIR}/ComfyUI/models" "checkpoints" "${BASE_DIR}/models/stable-diffusion"
sl_folder "${INSTANCE_CONF_DIR}/ComfyUI/models" "hypernetworks" "${BASE_DIR}/models/hypernetwork"
sl_folder "${INSTANCE_CONF_DIR}/ComfyUI/models" "loras" "${BASE_DIR}/models/lora"
sl_folder "${INSTANCE_CONF_DIR}/ComfyUI/models" "vae" "${BASE_DIR}/models/vae"
sl_folder "${INSTANCE_CONF_DIR}/ComfyUI/models" "vae_approx" "${BASE_DIR}/models/vae_approx"
sl_folder "${INSTANCE_CONF_DIR}/ComfyUI/models" "embeddings" "${BASE_DIR}/models/embeddings"
sl_folder "${INSTANCE_CONF_DIR}/ComfyUI/models" "upscale_models" "${BASE_DIR}/models/upscale"
sl_folder "${INSTANCE_CONF_DIR}/ComfyUI/models" "clip_vision" "${BASE_DIR}/models/clip_vision"
sl_folder "${INSTANCE_CONF_DIR}/ComfyUI/models" "clip" "${BASE_DIR}/models/clip"
sl_folder "${INSTANCE_CONF_DIR}/ComfyUI/models" "controlnet" "${BASE_DIR}/models/controlnet"
sl_folder "${INSTANCE_CONF_DIR}/ComfyUI/models" "t5" "${BASE_DIR}/models/t5"
sl_folder "${INSTANCE_CONF_DIR}/ComfyUI/models" "unet" "${BASE_DIR}/models/unet"

# Symlink the output directory to the instance-specific output folder
# This ensures ComfyUI writes to /outputs/<instance_name>/ by default
ln -sfn "${INSTANCE_OUTPUT_DIR}" "${INSTANCE_CONF_DIR}/ComfyUI/output"

# Launch ComfyUI
cd "${INSTANCE_CONF_DIR}/ComfyUI"
CMD="python3 main.py"
if [ -n "$WEBUI_PORT" ]; then
    CMD+=" --port ${WEBUI_PORT}"
fi
while IFS= read -r param; do
    if [[ $param != \#* ]]; then
        CMD+=" ${param}"
    fi
done < "${INSTANCE_CONF_DIR}/parameters.txt"

echo "---"
echo "Launching ComfyUI with command:"
echo "${CMD}"
echo "---"

eval $CMD
sleep infinity