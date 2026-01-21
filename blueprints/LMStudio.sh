### AIKORE-METADATA-START ###
# aikore.name = LM Studio
# aikore.category = Chat / LLM
# aikore.description = Discover, download, and run local LLMs. (Version 0.3.35).
# aikore.venv_type = conda
# aikore.venv_path = ./env
# aikore.persistent_mode = true
### AIKORE-METADATA-END ###

#!/bin/bash
set -e

source /opt/sd-install/functions.sh

export PATH="/home/abc/miniconda3/bin:$PATH"

echo "--- Starting Blueprint: LM Studio (Display Fix) for Instance: ${INSTANCE_NAME} ---"

mkdir -p "${INSTANCE_CONF_DIR}"
mkdir -p "${INSTANCE_OUTPUT_DIR}"

APP_DIR="${INSTANCE_CONF_DIR}/LMStudio"
VENV_DIR="${INSTANCE_CONF_DIR}/env"

# --- 1. Environment Setup (GUI Deps) ---
echo "--- Setting up Conda environment for GUI support ---"
if [ ! -d "${VENV_DIR}" ]; then
    echo "Creating Conda environment with Xorg libraries..."
    conda create -p "${VENV_DIR}" python=3.10 \
        gtk3 gdk-pixbuf cairo pango \
        alsa-lib nss nspr at-spi2-atk \
        libdrm libxkbcommon \
        xorg-libxcomposite \
        xorg-libxcursor \
        xorg-libxdamage \
        xorg-libxext \
        xorg-libxfixes \
        xorg-libxi \
        xorg-libxrandr \
        xorg-libxrender \
        xorg-libxscrnsaver \
        xorg-libxtst \
        mesa-libgl-devel-cos7-x86_64 \
        -c conda-forge -y
fi

source activate "${VENV_DIR}"

# --- 2. Download LM Studio ---
mkdir -p "${APP_DIR}"
cd "${APP_DIR}"

# URL for Version 0.3.35
LM_URL="https://installers.lmstudio.ai/linux/x64/0.3.35-1/LM-Studio-0.3.35-1-x64.AppImage"
FILENAME="LM_Studio.AppImage"

if [ ! -d "squashfs-root" ]; then
    if [ -f "$FILENAME" ]; then
        echo "Cleaning up potential corrupt file: $FILENAME"
        rm -f "$FILENAME"
    fi
fi

if [ ! -d "squashfs-root" ]; then
    echo "Downloading LM Studio 0.3.35..."
    wget -O "$FILENAME" "$LM_URL"

    # --- 3. Extract AppImage ---
    echo "Extracting AppImage (Bypassing FUSE)..."
    chmod +x "$FILENAME"
    ./"$FILENAME" --appimage-extract
    
    rm "$FILENAME"
else
    echo "LM Studio already extracted."
fi

# Verify extraction
BINARY_NAME="lm-studio"
if [ ! -f "squashfs-root/${BINARY_NAME}" ]; then
    echo "FATAL: Binary 'squashfs-root/${BINARY_NAME}' not found."
    ls -F "squashfs-root/"
    exit 1
fi

# --- 4. Configuration & Symlinks ---
export XDG_CONFIG_HOME="${INSTANCE_CONF_DIR}/config"
mkdir -p "${XDG_CONFIG_HOME}"

export XDG_CACHE_HOME="${INSTANCE_CONF_DIR}/cache"
mkdir -p "${XDG_CACHE_HOME}"

mkdir -p "${XDG_CACHE_HOME}/lm-studio/models"
sl_folder "${INSTANCE_OUTPUT_DIR}" "models_link" "${XDG_CACHE_HOME}/lm-studio" "models"

# --- 5. Launch ---
echo "--- Launching LM Studio ---"

# FIX 1: Explicitly set DISPLAY. 
# KasmVNC inside AiKore typically uses :1. We use :1 if DISPLAY is unset.
export DISPLAY=${DISPLAY:-:1}
echo "Targeting Display: $DISPLAY"

# FIX 2: Wait for X Server Socket
# We loop until the X server is actually ready to accept connections.
SOCKET_FILE="/tmp/.X11-unix/X${DISPLAY#:}"
echo "Waiting for X socket at $SOCKET_FILE..."

MAX_RETRIES=30
count=0
while [ ! -e "$SOCKET_FILE" ]; do
    sleep 1
    count=$((count+1))
    if [ $count -ge $MAX_RETRIES ]; then
        echo "WARNING: X socket not found after $MAX_RETRIES seconds. Trying launch anyway..."
        break
    fi
done
echo "X Server appears ready."

# FIX 3: DBus (Optional but helps Electron)
# If no DBus session exists, we try to act as if one does to silence errors,
# or we just rely on system default.
if [ -z "$DBUS_SESSION_BUS_ADDRESS" ]; then
   echo "No DBus session found, proceeding without specific DBus launch (common in Docker)."
fi

cd "${APP_DIR}/squashfs-root"

# We run the binary directly.
CMD="./${BINARY_NAME} --no-sandbox"

echo "Executing: ${CMD} in $(pwd)"
echo "NOTE: Open 'DESKTOP' view to interact."

eval $CMD
sleep infinity