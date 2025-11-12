# Global ARGs for dynamic image sources
ARG PYTORCH_WHEEL_IMAGE
ARG PYTORCH_RELEASE_TAG
ARG BASE_IMAGE_TAG=13.0.1-cudnn-devel-ubuntu24.04

# Stage to pull the dynamic PyTorch wheel image
FROM ${PYTORCH_WHEEL_IMAGE}:${PYTORCH_RELEASE_TAG} AS pytorch_wheel_image

# Use the same CUDA base image as other builds
FROM nvidia/cuda:${BASE_IMAGE_TAG} AS builder

ENV DEBIAN_FRONTEND=noninteractive
ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV MAX_JOBS=2
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
# Copy the pre-compiled PyTorch wheel from its container and install it.
# The debug logs showed the wheel is located in /wheel_output/dist/ inside the source image.
COPY --from=pytorch_wheel_image /wheel_output/dist/torch-*.whl /wheels_torch/
RUN python3.12 -m pip install --no-cache-dir wheel packaging scikit-build-core \
    && python3.12 -m pip install --no-cache-dir /wheels_torch/torch-*.whl

# --- Compile Wheels ---
WORKDIR /build

# flash-attn
RUN git clone https://github.com/Dao-AILab/flash-attention.git /build/flash-attention \
    && cd /build/flash-attention \
    && export TORCH_CUDA_ARCH_LIST="8.9" \
    && export FLASH_ATTENTION_FORCE_BUILD=TRUE \
    && python3.12 -m pip wheel --no-build-isolation . -w /wheels \
    && cd /build \
    && rm -rf flash-attention

# sageattention
RUN git clone https://github.com/thu-ml/SageAttention.git /build/SageAttention \
    && cd /build/SageAttention \
    && export TORCH_CUDA_ARCH_LIST="8.9" \
    && python3.12 -m pip wheel --no-build-isolation . -w /wheels \
    && cd /build \
    && rm -rf SageAttention

# --- Final Stage ---
# Create a clean final stage with only the wheels
FROM scratch
COPY --from=builder /wheels/*.whl /
