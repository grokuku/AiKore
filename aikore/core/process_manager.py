import subprocess
import os
import stat
import socket
from pathlib import Path # Use pathlib for a cleaner way to touch a file

# Directory definitions
INSTANCES_DIR = "/config/instances"
BLUEPRINTS_DIR = "/opt/sd-install/blueprints"
NGINX_SITES_AVAILABLE = "/etc/nginx/locations.d"
NGINX_RELOAD_FLAG = Path("/run/aikore/nginx_reload.flag")

def _find_free_port() -> int:
    """Finds an available TCP port on the host."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        return s.getsockname()[1]

def _reload_nginx():
    """
    Requests an NGINX reload by creating a flag file.
    A root-level service (`svc-nginx-reloader`) watches for this file.
    """
    try:
        print(f"Requesting NGINX reload by creating flag at {NGINX_RELOAD_FLAG}...")
        NGINX_RELOAD_FLAG.touch()
        print("Flag file created successfully.")
    except Exception as e:
        print(f"Error creating NGINX reload flag: {e}")
        raise Exception(f"Failed to request NGINX reload: {e}") from e

def start_instance_process(instance_name: str, blueprint_script: str, gpu_ids: str | None) -> (int, int):
    """
    Starts a blueprint script as a background subprocess for a given instance.
    Also manages NGINX configuration.
    Returns:
        tuple[int, int]: The PID and the assigned Port of the started process.
    """
    os.makedirs(INSTANCES_DIR, exist_ok=True)
    instance_path = os.path.join(INSTANCES_DIR, instance_name)
    os.makedirs(instance_path, exist_ok=True)
    os.makedirs(NGINX_SITES_AVAILABLE, exist_ok=True)

    source_script_path = os.path.join(BLUEPRINTS_DIR, blueprint_script)
    dest_script_path = os.path.join(instance_path, "launch.sh")
    with open(source_script_path, 'r') as src, open(dest_script_path, 'w') as dest:
        dest.write(src.read())
    st = os.stat(dest_script_path)
    os.chmod(dest_script_path, st.st_mode | stat.S_IEXEC)

    env = os.environ.copy()
    if gpu_ids:
        env["CUDA_VISIBLE_DEVICES"] = gpu_ids
    
    assigned_port = _find_free_port()
    env["WEBUI_PORT"] = str(assigned_port)

    nginx_conf_path = os.path.join(NGINX_SITES_AVAILABLE, f"{instance_name}.conf")
    nginx_conf_content = f"""
    location /app/{instance_name}/ {{
        proxy_pass http://127.0.0.1:{assigned_port}/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }}
    """
    with open(nginx_conf_path, 'w') as f:
        f.write(nginx_conf_content)
    
    _reload_nginx()
    
    stdout_log_path = os.path.join(instance_path, "stdout.log")
    stderr_log_path = os.path.join(instance_path, "stderr.log")
    stdout_log = open(stdout_log_path, 'w')
    stderr_log = open(stderr_log_path, 'w')

    process = subprocess.Popen(
        ['bash', dest_script_path],
        cwd=instance_path,
        env=env,
        stdout=stdout_log,
        stderr=stderr_log,
        preexec_fn=os.setsid
    )

    return process.pid, assigned_port

def cleanup_instance_process(instance_name: str):
    """
    Cleans up resources for a stopped instance, primarily its NGINX config.
    """
    nginx_conf_path = os.path.join(NGINX_SITES_AVAILABLE, f"{instance_name}.conf")
    if os.path.exists(nginx_conf_path):
        os.remove(nginx_conf_path)
        _reload_nginx()