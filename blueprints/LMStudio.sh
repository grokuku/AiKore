### AIKORE-METADATA-START ###
# aikore.name = LM Studio
# aikore.category = Chat / LLM
# aikore.description = Discover, download, and run local LLMs. (v0.4.x Compatible).
# aikore.venv_type = conda
# aikore.venv_path = ./env
# aikore.persistent_mode = true
### AIKORE-METADATA-END ###

#!/bin/bash
set -e

source /opt/sd-install/functions.sh

export PATH="/home/abc/miniconda3/bin:$PATH"

echo "--- Starting Blueprint: LM Studio (Update Fix) for Instance: ${INSTANCE_NAME} ---"

mkdir -p "${INSTANCE_CONF_DIR}"
mkdir -p "${INSTANCE_OUTPUT_DIR}"

APP_DIR="${INSTANCE_CONF_DIR}/LMStudio"
VENV_DIR="${INSTANCE_CONF_DIR}/env"

# --- 1. Isolation Strategy (The Fake Home) ---
FAKE_HOME="${INSTANCE_CONF_DIR}/internal_home"
mkdir -p "${FAKE_HOME}"
export HOME="${FAKE_HOME}"

echo "Instance Home Directory set to: ${FAKE_HOME}"

# --- 2. Environment Setup ---
echo "--- Setting up Conda environment ---"
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

# --- 3. Robust Update Logic (0.4.x Focus) ---
mkdir -p "${APP_DIR}"
cd "${APP_DIR}"

VERSION_FILE="installed_version.txt"
# Using the direct redirect URL to bypass the stuck manifest
REDIRECT_URL="https://lmstudio.ai/download/latest/linux/x64?format=AppImage"

echo "Checking for the truly latest version..."

# Extracting filename from redirect headers (e.g., LM-Studio-0.4.3-x64.AppImage)
LATEST_FILENAME=$(curl -sI "$REDIRECT_URL" | grep -i "location:" | awk '{print $2}' | tr -d '\r' | xargs basename)

if [ -z "$LATEST_FILENAME" ]; then
    echo "WARNING: Could not determine latest version from redirect. Falling back."
    LATEST_VERSION="0.3.35" # Legacy fallback
    DOWNLOAD_URL="https://installers.lmstudio.ai/linux/x64/0.3.35-1/LM-Studio-0.3.35-1-x64.AppImage"
else
    # Extract version number (e.g., 0.4.3) from filename like LM-Studio-0.4.3-x64.AppImage
    LATEST_VERSION=$(echo "$LATEST_FILENAME" | grep -oP '\d+\.\d+\.\d+' || echo "unknown")
    DOWNLOAD_URL="$REDIRECT_URL"
    echo "Latest Available: $LATEST_VERSION ($LATEST_FILENAME)"
fi

CURRENT_VERSION=""
if [ -f "$VERSION_FILE" ]; then
    CURRENT_VERSION=$(cat "$VERSION_FILE")
fi

NEED_UPDATE=false
if [ "$CURRENT_VERSION" != "$LATEST_VERSION" ]; then
    NEED_UPDATE=true
fi
if [ ! -f "squashfs-root/lm-studio" ]; then
    echo "Binary missing. Forcing installation."
    NEED_UPDATE=true
fi

if [ "$NEED_UPDATE" = true ]; then
    echo "--- Performing Installation ($LATEST_VERSION) ---"
    rm -rf squashfs-root
    rm -f *.AppImage
    
    echo "Downloading from: $DOWNLOAD_URL"
    wget -L -O "LM_Studio.AppImage" "$DOWNLOAD_URL"
    
    echo "Extracting AppImage..."
    chmod +x "LM_Studio.AppImage"
    ./"LM_Studio.AppImage" --appimage-extract > /dev/null
    rm "LM_Studio.AppImage"
    
    echo "$LATEST_VERSION" > "$VERSION_FILE"
    echo "Update complete."
fi

# --- 4. Symlinks ---
REAL_MODELS_DIR="${FAKE_HOME}/.cache/lm-studio/models"
mkdir -p "${REAL_MODELS_DIR}"
sl_folder "${INSTANCE_OUTPUT_DIR}" "models_link" "${REAL_MODELS_DIR}" ""

# --- 5. Launch Preparation ---
export ELECTRON_NO_SANDBOX=1
export PATH="${VENV_DIR}/bin:$PATH"
export LD_LIBRARY_PATH="${VENV_DIR}/lib:$LD_LIBRARY_PATH"
export DISPLAY=${DISPLAY:-:1}

# Wait for X Server
SOCKET_FILE="/tmp/.X11-unix/X${DISPLAY#:}"
echo "Waiting for X socket at $SOCKET_FILE..."
MAX_RETRIES=30
count=0
while [ ! -e "$SOCKET_FILE" ]; do
    sleep 1
    count=$((count+1))
    if [ $count -ge $MAX_RETRIES ]; then
        break
    fi
done

# Disable Auto-Updater (redundant since we manage it here)
UPDATER_PATH="${APP_DIR}/squashfs-root/resources/app-update.yml"
if [ -f "$UPDATER_PATH" ]; then
    mv "$UPDATER_PATH" "${UPDATER_PATH}.bak"
fi

# --- 6. SANDBOX NEUTRALIZATION ---
echo "--- Neutralizing Chrome Sandbox ---"
cd "${APP_DIR}/squashfs-root"
if [ -f "chrome-sandbox" ]; then
    mv "chrome-sandbox" "chrome-sandbox.bak"
fi

# --- 7. Launch ---
echo "--- Launching LM Studio ---"
BINARY_NAME="lm-studio"
exec ./${BINARY_NAME} --no-sandbox