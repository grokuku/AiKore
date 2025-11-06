import subprocess
import os
import stat
import socket
import re
import textwrap
import threading
import time
import requests
import signal
import psutil
import pty
import fcntl
import termios
import struct
from pathlib import Path
from subprocess import PIPE, STDOUT
from sqlalchemy.orm import Session

# We will need access to the DB models and the session factory
from aikore.database import models
from aikore.database.session import SessionLocal

# --- CONSTANTS ---
INSTANCES_DIR = "/config/instances"
OUTPUTS_DIR = "/config/outputs"
BLUEPRINTS_DIR = "/opt/sd-install/blueprints"
SCRIPTS_DIR = "/opt/sd-install/scripts"
NGINX_SITES_AVAILABLE = "/etc/nginx/locations.d"
NGINX_RELOAD_FLAG = Path("/run/aikore/nginx_reload.flag")

# Timeout in seconds before an instance is marked as 'stalled'
STALLED_TIMEOUT = 180
# How often the monitor thread checks the web port
MONITOR_POLL_INTERVAL = 2

# --- GLOBAL STATE ---
# In-memory dictionary to keep track of running processes and their monitor threads
# Structure: { instance_id: {"process": Popen_object, "monitor_thread": Thread_object} }
running_instances = {}

# --- HELPER FUNCTIONS ---

def _slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r'[^\w\s-]', '', value)
    value = re.sub(r'[\s_-]+', '-', value).strip('-')
    return value

def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        return s.getsockname()[1]

def _find_free_display() -> int:
    display = 10
    while os.path.exists(f"/tmp/.X11-unix/X{display}"):
        display += 1
    return display

def _reload_nginx():
    try:
        NGINX_RELOAD_FLAG.touch()
    except Exception as e:
        print(f"[ERROR] Failed to request NGINX reload: {e}")

def _cleanup_instance_files(instance_slug: str):
    """Cleans up NGINX conf and other temp files for an instance."""
    nginx_conf_path = os.path.join(NGINX_SITES_AVAILABLE, f"{instance_slug}.conf")
    if os.path.exists(nginx_conf_path):
        os.remove(nginx_conf_path)
        _reload_nginx()
    
    # Cleanup Firefox profile if it exists
    firefox_profile_dir = f"/tmp/firefox-profiles/{instance_slug}"
    if os.path.isdir(firefox_profile_dir):
        import shutil
        shutil.rmtree(firefox_profile_dir, ignore_errors=True)

# --- TERMINAL MANAGEMENT ---

def parse_blueprint_metadata(blueprint_filename: str) -> dict:
    """
    Parses the metadata block from a blueprint shell script.
    """
    metadata = {}
    blueprint_path = os.path.join(BLUEPRINTS_DIR, blueprint_filename)
    if not os.path.exists(blueprint_path):
        return metadata

    with open(blueprint_path, 'r') as f:
        in_metadata_block = False
        for line in f:
            if "### AIKORE-METADATA-START ###" in line:
                in_metadata_block = True
                continue
            if "### AIKORE-METADATA-END ###" in line:
                break
            if in_metadata_block:
                line = line.strip()
                if line.startswith('#') and '=' in line:
                    # Format is '# aikore.key = value'
                    parts = line[1:].strip().split('=', 1)
                    if len(parts) == 2 and parts[0].strip().startswith('aikore.'):
                        key = parts[0].strip().replace('aikore.', '', 1)
                        value = parts[1].strip()
                        metadata[key] = value
    return metadata


def start_terminal_process(instance: models.Instance):
    """
    Spawns a shell process inside a pseudo-terminal (PTY) for a given instance.
    """
    instance_conf_dir = os.path.join(INSTANCES_DIR, instance.name)
    metadata = parse_blueprint_metadata(instance.base_blueprint)
    
    venv_type = metadata.get('venv_type')
    venv_path = metadata.get('venv_path')

    command = ['/bin/bash']
    env = os.environ.copy()

    if venv_type and venv_path:
        full_venv_path = os.path.join(instance_conf_dir, venv_path)
        if venv_type == 'conda':
            # This launches a shell, sources the activate script for the specific env,
            # then 'exec' replaces that shell with a new one that inherits the environment.
            conda_activate_cmd = f"source /home/abc/miniconda3/bin/activate {full_venv_path} && exec /bin/bash"
            command = ['/bin/bash', '-c', conda_activate_cmd]
        elif venv_type == 'python':
            # For standard python venv, --rcfile is the correct approach
            activate_script = os.path.join(full_venv_path, 'bin', 'activate')
            command = ['/bin/bash', '--rcfile', activate_script]

    # Fork a process and connect the child's controlling terminal to a new PTY
    pid, master_fd = pty.fork()

    if pid == 0:  # Child process
        # Set the working directory for the new shell
        os.chdir(instance_conf_dir)
        # Execute the shell command
        os.execve(command[0], command, env)
    else:  # Parent process
        return pid, master_fd

