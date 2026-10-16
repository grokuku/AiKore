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

# C1: grace periods for the group-wide stop escalation. Escalation MUST be
# driven by the SURVIVAL OF THE PROCESS GROUP, never by the head process: a
# blueprint's head (e.g. `exec python setup.py`) installs no SIGTERM handler,
# so it dies in milliseconds while slow/failing descendants keep their RAM
# pinned. Modelled on Strata's own tools/strata_mcp.py (SIGTERM ~20s -> SIGKILL
# ~5s).
INSTANCE_SIGTERM_GRACE_SECONDS = 25
INSTANCE_SIGKILL_GRACE_SECONDS = 5
INSTANCE_GROUP_POLL_SECONDS = 0.25

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

def _append_instance_log(instance_name: str, message: str):
    """C7: append a manager event to the instance's own log file.

    The log surfaced by ``GET /api/instances/<id>/logs`` is
    ``INSTANCES_DIR/<name>/output.log``. Port reallocations and incomplete
    stops used to be plain ``print()`` calls only visible in `docker logs`;
    this makes them visible in the UI too. Best-effort: a logging failure must
    never abort the operation it is reporting.
    """
    try:
        conf_dir = os.path.join(INSTANCES_DIR, instance_name)
        os.makedirs(conf_dir, exist_ok=True)
        log_path = os.path.join(conf_dir, "output.log")
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(log_path, "a", encoding="utf-8", errors="replace") as f:
            f.write(f"[AiKore {stamp}] {message}\n")
    except Exception as e:  # noqa: BLE001 - logging must never break the caller
        print(f"[Manager-Error] Could not write to instance log for '{instance_name}': {e}")


def _port_range_str() -> str:
    return os.environ.get("AIKORE_INSTANCE_PORT_RANGE", "19001-19020")


def _get_instance_port_range():
    """Parse AIKORE_INSTANCE_PORT_RANGE into (start, end) or None if invalid."""
    port_range_str = _port_range_str()
    try:
        start_port, end_port = (int(x) for x in port_range_str.split('-', 1))
    except (ValueError, TypeError):
        return None
    if start_port > end_port:
        return None
    return start_port, end_port


def _find_free_port_in_range(start_port: int, end_port: int, other_used=(), exclude=()):
    """C5: return the smallest free TCP port STRICTLY inside [start, end].

    Deliberately does NOT use ``_find_free_port()`` (which binds to port 0 and
    therefore returns an ephemeral OS port, 32768-60999). That port is never
    inside the published ``AIKORE_INSTANCE_PORT_RANGE`` that docker-compose
    exposes, so persisting it silently breaks the LAN-accessible URL.

    Returns None when the range is saturated (every candidate is used or
    already bound).
    """
    excluded = set(exclude) | set(other_used)
    for candidate in range(start_port, end_port + 1):
        if candidate in excluded:
            continue
        if _can_bind_port(candidate):
            return candidate
    return None


