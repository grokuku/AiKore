#!/bin/bash

### AIKORE-METADATA-START ###
# aikore.name = Ternary Bonsai LLM
# aikore.category = Chat / LLM
# aikore.description = llama.cpp server with Ternary-Bonsai-8B (1.58-bit trinary LLM). OpenAI-compatible API.
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

echo "--- Starting Blueprint: Ternary Bonsai LLM for Instance: ${INSTANCE_NAME} ---"

mkdir -p "${INSTANCE_CONF_DIR}"
mkdir -p "${INSTANCE_OUTPUT_DIR}"

APP_DIR="${INSTANCE_CONF_DIR}/llama-cpp"
MODEL_DIR="${INSTANCE_CONF_DIR}/models"
VENV_DIR="${INSTANCE_CONF_DIR}/env"

# ---- Hardcoded versions (for testing) ----
LLAMA_RELEASE="prism-b8846-d104cf1"
LLAMA_ARCHIVE="llama-prism-b8846-d104cf1-bin-linux-cuda-12.8-x64.tar.gz"
LLAMA_URL="https://github.com/PrismML-Eng/llama.cpp/releases/download/${LLAMA_RELEASE}/${LLAMA_ARCHIVE}"
MODEL_FILE="Ternary-Bonsai-8B-Q2_0.gguf"
MODEL_URL="https://huggingface.co/prism-ml/Ternary-Bonsai-8B-gguf/resolve/main/${MODEL_FILE}"

# --- 1. Download llama.cpp binary (PrismML fork) ---
mkdir -p "${APP_DIR}"

if [ ! -f "${APP_DIR}/llama-server" ]; then
    echo "--- Downloading llama.cpp (PrismML fork) ---"
    wget -q --show-progress -O "/tmp/${LLAMA_ARCHIVE}" "${LLAMA_URL}"
    echo "--- Extracting llama.cpp ---"
    tar xzf "/tmp/${LLAMA_ARCHIVE}" -C "${APP_DIR}" --strip-components=1
    rm -f "/tmp/${LLAMA_ARCHIVE}"
    chmod +x "${APP_DIR}/llama-server" "${APP_DIR}/llama-cli" "${APP_DIR}/llama-bench"
    echo "--- llama.cpp installed ---"
else
    echo "--- llama.cpp binary already present ---"
fi

# --- 2. Download model ---
mkdir -p "${MODEL_DIR}"

if [ ! -f "${MODEL_DIR}/${MODEL_FILE}" ]; then
    echo "--- Downloading model: ${MODEL_FILE} (~2.1GB) ---"
    wget -q --show-progress -c -O "${MODEL_DIR}/${MODEL_FILE}" "${MODEL_URL}"
    echo "--- Model downloaded ---"
else
    echo "--- Model already present: ${MODEL_FILE} ---"
fi

# --- 3. CUDA 12.4 runtime via pip ---
# The llama.cpp binary needs libcudart.so.12, libcublas.so.12, etc.
# NVIDIA provides pip packages (nvidia-cublas-cu12, etc.) that bundle these .so files.
# After install, we symlink them to ${VENV_DIR}/lib/ so the dynamic linker finds them.
conda create -p "${VENV_DIR}" python=3.10 pip -c conda-forge -y
source activate "${VENV_DIR}"

# Ensure pip is available inside the environment
if [ ! -f "${VENV_DIR}/bin/pip" ]; then
    echo "--- pip not found in environment, installing via conda ---"
    conda install -p "${VENV_DIR}" pip -y
fi

pip install \
    nvidia-cuda-runtime-cu12 \
    nvidia-cublas-cu12 \
    nvidia-cufft-cu12 \
    nvidia-curand-cu12 \
    nvidia-cusolver-cu12 \
    nvidia-cusparse-cu12 \
    nvidia-cuda-nvrtc-cu12 \
    nvidia-nvjitlink-cu12

# Symlink all .so files into ${VENV_DIR}/lib/ so llama-server finds them
NVIDIA_SO=$(find "${VENV_DIR}/lib/python3.10/site-packages" -path "*/nvidia/*/lib/*.so*" 2>/dev/null)
for so in ${NVIDIA_SO}; do
    ln -sf "${so}" "${VENV_DIR}/lib/" 2>/dev/null || true
done

# Make conda CUDA libs available to llama-server
export LD_LIBRARY_PATH="${VENV_DIR}/lib:${LD_LIBRARY_PATH}"

# --- 4. API key ---
# Generate or reuse an API key to protect the endpoint
API_KEY_FILE="${INSTANCE_CONF_DIR}/api.key"
if [ ! -f "${API_KEY_FILE}" ]; then
    API_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(24))")
    echo "${API_KEY}" > "${API_KEY_FILE}"
    echo "--- Generated new API key: ${API_KEY} ---"
    echo "--- Key saved to ${API_KEY_FILE} ---"
else
    API_KEY=$(cat "${API_KEY_FILE}")
    echo "--- Reusing existing API key from ${API_KEY_FILE} ---"
fi

# --- 5. Launch llama.cpp server ---
echo "--- Launching Ternary Bonsai LLM server on port ${WEBUI_PORT} ---"

cd "${APP_DIR}"

CMD="${APP_DIR}/llama-server -m ${MODEL_DIR}/${MODEL_FILE} --host 0.0.0.0 --port ${WEBUI_PORT} -c 4096 -ngl 99 -t 4 --log-disable --api-key ${API_KEY}"

# Allow user to override launch args via launch_args.txt
if [ -f "${INSTANCE_CONF_DIR}/launch_args.txt" ]; then
    USER_ARGS=$(cat "${INSTANCE_CONF_DIR}/launch_args.txt")
    CMD+=" ${USER_ARGS}"
fi

echo "---"
echo "Launching Ternary Bonsai LLM:"
echo "${CMD}"
echo "---"
echo "OpenAI-compatible API: http://localhost:${WEBUI_PORT}/v1/chat/completions"
echo "API key: ${API_KEY}"
echo "Usage: curl -H 'Authorization: Bearer ${API_KEY}' ..."
echo ""

eval ${CMD}
sleep infinity