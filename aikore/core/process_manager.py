import subprocess
import os
import stat
import socket
import sys
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
import shutil
from pathlib import Path
from subprocess import PIPE, STDOUT
from sqlalchemy.orm import Session

# We will need access to the DB models and the session factory
from aikore.database import models
from aikore.database.session import SessionLocal

# LOT3 (M7): single shared metadata parser for all blueprint/launch.sh parsing.
from .metadata_parser import iter_metadata_entries, parse_metadata_file

# --- CONSTANTS ---
from aikore.config import INSTANCES_DIR, OUTPUTS_DIR, BLUEPRINTS_DIR, CUSTOM_BLUEPRINTS_DIR, SCRIPTS_DIR

# Keep local references for backward compatibility in this module
INSTANCES_DIR = INSTANCES_DIR
OUTPUTS_DIR = OUTPUTS_DIR
BLUEPRINTS_DIR = BLUEPRINTS_DIR
CUSTOM_BLUEPRINTS_DIR = CUSTOM_BLUEPRINTS_DIR
SCRIPTS_DIR = SCRIPTS_DIR
NGINX_SITES_AVAILABLE = "/etc/nginx/locations.d"
NGINX_RELOAD_FLAG = Path("/run/aikore/nginx_reload.flag")

# Monitor thread polls the web port every N seconds
MONITOR_POLL_INTERVAL = 1

# --- GLOBAL STATE ---
# In-memory dictionary to keep track of running processes and their monitor threads
# Structure: { instance_id: {"process": Popen_object, "monitor_thread": Thread_object} }
running_instances = {}

# LOT3 (M4): Firefox kiosk processes launched by monitor threads.
# They are deliberately started in their OWN session (start_new_session=True)
# so they are not part of the API server's process group nor of an instance's,
# and are tracked here to be explicitly terminated on stop/death of instance.
# Structure: { instance_id: Popen_object }
firefox_processes = {}

# LOT3 (M1): serializes free port/display allocation inside this process so two
# concurrent creations can never observe the same "free" resource between the
# probe and its use. Combined with the DB-level check in the API layer and the
# bind re-verification right before Popen (see start_instance_process).
allocation_lock = threading.RLock()

# --- HELPER FUNCTIONS ---

def _slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r'[^\w\s-]', '', value)
    value = re.sub(r'[\s_-]+', '-', value).strip('-')
    return value

def _find_free_port() -> int:
    # LOT3 (M1): the bind->close->rebind window is inherently TOCTOU-prone across
    # processes; the in-process allocation_lock removes the intra-process race,
    # and start_instance_process() re-verifies the bind right before spawning.
    with allocation_lock:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('', 0))
            return s.getsockname()[1]

def _display_in_use(display: int) -> bool:
    """LOT3 (M1): a display is taken if either its X11 socket OR its lock file exists."""
    return (
        os.path.exists(f"/tmp/.X11-unix/X{display}")
        or os.path.exists(f"/tmp/X{display}-lock")
    )

def _find_free_display() -> int:
    # LOT3 (M1): also honor /tmp/X{n}-lock, not only the X11 socket directory.
    with allocation_lock:
        display = 10
        while _display_in_use(display):
            display += 1
        return display

