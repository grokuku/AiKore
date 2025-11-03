#!/bin/bash

# This script is responsible for launching the Selkies WebRTC server and the
# target application inside the pre-configured Selkies desktop environment.

set -e

echo "--- Selkies Launcher Initializing ---"

# --- Arguments ---
INSTANCE_NAME="$1"
INSTANCE_PORT="$2"
BLUEPRINT_SCRIPT="$3"

if [ -z "$INSTANCE_NAME" ] || [ -z "$INSTANCE_PORT" ] || [ -z "$BLUEPRINT_SCRIPT" ]; then
    echo "[ERROR] Missing required arguments: INSTANCE_NAME, INSTANCE_PORT, BLUEPRINT_SCRIPT"
    exit 1
fi

# --- Environment Setup ---
# The base image already provides a running X server on :1
export DISPLAY=":1"

# We must use the absolute path to the python environment provided by the base image.
PYTHON_EXEC="/lsiopy/bin/selkies"

# The web assets for the UI are now copied to /opt/selkies-web during build.
SELKIES_WEB_ROOT="/opt/selkies-web"

echo "[INFO] Instance Name: ${INSTANCE_NAME}"
echo "[INFO] Instance Port: ${INSTANCE_PORT}"
echo "[INFO] Blueprint Script: ${BLUEPRINT_SCRIPT}"
echo "[INFO] DISPLAY: ${DISPLAY}"
echo "[INFO] Python Exec: ${PYTHON_EXEC}"
echo "[INFO] Selkies Web Root: ${SELKIES_WEB_ROOT}"

# --- Service Launching ---

# 1. Wait for X Server to be ready before launching any graphical applications.
echo "[INFO] Waiting for X Server to be ready..."
while ! xset -q >/dev/null 2>&1; do
    sleep 0.5
done
echo "[INFO] X Server is ready."

# 2. Start Selkies Python WebRTC Server
# We do not start Xvfb, openbox, or any audio server. We trust the base image.
echo "[INFO] Starting Selkies WebRTC server on instance port ${INSTANCE_PORT}..."
export SELKIES_PORT=${INSTANCE_PORT}
${PYTHON_EXEC} -m selkies.selkies --host 0.0.0.0 --gst-web ${SELKIES_WEB_ROOT} &

# 3. Run the Blueprint Application
echo "[INFO] Launching blueprint: ${BLUEPRINT_SCRIPT}"
# The blueprint script will inherit the DISPLAY environment variable.
/bin/bash ${BLUEPRINT_SCRIPT} &

echo "--- Selkies Launcher Setup Complete ---"

# Wait for all background processes to exit
wait