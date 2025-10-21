#!/bin/bash

# --- VNC & Firefox Runtime Installation Check ---
# This block checks if VNC components are installed. If not, it installs them.
# This is a workaround for build process issues. It uses 'sudo' because
# this entry script is executed as the non-root user 'abc'.
if [ ! -f /usr/bin/websockify ]; then
    echo "--- First run detected: Installing VNC and Firefox dependencies (with sudo) ---"
    
    # Using 'sudo' for all privileged operations
    sudo apt-get update -q
    
    # Install VNC components
    sudo apt-get install -y -q=2 tigervnc-standalone-server websockify novnc openbox
    
    # Install non-snap Firefox via Mozilla PPA
    sudo apt-get install -y -q=2 software-properties-common
    sudo add-apt-repository ppa:mozillateam/ppa -y
    
    # Use 'tee' with 'sudo' to write to a privileged file
    echo 'Package: *' | sudo tee /etc/apt/preferences.d/mozilla-firefox > /dev/null
    echo 'Pin: release o=LP-PPA-mozillateam' | sudo tee -a /etc/apt/preferences.d/mozilla-firefox > /dev/null
    echo 'Pin-Priority: 1001' | sudo tee -a /etc/apt/preferences.d/mozilla-firefox > /dev/null
    
    sudo apt-get update -q
    sudo apt-get install -y firefox
    
    echo "--- VNC and Firefox installation complete ---"
fi
# --- End of Runtime Installation Check ---


# Set environment variables
export PATH="/home/abc/miniconda3/bin:$PATH"

# Activate the base conda environment which will host AiKore
source activate base

echo "--- Installing/Updating AiKore dependencies ---"
pip install --upgrade pip
pip install -r /opt/sd-install/aikore/requirements.txt

echo "--- Starting AiKore Backend ---"
# Change to the application's root directory
cd /opt/sd-install

# Launch the FastAPI application using uvicorn on an internal port
exec uvicorn aikore.main:app --host 0.0.0.0 --port 8000