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

# Try to import torch for CUDA detection, handle if missing
try:
    import torch
    print("[DEBUG] torch imported successfully.")
except ImportError:
    torch = None
    print("[DEBUG] torch not found.")

router = APIRouter(prefix="/api/builder", tags=["Builder"])

# --- CONFIGURATION ---
INSTANCES_DIR = "/config/instances"
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
    "custom": {
        "label": "Custom Git Repository",
        "git_url": "", 
        "description": "Build a wheel from any Git repo containing setup.py or pyproject.toml.",
        "cmd_template": (
            "pip wheel {git_url} --wheel-dir={output_dir} --no-deps --no-build-isolation"
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
    
    if torch and torch.cuda.is_available():
        try:
            cap = torch.cuda.get_device_capability()
            detected_arch = f"{cap[0]}.{cap[1]}"
            gpu_name = torch.cuda.get_device_name()
        except Exception:
            pass

    return {
        "presets": PRESETS,
        "detected_arch": detected_arch,
        "gpu_name": gpu_name,
        "python_path": sys.executable
    }

@router.get("/versions/torch/{cuda_ver}")
def get_torch_versions_for_cuda(cuda_ver: str):
    """
    Dynamically fetches available torch versions from download.pytorch.org
    for the specific CUDA version. 
    Fallback to a default list if offline.
    """
    
    # Normalize input (e.g. "cu130" -> "cu130")
    if not cuda_ver.startswith("cu"):
        # Assuming cpu or rocm, but let's stick to cu for now
        pass
        
    index_url = f"https://download.pytorch.org/whl/{cuda_ver}/torch/"
    versions = set()
    
    # Default fallback list (in case of network failure)
    # Includes 2.10 as requested by user context
    fallback_versions = ["2.10.0", "2.9.1", "2.5.1", "2.4.1", "2.3.1", "2.1.2"]
    
    try:
        print(f"[DEBUG] Fetching versions from {index_url}...")
        # Use urllib to avoid adding 'requests' dependency if not present
        with urllib.request.urlopen(index_url, timeout=5) as response:
            html = response.read().decode('utf-8')
            
            # Regex to find links like: torch-2.5.1%2Bcu124-...
            # Pattern matches: torch-X.Y.Z%2B or torch-X.Y.Z+
            # We look for versions that match the requested cuda tag
            # Note: PyTorch index uses %2B for + sign
            
            # Simple pattern to extract "2.5.1" from "torch-2.5.1%2Bcu124-..."
            # We enforce that it must be followed by %2B or + and our cuda_ver (or compatible)
            # Actually, the directory /whl/cu130/ contains ONLY compatible wheels,
            # so we just need to extract the version number from "torch-X.Y.Z..."
            
            matches = re.findall(r'torch-([0-9]+\.[0-9]+\.[0-9]+)%2B', html)
            if not matches:
                # Try finding without %2B (older format or diff encoding)
                matches = re.findall(r'torch-([0-9]+\.[0-9]+\.[0-9]+)\+', html)
                
            for m in matches:
                versions.add(m)
                
        if not versions:
            print("[DEBUG] No versions found via regex, using fallback.")
            return sorted(fallback_versions, reverse=True)
            
        # Convert to list and sort descending
        # We use a simple lambda to handle semantic versioning broadly
        return sorted(list(versions), key=lambda s: list(map(int, s.split('.'))), reverse=True)

    except Exception as e:
        print(f"[DEBUG] Failed to fetch torch versions: {e}")
        return sorted(fallback_versions, reverse=True)

@router.get("/wheels", response_model=List[WheelMetadata])
def list_wheels():
    manifest = get_manifest()
    wheels = []
    
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
        
        # Environment name includes torch version now to distinguish them
        safe_torch_ver = requested_torch_ver.replace(".", "")
        env_name = f"builder_py{python_ver.replace('.','')}_{cuda_ver}_pt{safe_torch_ver}"
        
        # Log immediately to confirm connection
        await websocket.send_text(f"\x1b[34m[INFO] Initializing build process...\x1b[0m\r\n")
        await websocket.send_text(f"\x1b[34m[INFO] Target Environment: {env_name}\x1b[0m\r\n")
        await websocket.send_text(f"\x1b[34m[INFO] Requested Config: Torch {requested_torch_ver} | {cuda_ver}\x1b[0m\r\n")

        # 2. Environment Setup
        await websocket.send_text(f"\x1b[30;1m[CHECK] Verifying Conda environment...\x1b[0m\r\n")
        
        # Use full path for conda and grep
        env_exists_cmd = f"{CONDA_EXE} info --envs | /usr/bin/grep {env_name}"
        
        proc = await asyncio.create_subprocess_shell(
            env_exists_cmd, 
            stdout=asyncio.subprocess.PIPE, 
            stderr=asyncio.subprocess.PIPE,
            executable='/bin/bash'
        )
        await proc.wait()
        
        env_needs_creation = proc.returncode != 0
        
        if env_needs_creation:
            await websocket.send_text(f"\x1b[33m[INFO] Environment not found. Creating {env_name}...\x1b[0m\r\n")
            await websocket.send_text(f"\x1b[33m[WARN] This involves downloading Python and PyTorch (~2GB). Please wait.\x1b[0m\r\n")
            
            # Create Env Command
            create_cmd = f"{CONDA_EXE} create -n {env_name} python={python_ver} pip wheel setuptools packaging ninja -y"
            if await stream_subprocess(create_cmd, WHEELS_DIR, websocket) != 0:
                raise Exception("Failed to create Conda environment.")
            
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
            install_cmd = f"source {CONDA_BASE_DIR}/bin/activate {env_name} && pip install {torch_pkg} --index-url {index_url} --no-cache-dir"
            
            if await stream_subprocess(install_cmd, WHEELS_DIR, websocket) != 0:
                raise Exception("Failed to install PyTorch in builder environment.")
        
        # 2.5 DETECT TORCH VERSION (NEW)
        # We query the environment to find out exactly what version was installed
        detect_cmd = f"source {CONDA_BASE_DIR}/bin/activate {env_name} && python -c 'import torch; print(torch.__version__)'"
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

        final_cmd = f"source {CONDA_BASE_DIR}/bin/activate {env_name} && {raw_cmd}"

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