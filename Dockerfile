# The final image, starting from the buildbase which contains compiled artifacts.
FROM ghcr.io/grokuku/aikore-buildbase:latest

# --- Runtime System Dependencies ---
# Install only RUNTIME dependencies, moved from the buildbase image.
RUN apt-get update && apt-get install -y --no-install-recommends 
    libgnutls30 libpng16-16 libtiff5 libgif7 libavformat58 libavcodec58 libswscale5 libssl3 
    libxrandr2 libxcursor1 libfreetype6 libxtst6 libpixman-1-0 libxshmfence1 libxcvt0 libxkbfile1 
    libgbm1 libxfont2 
    # Runtime environment for launcher scripts
    xvfb 
    openbox 
    rsync 
    socat 
    && rm -rf /var/lib/apt/lists/*

# --- s6-overlay & Sudoers Configuration ---
# Copy s6-overlay and custom service configuration
COPY docker/root/ /

# Secure the sudoers file (Sudo ignores files with insecure permissions)
RUN chown root:root /etc/sudoers.d/aikore-sudo && \
    chmod 0440 /etc/sudoers.d/aikore-sudo

# --- Environment Variables ---
ENV DEBIAN_FRONTEND=noninteractive
ENV BASE_DIR=/config \
    SD_INSTALL_DIR=/opt/sd-install \
    XDG_CACHE_HOME=/config/temp

# Set compiler and Torch/CUDA architecture for any potential runtime compilations
ENV CC=/usr/bin/gcc-13
ENV CXX=/usr/bin/g++-13
ENV TORCH_CUDA_ARCH_LIST="8.0 8.6 8.7 8.9 9.0 9.0a 10 12"

# --- s6-overlay Script Cleanup ---
# Convert all s6 scripts to Unix line endings and ensure they are executable.
RUN find /etc/s6-overlay -type f -print0 | xargs -0 dos2unix --
RUN find /etc/s6-overlay -type f -name "run" -exec chmod +x {} +
RUN find /etc/s6-overlay -type f -name "finish" -exec chmod +x {} + || true

# --- Application Setup ---
# Create application directories
RUN mkdir -p ${BASE_DIR}/temp ${SD_INSTALL_DIR}

# Copy AiKore application and its blueprints
# The user 'abc' is created by the linuxserver.io base image, so we chown to it.
COPY --chown=abc:abc aikore/ ${SD_INSTALL_DIR}/aikore/
COPY --chown=abc:abc blueprints/ ${SD_INSTALL_DIR}/blueprints/
COPY --chown=abc:abc scripts/ ${SD_INSTALL_DIR}/scripts/

# Copy application scripts
COPY --chown=abc:abc entry.sh ${SD_INSTALL_DIR}/entry.sh
COPY --chown=abc:abc functions.sh ${SD_INSTALL_DIR}/functions.sh

# --- Script & Permission Cleanup ---
# Convert all copied .sh files to Unix line endings and make them executable.
RUN find ${SD_INSTALL_DIR} -type f -name "*.sh" -print0 | xargs -0 dos2unix -- && \
    find ${SD_INSTALL_DIR} -type f -name "*.sh" -print0 | xargs -0 chmod +x

# --- User and Environment Setup ---
# The user 'abc' with UID 1000 is created by the base image.
# We ensure its home directory and environment are set up correctly.
ENV XDG_CONFIG_HOME=/home/abc
ENV HOME=/home/abc

# Create and set permissions for the NGINX reload flag directory
RUN mkdir -p /run/aikore && \
    chown abc:abc /run/aikore

# Switch to the standard user for Conda installation
USER abc
WORKDIR /home/abc

# Install Miniforge for Python environment management
RUN cd /tmp && \
    wget https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh && \
    bash Miniforge3-Linux-x86_64.sh -b -p /home/abc/miniconda3 && \
    rm Miniforge3-Linux-x86_64.sh

# --- Final Ownership & Permissions ---
# Switch back to root temporarily to set final ownership.
USER root
RUN \
    chown -R abc:abc /home/abc && \
    chown -R abc:abc ${SD_INSTALL_DIR} && \
    chown -R abc:abc ${BASE_DIR}

# Switch back to the final user
USER abc
WORKDIR /home/abc

# Expose default ports
EXPOSE 9000/tcp
