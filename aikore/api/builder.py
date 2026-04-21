from fastapi import APIRouter, WebSocket, HTTPException, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Optional
import os
import json
import asyncio
import subprocess
import shutil
import sys
from datetime import datetime
import glob
import traceback
import urllib.request
import re

print("[DEBUG] Loading builder.py module...")

# Do NOT import torch at module level — it takes several minutes to load on slow disks.
# Instead, we use pynvml (already a project dependency) for GPU detection, and
# lazy-import torch only when actually needed (inside endpoint functions).
try:
    import pynvml
    print("[DEBUG] pynvml imported successfully.")
except ImportError:
    pynvml = None
    print("[DEBUG] pynvml not found.")

torch = None  # Will be lazy-loaded if needed

router = APIRouter(prefix="/api/builder", tags=["Builder"])

from aikore.config import INSTANCES_DIR

# --- CONFIGURATION ---
WHEELS_DIR = os.path.join(INSTANCES_DIR, ".wheels")
MANIFEST_FILE = os.path.join(WHEELS_DIR, "manifest.json")

# Environment management
CONDA_EXE = "/home/abc/miniconda3/bin/conda"
CONDA_BASE_DIR = "/home/abc/miniconda3"

# Ensure directory exists
os.makedirs(WHEELS_DIR, exist_ok=True)

# --- VERSIONS MAPPING ---
# Strict mapping to ensure successful builds. 
TORCH_VISION_MAP = {
    "2.11.0": "0.22.0",
    "2.10.0": "0.21.0",
    "2.9.1": "0.20.1",
    "2.9.0": "0.20.0",
    "2.8.0": "0.19.1",
    "2.7.0": "0.19.0",
    "2.6.0": "0.18.0",
    "2.5.1": "0.20.1",
    "2.4.1": "0.19.1",
    "2.4.0": "0.19.0",
    "2.3.1": "0.18.1",
    "2.2.2": "0.17.2",
    "2.1.2": "0.16.2", 
    "2.0.1": "0.15.2"
}

