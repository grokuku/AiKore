#!/bin/bash

# This script is responsible for launching and supervising the KasmVNC server
# and the target application inside a dedicated desktop environment.

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
if [ -z "$DISPLAY" ]; then
    echo "[ERROR] DISPLAY environment variable not set. This must be provided by AiKore."
    exit 1
fi

echo "[INFO] Instance Name: ${INSTANCE_NAME}"
echo "[INFO] Instance Port: ${INSTANCE_PORT}"
echo "[INFO] Blueprint Script: ${BLUEPRINT_SCRIPT}"
echo "[INFO] DISPLAY: ${DISPLAY}"

# --- Cleanup function ---
cleanup() {
    echo "[INFO] Cleaning up KasmVNC services..."
    # Kill all child processes of this script
    pkill -P $$
}

# Trap SIGTERM and SIGINT to call the cleanup function
trap cleanup SIGTERM SIGINT

# --- Service Launching ---

# 1. Start KasmVNC Server in the BACKGROUND.
# The native AcceptSetDesktopSize=1 option should handle resizing.
echo "[INFO] Starting KasmVNC server on port ${INSTANCE_PORT} for display ${DISPLAY}..."
/usr/local/bin/Xvnc \
    -interface 0.0.0.0 \
    -PublicIP 127.0.0.1 \
    -disableBasicAuth \
    -Log *:stdout:100 \
    -httpd /usr/local/share/kasmvnc/www \
    -sslOnly 0 \
    -SecurityTypes None \
    -websocketPort ${INSTANCE_PORT} \
    -depth 24 \
    ${DISPLAY} &

# Store the PID of the Xvnc process
XVNC_PID=$!

# Wait a moment for the X server to initialize
sleep 2

# 2. Start a lightweight window manager (Openbox) in the background
# It now has a display to connect to.
echo "[INFO] Starting Openbox..."
openbox &

# 3. Run the Blueprint Application in the background
echo "[INFO] Launching blueprint: ${BLUEPRINT_SCRIPT}"
/bin/bash "${BLUEPRINT_SCRIPT}" &

echo "--- KasmVNC Launcher Setup Complete ---"

# 4. Wait for the Xvnc process to exit.
# This keeps the script alive and allows 'trap' to function correctly.
wait ${XVNC_PID}