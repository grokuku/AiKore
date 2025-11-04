#!/bin/bash

# This script is responsible for launching the KasmVNC server and the
# target application inside the pre-configured desktop environment.

set -e

echo "--- KasmVNC Launcher Initializing ---"

# --- Arguments ---
INSTANCE_NAME="$1"
INSTANCE_PORT="$2"
BLUEPRINT_SCRIPT="$3"

if [ -z "$INSTANCE_NAME" ] || [ -z "$INSTANCE_PORT" ] || [ -z "$BLUEPRINT_SCRIPT" ]; then
    echo "[ERROR] Missing required arguments: INSTANCE_NAME, INSTANCE_PORT, BLUEPRINT_SCRIPT"
    exit 1
fi

# --- Environment Setup ---
# KasmVNC expects an X server to be running. We'll use Xvfb.
# We also need a window manager, Openbox is lightweight.
export DISPLAY=":1"

echo "[INFO] Instance Name: ${INSTANCE_NAME}"
echo "[INFO] Instance Port: ${INSTANCE_PORT}"
echo "[INFO] Blueprint Script: ${BLUEPRINT_SCRIPT}"
echo "[INFO] DISPLAY: ${DISPLAY}"

# --- Service Launching ---

# 1. Start Xvfb (X Virtual Framebuffer)
echo "[INFO] Starting Xvfb..."
Xvfb ${DISPLAY} -screen 0 1920x1080x24 -ac +extension GLX +render -noreset & 
XVFB_PID=$!
export XVFB_PID

# 2. Start a lightweight window manager (Openbox)
echo "[INFO] Starting Openbox..."
openbox & 
OPENBOX_PID=$!
export OPENBOX_PID

# 3. Start KasmVNC Server
echo "[INFO] Starting KasmVNC server on port ${INSTANCE_PORT}..."
# The KasmVNC server binary will be in /usr/local/bin after installation
# The web client files will be in /usr/local/share/kasmvnc/www
/usr/local/bin/Xvnc \
    -interface 0.0.0.0 \
    -PublicIP 127.0.0.1 \
    -disableBasicAuth \
    -RectThreads 0 \
    -Log *:stdout:100 \
    -httpd /usr/local/share/kasmvnc/www \
    -sslOnly 0 \
    -SecurityTypes None \
    -websocketPort ${INSTANCE_PORT} \
    -FreeKeyMappings ${DISPLAY} & 
KASMVNC_PID=$!
export KASMVNC_PID

# 4. Run the Blueprint Application
echo "[INFO] Launching blueprint: ${BLUEPRINT_SCRIPT}"
# The blueprint script will inherit the DISPLAY environment variable.
/bin/bash "${BLUEPRINT_SCRIPT}" & 
BLUEPRINT_PID=$!
export BLUEPRINT_PID

echo "--- KasmVNC Launcher Setup Complete ---"

# Wait for all background processes to exit
wait ${BLUEPRINT_PID}
kill ${KASMVNC_PID} ${OPENBOX_PID} ${XVFB_PID}
