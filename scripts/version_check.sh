#!/bin/bash

echo "--- System Information ---"

# Operating System
if [ -f /etc/os-release ]; then
    . /etc/os-release
    echo "OS: $PRETTY_NAME"
else
    echo "OS: $(uname -a)"
fi

# CPU
if [ -f /proc/cpuinfo ]; then
    echo "CPU: $(cat /proc/cpuinfo | grep "model name" | uniq | sed -e 's/model name[[:space:]]*: //')"
else
    echo "CPU: N/A"
fi

# RAM
if [ -f /proc/meminfo ]; then
    echo "RAM: $(free -h | awk '/^Mem/ {print $2}')"
else
    echo "RAM: N/A"
fi

# GPU and CUDA
if command -v nvidia-smi &> /dev/null
then
    echo ""
    echo "--- GPU & CUDA ---"
    nvidia-smi --query-gpu=gpu_name,driver_version,memory.total --format=csv,noheader,nounits | awk -F, '{print "GPU: " $1 "\nDriver Version: " $2 "\nGPU Memory: " $3 " MiB"}'
    echo "CUDA Version (from nvidia-smi): $(nvidia-smi | grep "CUDA Version" | awk '{print $9}')"
else
    echo "NVIDIA GPU not found or nvidia-smi is not installed."
fi

echo ""
echo "--- Python & Libraries ---"

# Check if a conda environment is active
if [ -n "$CONDA_PREFIX" ]; then
    echo "Active Conda Environment: $CONDA_PREFIX"
    PYTHON_CMD="python"
else
    echo "No active Conda environment found. Using system python."
    PYTHON_CMD="python3"
fi

# Python Version
if command -v $PYTHON_CMD &> /dev/null
then
    echo "Python: $($PYTHON_CMD --version)"

    # Python Libraries
    PYTHON_PACKAGES=(
        "torch"
        "torchvision"
        "xformers"
        "flash-attn"
        "sage-attention"
        "accelerate"
        "bitsandbytes"
        "triton"
        "peft"
        "numpy"
        "Pillow"
        "opencv-python"
        "transformers"
        "diffusers"
    )

    echo "Python Libraries:"
    for package in "${PYTHON_PACKAGES[@]}"; do
        # Use a clean python command to get the version
        version=$($PYTHON_CMD -c "import importlib.metadata; print(importlib.metadata.version('$package'))" 2>/dev/null)
        if [[ -z "$version" ]]; then
            version="Not Installed"
        fi
        printf "  %-17s: %s\n" "$package" "$version"
    done

    # Get CUDA version from PyTorch, check if torch is installed first
    if $($PYTHON_CMD -c "import importlib.util; print(importlib.util.find_spec('torch') is not None)" 2>/dev/null | grep -q "True"); then
        $PYTHON_CMD -c "import torch; print('CUDA Version (from PyTorch): ' + (torch.version.cuda if torch.cuda.is_available() else 'N/A'))"
    fi
else
    echo "Python not found."
fi

echo "---AIKORE-SEPARATOR---"

echo ""
echo "--- Dependency Check (pip check) ---"
if command -v $PYTHON_CMD &> /dev/null
then
    $PYTHON_CMD -m pip check
else
    echo "Python not found, cannot run pip check."
fi
