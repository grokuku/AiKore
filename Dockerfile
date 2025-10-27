# MODIFICATION ICI pour utiliser la nouvelle image de base
FROM ghcr.io/grokuku/aikore-buildbase:latest

# Copy s6-overlay and custom service configuration
COPY docker/root/ /

# --- System Dependencies ---
# Install socat, which is required for dynamic port activation.
RUN apt-get update && \
    apt-get install -y --no-install-recommends socat && \
    rm -rf /var/lib/apt/lists/*

# --- AJOUT IMPORTANT : Sécurisation du fichier sudoers ---
# Sudo ignore les fichiers avec des permissions non sécurisées.
# 0440 = lecture seule pour root et le groupe root.
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

# --- s6-overlay Script Cleanup and Permissions ---
# Convert all s6 scripts to Unix line endings and ensure they are executable.
RUN find /etc/s6-overlay -type f -print0 | xargs -0 dos2unix --
RUN find /etc/s6-overlay -type f -name "run" -exec chmod +x {} +
RUN find /etc/s6-overlay -type f -name "finish" -exec chmod +x {} + || true

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
    chown -R abc:abc ${BASE_DIR} && \
    # --- CORRECTION ---
    # Grant ownership of NGINX config directories to the app user.
    # This allows the backend to dynamically manage proxy configurations.
    chown -R abc:abc /etc/nginx

# Expose default ports
EXPOSE 9000/tcp