def _ensure_runtime_ports_free(db: Session, instance: models.Instance, max_attempts: int = 5) -> list:
    """LOT3 (M1): last-mile port/display verification right before the Popen.

    Ports allocated at creation time can be stale by start time (another
    service grabbed the port, leftover X lock, concurrent creation that raced
    past the API-level checks...). This helper:
      - normal mode: re-binds instance.port; if taken, or if it drifted OUTSIDE
        AIKORE_INSTANCE_PORT_RANGE, reallocates a free port INSIDE the range;
      - persistent mode: re-binds instance.persistent_port; if taken/out of
        range, picks the next free port of AIKORE_INSTANCE_PORT_RANGE; bumps
        the display if its lock/socket appeared meanwhile.
    Persists any reallocation to the DB. Raises RuntimeError when nothing
    usable can be found. Returns a list of human-readable events (C7) so the
    caller can surface them in the instance log AFTER the spawn (the log file
    is truncated at spawn time).

    C5: the normal branch is now symmetric with the persistent one — it NEVER
    falls back to an out-of-range ephemeral port.
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
    events = []
    port_range = _get_instance_port_range()
    port_range_str = _port_range_str()
    start_port, end_port = port_range if port_range else (None, None)

    def _record(message: str):
        print(f"[Manager] {message}")
        events.append(message)

    if instance.persistent_mode:
        public_port = instance.persistent_port
        out_of_range = (
            start_port is not None
            and public_port is not None
            and not (start_port <= public_port <= end_port)
        )
        if public_port is not None and (
            out_of_range or not _can_bind_port(public_port) or public_port in other_used
        ):
            replacement = None
            if start_port is not None:
                replacement = _find_free_port_in_range(
                    start_port, end_port, other_used, exclude=(public_port,)
                )
            if replacement is None:
                raise RuntimeError(
                    f"Cannot start persistent instance '{instance.name}': port "
                    f"{public_port} is unusable and no free port was found in the "
                    f"published range '{port_range_str}' (AIKORE_INSTANCE_PORT_RANGE)."
                )
            _record(
                f"Persistent port {public_port} unusable at start time "
                f"(out_of_range={out_of_range}); reallocated to {replacement}."
            )
            instance.persistent_port = replacement
            changed = True

        if instance.persistent_display is not None and _display_in_use(instance.persistent_display):
            replacement_display = _find_free_display()
            _record(
                f"Display :{instance.persistent_display} busy at start time; "
                f"reallocated to :{replacement_display}."
            )
            instance.persistent_display = replacement_display
            changed = True
    else:
        app_port = instance.port
        out_of_range = (
            start_port is not None
            and app_port is not None
            and not (start_port <= app_port <= end_port)
        )
        unusable = (
            app_port is None
            or out_of_range
            or app_port in other_used
            or not _can_bind_port(app_port)
        )
        if unusable:
            replacement = None
            if start_port is not None:
                replacement = _find_free_port_in_range(
                    start_port, end_port, other_used, exclude=(app_port,)
                )
            if replacement is None:
                raise RuntimeError(
                    f"Cannot start instance '{instance.name}': port {app_port} is "
                    f"unusable and no free port is available in the published range "
                    f"'{port_range_str}' (AIKORE_INSTANCE_PORT_RANGE). Refusing to "
                    f"fall back to an out-of-range ephemeral port."
                )
            _record(
                f"Application port {app_port} unusable at start time "
                f"(out_of_range={out_of_range}, busy={app_port is not None and app_port in other_used}); "
                f"reallocated to {replacement} within range '{port_range_str}'."
            )
            instance.port = replacement
            changed = True

    if changed:
        db.commit()
        db.refresh(instance)

    return events

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
    # FIX: une fois l'instance prête on CONTINUE à boucler (pas de break) :
    # l'entrée running_instances et le kiosque Firefox survivent ; on ne
    # teardown QUE lorsque le process meurt réellement (popen.poll() != None).
    app_ready = False

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
            # Poll the internal application port ONLY until the app is ready.
            if not app_ready:
                response = requests.get(f"http://127.0.0.1:{internal_app_port}", timeout=2)

                if response.status_code < 500:
                    app_ready = True
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
                # FIX: ne PAS break ici. On continue la boucle: l'entrée
                # running_instances et le kiosque Firefox restent vivants, et
                # la mort réelle du process (haut de boucle) provoquera le
                # teardown uniquement à ce moment-là.
                continue
            time.sleep(MONITOR_POLL_INTERVAL)

        except requests.exceptions.ConnectionError:
            # Process is alive but not yet listening on HTTP.
            # Don't mark as stalled — slow startup (model download, first boot)
            # is normal. We only mark stalled if the process dies.
            if not app_ready:
                elapsed = time.time() - start_time
                if elapsed - last_log_time >= 60:
                    print(f"[Monitor-{instance_id}] Still waiting for HTTP on port {internal_app_port} after {int(elapsed)}s (process alive)...")
                    last_log_time = elapsed
            time.sleep(MONITOR_POLL_INTERVAL)

        except Exception as e:
            if not app_ready:
                print(f"[Monitor-{instance_id}] An unexpected error occurred: {e}")
            time.sleep(MONITOR_POLL_INTERVAL)

    # Le process est réellement mort (ou n'est jamais devenu prêt).
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
    # C7: any reallocation is returned as an event and appended to the
    # instance log after the spawn (the log file is truncated by the Popen).
    startup_events = _ensure_runtime_ports_free(db, instance)

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
    # C2: persist the process-group id so a surviving group can still be
    # cleaned up after AiKore itself restarts (running_instances is in-memory
    # and lost on restart, and the bare PID may already be reaped). The child
    # was started with os.setsid(), so it is its own group leader (pgid == pid);
    # os.getpgid() confirms it and falls back to the pid on the (unlikely)
    # race where the child already exited.
    try:
        instance.pgid = os.getpgid(main_process.pid)
    except OSError:
        instance.pgid = main_process.pid
    instance.status = "starting"
    db.commit()

    # C7: surface the pre-spawn events (port reallocations) in the instance log.
    for event in startup_events:
        _append_instance_log(instance.name, event)

    monitor = threading.Thread(
        target=monitor_instance_thread,
        args=(instance.id, instance.pid, port_to_monitor, internal_app_port, instance.persistent_display, instance_slug, instance.port),
        kwargs={"popen": main_process},  # LOT3 (M2): zombie-safe liveness via poll()
        daemon=True
    )
    monitor.start()

    running_instances[instance.id] = {"process": main_process, "monitor_thread": monitor}
    print(f"[Manager] Started instance '{instance.name}' (PID: {instance.pid}) and its monitor thread.")


# --- PROCESS-GROUP TERMINATION (C1/C2/C3) ---

def _reap_head(process):
    """Non-blocking reap of the group HEAD process, if we hold a Popen handle.

    ``os.killpg(pgid, 0)`` reports a group as alive while its HEAD is still a
    zombie (the entry lingers in the process table until reaped). Calling
    ``poll()`` reaps our own child, so a dead head no longer keeps the group
    "alive" from the escalation's point of view.
    """
    if process is None:
        return
    try:
        process.poll()
    except Exception:  # noqa: BLE001 - reaping is best-effort
        pass


def _process_group_exists(pgid: int) -> bool:
    """True while at least one process still belongs to ``pgid``.

    ``os.killpg(pgid, 0)``: no exception => the group exists; ProcessLookupError
    (ESRCH) => empty/gone; PermissionError (EPERM) => a process exists but we
    may not signal it, which we treat as alive.
    """
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True


def _terminate_process_group(
    pgid: int,
    label: str,
    process=None,
    term_grace: float | None = None,
    kill_grace: float | None = None,
    poll_interval: float | None = None,
) -> bool:
    """C1: SIGTERM the whole GROUP -> wait -> SIGKILL if members survive.

    The escalation is driven by the SURVIVAL OF THE GROUP, not of the head
    process. Returns True when the group is gone (or was already gone), False
    when members are still alive after the SIGKILL window. Never raises for a
    group that disappeared mid-sequence.
    """
    if term_grace is None:
        term_grace = INSTANCE_SIGTERM_GRACE_SECONDS
    if kill_grace is None:
        kill_grace = INSTANCE_SIGKILL_GRACE_SECONDS
    if poll_interval is None:
        poll_interval = INSTANCE_GROUP_POLL_SECONDS

    def _wait_group_dead(grace: float) -> bool:
        deadline = time.time() + grace
        while True:
            _reap_head(process)
            if not _process_group_exists(pgid):
                return True
            if time.time() >= deadline:
                return False
            time.sleep(poll_interval)

    # 1. SIGTERM to the whole group.
    try:
        os.killpg(pgid, signal.SIGTERM)
        print(f"[Manager] Sent SIGTERM to the process group of {label} (pgid={pgid}).")
    except ProcessLookupError:
        print(f"[Manager] Process group of {label} (pgid={pgid}) already gone before SIGTERM.")
        return True
    except PermissionError as e:
        print(f"[Manager-ERROR] Not permitted to SIGTERM process group {pgid} ({label}): {e}")
        return False
    except OSError as e:
        print(f"[Manager-ERROR] Failed to SIGTERM process group {pgid} ({label}): {e}")
        return False

    # 2. Wait for the GROUP to die (the head dying instantly is NOT enough).
    if _wait_group_dead(term_grace):
        print(f"[Manager] Process group of {label} (pgid={pgid}) exited gracefully.")
        return True

    # 3. Escalate: SIGKILL the surviving members.
    print(
        f"[Manager] Process group of {label} (pgid={pgid}) survived {term_grace}s "
        f"after SIGTERM; sending SIGKILL."
    )
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        print(f"[Manager] Process group {pgid} ({label}) gone just before SIGKILL.")
        return True
    except PermissionError as e:
        print(f"[Manager-ERROR] Not permitted to SIGKILL process group {pgid} ({label}): {e}")
        return False
    except OSError as e:
        print(f"[Manager-ERROR] Failed to SIGKILL process group {pgid} ({label}): {e}")
        return False

    # 4. Wait again after the SIGKILL.
    if _wait_group_dead(kill_grace):
        print(f"[Manager] Process group of {label} (pgid={pgid}) terminated by SIGKILL.")
        return True

    print(
        f"[Manager-ERROR] Process group of {label} (pgid={pgid}) is STILL alive "
        f"after SIGKILL ({kill_grace}s). Memory may still be held."
    )
    return False


def _read_proc_cmdline(pid: int) -> str:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            return f.read().decode("utf-8", "replace").replace("\x00", " ")
    except OSError:
        return ""


def _read_proc_cwd(pid: int) -> str:
    try:
        return os.readlink(f"/proc/{pid}/cwd")
    except OSError:
        return ""


def _read_proc_uid(pid: int) -> int | None:
    try:
        return os.stat(f"/proc/{pid}").st_uid
    except OSError:
        return None


def _list_group_members(pgid: int) -> list:
    """PIDs whose process-group id equals ``pgid`` (from /proc/<pid>/stat)."""
    members = []
    try:
        entries = [n for n in os.listdir("/proc") if n.isdigit()]
    except OSError:
        return members
    for n in entries:
        try:
            with open(f"/proc/{n}/stat", "rb") as f:
                data = f.read().decode("utf-8", "replace")
        except OSError:
            continue
        # /proc/<pid>/stat: "pid (comm) state ppid pgrp session ...". comm can
        # contain spaces and parentheses, so parse after the LAST ')'.
        try:
            tail = data[data.rindex(")") + 2:].split()
            pgrp = int(tail[2])
        except (ValueError, IndexError):
            continue
        if pgrp == pgid:
            members.append(int(n))
    return members


def _group_belongs_to_instance(pgid: int, instance: models.Instance) -> bool:
    """C2 anti-PID-recycled guard: never kill a group blindly.

    A persisted pgid may have been recycled by an unrelated process after
    AiKore restarted. Only consider it ours when a member's cmdline or cwd
    references the instance (name, output path or its instances directory).
    Members belonging to another uid are ignored. Returns False when nothing
    can be tied to the instance, in which case the caller must NOT kill.
    """
    if pgid == os.getpid():
        return False
    try:
        my_uid = os.getuid()
    except AttributeError:
        my_uid = None

    markers = [m for m in (
        instance.name,
        getattr(instance, "output_path", None),
        _slugify(instance.name),
        os.path.join(INSTANCES_DIR, instance.name),
    ) if m]

    members = _list_group_members(pgid)
    if not members:
        # The head may have been reaped already; fall back to the leader itself.
        members = [pgid] if os.path.exists(f"/proc/{pgid}") else []
    if not members:
        return False

    for pid in members:
        uid = _read_proc_uid(pid)
        if uid is None:
            continue
        if my_uid is not None and uid != my_uid:
            continue
        blob = f"{_read_proc_cmdline(pid)} {_read_proc_cwd(pid)}"
        if any(marker in blob for marker in markers):
            return True
    return False


def _safe_terminate_persisted_group(instance: models.Instance):
    """C2/C3: kill a group recorded in the DB, guarded against PID reuse.

    Returns ``(dead, pgid)`` where ``dead`` is True only when the group is
    confirmed gone (or there was nothing to kill) and ``pgid`` is the group
    that was targeted (or None when no candidate existed).
    """
    pgid = getattr(instance, "pgid", None) or getattr(instance, "pid", None)
    if not pgid:
        return True, None
    if not _group_belongs_to_instance(pgid, instance):
        print(
            f"[Manager-WARNING] Refusing to kill process group {pgid} for instance "
            f"'{instance.name}': it no longer looks like this instance's group "
            f"(PID may have been recycled). Nothing killed."
        )
        return True, None
    label = f"instance '{instance.name}' (persisted pgid)"
    dead = _terminate_process_group(pgid, label)
    return dead, pgid


def cleanup_surviving_instance_groups(db: Session) -> int:
    """C2: on AiKore startup, terminate instance groups left over from a
    previous run (running_instances is in-memory and lost on restart).

    Must be called BEFORE the status rows are reset to 'stopped'. Each group
    is verified against the instance (anti-PID-recycled guard) and killed via
    the group-wide escalation. Returns the number of instances for which a
    surviving group was found. Never raises for a single bad row.
    """
    handled = 0
    try:
        instances = db.query(models.Instance).all()
    except Exception as e:  # noqa: BLE001 - startup must not crash on this
        print(f"[Manager-ERROR] Could not query instances for group cleanup: {e}")
        return 0

    for instance in instances:
        if instance.id in running_instances:
            continue
        pgid = getattr(instance, "pgid", None)
        pid = getattr(instance, "pid", None)
        if not pgid and not pid:
            continue
        handled += 1
        try:
            dead, targeted = _safe_terminate_persisted_group(instance)
            if targeted is not None:
                message = (
                    f"Startup cleanup: terminated surviving process group {targeted} "
                    f"left by the previous AiKore run (group_dead={dead})."
                )
            else:
                message = (
                    f"Startup cleanup: no surviving, verifiable process group for "
                    f"persisted pgid/pid {pgid or pid} (already gone or recycled)."
                )
            _append_instance_log(instance.name, message)
        except Exception as e:  # noqa: BLE001
            print(f"[Manager-ERROR] Startup cleanup failed for instance '{instance.name}': {e}")
    return handled


def stop_instance_process(db: Session, instance: models.Instance):
    """Stops a running instance process and its monitor thread.

    C1: the escalation (SIGTERM -> wait -> SIGKILL) is driven by the death of
    the whole process GROUP, not of the head process — see
    _terminate_process_group().
    C3: when the instance is not tracked in memory, the persisted pgid/pid is
    used (with an anti-PID-recycled guard) and a loud WARNING is emitted.
    C4: status is flipped to 'stopped' and the NGINX conf removed ONLY once the
    group is confirmed dead; otherwise the instance is left in a coherent
    'error' state (never a fake 'stopped') so the RAM leak stays visible.

    LOT3 (M3): the entry removal from running_instances and the Firefox
    teardown run in a `finally` block so they execute no matter how the kill
    sequence fails.
    """
    instance_id = instance.id
    group_dead = True

    try:
        if instance_id not in running_instances:
            # C3: not tracked in memory (e.g. after an AiKore restart). Do not
            # stay silent: attempt a persisted-state cleanup + WARNING.
            print(
                f"[Manager-WARNING] Stop requested but instance {instance_id} "
                f"('{instance.name}') is not in running_instances. "
                f"Attempting cleanup from persisted pgid/pid."
            )
            _append_instance_log(
                instance.name,
                "Stop requested while the instance was not tracked in memory "
                "(AiKore may have restarted); attempting persisted-group cleanup.",
            )
            group_dead, _targeted = _safe_terminate_persisted_group(instance)
        else:
            process_info = running_instances[instance_id]
            process = process_info["process"]
            try:
                pgid = process_info.get("pgid") or os.getpgid(process.pid)
            except OSError:
                pgid = process_info.get("pgid") or getattr(instance, "pgid", None) or process.pid
            process_info["pgid"] = pgid
            print(f"[Manager] Stopping process group for PID {process.pid} (pgid={pgid})...")
            group_dead = _terminate_process_group(
                pgid, f"instance '{instance.name}'", process=process
            )
    finally:
        # LOT3 (M3): unconditional teardown of the in-memory state.
        running_instances.pop(instance_id, None)
        # LOT3 (M4): kill the tracked kiosk Firefox, if any.
        terminate_firefox_for_instance(instance_id)
        # C4: the NGINX conf / Firefox profile are removed ONLY once the group
        # is really dead — otherwise the proxy would dangle on a live process.
        if group_dead:
            try:
                _cleanup_instance_files(_slugify(instance.name))
            except Exception as e:
                print(f"[Manager-Error] File cleanup failed for '{instance.name}': {e}")
        else:
            print(
                f"[Manager-ERROR] Keeping NGINX config / files for '{instance.name}': "
                f"its process group is still alive after SIGKILL."
            )
            _append_instance_log(
                instance.name,
                "Stop incomplete: the process group is still alive after SIGTERM+SIGKILL. "
                "NGINX config kept and status set to 'error' (memory may still be held).",
            )

    # LOT3 (B1): best-effort persist, loud ERROR on failure.
    try:
        if group_dead:
            instance.status = "stopped"
            instance.pid = None
            instance.pgid = None
        else:
            # C4: do NOT lie with a fake 'stopped'. 'error' is an existing
            # frontend status (CSS class status-error) and lets a later Stop
            # be retried (the stop endpoint only refuses when already
            # 'stopped'). Keep pid/pgid so the group can be retried or cleaned
            # up on the next AiKore startup.
            instance.status = "error"
        db.commit()
    except Exception as commit_err:
        print(
            f"[Manager-ERROR] Failed to persist stop status for instance "
            f"'{instance.name}' (id={instance_id}) after teardown: "
            f"{type(commit_err).__name__}: {commit_err}",
            file=sys.stderr,
        )
    if group_dead:
        print(f"[Manager] Instance {instance.name} stopped and cleaned up.")
    else:
        print(f"[Manager] Instance {instance.name} stop INCOMPLETE (process group still alive).")


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