# AiKore Blueprint Development Guide

    ## 1. Introduction
    A **Blueprint** in AiKore is a bash script responsible for bootstrapping, configuring, and launching an AI WebUI or backend service. Because AiKore uses a **Neutral Image Architecture**, the blueprint must handle the creation of its environment, the compilation/linking of dependencies, and the routing of its internal ports, without relying on pre-installed heavy modules in the base Docker image.

    ---

    ## 2. Global Variables & Base Setup
    Every blueprint is executed by the AiKore Process Manager, which injects specific environment variables. 

    ### Available Variables
    *   `INSTANCE_NAME`: Unique user-defined string for the instance.
    *   `INSTANCE_CONF_DIR`: Dedicated isolated directory for the instance (`/config/instances/{instance_name}`).
    *   `INSTANCE_OUTPUT_DIR`: Dedicated directory for generated outputs.
    *   `WEBUI_PORT`: The internal ephemeral port dynamically assigned to this instance.
    *   `BLUEPRINT_ID`: The filename of the blueprint script.
    *   `PYTHON_VERSION`, `TORCH_VERSION`, `PYTORCH_INDEX_URL`: Inherited from `/opt/sd-install/versions.env` (can be overridden by user).

    ### Mandatory Script Header
    A blueprint must always start with `set -e` (to fail fast on errors) and source the system functions:
    ```bash
    #!/bin/bash
    set -e
    source /opt/sd-install/functions.sh
    source /opt/sd-install/versions.env
    export PATH="/home/abc/miniconda3/bin:$PATH"
    ```

    ---

    ## 3. The Metadata Block
    AiKore parses the header of the script to generate the UI. It must be placed at the very top of the file:
    ```bash
    ### AIKORE-METADATA-START ###
    # aikore.name = AppName
    # aikore.category = Category (e.g., Image Generation, Training, Audio)
    # aikore.description = A short description of the tool.
    # aikore.venv_type = conda
    # aikore.venv_path = ./env
    ### AIKORE-METADATA-END ###
    ```

    ---

    ## 4. The 5-Step Blueprint Workflow

    ### Step 1: Repository Management
    Always check if the directory exists to either `git clone` or update the repository. 
    Use the built-in `check_remote "GIT_REF"` function for safe updates.
    ```bash
    if [ ! -d "${APP_DIR}/.git" ]; then
        git clone https://github.com/user/repo.git "${APP_DIR}"
    else
        cd "${APP_DIR}"
        check_remote "GIT_REF"
    fi
    ```

    ### Step 2: Environment Isolation
    Use Conda to isolate the environment. Always clean the cache and respect the user's custom python version if defined.
    ```bash
    conda clean -ya
    clean_env "${VENV_DIR}"

    if [ ! -d "${VENV_DIR}" ]; then
        conda create -p "${VENV_DIR}" python="${PYTHON_VERSION:-3.12}" -y
    fi
    source activate "${VENV_DIR}"
    ```

    ### Step 3: Dependency Handling (The Most Critical Step)
    AiKore relies on a centralized builder. **You must prevent the application's `requirements.txt` from overriding AiKore's optimized wheels.**

    1.  **Install Base PyTorch**: Always use the system variables.
        ```bash
        pip install torch==${TORCH_VERSION} torchvision torchaudio --index-url ${PYTORCH_INDEX_URL}
        ```
    2.  **Install Pre-built Wheels**: Install customized wheels (FlashAttention, XFormers) mapped to this instance.
        ```bash
        WHEELS_DIR="${INSTANCE_CONF_DIR}/wheels"
        if [ -d "${WHEELS_DIR}" ] && ls "${WHEELS_DIR}"/*.whl 1> /dev/null 2>&1; then
            pip install "${WHEELS_DIR}"/*.whl
        fi
        ```
    3.  **Filter `requirements.txt`**: Strip out packages already handled by AiKore before running pip install.
        ```bash
        PACKAGES_TO_EXCLUDE="torch|torchvision|torchaudio|xformers|bitsandbytes|flash-attn|sageattention"
        grep -v -i -E "^(${PACKAGES_TO_EXCLUDE})" requirements.txt > requirements-filtered.txt
        pip install -r requirements-filtered.txt
        ```

    ### Step 4: Storage & Symlinks
    Use the built-in `sl_folder` function to map the app's internal folders to the global AiKore `/config/models` structure, and link outputs to `INSTANCE_OUTPUT_DIR`.
    ```bash
    # sl_folder <source_parent_dir> <source_folder_name> <target_parent_dir> <target_folder_name>
    sl_folder "${APP_DIR}/models" "checkpoints" "/config/models" "stable-diffusion"
    
    TARGET_PARENT=$(dirname "$INSTANCE_OUTPUT_DIR")
    TARGET_FOLDER=$(basename "$INSTANCE_OUTPUT_DIR")
    sl_folder "${APP_DIR}" "outputs" "${TARGET_PARENT}" "${TARGET_FOLDER}"
    ```

    ### Step 5: Launch & Network Binding
    *   **Host**: The app **MUST** bind to `0.0.0.0` (not `127.0.0.1` or `localhost`), otherwise NGINX cannot proxy it.
    *   **Port**: The app **MUST** bind to `${WEBUI_PORT}`.
    ```bash
    CMD="python app.py --host 0.0.0.0 --port ${WEBUI_PORT}"
    eval $CMD
    sleep infinity
    ```

    ---

    ## 5. Advanced Scenarios & Best Practices

    ### Case A: Complex/Nested `requirements.txt` (e.g., ComfyUI Custom Nodes)
    If the application has sub-modules or plugins, you must dynamically find and filter all requirements files to prevent a rogue node from downgrading PyTorch.
    ```bash
    find "${CUSTOM_NODES_DIR}" -name "requirements.txt" -print0 | while IFS= read -r -d $'\0' req_file; do
        TEMP_REQ_FILE=$(mktemp)
        grep -v -i -E "^(${PACKAGES_TO_EXCLUDE})" "$req_file" > "$TEMP_REQ_FILE"
        if [ -s "$TEMP_REQ_FILE" ]; then pip install -r "$TEMP_REQ_FILE"; fi
        rm "$TEMP_REQ_FILE"
    done
    ```

    ### Case B: Hardcoded IPs or WebSockets (e.g., Vue/React Frontends)
    Some applications (like AceStepDAW) hardcode `127.0.0.1` for WebSocket connections, which breaks behind AiKore's Reverse Proxy. You must use `sed` to patch the source code dynamically before building.
    ```bash
    # Patch WebSocket routing to use the browser's current host instead of localhost
    find src -type f -exec sed -i "s|\`ws://127.0.0.1:\${this.port}\`|(window.location.protocol === 'https:' ? 'wss://' : 'ws://') + window.location.host + '/bridge'|g" {} +
    ```

    ### Case C: Multi-Process Applications (Backend + Frontend)
    If the application requires running a backend (e.g., Uvicorn) and a frontend (e.g., Node/Vite) simultaneously, run the backend in the background (`&`), trap its PID, and run the frontend in the foreground.
    ```bash
    # Start Backend
    BACKEND_CMD="python -m uvicorn api:app --host 0.0.0.0 --port 8001"
    eval ${BACKEND_CMD} &
    BACKEND_PID=$!

    # Ensure backend dies when the blueprint stops
    trap "kill $BACKEND_PID" EXIT SIGINT SIGTERM

    # Start Frontend on the allocated AiKore port
    npm run dev -- --host 0.0.0.0 --port ${WEBUI_PORT}
    ```

    ### Case D: Direct Asset Downloading
    If an application requires specific models at runtime that are not standard (e.g., JustRayzist specific safetensors), download them directly using `wget` into the correct structure, but only if they don't already exist.
    ```bash
    if [ ! -f "${TARGET_PATH}" ]; then
        wget -q --show