import subprocess
import os
import stat
import socket
import re # <--- Import regular expressions
from pathlib import Path
from subprocess import PIPE, STDOUT

# Directory definitions
INSTANCES_DIR = "/config/instances"
OUTPUTS_DIR = "/config/outputs"
BLUEPRINTS_DIR = "/opt/sd-install/blueprints"
NGINX_SITES_AVAILABLE = "/etc/nginx/locations.d"
NGINX_RELOAD_FLAG = Path("/run/aikore/nginx_reload.flag")

# NEW HELPER FUNCTION to create a filesystem-safe slug
def _slugify(value: str) -> str:
    """
    Converts a string to a URL-friendly "slug".
    Example: "My Test Instance!" -> "my-test-instance"
    """
    value = value.lower()
    value = re.sub(r'[^\w\s-]', '', value) # Remove non-alphanumeric chars
    value = re.sub(r'[\s_-]+', '-', value).strip('-') # Replace spaces/underscores with a single hyphen
    return value

def _find_free_port() -> int:
    """Finds an available TCP port on the host."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        return s.getsockname()[1]

def _find_free_display() -> int:
    """Finds an available X display number by checking for lock files."""
    display = 1
    while os.path.exists(f"/tmp/.X11-unix/X{display}"):
        display += 1
    return display

def _reload_nginx():
    """Requests an NGINX reload by creating a flag file."""
    try:
        print(f"Requesting NGINX reload by creating flag at {NGINX_RELOAD_FLAG}...")
        NGINX_RELOAD_FLAG.touch()
        print("Flag file created successfully.")
    except Exception as e:
        print(f"Error creating NGINX reload flag: {e}")
        raise Exception(f"Failed to request NGINX reload: {e}") from e

def start_instance_process(
    instance_name: str, 
    blueprint_script: str, 
    gpu_ids: str | None,
    persistent_mode: bool = False
) -> tuple[int, int | None, int | None, int | None]:
    """
    Starts a blueprint script for a given instance.
    If persistent_mode is True, it launches an isolated VNC session.
    Returns:
        tuple[int, int | None, int | None, int | None]: 
        (PID, app_port, vnc_web_port, vnc_display)
    """
    instance_conf_dir = os.path.join(INSTANCES_DIR, instance_name)
    instance_output_dir = os.path.join(OUTPUTS_DIR, instance_name)
    instance_slug = _slugify(instance_name) # <-- Create the slug

    os.makedirs(instance_conf_dir, exist_ok=True)
    os.makedirs(instance_output_dir, exist_ok=True)
    os.makedirs(NGINX_SITES_AVAILABLE, exist_ok=True)

    dest_script_path = os.path.join(instance_conf_dir, "launch.sh")

    if not os.path.exists(dest_script_path):
        source_script_path = os.path.join(BLUEPRINTS_DIR, blueprint_script)
        try:
            with open(source_script_path, 'r') as src, open(dest_script_path, 'w') as dest:
                dest.write(src.read())
        except FileNotFoundError:
            raise Exception(f"Blueprint file not found at {source_script_path}")

    st = os.stat(dest_script_path)
    os.chmod(dest_script_path, st.st_mode | stat.S_IEXEC)

    env = os.environ.copy()
    if gpu_ids:
        env["CUDA_VISIBLE_DEVICES"] = gpu_ids
    
    app_port = _find_free_port()
    env["WEBUI_PORT"] = str(app_port)

    env["INSTANCE_NAME"] = instance_name
    env["INSTANCE_CONF_DIR"] = instance_conf_dir
    env["INSTANCE_OUTPUT_DIR"] = instance_output_dir
    
    blueprint_id = os.path.splitext(blueprint_script)[0]
    env["BLUEPRINT_ID"] = blueprint_id

    if not persistent_mode:
        proxy_target_port = app_port
        main_cmd = ['bash', dest_script_path]
        vnc_web_port, vnc_display = None, None
    else:
        vnc_display = _find_free_display()
        vnc_web_port = _find_free_port()
        vnc_rfb_port = 5900 + vnc_display
        proxy_target_port = vnc_web_port

        vnc_launcher_path = os.path.join(instance_conf_dir, f"vnc_launcher_{instance_slug}.sh") # <-- Use slug here
        vnc_password_file = "/home/abc/.vnc/passwd" # Provided by base image

        vnc_launcher_content = f"""#!/bin/bash
# Launcher for instance '{instance_name}' on DISPLAY=:{vnc_display}

cleanup() {{
    echo "VNC launcher caught signal, cleaning up child processes..."
    kill 0
}}
trap cleanup SIGTERM SIGINT

echo "--- Starting VNC Server (Xvnc) on display :{vnc_display} (port {vnc_rfb_port}) ---"
/usr/bin/Xvnc :{vnc_display} \\
    -desktop VNC -auth /home/abc/.Xauthority -geometry 1280x800 -depth 24 \\
    -rfbwait 120000 -rfbauth {vnc_password_file} -rfbport {vnc_rfb_port} \\
    -fp /usr/share/fonts/X11/misc,/usr/share/fonts/X11/Type1 \\
    -SecurityTypes VncAuth,TLSVnc &

echo "--- Starting VNC Web Client (websockify) on port {vnc_web_port} ---"
/usr/bin/websockify -v --web /usr/share/novnc/ --cert /etc/ssl/novnc.pem {vnc_web_port} 127.0.0.1:{vnc_rfb_port} &

sleep 2
export DISPLAY=:{vnc_display}

echo "--- Starting Window Manager (openbox) ---"
/usr/bin/openbox-session &

echo "--- Starting WebUI script in background ---"
bash {dest_script_path} &

echo "--- Waiting 15s for server to initialize... ---"
sleep 15

echo "--- Launching Firefox ---"
firefox http://127.0.0.1:{app_port}

wait
"""
        with open(vnc_launcher_path, 'w') as f:
            f.write(vnc_launcher_content)
        
        os.chmod(vnc_launcher_path, stat.S_IRWXU)
        main_cmd = ['bash', vnc_launcher_path]

    # Use the slug for the NGINX config filename, but the original name in the location path
    nginx_conf_path = os.path.join(NGINX_SITES_AVAILABLE, f"{instance_slug}.conf")
    nginx_conf_content = f"""
    location /app/{instance_name}/ {{
        rewrite ^/app/[^/]+/(.*)$ /$1 break;
        proxy_pass http://127.0.0.1:{proxy_target_port}/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}
    """
    with open(nginx_conf_path, 'w') as f:
        f.write(nginx_conf_content)
    
    _reload_nginx()
    
    output_log_path = os.path.join(instance_conf_dir, "output.log")
    output_log = open(output_log_path, 'w')
    
    log_wrapper_cmd = ['gawk', '{{ print strftime("[%Y-%m-%d %H:%M:%S]"), $0; fflush(); }}']

    main_process = subprocess.Popen(
        main_cmd, cwd=instance_conf_dir, env=env,
        stdout=PIPE, stderr=STDOUT, preexec_fn=os.setsid
    )

    subprocess.Popen(
        log_wrapper_cmd, stdin=main_process.stdout,
        stdout=output_log, stderr=output_log
    )

    return main_process.pid, app_port, vnc_web_port, vnc_display

def cleanup_instance_process(instance_name: str):
    instance_slug = _slugify(instance_name) # <-- Use the slug to find the correct file
    nginx_conf_path = os.path.join(NGINX_SITES_AVAILABLE, f"{instance_slug}.conf")
    if os.path.exists(nginx_conf_path):
        os.remove(nginx_conf_path)
        _reload_nginx()