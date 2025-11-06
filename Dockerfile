# The final image, starting from the buildbase which now contains KasmVNC and our compiled Python wheels.
FROM ghcr.io/grokuku/aikore-buildbase:latest

# --- Runtime System Dependencies ---
# We add common utilities and a full build toolchain for runtime flexibility,
# allowing blueprints or users to compile dependencies if needed.

# --- Add Mozilla PPA to install Firefox without snap ---
RUN apt-get update && apt-get install -y --no-install-recommends software-properties-common && \
    add-apt-repository ppa:mozillateam/ppa && \
    printf "Package: firefox*\\nPin: release o=LP-PPA-mozillateam\\nPin-Priority: 1001\\n" > /etc/apt/preferences.d/mozilla-firefox && \
    apt-get update

RUN apt-get install -y --no-install-recommends \
    # Core application tools
    rsync \
    dos2unix \
    socat \
    # Compilation tools for runtime user needs
    cmake \
    build-essential \
    gcc-13 \
    g++-13 \
    git \
    # Common utility tools for debugging and scripting
    curl \
    wget \
    gnupg \
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
# Convert s6-overlay scripts to Unix line endings to prevent execution errors
RUN find /etc/s6-overlay/s6-rc.d/ -type f -print0 | xargs -0 dos2unix --

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

# Set compiler and Torch/CUDA architecture for any potential runtime compilations by Python
ENV CC=/usr/bin/gcc-13
ENV CXX=/usr/bin/g++-13
ENV TORCH_CUDA_ARCH_LIST="8.0 8.6 8.7 8.9 9.0 9.0a 10 12"

# --- Application Setup ---
# Create application directories
RUN mkdir -p ${BASE_DIR}/temp ${SD_INSTALL_DIR}

# Copy AiKore application and its blueprints
COPY --chown=abc:abc aikore/ ${SD_INSTALL_DIR}/aikore/
COPY --chown=abc:abc blueprints/ ${SD_INSTALL_DIR}/blueprints/
COPY --chown=abc:abc scripts/ ${SD_INSTALL_DIR}/scripts/

# Copy application scripts
COPY --chown=abc:abc entry.sh ${SD_INSTALL_DIR}/entry.sh
COPY --chown=abc:abc functions.sh ${SD_INSTALL_DIR}/functions.sh

# --- Script & Permission Cleanup ---
RUN find ${SD_INSTALL_DIR} -type f -name "*.sh" -print0 | xargs -0 dos2unix -- && \
    find ${SD_INSTALL_DIR} -type f -name "*.sh" -print0 | xargs -0 chmod +x

# --- User and Environment Setup ---
ENV XDG_CONFIG_HOME=/home/abc
ENV HOME=/home/abc

# --- CRITICAL REORDERING ---
# Set final ownership of all key directories BEFORE switching to the user.
RUN chown -R abc:abc /home/abc && \
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

# Activate conda, install Python dependencies
RUN . /home/abc/miniconda3/bin/activate && \
    pip install --no-cache-dir /wheels/*.whl && \
    pip install --no-cache-dir -r ${SD_INSTALL_DIR}/aikore/requirements.txt

# --- Final Step: Switch back to root ---
# The container must start as root to allow the s6-overlay init system to function.
USER root

# Expose AiKore's default port
EXPOSE 9000/tcp