def resize_terminal_process(master_fd: int, rows: int, cols: int):
    """
    Resizes the pseudo-terminal window size.
    """
    try:
        # Pack the new window size into a struct
        winsize = struct.pack('HHHH', rows, cols, 0, 0)
        # Set the new window size using a system call
        fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)
    except Exception as e:
        print(f"[ERROR] Failed to resize terminal: {e}")


# --- CORE MONITORING LOGIC ---

def monitor_instance_thread(instance_id: int, pid: int, port_to_monitor: int, internal_app_port: int, persistent_display: int | None, instance_slug: str):
    """
    Runs in a background thread to monitor an instance's web server.
    Updates the instance status and launches Firefox when ready.
    """
    start_time = time.time()
    
    while psutil.pid_exists(pid):
        try:
            # Poll the internal application port to confirm it's truly ready
            response = requests.get(f"http://127.0.0.1:{internal_app_port}", timeout=2)
            
            if response.status_code < 500:
                print(f"[Monitor-{instance_id}] Instance is RUNNING on port {internal_app_port}.")
                with SessionLocal() as db:
                    db.query(models.Instance).filter(models.Instance.id == instance_id).update({"status": "started"})
                    db.commit()

                if persistent_display is not None:
                    print(f"[Monitor-{instance_id}] Persistent mode detected. Launching Firefox on display :{persistent_display}.")
                    firefox_profile_dir = f"/tmp/firefox-profiles/{instance_slug}"
                    os.makedirs(firefox_profile_dir, exist_ok=True)
                    
                    ff_env = os.environ.copy()
                    ff_env["DISPLAY"] = f":{persistent_display}"
                    
                    target_url = f'http://127.0.0.1:{internal_app_port}'
                    print(f"[Monitor-{instance_id}] Pointing internal Firefox to {target_url}")
                    
                    subprocess.Popen(
                        ['/usr/bin/firefox', '--profile', firefox_profile_dir, '--kiosk', '-url', target_url],
                        env=ff_env
                    )
                break
        
        except requests.exceptions.ConnectionError:
            elapsed_time = time.time() - start_time
            if elapsed_time > STALLED_TIMEOUT:
                with SessionLocal() as db:
                    instance = db.query(models.Instance).filter(models.Instance.id == instance_id).first()
                    if instance and instance.status == "starting":
                        instance.status = "stalled"
                        db.commit()
                        print(f"[Monitor-{instance_id}] Instance has been starting for >{STALLED_TIMEOUT}s. Marked as STALLED.")
            
            time.sleep(MONITOR_POLL_INTERVAL)
        
        except Exception as e:
            print(f"[Monitor-{instance_id}] An unexpected error occurred: {e}")
            time.sleep(MONITOR_POLL_INTERVAL)
    
    print(f"[Monitor-{instance_id}] Process with PID {pid} no longer exists. Monitor thread exiting.")

# --- PROCESS MANAGEMENT INTERFACE ---

