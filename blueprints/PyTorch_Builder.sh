### AIKORE-METADATA-START ###
# aikore.name = PyTorch Builder
# aikore.category = System / Tools
# aikore.description = Compiles a specific version of PyTorch from source. This is a long process.
# aikore.venv_type = none
### AIKORE-METADATA-END ###

#!/bin/bash
# Exit immediately if a command exits with a non-zero status.
set -e

# --- Configuration ---
# Variables to easily control the build process.
PYTORCH_TAG="v2.9.0"
TORCH_CUDA_ARCH_LIST="8.9" # Space-separated list
WHEEL_DIR="/wheels"

# --- Script Start ---
echo "--- Starting Blueprint: PyTorch Builder ---"
echo "This script will attempt to build PyTorch ${PYTORCH_TAG} for CUDA architectures: ${TORCH_CUDA_ARCH_LIST}"
echo "This is a very long process and can take over an hour."

# --- Check for Existing Wheel ---
# Clean the version tag to match wheel naming conventions (e.g., v2.9.0 -> 2.9.0)
PYTORCH_TAG_CLEAN=$(echo "${PYTORCH_TAG}" | sed 's/^v//')

# Check if a wheel for this version already exists. The exact name can vary slightly.
if ls "${WHEEL_DIR}/torch-${PYTORCH_TAG_CLEAN}"*.whl 1> /dev/null 2>&1; then
    echo "---"
    echo "SUCCESS: A PyTorch wheel for version ${PYTORCH_TAG} already exists in ${WHEEL_DIR}."
    echo "Skipping build."
    echo "---"
    exit 0
fi

# --- Build Preparation ---
echo "--- Preparing build environment ---"
# Create a temporary directory for the build to ensure it's clean
BUILD_DIR=$(mktemp -d)
# Set up a trap to ensure the build directory is cleaned up on exit
trap 'echo "--- Cleaning up temporary build directory ---"; rm -rf "${BUILD_DIR}"' EXIT

echo "Build will occur in temporary directory: ${BUILD_DIR}"

# --- Dependency Check/Install ---
# The base AiKore image should have these, but we run it just in case.
# The apt-get commands are removed as they cause permission errors and dependencies are already in the base image.

# --- Python Build Dependencies ---
echo "--- Installing Python build dependencies ---"
python3 -m pip install --no-cache-dir wheel packaging scikit-build-core numpy cython six

# --- Source Code Checkout ---
echo "--- Cloning PyTorch repository (version ${PYTORCH_TAG}) ---"
git clone --branch ${PYTORCH_TAG} https://github.com/pytorch/pytorch.git "${BUILD_DIR}/pytorch"
cd "${BUILD_DIR}/pytorch"

echo "--- Initializing submodules ---"
git submodule update --init --recursive

# --- Compilation ---
echo "============================================================================"
echo "Starting PyTorch Compilation..."
echo "This is the long part. Please be patient."
echo "============================================================================"

# Set all environment variables for the build
export CMAKE_BUILD_TYPE=Release
export TORCH_CUDA_ARCH_LIST="${TORCH_CUDA_ARCH_LIST}"
export USE_CUDA=1
export BUILD_TEST=0
export CUDACXX=/usr/local/cuda/bin/nvcc
# Use MAX_JOBS from the container environment if available, otherwise default to 2
export MAX_JOBS=${MAX_JOBS:-2}

# Run the build command
python3 -m pip wheel . --wheel-dir "${BUILD_DIR}/dist"

echo "============================================================================"
echo "Compilation command finished."
echo "============================================================================"

# --- Finalization ---
echo "--- Finalizing build ---"
# Find the generated wheel file (there should be only one)
BUILT_WHEEL=$(find "${BUILD_DIR}/dist" -name "*.whl")

if [ -z "${BUILT_WHEEL}" ]; then
    echo "!!! ERROR: Build command finished, but no wheel file was found in ${BUILD_DIR}/dist"
    exit 1
fi

echo "Successfully built wheel: $(basename "${BUILT_WHEEL}")"

echo "Moving wheel to shared directory: ${WHEEL_DIR}"
mv "${BUILT_WHEEL}" "${WHEEL_DIR}/"

echo "---"
echo "SUCCESS: PyTorch wheel has been built and moved to ${WHEEL_DIR}."
echo "The instance can now be stopped."
echo "---"

# The script will exit here, and the trap will clean up the build directory.
