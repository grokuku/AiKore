from fastapi import APIRouter, WebSocket, HTTPException, WebSocketDisconnect
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
            "source_preset": meta.get("source_preset", "Unknown")
        })
    
    # Sort by date new -> old
    wheels.sort(key=lambda x: x['created_at'], reverse=True)
    return wheels

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
        
        if preset_key not in PRESETS:
            print("[DEBUG] Invalid preset.")
            await websocket.send_text("\x1b[31m[ERROR] Invalid preset selected.\x1b[0m\r\n")
            await websocket.close()
            return

        preset = PRESETS[preset_key]
        git_url = custom_url if preset_key == "custom" else preset["git_url"]
        
        env_name = f"builder_py{python_ver.replace('.','')}_{cuda_ver}"
        
        # Log immediately to confirm connection
        await websocket.send_text(f"\x1b[34m[INFO] Initializing build process...\x1b[0m\r\n")
        await websocket.send_text(f"\x1b[34m[INFO] Target Environment: {env_name}\x1b[0m\r\n")

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
        print(f"[DEBUG] Env needs creation: {env_needs_creation}")
        
        if env_needs_creation:
            await websocket.send_text(f"\x1b[33m[INFO] Environment not found. Creating {env_name}...\x1b[0m\r\n")
            await websocket.send_text(f"\x1b[33m[WARN] This involves downloading Python and PyTorch (~2GB). Please wait.\x1b[0m\r\n")
            
            # Create Env Command - ADDED packaging and ninja
            create_cmd = f"{CONDA_EXE} create -n {env_name} python={python_ver} pip wheel setuptools packaging ninja -y"
            if await stream_subprocess(create_cmd, WHEELS_DIR, websocket) != 0:
                raise Exception("Failed to create Conda environment.")
            
            # Install PyTorch Command
            await websocket.send_text(f"\x1b[34m[INFO] Installing PyTorch ({cuda_ver}) headers...\x1b[0m\r\n")
            torch_pkg = "torch torchvision"
            index_url = f"https://download.pytorch.org/whl/{cuda_ver}"
            install_cmd = f"source {CONDA_BASE_DIR}/bin/activate {env_name} && pip install {torch_pkg} --index-url {index_url} --no-cache-dir"
            
            if await stream_subprocess(install_cmd, WHEELS_DIR, websocket) != 0:
                raise Exception("Failed to install PyTorch in builder environment.")
                
        else:
            await websocket.send_text(f"\x1b[32m[INFO] Using existing environment.\x1b[0m\r\n")

        # 3. Prepare Build
        build_tmp_dir = os.path.join(WHEELS_DIR, "build_tmp")
        if os.path.exists(build_tmp_dir):
            shutil.rmtree(build_tmp_dir)
        os.makedirs(build_tmp_dir)

        # Template substitution
        raw_cmd = preset["cmd_template"].format(
            git_url=git_url,
            arch=target_arch,
            output_dir=WHEELS_DIR,
            python="python -u" 
        )

        final_cmd = f"source {CONDA_BASE_DIR}/bin/activate {env_name} && {raw_cmd}"

        await websocket.send_text(f"\x1b[34m[INFO] Starting compilation for {preset['label']}...\x1b[0m\r\n")
        await websocket.send_text(f"\x1b[30;1m[CMD] {final_cmd}\x1b[0m\r\n\r\n")

        # 4. Execution
        return_code = await stream_subprocess(final_cmd, build_tmp_dir, websocket)

        # 5. Cleanup & Manifest
        shutil.rmtree(build_tmp_dir, ignore_errors=True)

        if return_code == 0:
            await websocket.send_text(f"\r\n\x1b[32m[SUCCESS] Build completed successfully.\x1b[0m\r\n")
            
            list_of_files = glob.glob(os.path.join(WHEELS_DIR, "*.whl"))
            if list_of_files:
                latest_file = max(list_of_files, key=os.path.getctime)
                filename = os.path.basename(latest_file)
                
                update_manifest(filename, {
                    "cuda_arch": target_arch,
                    "source_preset": preset_key,
                    "git_url": git_url,
                    "python_ver": python_ver,
                    "cuda_ver": cuda_ver
                })
                await websocket.send_text(f"\x1b[32m[INFO] Created: {filename}\x1b[0m\r\n")
        else:
            await websocket.send_text(f"\r\n\x1b[31m[FAILURE] Build failed with exit code {return_code}.\x1b[0m\r\n")

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