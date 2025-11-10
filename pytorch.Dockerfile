# syntax=docker/dockerfile:1

# This Dockerfile is dedicated to compiling a specific version of PyTorch from source.
# It is designed to be used with a GitHub Actions workflow that passes build arguments.

ARG BASE_IMAGE_TAG=13.0.2-cudnn-runtime-ubuntu24.04
FROM nvidia/cuda:${BASE_IMAGE_TAG}

ARG PYTORCH_TAG=v2.9.0
ARG TORCH_CUDA_ARCH_LIST="8.9"
ARG PYTHON_VERSION=3.12

ENV DEBIAN_FRONTEND=noninteractive
ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV MAX_JOBS=4

# --- System Dependencies ---
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential wget curl git cmake gnupg bc rsync ffmpeg ninja-build \
    libxft2 xvfb libopenblas-dev \
    python${PYTHON_VERSION} python${PYTHON_VERSION}-dev python${PYTHON_VERSION}-venv python3-setuptools python3-pip \
    && update-alternatives --install /usr/bin/python3 python3 /usr/bin/python${PYTHON_VERSION} 1 \
    && update-alternatives --install /usr/bin/python python /usr/bin/python${PYTHON_VERSION} 1 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# --- Python Build Dependencies ---
# We install them here to ensure they are cached by Docker unless changed.
RUN python3 -m pip install --no-cache-dir wheel packaging scikit-build-core numpy cython

# --- PyTorch Compilation ---
WORKDIR /build
RUN git clone --branch ${PYTORCH_TAG} https://github.com/pytorch/pytorch.git . \
    && git submodule update --init --recursive \
    && echo "============================================================================"
&& echo "Starting PyTorch ${PYTORCH_TAG} compilation for CUDA arches: ${TORCH_CUDA_ARCH_LIST}"
&& echo "============================================================================"
&& export CMAKE_BUILD_TYPE=Release \
    && export TORCH_CUDA_ARCH_LIST="${TORCH_CUDA_ARCH_LIST}" \
    && export USE_CUDA=1 \
    && export BUILD_TEST=0 \
    && export CUDACXX=/usr/local/cuda/bin/nvcc \
    && python3 -m pip wheel . --wheel-dir /dist

# --- Final Stage ---
# A minimal image to hold the final wheel.
FROM scratch
COPY --from=0 /dist/ /dist/
