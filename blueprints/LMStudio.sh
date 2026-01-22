### AIKORE-METADATA-START ###
# aikore.name = LM Studio
# aikore.category = Chat / LLM
# aikore.description = Discover, download, and run local LLMs. (Sandbox Fixed).
# aikore.venv_type = conda
# aikore.venv_path = ./env
# aikore.persistent_mode = true
### AIKORE-METADATA-END ###

#!/bin/bash
set -e

source /opt/sd-install/functions.sh

export PATH="/home/abc/miniconda3/bin:$PATH"

echo "--- Starting Blueprint: LM Studio (Sandbox Fix) for Instance: ${INSTANCE_NAME} ---"

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

# --- 3. Robust Update Logic ---
mkdir -p "${APP_DIR}"
cd "${APP_DIR}"

VERSION_FILE="installed_version.txt"
MANIFEST_URL="https://installers.lmstudio.ai/linux/x64/latest-linux.yml"
BASE_URL="https://installers.lmstudio.ai/linux/x64"

FALLBACK_VERSION="0.3.35"
FALLBACK_FILENAME="LM-Studio-0.3.35-1-x64.AppImage"
FALLBACK_URL="https://installers.lmstudio.ai/linux/x64/0.3.35-1/LM-Studio-0.3.35-1-x64.AppImage"

echo "Checking for updates..."

LATEST_VERSION=""
LATEST_FILENAME=""
DOWNLOAD_URL=""

if curl -sL -f "$MANIFEST_URL" -o manifest.yml; then
    LATEST_VERSION=$(grep "version:" manifest.yml | head -n 1 | awk '{print $2}' | tr -d '"' | tr -d ' ')
    LATEST_FILENAME=$(grep "path:" manifest.yml | head -n 1 | awk '{print $2}' | tr -d '"' | tr -d ' ')
    if [ -z "$LATEST_FILENAME" ]; then
        LATEST_FILENAME=$(grep "url:" manifest.yml | head -n 1 | awk '{print $2}' | tr -d '"' | tr -d ' ')
    fi
    
    if [ -n "$LATEST_FILENAME" ]; then
        if [[ "$LATEST_FILENAME" == http* ]]; then
            DOWNLOAD_URL="$LATEST_FILENAME"
        else
            DOWNLOAD_URL="${BASE_URL}/${LATEST_FILENAME}"
        fi
    fi
else
    echo "WARNING: Failed to download update manifest."
fi

if [ -z "$LATEST_VERSION" ] || [ -z "$DOWNLOAD_URL" ]; then
    echo "Using Fallback Version: $FALLBACK_VERSION"
    LATEST_VERSION="$FALLBACK_VERSION"
    DOWNLOAD_URL="$FALLBACK_URL"
else
    echo "Latest Available: $LATEST_VERSION"
fi

CURRENT_VERSION=""
if [ -f "$VERSION_FILE" ]; then
    CURRENT_VERSION=$(cat "$VERSION_FILE")
fi

NEED_UPDATE=false
if [ -z "$CURRENT_VERSION" ] || [ "$CURRENT_VERSION" != "$LATEST_VERSION" ]; then
    NEED_UPDATE=true
fi
if [ ! -f "squashfs-root/lm-studio" ]; then
    echo "Installation check failed. Forcing update/reinstall."
    NEED_UPDATE=true
fi

if [ "$NEED_UPDATE" = true ]; then
    echo "--- Performing Installation ($LATEST_VERSION) ---"
    rm -rf squashfs-root
    rm -f *.AppImage manifest.yml
    
    wget -O "LM_Studio.AppImage" "$DOWNLOAD_URL"
    
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

# Disable Auto-Updater
UPDATER_PATH="${APP_DIR}/squashfs-root/resources/app-update.yml"
if [ -f "$UPDATER_PATH" ]; then
    mv "$UPDATER_PATH" "${UPDATER_PATH}.bak"
fi

# --- 6. SANDBOX NEUTRALIZATION (THE FIX) ---
echo "--- Neutralizing Chrome Sandbox ---"
cd "${APP_DIR}/squashfs-root"

# If the chrome-sandbox binary exists, Electron will check its permissions (and fail).
# We rename it so Electron assumes it's missing and relies on --no-sandbox instead.
if [ -f "chrome-sandbox" ]; then
    echo "Renaming chrome-sandbox to prevent permission errors..."
    mv "chrome-sandbox" "chrome-sandbox.bak"
fi

# --- 7. Launch ---
echo "--- Launching LM Studio ---"

BINARY_NAME="lm-studio"
# Important: We explicitely pass --no-sandbox here as well
CMD="./${BINARY_NAME} --no-sandbox"

echo "Executing: ${CMD}"
eval $CMD
sleep infinity