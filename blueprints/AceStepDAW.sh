#!/bin/bash

### AIKORE-METADATA-START ###
# aikore.name = ACE-Step
# aikore.category = Audio Generation
# aikore.description = ACE-Step 1.5 Engine with Browser-based DAW (LEGO-style music pipeline).
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

echo "--- Starting Blueprint: ${BLUEPRINT_ID} for Instance: ${INSTANCE_NAME} ---"

# Ensure instance-specific directories exist
mkdir -p "${INSTANCE_CONF_DIR}"
mkdir -p "${INSTANCE_OUTPUT_DIR}"

BACKEND_DIR="${INSTANCE_CONF_DIR}/ACE-Step-1.5"
FRONTEND_DIR="${INSTANCE_CONF_DIR}/ACE-Step-DAW"
VENV_DIR="${INSTANCE_CONF_DIR}/env"

# 1. Install or update repositories
if [ ! -d "${BACKEND_DIR}/.git" ]; then
    echo "Cloning Backend..."
    git clone https://github.com/ace-step/ACE-Step-1.5.git "${BACKEND_DIR}"
fi

if [ ! -d "${FRONTEND_DIR}/.git" ]; then
    echo "Cloning Frontend..."
    git clone https://github.com/ace-step/ACE-Step-DAW.git "${FRONTEND_DIR}"
fi

# --- Environment Setup ---
conda clean -ya
clean_env "${VENV_DIR}"

if [ ! -d "${VENV_DIR}" ]; then
    echo "Creating Conda environment (Python 3.12)..."
    conda create -p "${VENV_DIR}" python="${PYTHON_VERSION:-3.12}" nodejs ffmpeg -c conda-forge -y
fi

source activate "${VENV_DIR}"

# --- Dependency Installation ---
# FORCING strict alignment from versions.env to avoid ABI symbol conflicts
pip install torch==${TORCH_VERSION} torchvision==${TORCHVISION_VERSION} torchaudio==${TORCHAUDIO_VERSION} --index-url ${PYTORCH_INDEX_URL}

# Install Backend
cd "${BACKEND_DIR}"
PACKAGES_TO_EXCLUDE="torch|torchvision|torchaudio|xformers|bitsandbytes|flash-attn|sageattention|nano-vllm"
if [ -f "requirements.txt" ]; then
    grep -v -i -E "^(${PACKAGES_TO_EXCLUDE})" "requirements.txt" > "requirements-filtered.txt"
    pip install -r requirements-filtered.txt
fi
pip install hatchling build setuptools wheel editables uvicorn
pip install -e . --no-build-isolation --no-deps --extra-index-url ${PYTORCH_INDEX_URL}

# --- Frontend Patching & Installation ---
cd "${FRONTEND_DIR}"

echo "Applying Docker patches to Frontend..."

# Patch 1: Crypto randomUUID (for non-HTTPS contexts)
POLYFILL="<script>if(!window.crypto.randomUUID){window.crypto.randomUUID=function(){return([1e7]+-1e3+-4e3+-8e3+-1e11).replace(/[018]/g,function(c){return(c^(crypto.getRandomValues(new Uint8Array(1))[0]\&15>>c/4)).toString(16)})}}</script>"
if ! grep -q "window.crypto.randomUUID" index.html; then
    sed -i "s|<head>|<head>${POLYFILL}|" index.html
fi

# Patch 2: Redirect dynamic WebSocket 127.0.0.1 to current host/bridge
find src -type f -exec sed -i "s|\`ws://127.0.0.1:\${this.port}\`|(window.location.protocol === 'https:' ? 'wss://' : 'ws://') + window.location.host + '/bridge'|g" {} +

# Patch 3: Configure Vite for Reverse Proxy and allowed hosts
if [ -f "vite.config.ts" ]; then
    # Fix 1: Ensure Vite server binds to 0.0.0.0
    sed -i "s|host: '127.0.0.1'|host: '0.0.0.0'|g" vite.config.ts
    
    # Fix 2: Allow all hosts (for ace.holaf.fr)
    if ! grep -q "allowedHosts" vite.config.ts; then
        sed -i "s|server: {|server: { allowedHosts: 'all',|g" vite.config.ts
    fi

    # Fix 3: Inject WebSocket proxy for /bridge if not present
    if ! grep -q '"/bridge"' vite.config.ts; then
        sed -i 's|proxy: {|proxy: { "/bridge": { target: "ws://127.0.0.1:8001", ws: true, changeOrigin: true, secure: false, rewrite: (path) => path.replace(/^\\/bridge/, "") },|' vite.config.ts
    fi
fi

# Patch 4: Fix WASM Engine initialization (target the named export)
if [ -f "src/engine/EffectsEngine.ts" ]; then
    sed -i "s|await eng.initialize(ctx)|await (eng.wasmDspEngine \|\| eng).initialize(ctx)|g" src/engine/EffectsEngine.ts
fi

# Patch 5: Guard against undefined AudioWorklet (backup for non-HTTPS browsers)
if [ -f "src/wasm/WasmDspEngine.ts" ]; then
    sed -i 's|await audioContext.audioWorklet.addModule|if (audioContext.audioWorklet) await audioContext.audioWorklet.addModule|g' src/wasm/WasmDspEngine.ts
fi

if [ ! -d "node_modules" ]; then
    npm install
fi

# --- Launch ---
echo "--- Launching Services ---"
export PYTORCH_ALLOC_CONF=expandable_segments:True

# Start Backend API
cd "${BACKEND_DIR}"
BACKEND_CMD="python -m uvicorn acestep.api_server:app --host 0.0.0.0 --port 8001 --workers 1"
echo "--> Starting Engine: ${BACKEND_CMD}"
eval ${BACKEND_CMD} &
BACKEND_PID=$!
trap "kill $BACKEND_PID" EXIT SIGINT SIGTERM

# Start Frontend
cd "${FRONTEND_DIR}"
echo "--> Starting Web DAW (Port ${WEBUI_PORT})"
npm run dev -- --host 0.0.0.0 --port ${WEBUI_PORT}