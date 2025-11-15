# Global ARGs for dynamic image sources
ARG BASE_IMAGE_TAG=13.0.2-cudnn-devel-ubuntu24.04

# Use the same CUDA base image as other builds
FROM nvidia/cuda:${BASE_IMAGE_TAG} AS builder

ENV DEBIAN_FRONTEND=noninteractive
ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV MAX_JOBS=8
ENV PIP_EXTRA_INDEX_URL=https://download.pytorch.org/whl/cu130
WORKDIR /build

# --- System Dependencies ---
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential wget curl git cmake ninja-build libopenblas-dev \
    python3.12 python3.12-dev python3-pip \
    && update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1 \
    && update-alternatives --install /usr/bin/python python /usr/bin/python3.12 1 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Add CUDA to PATH
ENV PATH="/usr/local/cuda/bin:${PATH}"

# --- Install PyTorch ---
# Install PyTorch, TorchVision, and TorchAudio from the official index for CUDA 12.1
RUN python3.12 -m pip install --no-cache-dir wheel packaging scikit-build-core \
    && python3.12 -m pip install torch torchvision
# --- CLEANUP and PREPARATION before wheel compilation ---
# Désinstalle TOUS les paquets nvidia-* pour s'assurer qu'il n'y a pas de conflit.
# Les bonnes versions (cu13) seront réinstallées en tant que dépendances lors de la compilation.
RUN python3.12 -m pip uninstall -y nvidia-cublas-cu12 nvidia-cuda-cupti-cu12 nvidia-cuda-nvrtc-cu12 nvidia-cuda-runtime-cu12 nvidia-cudnn-cu12 nvidia-cufft-cu12 nvidia-cufile-cu12 nvidia-curand-cu12 nvidia-cusolver-cu12 nvidia-cusparse-cu12 nvidia-cusparselt-cu12 nvidia-nccl-cu12 nvidia-nvjitlink-cu12 nvidia-nvshmem-cu12 nvidia-nvtx-cu12 || echo "No cu12 packages to uninstall"

# --- Compile Wheels ---
WORKDIR /build

# flash-attn
RUN git clone https://github.com/Dao-AILab/flash-attention.git /build/flash-attention \
    && cd /build/flash-attention \
    && export TORCH_CUDA_ARCH_LIST="7.0 7.5 8.0 8.6 9.0 10 12" \
    && export FLASH_ATTENTION_FORCE_BUILD=TRUE \
    # Ajout de CUDA_HOME pour guider le script de build
    && export CUDA_HOME=/usr/local/cuda \
    && python3.12 -m pip wheel --no-build-isolation . -w /wheels \
    && cd /build \
    && rm -rf flash-attention

# sageattention
RUN git clone https://github.com/thu-ml/SageAttention.git /build/SageAttention \
    && cd /build/SageAttention \
    && export TORCH_CUDA_ARCH_LIST="7.0 7.5 8.0 8.6 9.0 10 12" \
    # Ajout de CUDA_HOME pour guider le script de build
    && export CUDA_HOME=/usr/local/cuda \
    && python3.12 -m pip wheel --no-build-isolation . -w /wheels \
    && cd /build \
    && rm -rf SageAttention

# --- Final Stage (Exporter) ---
# This stage contains only the compiled wheels for export.
FROM scratch AS exporter
COPY --from=builder /wheels/*.whl /
