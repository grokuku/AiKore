# Global ARGs for dynamic image sources
ARG BASE_IMAGE_TAG=13.0.2-cudnn-devel-ubuntu24.04

# Use the same CUDA base image as other builds
FROM nvidia/cuda:${BASE_IMAGE_TAG} AS builder

ENV DEBIAN_FRONTEND=noninteractive
ENV PIP_BREAK_SYSTEM_PACKAGES=1
# Augmenter les jobs peut faire crasher le build si pas assez de RAM dans Docker
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
ENV CUDA_HOME="/usr/local/cuda"

# --- Install PyTorch ---
RUN python3.12 -m pip install --no-cache-dir wheel packaging setuptools scikit-build-core \
    && python3.12 -m pip install torch==2.9.1 torchvision==0.24.1 --index-url https://download.pytorch.org/whl/cu130

# --- Compile Wheels ---
WORKDIR /build

# sageattention
# CORRECTIONS ICI :
# 1. Utilisation de ENV globaux pour la ligne (plus sûr)
# 2. Ajout de FORCE_CUDA=1 (CRITIQUE car pas de GPU pendant le build docker)
# 3. Suppression des config-settings cmake inutiles
# 4. Utilisation de setup.py bdist_wheel au lieu de pip wheel pour contrôle total
RUN git clone https://github.com/thu-ml/SageAttention.git /build/SageAttention \
    && cd /build/SageAttention \
    && export FORCE_CUDA=1 \
    && export TORCH_CUDA_ARCH_LIST="7.5 8.0 8.6 8.7 8.9" \
    && python3.12 setup.py bdist_wheel --dist-dir /wheels \
    && cd /build \
    && rm -rf SageAttention

# flash-attn
# Même logique : FORCE_CUDA est vital ici aussi
RUN git clone https://github.com/Dao-AILab/flash-attention.git /build/flash-attention \
    && cd /build/flash-attention \
    && export FLASH_ATTENTION_FORCE_BUILD=TRUE \
    && export FORCE_CUDA=1 \
    && export TORCH_CUDA_ARCH_LIST="7.5 8.0 8.6 8.7 8.9 12" \
    && python3.12 setup.py bdist_wheel --dist-dir /wheels \
    && cd /build \
    && rm -rf flash-attention

# --- Final Stage (Exporter) ---
FROM scratch AS exporter
COPY --from=builder /wheels/*.whl /