# --- PRESETS DEFINITION ---
PRESETS = {
    "sageattention": {
        "label": "SageAttention (FlashAttention Alternative)",
        "git_url": "https://github.com/thu-ml/SageAttention.git",
        "description": "Optimized attention mechanism. Requires CUDA.",
        "cmd_template": (
            "git clone {git_url} source_code && "
            "cd source_code && "
            "export FORCE_CUDA=1 && "
            "export TORCH_CUDA_ARCH_LIST='{arch}' && "
            "{python} setup.py bdist_wheel --dist-dir {output_dir} && "
            "cd .. && "
            "rm -rf source_code"
        )
    },
    "flash-attn": {
        "label": "FlashAttention-2 (Dao-AILab)",
        "git_url": "https://github.com/Dao-AILab/flash-attention.git",
        "description": "Fast and memory-efficient exact attention.",
        "cmd_template": (
            "git clone {git_url} source_code && "
            "cd source_code && "
            "export MAX_JOBS=2 && "
            "export TORCH_CUDA_ARCH_LIST='{arch}' && "
            "{python} -m pip wheel --no-build-isolation . -w {output_dir} && "
            "cd .. && "
            "rm -rf source_code"
        )
    },
    "bitsandbytes": {
        "label": "BitsAndBytes (Quantization)",
        "git_url": "https://github.com/TimDettmers/bitsandbytes.git",
        "description": "8-bit optimizers and matrix multiplication.",
        "cmd_template": (
            "git clone {git_url} source_code && "
            "cd source_code && "
            "export TORCH_CUDA_ARCH_LIST='{arch}' && "
            "{python} -m pip wheel --no-build-isolation . -w {output_dir} && "
            "cd .. && "
            "rm -rf source_code"
        )
    },
    "diso": {
        "label": "Diso (Gaussian Splatting Utility)",
        "git_url": "https://github.com/SarahWeiii/diso",
        "description": "Utility for Trellis / 3D Gaussian Splatting.",
        "cmd_template": (
            "git clone {git_url} source_code --recurse-submodules && "
            "cd source_code && "
            "export TORCH_CUDA_ARCH_LIST='{arch}' && "
            "{python} -m pip wheel --no-build-isolation . -w {output_dir} && "
            "cd .. && "
            "rm -rf source_code"
        )
    },
    "nvdiffrast": {
        "label": "Nvdiffrast (NVIDIA Differentiable Rasterization)",
        "git_url": "https://github.com/NVlabs/nvdiffrast.git",
        "description": "High-performance differentiable rendering.",
        "cmd_template": (
            "git clone {git_url} source_code && "
            "cd source_code && "
            "export TORCH_CUDA_ARCH_LIST='{arch}' && "
            "{python} -m pip wheel --no-build-isolation . -w {output_dir} && "
            "cd .. && "
            "rm -rf source_code"
        )
    },
    "xformers": {
        "label": "XFormers (Memory-efficient Attention)",
        "git_url": "https://github.com/facebookresearch/xformers.git",
        "description": "Hackable and optimized Transformers building blocks.",
        "cmd_template": (
            "git clone {git_url} source_code && "
            "cd source_code && "
            "git submodule update --init --recursive && "
            "export MAX_JOBS=1 && "
            "export TORCH_CUDA_ARCH_LIST='{arch}' && "
            "{python} -m pip wheel --no-build-isolation . -w {output_dir} && "
            "cd .. && "
            "rm -rf source_code"
        )
    },
    "kaolin": {
        "label": "Kaolin (NVIDIA 3D Deep Learning) - 5090 Fork",
        "git_url": "https://github.com/HarrisonPrism/kaolin_5090.git",
        "description": "A PyTorch Library for Accelerating 3D Deep Learning Research.",
        "cmd_template": (
            "git clone {git_url} source_code && "
            "cd source_code && "
            "export IGNORE_TORCH_VER=1 && "
            "export TORCH_CUDA_ARCH_LIST='{arch}' && "
            "{python} -m pip wheel --no-build-isolation . -w {output_dir} && "
            "cd .. && "
            "rm -rf source_code"
        )
    },
    "diff_gaussian_rasterization": {
        "label": "Diff-Gaussian-Rasterization (Mip-Splatting)",
        "git_url": "https://github.com/autonomousvision/mip-splatting",
        "description": "Rasterization engine for 3D Gaussian Splatting.",
        "cmd_template": (
            "git clone {git_url} source_code --recurse-submodules && "
            "cd source_code/submodules/diff-gaussian-rasterization && "
            "export TORCH_CUDA_ARCH_LIST='{arch}' && "
            "{python} -m pip wheel --no-build-isolation . -w {output_dir} && "
            "cd ../../../ && "
            "rm -rf source_code"
        )
    },
    "vox2seq": {
        "label": "Vox2Seq (TRELLIS Extension)",
        "git_url": "https://github.com/microsoft/TRELLIS",
        "description": "Voxel to Sequence extension for TRELLIS 3D generation.",
        "cmd_template": (
            "git clone {git_url} source_code --recurse-submodules && "
            "cd source_code/extensions/vox2seq && "
            "export TORCH_CUDA_ARCH_LIST='{arch}' && "
            "{python} -m pip wheel --no-build-isolation . -w {output_dir} && "
            "cd ../../../ && "
            "rm -rf source_code"
        )
    },
    "open3d": {
        "label": "Open3D (CUDA & PyTorch Ops)",
        "git_url": "https://github.com/isl-org/Open3D.git",
        "description": "3D data processing library. Compiled with CUDA and PyTorch ops (Headless). Very heavy build.",
        "cmd_template": (
            "git clone {git_url} source_code --recurse-submodules && "
            "cd source_code && "
            "mkdir build && cd build && "
            "export ARCH_NUM=$(echo {arch} | tr -d '.') && "
            "export PT_ABI=$({python} -c \"import torch; print('ON' if torch._C._GLIBCXX_USE_CXX11_ABI else 'OFF')\") && "
            "cmake -DCMAKE_BUILD_TYPE=Release "
            "-DCMAKE_PREFIX_PATH=$CONDA_PREFIX "
            "-DBUILD_CUDA_MODULE=ON "
            "-DBUILD_PYTORCH_OPS=ON "
            "-DBUILD_TENSORFLOW_OPS=OFF "
            "-DBUILD_GUI=OFF "
            "-DBUILD_EXAMPLES=OFF "
            "-DENABLE_HEADLESS_RENDERING=ON "
            "-DGLIBCXX_USE_CXX11_ABI=${{PT_ABI}} "
            "-DPython3_EXECUTABLE=$(which python) "
            "-DCMAKE_CUDA_ARCHITECTURES=${{ARCH_NUM}} "
            ".. && "
            "make -j4 pip-package && "
            "cp lib/python_package/pip_package/*.whl {output_dir}/ && "
            "cd ../../ && "
            "rm -rf source_code"
        )
    },
    "custom": {
        "label": "Custom Git Repository",
        "git_url": "", 
        "description": "Build a wheel from any Git repo containing setup.py or pyproject.toml.",
        "cmd_template": (
            "export TORCH_CUDA_ARCH_LIST='{arch}' && "
            "{python} -m pip wheel {git_url} --wheel-dir={output_dir} --no-deps --no-build-isolation"
        )
    }
}

