#!/bin/bash

# AiKore VNC Debugging Script
# This script checks for the existence and permissions of all binaries
# and files required by the persistent (VNC) mode.

echo "--- AiKore VNC Environment Sanity Check ---"

# Helper function to check for a file or binary
check_item() {
    local path="$1"
    local type_desc="$2"
    echo -n "Checking for ${type_desc} at ${path}... "
    
    if [ ! -e "${path}" ]; then
        echo "[ FAILED ] - Does not exist."
        return
    fi
    
    if [ -d "${path}" ]; then
        echo "[ OK ] - Exists and is a directory."
        return
    fi
    
    if [ -f "${path}" ] && [ ! -x "${path}" ]; then
        echo "[ OK ] - Exists as a non-executable file."
        ls -l "${path}"
    elif [ -x "${path}" ]; then
        echo "[ OK ] - Exists and is executable."
        ls -l "${path}"
    else
        echo "[ FAILED ] - Exists but is not a regular file or executable."
        ls -l "${path}"
    fi
}

echo "--- 1. Verifying key binaries and files ---"
check_item "/usr/bin/Xvnc" "VNC Server"
check_item "/usr/bin/websockify" "VNC Web Client"
check_item "/usr/bin/openbox-session" "Window Manager"
check_item "/usr/bin/firefox" "Web Browser"
check_item "/usr/share/novnc" "noVNC web assets"
check_item "/etc/ssl/novnc.pem" "SSL Certificate"
check_item "/home/abc/.vnc/passwd" "VNC Password File"

echo ""
echo "--- 2. Attempting to start websockify manually ---"
echo "This test will reveal dependency or configuration errors."
echo "Starting websockify for 5 seconds..."

# We simulate the real command, but point to a dummy target port (6080)
# The output will tell us if the command itself is valid.
/usr/bin/websockify -v --web /usr/share/novnc/ --cert /etc/ssl/novnc.pem 6081 127.0.0.1:6080 &
WEBSOCKIFY_PID=$!

sleep 5

# Check if the process is still running
if ps -p $WEBSOCKIFY_PID > /dev/null; then
    echo "[ SUCCESS ] - websockify process is still running after 5 seconds."
    kill $WEBSOCKIFY_PID
    echo "Cleaned up websockify process."
else
    echo "[ FAILED ] - websockify process terminated prematurely. See output above for errors."
fi

echo ""
echo "--- 3. Checking for library dependencies (if ldd is available) ---"
if command -v ldd > /dev/null; then
    echo "Analyzing websockify dependencies:"
    ldd /usr/bin/websockify || echo "ldd command failed."
else
    echo "ldd command not found. Skipping dependency check."
fi

echo ""
echo "--- Sanity Check Complete ---"