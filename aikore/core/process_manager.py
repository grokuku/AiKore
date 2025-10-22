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

# --- CORE MONITORING LOGIC ---

def monitor_instance_thread(instance_id: int, pid: int, port: int, vnc_display: int | None, instance_slug: str):
    """
    Runs in a background thread to monitor an instance's web server.
    Updates the instance status and launches Firefox when ready.
    """
    start_time = time.time()
    
    while psutil.pid_exists(pid):
        # Check if the web application is accessible
        try:
            response = requests.get(f"http://127.0.0.1:{port}", timeout=2)
            # We consider any successful HTTP response as the service being ready
            if response.status_code < 500:
                print(f"[Monitor-{instance_id}] Instance is RUNNING on port {port}.")
                with SessionLocal() as db:
                    db.query(models.Instance).filter(models.Instance.id == instance_id).update({"status": "started"})
                    db.commit()

                # If in VNC mode, launch Firefox now
                if vnc_display is not None:
                    print(f"[Monitor-{instance_id}] VNC mode detected. Launching Firefox on display :{vnc_display}.")
                    firefox_profile_dir = f"/tmp/firefox-profiles/{instance_slug}"
                    os.makedirs(firefox_profile_dir, exist_ok=True)
                    
                    # Set homepage via user.js for reliability
                    user_js_path = os.path.join(firefox_profile_dir, "user.js")
                    with open(user_js_path, 'w') as f:
                        f.write(f'user_pref("browser.startup.homepage", "http://127.0.0.1:{port}");\n')
                        f.write('user_pref("browser.startup.page", 1);\n')

                    ff_env = os.environ.copy()
                    ff_env["DISPLAY"] = f":{vnc_display}"
                    subprocess.Popen(
                        ['/usr/bin/firefox', '--no-sandbox', '--profile', firefox_profile_dir, '--kiosk'],
                        env=ff_env
                    )
                break # Exit the monitoring loop on success
        
        except requests.exceptions.ConnectionError:
            # Application is not yet ready, check for timeout
            elapsed_time = time.time() - start_time
            if elapsed_time > STALLED_TIMEOUT:
                with SessionLocal() as db:
                    # Update to 'stalled' only if it's currently 'starting'
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

    dest_script_path = os.path.join(instance_conf_dir, "launch.sh")
    source_script_path = os.path.join(BLUEPRINTS_DIR, instance.base_blueprint)
    try:
        with open(source_script_path, 'r') as src, open(dest_script_path, 'w') as dest:
            dest.write(src.read())
    except FileNotFoundError:
        raise Exception(f"Blueprint file not found at {source_script_path}")
    os.chmod(dest_script_path, os.stat(dest_script_path).st_mode | stat.S_IEXEC)

    env = os.environ.copy()
    if instance.gpu_ids:
        env["CUDA_VISIBLE_DEVICES"] = instance.gpu_ids
    
    env["WEBUI_PORT"] = str(instance.port)
    env["INSTANCE_NAME"] = instance.name
    env["INSTANCE_CONF_DIR"] = instance_conf_dir
    env["INSTANCE_OUTPUT_DIR"] = instance_output_dir
    env["BLUEPRINT_ID"] = os.path.splitext(instance.base_blueprint)[0]
    
    main_cmd = ['bash', dest_script_path]
    
    if instance.persistent_mode:
        # CORRECTIVE ACTION: Add a guard clause to prevent TypeError with old DB entries
        if instance.vnc_display is None or instance.vnc_port is None:
            instance.status = "stopped"
            db.commit()
            raise ValueError(
                "Instance is in persistent mode but is missing VNC port/display values. "
                "This can happen with instances created with a previous version. Please recreate it."
            )

        vnc_launcher_path = os.path.join(instance_conf_dir, f"vnc_launcher_{instance_slug}.sh")
        vnc_launcher_content = f"""
        #!/bin/bash
        cleanup() {{ kill 0; }}
        trap cleanup SIGTERM SIGINT
        
        /usr/bin/Xvnc :{instance.vnc_display} -rfbport {5900 + instance.vnc_display} -SecurityTypes None &
        /usr/bin/websockify -v --web /usr/share/novnc/ {instance.vnc_port} 127.0.0.1:{5900 + instance.vnc_display} &
        
        sleep 2
        export DISPLAY=:{instance.vnc_display}
        
        /usr/bin/openbox-session &
        bash {dest_script_path} &
        wait
        """
        with open(vnc_launcher_path, 'w') as f:
            f.write(textwrap.dedent(vnc_launcher_content))
        os.chmod(vnc_launcher_path, stat.S_IRWXU)
        main_cmd = ['bash', vnc_launcher_path]
    
    # NGINX Configuration (unchanged logic)
    proxy_target_port = instance.vnc_port if instance.persistent_mode else instance.port
    if instance.persistent_mode:
        nginx_conf_content = f"""
        location /ws/{instance.name}/ {{ proxy_pass http://127.0.0.1:{proxy_target_port}/; proxy_http_version 1.1; proxy_set_header Upgrade $http_upgrade; proxy_set_header Connection "upgrade"; }}
        location /app/{instance.name}/ {{
            if ($uri = /app/{instance.name}/) {{ return 302 $scheme://$http_host${{uri}}vnc.html?autoconnect=true&resize=remote&path=/ws/{instance.name}/; }}
            proxy_pass http://127.0.0.1:{proxy_target_port}/;
        }}"""
    else:
        nginx_conf_content = f"""
        location /app/{instance.name}/ {{
            rewrite ^/app/[^/]+/(.*)$ /$1 break;
            proxy_pass http://127.0.0.1:{proxy_target_port}/;
            proxy_http_version 1.1; proxy_set_header Upgrade $http_upgrade; proxy_set_header Connection "upgrade";
            proxy_set_header Host $host; proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for; proxy_set_header X-Forwarded-Proto $scheme;
        }}"""
    with open(os.path.join(NGINX_SITES_AVAILABLE, f"{instance_slug}.conf"), 'w') as f:
        f.write(nginx_conf_content)
    _reload_nginx()

    # Launch Process and Monitor Thread
    output_log_path = os.path.join(instance_conf_dir, "output.log")
    with open(output_log_path, 'w') as output_log:
        main_process = subprocess.Popen(main_cmd, cwd=instance_conf_dir, env=env, stdout=output_log, stderr=output_log, preexec_fn=os.setsid)
    
    instance.pid = main_process.pid
    instance.status = "starting"
    db.commit()

    monitor = threading.Thread(
        target=monitor_instance_thread,
        args=(instance.id, instance.pid, instance.port, instance.vnc_display, instance_slug),
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