class BuildRequest(BaseModel):
    preset: str
    git_url: Optional[str] = None
    cuda_arch: str
    force_rebuild: bool = False

class WheelMetadata(BaseModel):
    filename: str
    size_mb: float
    created_at: str
    cuda_arch: str
    cuda_ver: str
    torch_ver: str
    source_preset: str

# --- HELPERS ---

def get_manifest():
    if not os.path.exists(MANIFEST_FILE):
        return {}
    try:
        with open(MANIFEST_FILE, 'r') as f:
            return json.load(f)
    except:
        return {}

def update_manifest(filename, meta):
    data = get_manifest()
    data[filename] = meta
    with open(MANIFEST_FILE, 'w') as f:
        json.dump(data, f, indent=4)

def remove_from_manifest(filename):
    data = get_manifest()
    if filename in data:
        del data[filename]
        with open(MANIFEST_FILE, 'w') as f:
            json.dump(data, f, indent=4)

async def stream_subprocess(cmd, cwd, websocket, env_vars=None):
    """Helper to run a command and stream output to websocket."""
    print(f"[DEBUG] Executing command in {cwd}: {cmd}")
    
    # Merge current environment with custom vars and force unbuffered output
    full_env = os.environ.copy()
    full_env["PYTHONUNBUFFERED"] = "1"
    if env_vars:
        full_env.update(env_vars)
        
    process = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=cwd,
        env=full_env,
        executable='/bin/bash'
    )
    
    while True:
        line = await process.stdout.readline()
        if not line:
            break
        try:
            decoded_line = line.decode('utf-8', errors='replace')
            await websocket.send_text(decoded_line)
        except Exception as e:
            print(f"[DEBUG] Error sending log line: {e}")
            break
    
    return await process.wait()

# --- ENDPOINTS ---

@router.get("/info")
def get_builder_info():
    """Returns available presets and detected GPU architecture."""
    detected_arch = "8.9" # Default fallback
    gpu_name = "Unknown"
    
    # Use pynvml for GPU detection (lightweight, loads in milliseconds)
    # torch import is intentionally avoided at module level due to multi-minute load times
    if pynvml:
        try:
            pynvml.nvmlInit()
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            cap = pynvml.nvmlDeviceGetCudaComputeCapability(handle)
            detected_arch = f"{cap[0]}.{cap[1]}"
            gpu_name = pynvml.nvmlDeviceGetName(handle)
            # Decode bytes if needed (older pynvml versions return bytes)
            if isinstance(gpu_name, bytes):
                gpu_name = gpu_name.decode('utf-8')
            pynvml.nvmlShutdown()
        except Exception as e:
            print(f"[DEBUG] pynvml GPU detection failed: {e}")

    return {
        "presets": PRESETS,
        "detected_arch": detected_arch,
        "gpu_name": gpu_name,
        "python_path": sys.executable
    }
    
