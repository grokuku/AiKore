# The final neutral image, starting directly from KasmVNC Ubuntu Noble.
# No pre-built wheels are included. All module building is deferred to the AiKore Module Builder.
FROM ghcr.io/linuxserver/baseimage-kasmvnc:ubuntunoble

# --- Runtime System Dependencies ---
# We add common utilities and a full build toolchain for runtime flexibility,
# allowing the internal AiKore Module Builder to compile dependencies on demand.

# --- Add Mozilla PPA & NVIDIA CUDA Repo ---
RUN apt-get update && apt-get install -y --no-install-recommends software-properties-common wget gnupg && \
    add-apt-repository ppa:mozillateam/ppa && \
    printf "Package: firefox*\\nPin: release o=LP-PPA-mozillateam\\nPin-Priority: 1001\\n" > /etc/apt/preferences.d/mozilla-firefox && \
    wget https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2404/x86_64/cuda-keyring_1.1-1_all.deb && \
    dpkg -i cuda-keyring_1.1-1_all.deb && \
    rm cuda-keyring_1.1-1_all.deb && \
    apt-get update

# --- Install All System Dependencies ---
RUN apt-get update && apt-get install -y --no-install-recommends \
    # CUDA Toolkit (System-level compiler for the Module Builder)
    cuda-toolkit-13-0 \
    # Audio Backend for Torchaudio
    ffmpeg \
    # Core application tools
    rsync \
    dos2unix \
    socat \
    # Compilation tools for the Module Builder
    cmake \
    build-essential \
    gcc-13 \
    g++-13 \
    git \
    ninja-build \
    # Common utility tools for debugging and scripting
    curl \
    mc \
    bc \
    nano \
    python3-xdg \
    # KasmVNC/Persistent mode dependencies
    xvfb \
    firefox \
    && rm -rf /var/lib/apt/lists/*

# --- s6-overlay & Sudoers Configuration ---
# Copy our custom s6-overlay services and sudoers configuration
COPY docker/root/ /

# Ensure all s6-overlay scripts are executable and have correct line endings.
RUN find /etc/s6-overlay/ -type f -print0 | xargs -0 dos2unix -- && \
    find /etc/s6-overlay/ -type f -print0 | xargs -0 chmod +x

# Secure the sudoers file (Sudo ignores files with insecure permissions)
RUN chown root:root /etc/sudoers.d/aikore-sudo && \
    chmod 0440 /etc/sudoers.d/aikore-sudo

# --- Override and Neutralize Default Desktop Services ---
RUN printf '#!/bin/bash\n# Service disabled by AiKore\nexit 0\n' > /etc/s6-overlay/s6-rc.d/svc-de/run && \
    printf '#!/bin/bash\n# Service disabled by AiKore\nexit 0\n' > /etc/s6-overlay/s6-rc.d/svc-pulseaudio/run && \
    printf '#!/bin/bash\n# Service disabled by AiKore\nexit 0\n' > /etc/s6-overlay/s6-rc.d/svc-kasmvnc/run && \
    chmod +x /etc/s6-overlay/s6-rc.d/svc-de/run && \
    chmod +x /etc/s6-overlay/s6-rc.d/svc-pulseaudio/run && \
    chmod +x /etc/s6-overlay/s6-rc.d/svc-kasmvnc/run

# --- Environment Variables ---
ENV BASE_DIR=/config \
    SD_INSTALL_DIR=/opt/sd-install \
    XDG_CACHE_HOME=/config/temp

# Set compiler for runtime compilations by the Module Builder
ENV CC=/usr/bin/gcc-13
ENV CXX=/usr/bin/g++-13
# Note: Versioning variables (TORCH_VERSION, etc.) are loaded dynamically from versions.env
ENV CUDA_HOME=/usr/local/cuda
ENV PATH="/usr/local/cuda/bin:${PATH}"
ENV CPLUS_INCLUDE_PATH="/usr/local/cuda/include:${CPLUS_INCLUDE_PATH}"

# --- Application Setup ---
# Create application directories
RUN mkdir -p ${BASE_DIR}/temp ${SD_INSTALL_DIR}

# Copy AiKore application and its blueprints
COPY --chown=abc:abc aikore/ ${SD_INSTALL_DIR}/aikore/
COPY --chown=abc:abc blueprints/ ${SD_INSTALL_DIR}/blueprints/
COPY --chown=abc:abc scripts/ ${SD_INSTALL_DIR}/scripts/

# Copy application scripts and the version manifest
COPY --chown=abc:abc entry.sh ${SD_INSTALL_DIR}/entry.sh
COPY --chown=abc:abc functions.sh ${SD_INSTALL_DIR}/functions.sh
COPY --chown=abc:abc versions.env ${SD_INSTALL_DIR}/versions.env

# Add the manifest to the global profile so interactive shells automatically load the variables
RUN echo '#!/bin/bash\nset -a\nsource /opt/sd-install/versions.env\nset +a' > /etc/profile.d/aikore_versions.sh && \
    chmod +x /etc/profile.d/aikore_versions.sh

# --- Script & Permission Cleanup ---
RUN find ${SD_INSTALL_DIR} -type f -name "*.sh" -print0 | xargs -0 dos2unix -- && \
    find ${SD_INSTALL_DIR} -type f -name "*.sh" -print0 | xargs -0 chmod +x && \
    dos2unix ${SD_INSTALL_DIR}/versions.env

# --- User and Environment Setup ---
ENV XDG_CONFIG_HOME=/home/abc
ENV HOME=/home/abc

# Set final ownership of all key directories BEFORE switching to the user.
RUN mkdir -p /home/abc && \
    chown -R abc:abc /home/abc && \
    chown -R abc:abc ${SD_INSTALL_DIR} && \
    chown -R abc:abc ${BASE_DIR} && \
    mkdir -p /run/aikore && \
    chown abc:abc /run/aikore

# Switch to the standard user for Conda installation
USER abc
WORKDIR /home/abc

# Install Miniforge for Python environment management
RUN cd /tmp && \
    wget https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh && \
    bash Miniforge3-Linux-x86_64.sh -b -p /home/abc/miniconda3 && \
    rm Miniforge3-Linux-x86_64.sh

# Activate conda, install Python dependencies (No global wheels anymore)
RUN . /home/abc/miniconda3/bin/activate && \
    pip install --no-cache-dir -r ${SD_INSTALL_DIR}/aikore/requirements.txt

# --- Final Step: Switch back to root ---
# The container must start as root to allow the s6-overlay init system to function.
USER root

# Expose AiKore's default port
EXPOSE 9000/tcp