def start_instance_process(db: Session, instance: models.Instance):
    """
    Starts the instance process and its associated monitoring thread.
    """
    if instance.id in running_instances:
        raise Exception(f"Instance {instance.id} is already running.")

    instance_conf_dir = os.path.join(INSTANCES_DIR, instance.name)
    instance_output_dir = os.path.join(OUTPUTS_DIR, instance.name)
    instance_slug = _slugify(instance.name)

    os.makedirs(instance_conf_dir, exist_ok=True)
    os.makedirs(instance_output_dir, exist_ok=True)
    os.makedirs(NGINX_SITES_AVAILABLE, exist_ok=True)

    global_tmp_dir = "/config/tmp"
    os.makedirs(global_tmp_dir, exist_ok=True)

    dest_script_path = os.path.join(instance_conf_dir, "launch.sh")
    source_script_path = os.path.join(BLUEPRINTS_DIR, instance.base_blueprint)
    try:
        with open(source_script_path, 'r') as src, open(dest_script_path, 'w') as dest:
            dest.write(src.read())
    except FileNotFoundError:
        raise Exception(f"Blueprint file not found at {source_script_path}")
    os.chmod(dest_script_path, os.stat(dest_script_path).st_mode | stat.S_IEXEC)

    env = os.environ.copy()
    env["TMPDIR"] = global_tmp_dir
    if instance.gpu_ids:
        env["CUDA_VISIBLE_DEVICES"] = instance.gpu_ids
    
    env["WEBUI_PORT"] = str(instance.port)
    env["INSTANCE_NAME"] = instance.name
    env["INSTANCE_CONF_DIR"] = instance_conf_dir
    env["INSTANCE_OUTPUT_DIR"] = instance_output_dir
    env["BLUEPRINT_ID"] = os.path.splitext(instance.base_blueprint)[0]
    env["SUBFOLDER"] = f"/instance/{instance_slug}/"
    
    port_to_monitor = instance.port
    internal_app_port = instance.port

    if instance.persistent_mode:
        kasm_launcher_path = os.path.join(SCRIPTS_DIR, "kasm_launcher.sh")
        main_cmd = [
            'bash', 
            kasm_launcher_path, 
            instance.name, 
            str(instance.persistent_port),
            dest_script_path
        ]
        port_to_monitor = instance.persistent_port
        
        # --- CRITICAL FIX ---
        # Pass the determined display number to the launcher script.
        env["DISPLAY"] = f":{instance.persistent_display}"

        print(f"[Manager] Persistent mode: Bypassing NGINX proxy. Instance will be directly accessible on port {instance.persistent_port}.")

    else:
        main_cmd = ['bash', dest_script_path]
        
        nginx_conf_path = os.path.join(NGINX_SITES_AVAILABLE, f"{instance_slug}.conf")
        nginx_conf = textwrap.dedent(f"""
            location /instance/{instance_slug}/ {{
                proxy_pass http://127.0.0.1:{instance.port}/;
                proxy_http_version 1.1;
                proxy_set_header Upgrade $http_upgrade;
                proxy_set_header Connection "upgrade";
                proxy_set_header Host $host;
                proxy_buffering off;
            }}
        """)
        with open(nginx_conf_path, 'w') as f:
            f.write(nginx_conf)
        _reload_nginx()

    output_log_path = os.path.join(instance_conf_dir, "output.log")
    with open(output_log_path, 'w') as output_log:
        main_process = subprocess.Popen(main_cmd, cwd=instance_conf_dir, env=env, stdout=output_log, stderr=output_log, preexec_fn=os.setsid)
    
    instance.pid = main_process.pid
    instance.status = "starting"
    db.commit()

    monitor = threading.Thread(
        target=monitor_instance_thread,
        args=(instance.id, instance.pid, port_to_monitor, internal_app_port, instance.persistent_display, instance_slug),
        daemon=True
    )
    monitor.start()

    running_instances[instance.id] = {"process": main_process, "monitor_thread": monitor}
    print(f"[Manager] Started instance '{instance.name}' (PID: {instance.pid}) and its monitor thread.")


def stop_instance_process(db: Session, instance: models.Instance):
    """
    Stops a running instance process and its monitor thread.
    """
    instance_id = instance.id
    if instance_id not in running_instances:
        print(f"[Manager] Stop requested, but instance {instance_id} not in running_instances dict. Cleaning up files.")
    else:
        process_info = running_instances[instance_id]
        process = process_info["process"]
        print(f"[Manager] Stopping process group for PID {process.pid}...")
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            process.wait(timeout=10)
        except ProcessLookupError:
            print(f"[Manager] Process with PID {process.pid} not found. It may have already terminated.")
        except subprocess.TimeoutExpired:
            print(f"[Manager] Process did not terminate gracefully. Sending SIGKILL.")
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except Exception as e:
            print(f"[Manager] Error stopping process: {e}")
        
        del running_instances[instance_id]
    
    _cleanup_instance_files(_slugify(instance.name))
    
    instance.status = "stopped"
    instance.pid = None
    db.commit()
    print(f"[Manager] Instance {instance.name} stopped and cleaned up.")