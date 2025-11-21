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
# Install PyTorch, TorchVision, from the official index for CUDA 13.0
RUN python3.12 -m pip install --no-cache-dir wheel packaging scikit-build-core \
    && python3.12 -m pip install torch==2.9.1 torchvision==0.24.1 --index-url https://download.pytorch.org/whl/cu130

# --- Compile Wheels ---
WORKDIR /build

# sageattention
RUN git clone https://github.com/thu-ml/SageAttention.git /build/SageAttention \
    && cd /build/SageAttention \
    && TORCH_CUDA_ARCH_LIST="7.5 8.0 8.6 8.7 8.9 12" python3.12 -m pip wheel --no-build-isolation . -w /wheels --verbose --config-settings="cmake.args=-DCMAKE_CUDA_ARCHITECTURES=75;80;86;87;89;120" \
    && cd /build \
    && rm -rf SageAttention

# flash-attn
RUN git clone https://github.com/Dao-AILab/flash-attention.git /build/flash-attention \
    && cd /build/flash-attention \
    && FLASH_ATTENTION_FORCE_BUILD=TRUE \
    TORCH_CUDA_ARCH_LIST="7.5 8.0 8.6 8.7 8.9 12" \
    python3.12 -m pip wheel --verbose --no-build-isolation . -w /wheels \
    && cd /build \
    && rm -rf SageAttention

# --- Final Stage (Exporter) ---
# This stage contains only the compiled wheels for export.
FROM scratch AS exporter
COPY --from=builder /wheels/*.whl /