def _can_bind_port(port: int) -> bool:
    """LOT3 (M1): true if no ACTIVE listener currently holds the TCP port.

    SO_REUSEADDR is set so sockets sitting in TIME_WAIT do not produce false
    positives; only a live listener (the real conflict) makes the bind fail.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("", port))
        return True
    except OSError:
        return False

def _ensure_runtime_ports_free(db: Session, instance: models.Instance, max_attempts: int = 5):
    """LOT3 (M1): last-mile port/display verification right before the Popen.

    Ports allocated at creation time can be stale by start time (another
    service grabbed the port, leftover X lock, concurrent creation that raced
    past the API-level checks...). This helper:
      - normal mode: re-binds instance.port; if taken, allocates another free
        ephemeral port;
      - persistent mode: re-binds instance.persistent_port; if taken, picks the
        next free port of AIKORE_INSTANCE_PORT_RANGE; bumps the display if its
        lock/socket appeared meanwhile.
    Persists any reallocation to the DB. Raises RuntimeError when nothing
    usable can be found.
    """
    # Ports held by OTHER instances, per the DB.
    other_used = {
        p for (p,) in db.query(models.Instance.port)
        .filter(models.Instance.id != instance.id).all() if p is not None
    } | {
        p for (p,) in db.query(models.Instance.persistent_port)
        .filter(models.Instance.id != instance.id).all() if p is not None
    }

    changed = False

    if instance.persistent_mode:
        public_port = instance.persistent_port
        pool_ok = True
        port_range_str = os.environ.get("AIKORE_INSTANCE_PORT_RANGE", "19001-19020")
        try:
            start_port, end_port = map(int, port_range_str.split('-'))
        except (ValueError, TypeError):
            pool_ok = False

        if public_port is not None and (not _can_bind_port(public_port) or public_port in other_used):
            replacement = None
            if pool_ok:
                for _ in range(max_attempts):
                    candidate = _find_free_port()
                    if (
                        start_port <= candidate <= end_port
                        and candidate not in other_used
                        and candidate != public_port
                        and _can_bind_port(candidate)
                    ):
                        replacement = candidate
                        break
            if replacement is None:
                raise RuntimeError(
                    f"Cannot start persistent instance '{instance.name}': port "
                    f"{public_port} is busy and no free replacement found in range '{port_range_str}'."
                )
            print(f"[Manager] Port {public_port} busy at start time; reallocating persistent port to {replacement}.")
            instance.persistent_port = replacement
            changed = True

        if instance.persistent_display is not None and _display_in_use(instance.persistent_display):
            replacement_display = _find_free_display()
            print(f"[Manager] Display :{instance.persistent_display} busy at start time; reallocating to :{replacement_display}.")
            instance.persistent_display = replacement_display
            changed = True
    else:
        app_port = instance.port
        if app_port is not None and (not _can_bind_port(app_port) or app_port in other_used):
            replacement = None
            for _ in range(max_attempts):
                candidate = _find_free_port()
                if candidate not in other_used and _can_bind_port(candidate):
                    replacement = candidate
                    break
            if replacement is None:
                raise RuntimeError(
                    f"Cannot start instance '{instance.name}': port {app_port} is busy "
                    f"and no free replacement port could be allocated."
                )
            print(f"[Manager] Port {app_port} busy at start time; reallocating application port to {replacement}.")
            instance.port = replacement
            changed = True

    if changed:
        db.commit()
        db.refresh(instance)

def remove_nginx_config(instance_slug: str):
    """LOT3 (M9): removes the NGINX location conf of an instance (best effort).

    Used after a rename so the stale '{old_slug}.conf' does not linger until
    the next stop/start cycle.
    """
    nginx_conf_path = os.path.join(NGINX_SITES_AVAILABLE, f"{instance_slug}.conf")
    try:
        if os.path.exists(nginx_conf_path):
            os.remove(nginx_conf_path)
            _reload_nginx()
            print(f"[Manager] Removed stale NGINX config '{nginx_conf_path}'.")
    except Exception as e:
        print(f"[Manager-Error] Could not remove NGINX config '{nginx_conf_path}': {e}")

def terminate_firefox_for_instance(instance_id: int):
    """LOT3 (M4): terminates the tracked Firefox kiosk process of an instance.

    Firefox is launched by the monitor thread WITHOUT setsid originally, which
    left it orphaned (and accumulating) after every stop/restart because the
    instance killpg never reached it. It now runs in its own session and is
    killed explicitly here.
    """
    ff_proc = firefox_processes.pop(instance_id, None)
    if ff_proc is None:
        return
    try:
        os.killpg(os.getpgid(ff_proc.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass
    except Exception as e:
        print(f"[Manager-Error] Failed to TERM Firefox group for instance {instance_id}: {e}")
    try:
        ff_proc.wait(timeout=5)
        print(f"[Manager] Firefox (PID {ff_proc.pid}) terminated for instance {instance_id}.")
    except subprocess.TimeoutExpired:
        print(f"[Manager] Firefox (PID {ff_proc.pid}) did not exit; sending SIGKILL.")
        try:
            os.killpg(os.getpgid(ff_proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            try:
                ff_proc.kill()
            except Exception:
                pass
        try:
            ff_proc.wait(timeout=5)
        except Exception:
            pass
    except Exception as e:
        print(f"[Manager-Error] Error while reaping Firefox for instance {instance_id}: {e}")

def _reload_nginx():
    try:
        NGINX_RELOAD_FLAG.touch()
    except Exception as e:
        print(f"[ERROR] Failed to request NGINX reload: {e}")

def update_nginx_config(db: Session):
    """
    Regenerates NGINX configuration for all active, non-persistent instances
    and reloads the NGINX service. This allows updating routing (like hostnames)
    without killing the instance processes.
    """
    # Find all instances that are started
    active_instances = db.query(models.Instance).filter(models.Instance.status == "started").all()
    
    updated_count = 0
    
    for instance in active_instances:
        # Persistent instances use KasmVNC on a separate port, they don't use this NGINX proxy logic.
        if instance.persistent_mode:
            continue
            
        instance_slug = _slugify(instance.name)
        nginx_conf_path = os.path.join(NGINX_SITES_AVAILABLE, f"{instance_slug}.conf")
        
        # Re-generate the standard location block.
        # Currently, the proxy logic relies on relative paths (/instance/name/).
        # If custom hostname logic requiring 'server_name' blocks is implemented later, 
        # it should be added here.
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
        
        try:
            with open(nginx_conf_path, 'w') as f:
                f.write(nginx_conf)
            updated_count += 1
        except Exception as e:
            print(f"[Manager-Error] Could not update NGINX config for {instance.name}: {e}")

    if updated_count > 0:
        _reload_nginx()
        print(f"[Manager] Refreshed NGINX configuration for {updated_count} active instances.")

def _cleanup_instance_files(instance_slug: str):
    """Cleans up NGINX conf and other temp files for an instance.

    LOT3: best-effort per item so one failing removal never aborts the whole
    cleanup chain (it runs inside stop_instance_process's finally block).
    """
    nginx_conf_path = os.path.join(NGINX_SITES_AVAILABLE, f"{instance_slug}.conf")
    try:
        if os.path.exists(nginx_conf_path):
            os.remove(nginx_conf_path)
            _reload_nginx()
    except OSError as e:
        print(f"[Manager-Error] Could not remove NGINX conf '{nginx_conf_path}': {e}")
    
    # Cleanup Firefox profile if it exists
    firefox_profile_dir = f"/tmp/firefox-profiles/{instance_slug}"
    if os.path.isdir(firefox_profile_dir):
        shutil.rmtree(firefox_profile_dir, ignore_errors=True)

# --- TERMINAL MANAGEMENT ---

def _find_blueprint_path(blueprint_filename: str) -> str | None:
    """
    Finds the actual path to a blueprint file.
    Checks custom blueprints first, then stock blueprints.
    Returns None if neither is found.
    """
    custom_path = os.path.join(CUSTOM_BLUEPRINTS_DIR, blueprint_filename)
    if os.path.exists(custom_path):
        return custom_path
    stock_path = os.path.join(BLUEPRINTS_DIR, blueprint_filename)
    if os.path.exists(stock_path):
        return stock_path
    return None


def parse_blueprint_metadata(blueprint_filename: str) -> dict:
    """
    Parses the metadata block from a blueprint shell script.
    Checks custom blueprints first, then stock blueprints.

    LOT3 (M7): delegates to the shared metadata_parser so all parsers stay in
    sync (dequoted values, single implementation).
    """
    blueprint_path = _find_blueprint_path(blueprint_filename)
    if not blueprint_path:
        return {}
    return parse_metadata_file(blueprint_path)


def _parse_venv_from_launch_sh(launch_sh_path: str) -> dict:
    """
    Reads the AIKORE-METADATA block from an instance's launch.sh file.
    This is the most reliable source because it's the actual file the instance uses at runtime.
    Falls back to blueprint metadata if launch.sh doesn't exist or has no metadata.

    LOT3 (M7): delegates to the shared metadata_parser (dequoted values).
    """
    if not os.path.exists(launch_sh_path):
        return {}
    return parse_metadata_file(launch_sh_path)


def start_terminal_process(instance: models.Instance):
    """
    Spawns a shell process inside a pseudo-terminal (PTY) for a given instance.
    For satellite instances, it uses the parent's configuration directory.
    """
    # --- NEW: Logic to handle satellite vs. normal instances ---
    is_satellite = instance.parent_instance_id is not None
    
    if is_satellite:
        with SessionLocal() as db:
            from aikore.database import crud # Local import to avoid circular dependency
            parent_instance = crud.get_instance(db, instance_id=instance.parent_instance_id)
            if not parent_instance:
                raise Exception(f"Parent instance with ID {instance.parent_instance_id} not found for satellite instance {instance.name}.")
        
            print(f"[Terminal] Opening terminal for '{instance.name}' in context of parent '{parent_instance.name}'.")
            # A satellite uses its parent's directory for scripts and environment.
            effective_conf_dir = os.path.join(INSTANCES_DIR, parent_instance.name)
    else:
        # A normal instance uses its own directory.
        effective_conf_dir = os.path.join(INSTANCES_DIR, instance.name)

    # --- Read venv metadata from the instance's launch.sh (most reliable source) ---
    # The launch.sh is the actual file used at runtime. If it has metadata, it's definitive.
    # If not (e.g. no metadata block), fall back to the original blueprint.
    launch_sh_path = os.path.join(effective_conf_dir, "launch.sh")
    metadata = _parse_venv_from_launch_sh(launch_sh_path)
    
    # If launch.sh doesn't have metadata, fall back to the blueprint
    if not metadata.get('venv_type') or not metadata.get('venv_path'):
        fallback_metadata = parse_blueprint_metadata(instance.base_blueprint)
        # Merge: launch.sh takes priority, blueprint fills gaps
        for key in ('venv_type', 'venv_path'):
            if key not in metadata and key in fallback_metadata:
                metadata[key] = fallback_metadata[key]
    
    venv_type = metadata.get('venv_type')
    venv_path = metadata.get('venv_path')

    command = ['/bin/bash']
    env = os.environ.copy()
    
    # --- Apply GPU settings to terminal as well ---
    env["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
    if instance.gpu_ids and instance.gpu_ids.strip():
        env["CUDA_VISIBLE_DEVICES"] = instance.gpu_ids.strip()

    if venv_type and venv_path:
        full_venv_path = os.path.join(effective_conf_dir, venv_path)
        if venv_type == 'conda':
            # This launches a shell, sources the activate script for the specific env,
            # then 'exec' replaces that shell with a new one that inherits the environment.
            conda_activate_cmd = f"source /home/abc/miniconda3/bin/activate {full_venv_path} && exec /bin/bash"
            command =['/bin/bash', '-c', conda_activate_cmd]
        elif venv_type == 'python':
            # For standard python venv, --rcfile is the correct approach
            activate_script = os.path.join(full_venv_path, 'bin', 'activate')
            command =['/bin/bash', '--rcfile', activate_script]

    # Fork a process and connect the child's controlling terminal to a new PTY
    pid, master_fd = pty.fork()

    if pid == 0:  # Child process
        # Set the working directory for the new shell
        os.chdir(effective_conf_dir)
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

def monitor_instance_thread(instance_id: int, pid: int, port_to_monitor: int, internal_app_port: int, persistent_display: int | None, instance_slug: str, internal_web_port: int | None = None, popen=None):
    """
    Runs in a background thread to monitor an instance's web server.
    Updates the instance status and launches Firefox when ready.
    
    port_to_monitor: the port to poll for readiness (public-facing port).
    internal_app_port: same as port_to_monitor for normal mode; persistent_port for persistent mode.
    internal_web_port: the actual internal web app port (instance.port). Used by Firefox in persistent mode.
    popen: LOT3 (M2) optional Popen handle. When provided, liveness is driven by
        popen.poll() instead of psutil.pid_exists(pid): poll() reaps the child,
        so a zombie process can no longer keep this loop spinning forever and
        the instance stuck in 'starting'.
    """
    start_time = time.time()
    last_log_time = 0.0
    
    while True:
        # --- LOT3 (M2): zombie-safe liveness check -------------------------
        # poll() returns None while alive AND reaps the process once dead,
        # which psutil.pid_exists() alone never does for our own children.
        if popen is not None:
            if popen.poll() is not None:
                break
        elif not psutil.pid_exists(pid):
            break
        try:
            # Poll the internal application port to confirm it's truly ready
            response = requests.get(f"http://127.0.0.1:{internal_app_port}", timeout=2)
            
            if response.status_code < 500:
                print(f"[Monitor-{instance_id}] Instance is RUNNING on port {internal_app_port}.")
                with SessionLocal() as db:
                    # LOT3 (M2): promote starting->started ONLY. If the instance
                    # was stopped concurrently, its 'stopped' status must not be
                    # overwritten back to 'started' by this late transition.
                    updated_rows = (
                        db.query(models.Instance)
                        .filter(
                            models.Instance.id == instance_id,
                            models.Instance.status == "starting",
                        )
                        .update({"status": "started"})
                    )
                    db.commit()
                    if updated_rows == 0:
                        print(f"[Monitor-{instance_id}] Status no longer 'starting'; skipping 'started' update.")

                if persistent_display is not None:
                    print(f"[Monitor-{instance_id}] Persistent mode detected. Launching Firefox on display :{persistent_display}.")
                    firefox_profile_dir = f"/tmp/firefox-profiles/{instance_slug}"
                    os.makedirs(firefox_profile_dir, exist_ok=True)
                    
                    ff_env = os.environ.copy()
                    ff_env["DISPLAY"] = f":{persistent_display}"
                    
                    target_url = f'http://127.0.0.1:{internal_web_port or internal_app_port}'
                    print(f"[Monitor-{instance_id}] Pointing internal Firefox to {target_url}")
                    
                    # LOT3 (M4): own session + tracked handle. Previously this
                    # Popen inherited the API server's process group, so the
                    # instance killpg never reached it -> orphaned kiosk
                    # Firefox piling up on every stop/restart.
                    ff_process = subprocess.Popen(
                        ['/usr/bin/firefox', '--profile', firefox_profile_dir, '--kiosk', '-url', target_url],
                        env=ff_env,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        start_new_session=True,
                    )
                    firefox_processes[instance_id] = ff_process
                break
        
        except requests.exceptions.ConnectionError:
            # Process is alive but not yet listening on HTTP.
            # Don't mark as stalled — slow startup (model download, first boot)
            # is normal. We only mark stalled if the process dies.
            elapsed = time.time() - start_time
            if elapsed - last_log_time >= 60:
                print(f"[Monitor-{instance_id}] Still waiting for HTTP on port {internal_app_port} after {int(elapsed)}s (process alive)...")
                last_log_time = elapsed
            time.sleep(MONITOR_POLL_INTERVAL)
        
        except Exception as e:
            print(f"[Monitor-{instance_id}] An unexpected error occurred: {e}")
            time.sleep(MONITOR_POLL_INTERVAL)
    
    # Process died while still in "starting" status — mark as stalled
    print(f"[Monitor-{instance_id}] Process with PID {pid} no longer exists.")
    with SessionLocal() as db:
        # LOT3 (M1): atomic conditional UPDATE — the read-check-write above a
        # raced with a concurrent stop() (whose 'stopped' write could be
        # clobbered back to 'stalled') or with a late 'started' promotion.
        # Only a row still in 'starting' transitions to 'stalled', in ONE
        # statement. WIP print messages preserved.
        stalled_rows = (
            db.query(models.Instance)
            .filter(
                models.Instance.id == instance_id,
                models.Instance.status == "starting",
            )
            .update({"status": "stalled"})
        )
        db.commit()
        if stalled_rows:
            print(f"[Monitor-{instance_id}] Process died before becoming ready. Marked as STALLED.")

    # --- LOT3 (M2/M4): teardown after death, additive to the WIP logic above ---
    # 1. Make sure the child is reaped even on the psutil fallback path (no
    #    Popen handle -> nothing to wait on; poll path already reaped it).
    if popen is not None:
        try:
            popen.wait(timeout=5)
        except Exception:
            pass
    # 2. Drop the running_instances entry: a dead entry used to leak forever and
    #    make later starts fail with "already running".
    removed = running_instances.pop(instance_id, None)
    if removed is not None:
        print(f"[Monitor-{instance_id}] Removed dead process entry from running_instances.")
        # 3. Never leave an orphaned kiosk Firefox behind when the app dies.
        # LOT3 (M3): only when the entry was still present — an explicit
        # stop() removes the entry and runs its own terminate_firefox_for_
        # instance() teardown, so this exiting monitor must not duplicate it
        # (and must not touch a Firefox a fresh start just spawned).
        terminate_firefox_for_instance(instance_id)
    print(f"[Monitor-{instance_id}] Monitor thread exiting.")

# --- PROCESS MANAGEMENT INTERFACE ---

def rebuild_instance_env(db: Session, instance: models.Instance):
    """
    Triggers a rebuild of the instance's environment.
    If running, it stops and restarts it. If stopped, it simply prepares the rebuild for the next start.
    """
    print(f"[Manager] Rebuild requested for instance {instance.name} (ID: {instance.id}).")
    was_running = instance.status != "stopped"

    # 1. Stop the instance if it's running
    if was_running:
        print(f"[Manager] Stopping active instance {instance.name} before rebuild...")
        stop_instance_process(db, instance)
        db.refresh(instance)

    # 2. Create the trigger file
    instance_conf_dir = Path(INSTANCES_DIR) / instance.name
    rebuild_trigger_file = instance_conf_dir / ".rebuild-env"
    try:
        rebuild_trigger_file.touch()
        print(f"[Manager] Created rebuild trigger file: {rebuild_trigger_file}")
    except Exception as e:
        raise Exception(f"Failed to create rebuild trigger file for {instance.name}: {e}")

    # 3. Restart the instance ONLY if it was running before
    if was_running:
        print(f"[Manager] Restarting instance {instance.name} to trigger environment rebuild...")
        start_instance_process(db, instance)
    else:
        print(f"[Manager] Instance {instance.name} was stopped. Rebuild will occur on next manual start.")

def start_instance_process(db: Session, instance: models.Instance):
    """
    Starts the instance process and its associated monitoring thread.
    Handles both normal instances and 'satellite' instances linked to a parent.
    """
    if instance.id in running_instances:
        raise Exception(f"Instance {instance.id} is already running.")

    # --- SAFETY CHECK: Ensure ports are defined ---
    if instance.persistent_mode and (instance.persistent_port is None or instance.persistent_display is None):
        raise ValueError(f"Cannot start persistent instance '{instance.name}': persistent_port or persistent_display is missing. Please update configuration.")
    if not instance.persistent_mode and instance.port is None:
        raise ValueError(f"Cannot start instance '{instance.name}': port is missing. Please update configuration.")


    # --- NEW: Logic to handle satellite vs. normal instances ---
    is_satellite = instance.parent_instance_id is not None
    
    # The directory for logs and where the process will run from.
    log_and_cwd_dir = os.path.join(INSTANCES_DIR, instance.name)
    
    if is_satellite:
        from aikore.database import crud  # Local import to avoid circular dependency
        parent_instance = crud.get_instance(db, instance_id=instance.parent_instance_id)
        if not parent_instance:
            raise Exception(f"Parent instance with ID {instance.parent_instance_id} not found for satellite instance {instance.name}.")
        
        print(f"[Manager] Starting '{instance.name}' as a satellite of '{parent_instance.name}'.")
        # A satellite uses its parent's directory for scripts and environment.
        effective_conf_dir = os.path.join(INSTANCES_DIR, parent_instance.name)
        effective_instance_name = parent_instance.name
    else:
        print(f"[Manager] Starting '{instance.name}' as a normal instance.")
        # A normal instance uses its own directory for everything.
        effective_conf_dir = log_and_cwd_dir
        effective_instance_name = instance.name

    # --- Filesystem and Path Setup ---
    dest_script_path = os.path.join(effective_conf_dir, "launch.sh")
    
    # Use the custom output_path if available, otherwise fall back to the instance name.
    output_folder_name = instance.output_path or instance.name
    instance_output_dir = os.path.join(OUTPUTS_DIR, output_folder_name)
    instance_slug = _slugify(instance.name)

    os.makedirs(log_and_cwd_dir, exist_ok=True)
    os.makedirs(instance_output_dir, exist_ok=True)
    os.makedirs(NGINX_SITES_AVAILABLE, exist_ok=True)

    global_tmp_dir = "/config/tmp"
    os.makedirs(global_tmp_dir, exist_ok=True)
    
    # --- NEW: Write aikore_vars.env for custom versions ---
    custom_vars_path = os.path.join(effective_conf_dir, "aikore_vars.env")
    try:
        with open(custom_vars_path, "w") as vars_file:
            vars_file.write("# Auto-generated by AiKore Custom Versions\n")
            if instance.python_version:
                vars_file.write(f'export PYTHON_VERSION="{instance.python_version}"\n')
            if instance.cuda_version:
                vars_file.write(f'export CUDA_VERSION="{instance.cuda_version}"\n')
                # Map CUDA version to PyTorch Index URL format (e.g., 12.1 -> cu121)
                cu_suffix = instance.cuda_version.replace(".", "")
                vars_file.write(f'export PYTORCH_INDEX_URL="https://download.pytorch.org/whl/cu{cu_suffix}"\n')
            if instance.torch_version:
                vars_file.write(f'export TORCH_VERSION="{instance.torch_version}"\n')
        print(f"[Manager] Wrote custom environment variables to {custom_vars_path}")
    except Exception as e:
        print(f"[Manager-Error] Could not write aikore_vars.env: {e}")

    # For normal instances, ensure the launch script exists, copying from blueprint if needed.
    # For satellites, we assume the parent's script is already there.
    if not is_satellite:
        if not os.path.exists(dest_script_path):
            print(f"[Manager] launch.sh not found for '{instance.name}'. Creating from blueprint '{instance.base_blueprint}'.")
            custom_blueprint_path = os.path.join(CUSTOM_BLUEPRINTS_DIR, instance.base_blueprint)
            stock_blueprint_path = os.path.join(BLUEPRINTS_DIR, instance.base_blueprint)
            
            source_script_path = custom_blueprint_path if os.path.exists(custom_blueprint_path) else stock_blueprint_path

            try:
                shutil.copy(source_script_path, dest_script_path)
            except FileNotFoundError:
                raise Exception(f"Blueprint file not found at {source_script_path}")
        else:
            print(f"[Manager] Existing launch.sh found for '{instance.name}'. Using it directly.")

    if not os.path.exists(dest_script_path):
        raise FileNotFoundError(f"Launch script not found for instance '{instance.name}' at expected path '{dest_script_path}'. The parent instance may be missing its script.")

    os.chmod(dest_script_path, os.stat(dest_script_path).st_mode | stat.S_IXUSR)

    # --- Environment Setup ---
    env = os.environ.copy()
    env["TMPDIR"] = global_tmp_dir
    
    # --- GPU Configuration ---
    # Ensure PCI_BUS_ID ordering to prevent mismatches between expected and actual GPU indices
    env["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
    
    if instance.gpu_ids and instance.gpu_ids.strip():
        env["CUDA_VISIBLE_DEVICES"] = instance.gpu_ids.strip()
        print(f"[Manager] Instance '{instance.name}': GPU assignment set to '{env['CUDA_VISIBLE_DEVICES']}'")
    else:
        # If no GPUs are selected, we assume the user wants standard behavior (usually All GPUs or CPU only depending on app)
        # Explicitly logging this condition for debugging.
        print(f"[Manager] Instance '{instance.name}': No specific GPUs selected (gpu_ids is empty). Inheriting default visibility (usually ALL).")
    
    # CRITICAL: These env vars must point to the correct context.
    # The running script needs to know the name/dirs of the *effective* instance (the parent for satellites).
    # NOTE (LOT3 H1): WEBUI_PORT is set LATER, after _ensure_runtime_ports_free().
    env["INSTANCE_NAME"] = effective_instance_name
    env["INSTANCE_CONF_DIR"] = effective_conf_dir
    env["INSTANCE_OUTPUT_DIR"] = instance_output_dir # Output dir is unique to the child
    env["BLUEPRINT_ID"] = os.path.splitext(instance.base_blueprint)[0]
    env["SUBFOLDER"] = f"/instance/{instance_slug}/"
    
    # Inject custom versions directly into env just in case scripts read env vars instead of sourcing the file
    if instance.python_version: env["PYTHON_VERSION"] = instance.python_version
    if instance.cuda_version: env["CUDA_VERSION"] = instance.cuda_version
    if instance.torch_version: env["TORCH_VERSION"] = instance.torch_version
    
    # --- LOT3 (M1): verify ports/display are REALLY free right before spawn,
    # reallocating (and persisting) if something grabbed them since creation.
    _ensure_runtime_ports_free(db, instance)

    # --- LOT3 (H1): capture WEBUI_PORT + monitor/app ports ONLY AFTER
    # _ensure_runtime_ports_free(). Capturing them before (previous order)
    # read pre-realloc stale values: the app could be spawned on a busy old
    # port while the monitor polled the newly allocated one. The persistent
    # block below (which overrides both from persistent_port) already runs
    # after, so both modes now read final values.
    env["WEBUI_PORT"] = str(instance.port)
    port_to_monitor = instance.port
    internal_app_port = instance.port

    # --- Command Execution ---
    if instance.persistent_mode:
        kasm_launcher_path = os.path.join(SCRIPTS_DIR, "kasm_launcher.sh")
        main_cmd =['bash', kasm_launcher_path, instance.name, str(instance.persistent_port), dest_script_path]
        # In persistent mode, the user-facing interface is on persistent_port.
        # Monitor that port to ensure the VNC/Kasm interface is actually ready
        # before marking the instance as "started".
        port_to_monitor = instance.persistent_port
        internal_app_port = instance.persistent_port
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

    output_log_path = os.path.join(log_and_cwd_dir, "output.log")
    with open(output_log_path, 'w') as output_log:
        main_process = subprocess.Popen(main_cmd, cwd=log_and_cwd_dir, env=env, stdout=output_log, stderr=output_log, preexec_fn=os.setsid)
    
    instance.pid = main_process.pid
    instance.status = "starting"
    db.commit()

    monitor = threading.Thread(
        target=monitor_instance_thread,
        args=(instance.id, instance.pid, port_to_monitor, internal_app_port, instance.persistent_display, instance_slug, instance.port),
        kwargs={"popen": main_process},  # LOT3 (M2): zombie-safe liveness via poll()
        daemon=True
    )
    monitor.start()

    running_instances[instance.id] = {"process": main_process, "monitor_thread": monitor}
    print(f"[Manager] Started instance '{instance.name}' (PID: {instance.pid}) and its monitor thread.")


def stop_instance_process(db: Session, instance: models.Instance):
    """
    Stops a running instance process and its monitor thread.

    LOT3 (M3): the entry removal from running_instances, the Firefox teardown
    and the file cleanup now run in a `finally` block so they execute no matter
    how the kill sequence fails (a ProcessLookupError on the SIGKILL escalation
    used to raise out of this function, leaving the instance locked with a
    stale entry and an HTTP 500).
    """
    instance_id = instance.id
    try:
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
                # LOT3 (M3): the process may have died between the SIGTERM and
                # this escalation; ProcessLookupError must not escape.
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                except ProcessLookupError:
                    print(f"[Manager] Process group {process.pid} already gone before SIGKILL.")
                try:
                    process.wait(timeout=5)
                except Exception:
                    pass
            except Exception as e:
                print(f"[Manager] Error stopping process: {e}")
    finally:
        # LOT3 (M3): unconditional teardown — previously `del
        # running_instances[instance_id]` and _cleanup_instance_files were
        # skipped entirely when the kill sequence raised.
        running_instances.pop(instance_id, None)
        # LOT3 (M4): kill the tracked kiosk Firefox, if any.
        terminate_firefox_for_instance(instance_id)
        try:
            _cleanup_instance_files(_slugify(instance.name))
        except Exception as e:
            print(f"[Manager-Error] File cleanup failed for '{instance.name}': {e}")
    
    # LOT3 (B1): this commit used to sit OUTSIDE the try/finally — a DB error
    # here (locked file, full volume) meant the process was killed but the
    # instance stayed 'started' forever, with no trace. Best-effort persist,
    # loud ERROR on failure.
    try:
        instance.status = "stopped"
        instance.pid = None
        db.commit()
    except Exception as commit_err:
        print(
            f"[Manager-ERROR] Failed to persist 'stopped' status for instance "
            f"'{instance.name}' (id={instance_id}) after teardown: "
            f"{type(commit_err).__name__}: {commit_err}",
            file=sys.stderr,
        )
    print(f"[Manager] Instance {instance.name} stopped and cleaned up.")


def _get_instance_venv_metadata(instance: models.Instance, instance_conf_dir: str) -> dict:
    """
    Resolves venv metadata for an instance by first checking its launch.sh
    (the actual runtime file), then falling back to the original blueprint.
    This is the same pattern used by start_terminal_process().
    """
    launch_sh_path = os.path.join(instance_conf_dir, "launch.sh")
    metadata = _parse_venv_from_launch_sh(launch_sh_path)

    # If launch.sh doesn't have metadata, fall back to the blueprint
    if not metadata.get('venv_type') or not metadata.get('venv_path'):
        fallback_metadata = parse_blueprint_metadata(instance.base_blueprint)
        for key in ('venv_type', 'venv_path'):
            if key not in metadata and key in fallback_metadata:
                metadata[key] = fallback_metadata[key]

    return metadata


def run_version_check(instance: models.Instance) -> str:
    """
    Runs the version check script within the instance's environment.
    """
    instance_conf_dir = os.path.join(INSTANCES_DIR, instance.name)
    metadata = _get_instance_venv_metadata(instance, instance_conf_dir)
    
    venv_type = metadata.get('venv_type')
    venv_path = metadata.get('venv_path')
    
    script_path = os.path.join(SCRIPTS_DIR, "version_check.sh")
    command =['/bin/bash', script_path] # Default command

    if venv_type and venv_path:
        full_venv_path = os.path.join(instance_conf_dir, venv_path)
        if venv_type == 'conda' and os.path.isdir(full_venv_path):
            # Command to activate conda env and then run the script
            activate_and_run_cmd = f"source /home/abc/miniconda3/bin/activate {full_venv_path} && bash {script_path}"
            command =['/bin/bash', '-c', activate_and_run_cmd]
        elif venv_type == 'python' and os.path.exists(os.path.join(full_venv_path, 'bin', 'activate')):
            # For standard python venv, we can source it in a subshell
            activate_and_run_cmd = f"source {os.path.join(full_venv_path, 'bin', 'activate')} && bash {script_path}"
            command = ['/bin/bash', '-c', activate_and_run_cmd]

    try:
        result = subprocess.run(
            command,
            cwd=instance_conf_dir,
            capture_output=True,
            text=True,
            timeout=120 # 120-second timeout for safety
        )
        if result.returncode != 0:
            # Combine stdout and stderr for better error diagnosis
            error_output = f"Error running version check:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
            return error_output
        return result.stdout
    except subprocess.TimeoutExpired:
        return "Error: The version check script timed out."
    except Exception as e:
        return f"An unexpected error occurred while running version check: {e}"

def run_command_in_instance_venv(instance: models.Instance, command_to_run: str) -> (bool, str):
    """
    Runs a given shell command within the instance's configured virtual environment.
    Returns a tuple of (success: bool, output: str).
    """
    instance_conf_dir = os.path.join(INSTANCES_DIR, instance.name)
    metadata = _get_instance_venv_metadata(instance, instance_conf_dir)
    
    venv_type = metadata.get('venv_type')
    venv_path = metadata.get('venv_path')
    
    command = ['/bin/bash', '-c', command_to_run] # Default command if no venv

    if venv_type and venv_path:
        full_venv_path = os.path.join(instance_conf_dir, venv_path)
        if venv_type == 'conda' and os.path.isdir(full_venv_path):
            activate_and_run_cmd = f"source /home/abc/miniconda3/bin/activate {full_venv_path} && {command_to_run}"
            command =['/bin/bash', '-c', activate_and_run_cmd]
        elif venv_type == 'python' and os.path.exists(os.path.join(full_venv_path, 'bin', 'activate')):
            activate_and_run_cmd = f"source {os.path.join(full_venv_path, 'bin', 'activate')} && {command_to_run}"
            command =['/bin/bash', '-c', activate_and_run_cmd]

    try:
        print(f"[Manager] Running command in venv for '{instance.name}': {command_to_run}")
        result = subprocess.run(
            command,
            cwd=instance_conf_dir,
            capture_output=True,
            text=True,
            timeout=300 # 5-minute timeout for pip installs
        )
        if result.returncode != 0:
            error_output = f"Error running command:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
            print(f"[Manager] Command failed for '{instance.name}': {error_output}")
            return False, error_output
        
        print(f"[Manager] Command succeeded for '{instance.name}'.")
        return True, result.stdout
    except subprocess.TimeoutExpired:
        error_msg = "Error: The command timed out."
        print(f"[Manager] Command timed out for '{instance.name}'.")
        return False, error_msg
    except Exception as e:
        error_msg = f"An unexpected error occurred: {e}"
        print(f"[Manager] Command failed for '{instance.name}' with exception: {e}")
        return False, error_msg