# --- NEW: Cache for python versions ---
_cached_python_versions =[]

@router.get("/versions/python")
async def get_available_python_versions():
    """
    Finds available python versions using conda search.
    Results are cached to avoid slow repeated calls.
    """
    global _cached_python_versions
    if _cached_python_versions:
        return _cached_python_versions

    try:
        cmd = f"{CONDA_EXE} search ^python$ --json"
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        
        if proc.returncode == 0:
            data = json.loads(stdout.decode())
            versions = set()
            for entry in data.get("python",[]):
                ver = entry.get("version", "")
                # Match major.minor and ensure it's >= 3.10
                match = re.match(r'^(3\.(1[0-9]|[0-9]))', ver)
                if match:
                    versions.add(match.group(1))
            
            # Sort descending (e.g. 3.15, 3.14...)
            _cached_python_versions = sorted(list(versions), key=lambda x:[int(p) for p in x.split('.')], reverse=True)
            return _cached_python_versions
    except Exception as e:
        print(f"[DEBUG] Failed to discover python versions: {e}")
    
    # Fallback if conda fails
    return["3.15", "3.14", "3.13", "3.12", "3.11", "3.10"]

@router.get("/versions/torch/{cuda_ver}")
def get_torch_versions_for_cuda(cuda_ver: str):
    """
    Dynamically fetches available torch versions from download.pytorch.org
    for the specific CUDA version. 
    Fallback to a default list if offline.
    """
    index_url = f"https://download.pytorch.org/whl/{cuda_ver}/torch/"
    versions = set()
    
    # Updated fallback list for 2026 (CUDA 12.6, 12.8, 13.0 compatible)
    fallback_versions =["2.11.0", "2.10.0", "2.9.1", "2.8.0", "2.7.0", "2.6.0", "2.5.1", "2.4.1"]
    
    try:
        print(f"[DEBUG] Fetching versions from {index_url}...")
        # Added User-Agent to prevent 403 Forbidden from PyTorch CDN
        req = urllib.request.Request(
            index_url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            html = response.read().decode('utf-8')
            
            matches = re.findall(r'torch-([0-9]+\.[0-9]+\.[0-9]+)%2B', html)
            if not matches:
                matches = re.findall(r'torch-([0-9]+\.[0-9]+\.[0-9]+)\+', html)
                
            for m in matches:
                versions.add(m)
                
        if not versions:
            print("[DEBUG] No versions found via regex, using fallback.")
            return sorted(fallback_versions, reverse=True)
            
        def safe_version_key(s):
            return[int(p) if p.isdigit() else 0 for p in re.split(r'\D+', s) if p]
            
        return sorted(list(versions), key=safe_version_key, reverse=True)

    except Exception as e:
        print(f"[DEBUG] Failed to fetch torch versions: {e}")
        return sorted(fallback_versions, reverse=True)

@router.get("/wheels", response_model=List[WheelMetadata])
def list_wheels():
    manifest = get_manifest()
    wheels =[]
    
    # Scan directory
    files = glob.glob(os.path.join(WHEELS_DIR, "*.whl"))
    for p in files:
        fname = os.path.basename(p)
        try:
            stats = os.stat(p)
            size_mb = round(stats.st_size / (1024 * 1024), 2)
            created_at = datetime.fromtimestamp(stats.st_mtime).strftime("%Y-%m-%d %H:%M")
        except OSError:
            continue
        
        # Merge with manifest data if available
        meta = manifest.get(fname, {})
        
        wheels.append({
            "filename": fname,
            "size_mb": size_mb,
            "created_at": created_at,
            "cuda_arch": meta.get("cuda_arch", "N/A"),
            "cuda_ver": meta.get("cuda_ver", "N/A"),
            "torch_ver": meta.get("torch_ver", "N/A"),
            "source_preset": meta.get("source_preset", "Unknown")
        })
    
    # Sort by date new -> old
    wheels.sort(key=lambda x: x['created_at'], reverse=True)
    return wheels

@router.get("/wheels/{filename}/download")
def download_wheel(filename: str):
    safe_name = os.path.basename(filename) # Prevent directory traversal
    path = os.path.join(WHEELS_DIR, safe_name)
    
    if os.path.exists(path):
        return FileResponse(path, media_type='application/octet-stream', filename=safe_name)
    raise HTTPException(status_code=404, detail="File not found")

@router.delete("/wheels/{filename}")
def delete_wheel(filename: str):
    safe_name = os.path.basename(filename) # Prevent directory traversal
    path = os.path.join(WHEELS_DIR, safe_name)
    
    if os.path.exists(path):
        os.remove(path)
        remove_from_manifest(safe_name)
        return {"ok": True}
    raise HTTPException(status_code=404, detail="File not found")

@router.websocket("/build")
async def build_websocket(websocket: WebSocket):
    print("[DEBUG] WebSocket connection request received.")
    await websocket.accept()
    print("[DEBUG] WebSocket accepted.")
    
    try:
        # 1. Receive Configuration
        data = await websocket.receive_json()
        print(f"[DEBUG] Received build config: {data}")
        
        preset_key = data.get("preset")
        target_arch = data.get("arch")
        custom_url = data.get("git_url")
        python_ver = data.get("python_ver", "3.12")
        cuda_ver = data.get("cuda_ver", "cu130")
        # Extract requested torch version
        requested_torch_ver = data.get("torch_ver", "2.5.1")
        
        if preset_key not in PRESETS:
            print("[DEBUG] Invalid preset.")
            await websocket.send_text("\x1b[31m[ERROR] Invalid preset selected.\x1b[0m\r\n")
            await websocket.close()
            return

        preset = PRESETS[preset_key]
        git_url = custom_url if preset_key == "custom" else preset["git_url"]
        
        # --- NEW: Auto-fix git URLs for pip wheel ---
        if preset_key == "custom" and git_url:
            # If it's a standard web URL, not already git+, and not explicitly an archive
            if git_url.startswith("http") and not git_url.startswith("git+") and not git_url.endswith((".whl", ".zip", ".tar.gz")):
                git_url = "git+" + git_url
        
        # Environment name includes torch version now to distinguish them
        safe_torch_ver = requested_torch_ver.replace(".", "")
        env_name = f"builder_py{python_ver.replace('.','')}_{cuda_ver}_pt{safe_torch_ver}"
        
        # --- SECURITY: Validate env_name to prevent shell injection ---
        if not re.match(r'^[a-zA-Z0-9_-]+$', env_name):
            await websocket.send_text(f"\x1b[31m[ERROR] Invalid environment name '{env_name}'. Only alphanumeric characters, hyphens and underscores are allowed.\x1b[0m\r\n")
            await websocket.close()
            return
        
        # Log immediately to confirm connection
        await websocket.send_text(f"\x1b[34m[INFO] Initializing build process...\x1b[0m\r\n")
        await websocket.send_text(f"\x1b[34m[INFO] Target Environment: {env_name}\x1b[0m\r\n")
        await websocket.send_text(f"\x1b[34m[INFO] Requested Config: Torch {requested_torch_ver} | {cuda_ver}\x1b[0m\r\n")

        # 2. Environment Setup
        env_path = f"{CONDA_BASE_DIR}/envs/{env_name}"
        # Use "conda run" instead of "source activate" for reliable env isolation.
        # The legacy "source activate" silently fails in non-interactive shells
        # (created by asyncio.create_subprocess_shell) because conda shell functions
        # aren't initialized — .bashrc is never sourced. "conda run -n <name>"
        # handles environment setup (PATH, CONDA_PREFIX, LD_LIBRARY_PATH) internally
        # regardless of the shell context.
        conda_run = f"{CONDA_EXE} run -n {env_name} --no-capture-output"
        
        await websocket.send_text(f"\x1b[30;1m[CHECK] Verifying Conda environment...\x1b[0m\r\n")
        
        # Check if environment exists using conda CLI (more reliable for conda-named envs)
        # os.path.isdir can report True for leftover directories from failed creates
        conda_check_proc = await asyncio.create_subprocess_shell(
            f"{CONDA_EXE} env list 2>/dev/null | grep -qw '{env_name}'",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await conda_check_proc.wait()
        env_exists = conda_check_proc.returncode == 0
        
        if not env_exists:
            await websocket.send_text(f"\x1b[33m[INFO] Environment not found. Creating {env_name}...\x1b[0m\r\n")
            await websocket.send_text(f"\x1b[33m[WARN] This involves downloading Python and PyTorch (~2GB). Please wait.\x1b[0m\r\n")
            
            # Create Env Command
            create_cmd = f"{CONDA_EXE} create -n {env_name} python={python_ver} pip wheel setuptools packaging ninja -y"
            if await stream_subprocess(create_cmd, WHEELS_DIR, websocket) != 0:
                raise Exception("Failed to create Conda environment.")
        
        # ALWAYS verify that torch is actually installed in the environment.
        # A previous build may have created the env but failed during torch installation.
        torch_check_cmd = f'{conda_run} python -c "import torch; print(torch.__version__)"'
        proc = await asyncio.create_subprocess_shell(
            torch_check_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            executable='/bin/bash'
        )
        torch_check_output, torch_check_stderr = await proc.communicate()
        torch_is_installed = proc.returncode == 0 and bool(torch_check_output.strip())
        
        if not torch_is_installed:
            await websocket.send_text(f"\x1b[33m[INFO] PyTorch not found in environment. Installing...\x1b[0m\r\n")
            # Install PyTorch Command
            # Determine Torchvision version based on Torch version
            vision_ver = TORCH_VISION_MAP.get(requested_torch_ver)
            
            if not vision_ver:
                    await websocket.send_text(f"\x1b[33m[WARN] Unknown Torch version {requested_torch_ver}. Installing latest compatible torchvision (might break).\x1b[0m\r\n")
                    # If unknown, we do NOT pin torchvision and let pip resolve it
                    torch_pkg = f"torch=={requested_torch_ver} torchvision"
            else:
                    torch_pkg = f"torch=={requested_torch_ver} torchvision=={vision_ver}"

            await websocket.send_text(f"\x1b[34m[INFO] Installing {torch_pkg}...\x1b[0m\r\n")
            index_url = f"https://download.pytorch.org/whl/{cuda_ver}"
            install_cmd = f"{conda_run} pip install {torch_pkg} --index-url {index_url} --no-cache-dir"
            
            if await stream_subprocess(install_cmd, WHEELS_DIR, websocket) != 0:
                raise Exception("Failed to install PyTorch in builder environment.")

        # --- NEW: Ensure modern build tools are present (fixes bitsandbytes and others) ---
        # Exécuté systématiquement, même si l'environnement existait déjà.
        await websocket.send_text(f"\x1b[34m[INFO] Verifying modern build tools (cmake, scikit-build-core)...\x1b[0m\r\n")
        build_tools_cmd = f"{conda_run} pip install cmake scikit-build-core"
        if await stream_subprocess(build_tools_cmd, WHEELS_DIR, websocket) != 0:
            await websocket.send_text(f"\x1b[33m[WARN] Failed to update build tools. Build might fail.\x1b[0m\r\n")

        # 2.5 DETECT TORCH VERSION (NEW)
        # We query the environment to find out exactly what version was installed
        detect_cmd = f'{conda_run} python -c "import torch; print(torch.__version__)"'
        proc = await asyncio.create_subprocess_shell(
            detect_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            executable='/bin/bash'
        )
        stdout, stderr = await proc.communicate()
        detected_torch_ver = stdout.decode().strip()
        
        if not detected_torch_ver:
            detected_torch_ver = "Unknown"
        else:
            await websocket.send_text(f"\x1b[32m[INFO] Confirmed PyTorch Version: {detected_torch_ver}\x1b[0m\r\n")

        # 3. Prepare Build
        build_tmp_dir = os.path.join(WHEELS_DIR, "build_tmp")
        if os.path.exists(build_tmp_dir):
            shutil.rmtree(build_tmp_dir)
        os.makedirs(build_tmp_dir)

        # Template substitution
        raw_cmd = preset["cmd_template"].format(
            git_url=git_url,
            arch=target_arch,
            output_dir=build_tmp_dir, 
            python="python -u" 
        )

        # Write build command to a temporary script to avoid shell quoting issues.
        # The raw_cmd contains && chains, cd, export, and potentially nested quotes
        # (e.g. TORCH_CUDA_ARCH_LIST='8.9'). Wrapping it in "bash -c '...'" would
        # require fragile quote escaping. A temp script is clean and reliable.
        build_script = os.path.join(build_tmp_dir, "_aikore_build.sh")
        with open(build_script, 'w') as f:
            f.write("#!/bin/bash\nset -e\n")
            f.write(raw_cmd + "\n")
        os.chmod(build_script, 0o755)

        final_cmd = f"{conda_run} bash {build_script}"

        await websocket.send_text(f"\x1b[34m[INFO] Starting compilation for {preset['label']}...\x1b[0m\r\n")
        await websocket.send_text(f"\x1b[30;1m[CMD] {final_cmd}\x1b[0m\r\n\r\n")

        # 4. Execution
        return_code = await stream_subprocess(final_cmd, build_tmp_dir, websocket)

        # 5. Cleanup, Rename & Manifest
        if return_code == 0:
            await websocket.send_text(f"\r\n\x1b[32m[SUCCESS] Build completed successfully.\x1b[0m\r\n")
            
            # Look for wheels ONLY in the temp directory (ensures we get the one we just built)
            list_of_files = glob.glob(os.path.join(build_tmp_dir, "*.whl"))
            
            if list_of_files:
                # There should usually be only one, but take the latest just in case
                generated_file_path = max(list_of_files, key=os.path.getctime)
                original_filename = os.path.basename(generated_file_path)
                
                # --- RENAMING LOGIC ---
                # Example: package-1.0-cp312...whl -> package-1.0-cp312...+arch8.9.whl
                name_part, ext = os.path.splitext(original_filename)
                
                # Add architecture suffix to filename
                final_filename = f"{name_part}+arch{target_arch}{ext}"
                final_path = os.path.join(WHEELS_DIR, final_filename)
                
                # Move from tmp to final
                shutil.move(generated_file_path, final_path)
                
                update_manifest(final_filename, {
                    "cuda_arch": target_arch,
                    "source_preset": preset_key,
                    "git_url": git_url,
                    "python_ver": python_ver,
                    "cuda_ver": cuda_ver,
                    "torch_ver": detected_torch_ver
                })
                await websocket.send_text(f"\x1b[32m[INFO] Saved as: {final_filename}\x1b[0m\r\n")
        else:
            await websocket.send_text(f"\r\n\x1b[31m[FAILURE] Build failed with exit code {return_code}.\x1b[0m\r\n")
            
        # Clean up temp dir
        shutil.rmtree(build_tmp_dir, ignore_errors=True)

    except Exception as e:
        print(f"[DEBUG] Exception in build_websocket: {e}")
        traceback.print_exc()
        # Catch-all for early crashes
        try:
            await websocket.send_text(f"\r\n\x1b[31m[CRITICAL ERROR] {str(e)}\x1b[0m\r\n")
        except:
            pass
    finally:
        print("[DEBUG] Closing WebSocket.")
        try:
            await websocket.close()
        except:
            pass