FROM ghcr.io/grokuku/stable-diffusion-buildbase:latest

# Copy s6-overlay and custom service configuration
COPY docker/root/ /

# --- Environment Variables ---
ENV DEBIAN_FRONTEND=noninteractive
ENV BASE_DIR=/config \
    SD_INSTALL_DIR=/opt/sd-install \
    XDG_CACHE_HOME=/config/temp

# Set compiler and Torch/CUDA architecture for any potential runtime compilations
ENV CC=/usr/bin/gcc-13
ENV CXX=/usr/bin/g++-13
ENV TORCH_CUDA_ARCH_LIST="8.0 8.6 8.7 8.9 9.0 9.0a 10 12"

# --- System & Package Installation ---
RUN apt-get update -q && \
    # Install system dependencies for Ubuntu 24.04, including dos2unix for script cleanup
    apt-get install -y -q=2 curl \
    software-properties-common \
    wget \
    gnupg \
    mc \
    bc \
    nano \
    rsync \
    libxft2 \
    xvfb \
    cmake \
    build-essential \
    ffmpeg \
    gcc-13 \
    g++-13 \
    git \
    gawk \
    dos2unix && \
    # Remove any conflicting system Python to ensure Conda's version is used
    apt-get purge python3 -y && \
    # Install CUDA Toolkit for Ubuntu 24.04
    cd /tmp/ && \
    wget https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2404/x86_64/cuda-keyring_1.1-1_all.deb && \
    dpkg -i cuda-keyring_1.1-1_all.deb && \
    # Ajoute le dépôt Microsoft pour dotnet
    wget https://packages.microsoft.com/config/ubuntu/24.04/packages-microsoft-prod.deb -O packages-microsoft-prod.deb && \
    dpkg -i packages-microsoft-prod.deb && \
    rm packages-microsoft-prod.deb && \
    apt-get update && \
    apt-get -y install cuda-toolkit-12-8 dotnet-sdk-8.0 && \
    # Clean up package cache
    apt autoremove -y && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# --- s6-overlay Script Cleanup and Permissions ---
# Convert all s6 scripts to Unix line endings and ensure they are executable.
# This prevents errors caused by files edited on Windows (CRLF).
RUN find /etc/s6-overlay -type f -print0 | xargs -0 dos2unix --
RUN find /etc/s6-overlay -type f -name "run" -exec chmod +x {} +
RUN find /etc/s6-overlay -type f -name "finish" -exec chmod +x {} + || true

# --- KasmVNC Pacification ---
# Create a dummy openbox-session script to prevent log spam.
RUN printf '%s\n' '#!/bin/bash' 'exit 0' > /usr/bin/openbox-session && chmod +x /usr/bin/openbox-session
# Overwrite the window manager startup script to prevent the nvidia-smi loop.
RUN echo '#!/bin/bash\necho "Window manager startup script disabled for AiKore."\nsleep infinity' > /defaults/startwm.sh && chmod +x /defaults/startwm.sh

# --- Application Setup ---
# Create application directories
RUN mkdir -p ${BASE_DIR}/temp ${SD_INSTALL_DIR}

# Copy AiKore application and its blueprints
COPY --chown=abc:abc aikore/ ${SD_INSTALL_DIR}/aikore/
COPY --chown=abc:abc blueprints/ ${SD_INSTALL_DIR}/blueprints/

# Copy application scripts
COPY --chown=abc:abc entry.sh ${SD_INSTALL_DIR}/entry.sh
COPY --chown=abc:abc functions.sh ${SD_INSTALL_DIR}/functions.sh

# --- SCRIPT CLEANUP & PERMISSIONS ---
# Convert all copied .sh files to Unix line endings and make them executable.
RUN find ${SD_INSTALL_DIR} -type f -name "*.sh" -print0 | xargs -0 dos2unix -- && \
    find ${SD_INSTALL_DIR} -type f -name "*.sh" -print0 | xargs -0 chmod +x

# --- User and Environment Setup ---
# Set home directory for the application user
ENV XDG_CONFIG_HOME=/home/abc
ENV HOME=/home/abc
RUN mkdir /home/abc && \
    chown -R abc:abc /home/abc

# Install Miniforge for Python environment management (uses conda-forge by default)
RUN cd /tmp && \
    # URL for Miniforge installer
    wget https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh && \
    # Install Miniforge directly into the path expected by all launch scripts
    bash Miniforge3-Linux-x86_64.sh -b -p /home/abc/miniconda3 && \
    rm Miniforge3-Linux-x86_64.sh && \
    # Set final ownership for application folders
    chown -R abc:abc /root && \
    chown -R abc:abc ${SD_INSTALL_DIR} && \
    chown -R abc:abc /home/abc && \
    chown -R abc:abc ${BASE_DIR}

# Expose default ports
EXPOSE 9000/tcp