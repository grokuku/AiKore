# AiKore: Technical Project Roadmap & Audit Report

## 0. META: Interaction Rules & Protocols

### Purpose
This file is the **single source of truth** for any LLM working on AiKore. It must provide a complete architectural understanding without reading every source file. It bridges raw code structure and high-level business logic.

### Protocol for Updates
When a major change is made, update this file:
1. **Structural Changes**: Update Section 2 (File Tree).
2. **Schema Evolutions**: Update Section 5 (Database Schema).
3. **Logic Shifts**: Update Section 3 (Key Concepts).
4. **Bug Fixes**: Update Section 8 (Known Bugs & Issues).

**Golden Rule**: Never paste raw code blocks. Use concise, high-level functional descriptions.

---

## 1. System Overview

AiKore is a monolithic orchestration platform for managing AI WebUIs inside a **single Docker container**.
It uses a **"Neutral Image Architecture"**: the base Docker image is lightweight (OS + System CUDA 13.0 + Conda), and all heavy modules are compiled on-demand via the internal Module Builder.

### Core Stack
| Layer | Technology |
|---|---|
| Process Supervisor | `s6-overlay` (manages backend services + NGINX) |
| Backend | Python 3.12 + **FastAPI** + **SQLAlchemy 2.0** (SQLite) + Pydantic v2 |
| Frontend | Vanilla JavaScript (ES Modules). `Split.js`, `xterm.js`, `CodeMirror`, `AnsiUp`, `SortableJS` |
| Reverse Proxy | **NGINX** (Dynamic config per-instance, WS upgrade support, flag-based reload) |
| Persistent Desktop | **KasmVNC** + Openbox (per-instance sessions, Firefox auto-launch) |
| GPU Monitoring | `pynvml` (NVIDIA NVML bindings) |
| DB | SQLite at `/config/aikore.db` (Schema V6, auto-migration on startup) |

### Container Paths (Hardcoded)
| Path | Purpose |
|---|---|
| `/config/instances/` | All instance data directories |
| `/config/instances/.wheels/` | Global compiled `.whl` storage + `manifest.json` |
| `/config/instances/{name}/wheels/` | Per-instance symlinked/copy wheels (PEP 425 clean) |
| `/config/outputs/` | Shared output directory |
| `/config/custom_blueprints/` | User-saved blueprint `.sh` files (persistent) |
| `/config/aikore.db` | SQLite database |
| `/config/tmp/` | Global TMPDIR for instances |
| `/config/trashcan/` | Soft-delete destination |
| `/opt/sd-install/blueprints/` | Stock blueprint `.sh` scripts (read-only image) |
| `/opt/sd-install/scripts/` | Helper scripts (`kasm_launcher.sh`, `version_check.sh`) |
| `/home/abc/miniconda3/` | Conda installation |
| `/etc/nginx/locations.d/` | Per-instance NGINX location blocks |
| `/run/aikore/nginx_reload.flag` | Flag file: s6-overlay watches this and reloads NGINX |

---

## 2. Project Structure & File Tree

```text
.
├── aikore/                             # MAIN APPLICATION PACKAGE
│   ├── api/                            # FastAPI Routers
│   │   ├── instances.py                # CORE: CRUD, Start/Stop, Copy/Instantiate, WebSocket Terminal, Wheel Sync, Delete (trash/permanent), File R/W, Port Allocation, Self-healing
│   │   ├── builder.py                  # MODULE BUILDER: Dynamic Torch version scraping, Presets, Conda env isolation, Wheel compilation via WebSocket, Wheel CRUD
│   │   └── system.py                   # System Stats (pynvml), Blueprint listing (stock+custom), Custom Blueprint creation, Available Ports, Debug NGINX
│   │
│   ├── core/                           # Business Logic
│   │   ├── blueprint_parser.py         # Reads `aikore.venv_path` from `### AIKORE-METADATA ###` blocks in .sh files
│   │   └── process_manager.py          # BRAIN: Subprocess mgmt (start/stop/monitor), PTY generation (terminal), NGINX config generation, Conda/venv activation, Monitor threads (stalled detection), Rebuild triggers, Version check execution, Command-in-venv runner
│   │
│   ├── database/                       # Persistence Layer
│   │   ├── crud.py                     # DB Operations: Create/Read/Update/Delete, Copy (placeholder + background), Instantiate (satellite), Autostart query
│   │   ├── migration.py                # Auto-migration V1→V6 on startup (backup→transfer→verify pattern for V1-V4, ALTER TABLE for V5-V6). Uses unique `DeclarativeBase` subclasses per version.
│   │   ├── models.py                   # SQLAlchemy models: `Instance` (all columns), `AikoreMeta` (k/v store for schema_version)
│   │   └── session.py                  # Engine, `SessionLocal`, `Base(DeclarativeBase)`, `get_db()` dependency
│   │
│   ├── schemas/                        # Pydantic v2 Models
│   │   └── instance.py                 # InstanceBase, InstanceCreate (with source_instance_id), InstanceUpdate (no `port` field), InstanceRead, InstanceCopy, InstanceInstantiate
│   │
│   ├── static/
│   │   ├── css/
│   │   │   ├── base.css                # Layout (80% scale), Split.js gutters, pane system
│   │   │   ├── components.css          # Context menus, progress bars, GPU checkboxes, hostname switch, toast notifications
│   │   │   ├── instances.css           # Compact table (28px rows), drag handles, tree connector, status badges (stopped/starting/started/stalled/error/installing with pulse animation), dirty row highlight
│   │   │   ├── modals.css              # Modal overlays
│   │   │   └── tools.css               # Tools pane: Builder (2-col grid + wheels table + terminal), Wheels Manager (dual-pane), File Editor, Terminal, Log Viewer, Welcome iframe
│   │   ├── js/
│   │   │   ├── api.js                  # Fetch wrappers, `handleResponse()` helper, centralized error parsing
│   │   │   ├── eventHandlers.js        # Global Save (batched update confirmation), Add New Instance, Row action buttons, Tools context menu dispatch, Editor Update/Save Custom buttons
│   │   │   ├── main.js                # Entry Point: Polling loop (500ms for starting/installing, 2000ms default), Grouped rendering (parent/satellite tbody), Builder button injection, Stats polling, Split.js init, SortableJS init, localStorage for layout persistence
│   │   │   ├── modals.js               # Modal event handlers: Delete (trash/permanent), Overwrite, Rebuild, Restart, Save Custom Blueprint, Update Confirm (with cancel revert)
│   │   │   ├── state.js                # Centralized State Store + DOM references (`DOM` and `state` exports)
│   │   │   ├── tools.js                # All tool views: Builder (dynamic torch population, WebSocket build, terminal), Wheels Manager (dual-pane, toggle, sync API), Log Viewer (polling, ansi_up), Terminal (xterm.js + WebSocket), Editor (CodeMirror), Version Check, Welcome Screen
│   │   │   └── ui.js                   # DOM manipulation: renderInstanceRow (full row creation with all fields, GPU checkboxes, env selects, port select, drag handle, tree connector), updateInstanceRow (status/button sync), checkRowForChanges (dirty detection), buildInstanceUrl (proxy vs VNC vs custom hostname), showToast, updateSystemStats
│   │   ├── welcome/                    # Welcome animation (single-file canvas renderer with wave effect + color cycling)
│   │   │   ├── index.html              # Loads only main.js (no separate renderer/effects files)
│   │   │   ├── style.css               # CRT scanlines, dark background
│   │   │   ├── js/main.js              # Self-contained animation: fetches ASCII logo, auto-fits, wave effect, color cycling
│   │   │   └── logos/aikore-smooth.txt  # ASCII art logo file
│   │   └── index.html                  # Main HTML: Split panes, all modal overlays, CDN scripts (Split.js, xterm.js, CodeMirror, SortableJS, AnsiUp), GPU stat template
│   │
│   ├── main.py                         # FastAPI entry: `lifespan` async context manager (NVML init, status reset, log cleanup, autostart), router registration, static mount
│   └── requirements.txt                # fastapi, uvicorn, sqlalchemy, pydantic, websockets, psutil, nvidia-ml-py, PyXDG
│
├── blueprints/                         # Stock installation scripts (each has AIKORE-METADATA block, sources versions.env)
│   ├── ComfyUI.sh                      # Image generation (Conda, Python 3.11)
│   ├── IOPaint.sh                      # Image inpainting (Conda, Python 3.11)
│   ├── LMStudio.sh                     # LLM serving (Conda, Python 3.11, persistent mode)
│   └── Voicebox.sh                     # AI voice studio (Conda, Python 3.11, bun frontend build)
├── docker/                             # Container overlay (s6 services, NGINX config)
├── entry.sh                            # Container entrypoint
├── functions.sh                        # Shell helper functions
├── Dockerfile                          # Neutral Image definition (standalone, no intermediate builds)
├── .dockerignore                       # Excludes non-essential files from Docker build context
├── .versions/torch                     # PyTorch release tag for build args (e.g., torch-v2.9.0)
├── .github/workflows/
│   ├── docker-build.yml                # Release build + push to GHCR (on published release, or manual with no-cache option)
│   └── docker-build-test.yml           # Manual test build, tags :test (workflow_dispatch only)
└── versions.env                        # Centralized version defaults (TORCH_VERSION, PYTORCH_INDEX_URL, etc.)
```

---

## 3. Key Concepts & Logic

### Instance Types
| Type | Description | Venv | Script | NGINX |
|---|---|---|---|---|
| **Standard** | Headless, proxied via NGINX | Own `./env` | Own `launch.sh` | `location /instance/{slug}/` |
| **Persistent** | GUI, KasmVNC on dedicated port | Own `./env` | Own `launch.sh` (via kasm_launcher.sh) | None (direct VNC port) |
| **Satellite** | Lightweight, reuses parent's venv | Parent's `./env` | Parent's `launch.sh` (read-only) | Own `location /instance/{slug}/` |

### Instance Lifecycle
- **Create**: DB entry + copy blueprint to `launch.sh` (or copy from source instance)
- **Start**: `process_manager.start_instance_process()` → writes `aikore_vars.env`, allocates ports, generates NGINX conf, spawns `bash launch.sh` as subprocess, starts monitor thread
- **Monitor Thread**: Polls `http://127.0.0.1:{port}` every 1s. If 200→`started`, if >180s→`stalled`. For persistent→auto-launches Firefox in VNC.
- **Stop**: `SIGTERM` to process group, 10s timeout → `SIGKILL`, cleanup NGINX conf, set `stopped`

### Port Management
- **Pool**: Env var `AIKORE_INSTANCE_PORT_RANGE` (default `19001-19020`)
- **Standard**: Pool port → `instance.port` (public NGINX endpoint)
- **Persistent**: Pool port → `instance.persistent_port` (public VNC), ephemeral → `instance.port` (internal app)
- **Self-Healing**: On start, if `port` is `None`, auto-allocate from pool
- **Conflict Check**: Uses `_allocate_ports()` with `instance_to_exclude_id` for updates

### NGINX Integration
- Each running instance gets a `location /instance/{slug}/` block in `/etc/nginx/locations.d/{slug}.conf`
- Reload mechanism: `_reload_nginx()` touches `/run/aikore/nginx_reload.flag`, watched by s6-overlay
- Config can be refreshed live (hostname changes) without restarting instances

### Blueprint Metadata Format
```bash
### AIKORE-METADATA-START ###
# aikore.name = ComfyUI
# aikore.category = Image Generation  # Displayed in custom blueprint dropdown
# aikore.description = A powerful and modular GUI for Stable Diffusion.
# aikore.venv_type = conda       # or "python"
# aikore.venv_path = ./env
### AIKORE-METADATA-END ###
```
Parsed by `blueprint_parser.py` (venv_path), `process_manager.parse_blueprint_metadata()` (venv_type/venv_path), and `system.py get_available_blueprints()` (category for dropdown display).

### Module Builder Workflow
1. User selects Preset + Python + CUDA + Torch + GPU Arch
2. **Version data is fetched dynamically**: Python from Conda (`/api/builder/versions/python`), CUDA from PyTorch index (`/api/builder/versions/cuda`), Torch from PyTorch index (`/api/builder/versions/torch/{cu}`). All have hardcoded fallbacks.
3. Backend creates isolated Conda env `builder_py{ver}_{cu}{ver}_pt{ver}` via `source activate` (not `conda run`)
4. Installs `torch=={ver} torchvision torchaudio` from PyTorch wheel index (no version pin on torchvision/torchaudio — pip resolves compatibility)
5. Compiles wheel using `nvcc` (System CUDA 13.0)
6. Renames wheel with `+arch{X.Y}` suffix (e.g., `sageattention-1.0+arch8.9.whl`)
7. Stores in `/config/instances/.wheels/` with metadata in `manifest.json`

### Wheel Sync System
- **Global wheels** (`.wheels/`): Stored WITH `+arch` suffix (metadata)
- **Instance wheels** (`{name}/wheels/`): Stored WITHOUT suffix (PEP 425 compatible, pip-installable)
- `_clean_wheel_name()` regex strips `+archX.Y` → pip sees standard wheel name
- Sync API: Takes list of desired filenames → copies from global (renaming), removes extras

### UI Architecture
- **Polling**: `fetchAndRenderInstances()` with adaptive interval (500ms when `starting`/`installing`, 2000ms idle)
- **Dirty Row Detection**: `checkRowForChanges()` compares field values vs `dataset.original*`
- **Global Save**: Batched confirmation modal → sequential `PUT /instances/{id}` for all dirty rows
- **Grouped Rendering**: Parent instances as `<tbody class="instance-group">`, satellites as child `<tr>` with tree connector
- **Drag & Drop**: SortableJS on `<tbody>` groups, order persisted in `localStorage`

---

## 4. API Endpoints Summary

| Method | Path | Handler | Description |
|---|---|---|---|
| GET | `/api/instances/` | `read_all_instances` | List all instances |
| POST | `/api/instances/` | `create_new_instance` | Create instance (standard or copy) |
| PUT | `/api/instances/{id}` | `update_instance_details` | Full update with smart restart/hot-swap logic |
| DELETE | `/api/instances/{id}` | `delete_instance` | Delete (trash or permanent), background file ops |
| POST | `/api/instances/{id}/start` | `start_instance` | Start (with self-healing port allocation) |
| POST | `/api/instances/{id}/stop` | `stop_instance` | Stop process group |
| POST | `/api/instances/{id}/copy` | `copy_instance` | Async clone (placeholder + background copy) |
| POST | `/api/instances/{id}/instantiate` | `instantiate_instance` | Create satellite |
| POST | `/api/instances/{id}/rebuild` | `rebuild_instance` | Create `.rebuild-env` trigger file |
| POST | `/api/instances/{id}/version-check` | `version_check` | Run version_check.sh in venv |
| GET | `/api/instances/{id}/logs` | `get_instance_logs` | Tail logs with byte offset |
| GET | `/api/instances/{id}/file` | `get_instance_file` | Read launch.sh |
| PUT | `/api/instances/{id}/file` | `update_instance_file` | Write launch.sh (optional restart) |
| GET | `/api/instances/{id}/wheels` | `get_instance_wheels` | List global wheels with `installed` status |
| POST | `/api/instances/{id}/wheels` | `sync_instance_wheels` | Sync desired wheel set to instance |
| WS | `/api/instances/{id}/terminal` | `instance_terminal_endpoint` | PTY terminal (xterm.js) |
| GET | `/api/system/info` | `get_system_info` | GPU count (pynvml) |
| GET | `/api/system/stats` | `get_system_stats` | CPU/RAM/GPU real-time stats |
| GET | `/api/system/blueprints` | `get_available_blueprints` | Stock + custom blueprint listing with `{filename, category}` objects |
| POST | `/api/system/blueprints/custom` | `create_custom_blueprint` | Save custom .sh file |
| GET | `/api/system/available-ports` | `get_available_ports` | Free ports in pool |
| GET | `/api/system/debug-nginx` | `debug_nginx` | NGINX config debug dump |
| GET | `/api/builder/info` | `get_builder_info` | Presets, detected GPU arch, python path |
| GET | `/api/builder/versions/python` | `get_available_python_versions` | Conda search results (cached) |
| GET | `/api/builder/versions/cuda` | `get_available_cuda_versions` | Scrapes PyTorch wheel index, returns `{cu, version}` objects |
| GET | `/api/builder/versions/torch/{cu}` | `get_torch_versions_for_cuda` | Scrape PyTorch index, fallback list |
| GET | `/api/builder/wheels` | `list_wheels` | List built wheels with metadata |
| GET | `/api/builder/wheels/{name}/download` | `download_wheel` | Download .whl file |
| DELETE | `/api/builder/wheels/{name}` | `delete_wheel` | Delete .whl + manifest entry |
| WS | `/api/builder/build` | `build_websocket` | Stream build process, save wheel |

---

## 5. Database Schema (V6)

**Table: `instances`**

| Column | Type | Nullable | Default | Description |
|---|---|---|---|---|
| `id` | INTEGER | No | PK | Primary Key |
| `parent_instance_id` | INTEGER | Yes | — | Links satellite to parent (NULL=standard) |
| `name` | VARCHAR | No | — | Unique name |
| `base_blueprint` | VARCHAR | No | — | Script filename (e.g., `ComfyUI.sh`) |
| `gpu_ids` | VARCHAR | Yes | — | `CUDA_VISIBLE_DEVICES` (e.g., `"0,1"`) |
| `autostart` | BOOLEAN | No | False | Start on container boot |
| `persistent_mode` | BOOLEAN | No | False | KasmVNC mode |
| `hostname` | VARCHAR | Yes | — | Custom URL override |
| `use_custom_hostname` | BOOLEAN | No | False | Enable custom hostname |
| `output_path` | VARCHAR | Yes | — | Override output folder name |
| `python_version` | VARCHAR | Yes | — | Custom Python version override |
| `cuda_version` | VARCHAR | Yes | — | Custom CUDA version override (e.g., `"12.1"`) |
| `torch_version` | VARCHAR | Yes | — | Custom Torch version override (e.g., `"2.5.1"`) |
| `status` | VARCHAR | No | `"stopped"` | `stopped`, `starting`, `stalled`, `started`, `installing`, `error` |
| `pid` | INTEGER | Yes | — | Process ID |
| `port` | INTEGER | Yes | — | Internal HTTP port |
| `persistent_port` | INTEGER | Yes | — | Public VNC port |
| `persistent_display` | INTEGER | Yes | — | X11 Display ID |

**Table: `aikore_meta`**

| Column | Type | Description |
|---|---|---|
| `key` | VARCHAR (PK) | Metadata key (e.g., `schema_version`) |
| `value` | VARCHAR | Metadata value (e.g., `6`) |

### Migration Pattern
- **V1→V4**: Full dump-and-reload (backup DB → create new schema → copy data → verify count → commit or rollback + `sys.exit`). Each migration uses isolated `DeclarativeBase` subclasses.
- **V5→V6**: Simple `ALTER TABLE ADD COLUMN` + update `schema_version` meta key.
- **Fresh DB**: `models.Base.metadata.create_all()` + insert `schema_version=6`.

---

## 6. Frontend State Management

### `state.js` Exports
- **`DOM`**: Cached references to all key elements (tables, modals, containers, buttons, progress bars)
- **`state`**: Application state including `availableBlueprints`, `availablePorts`, `systemInfo`, `versions` (python/cuda/torchCache), `currentMenuInstance`, `instanceToDeleteId`, `pendingUpdates`, `activeLogInstanceId`, `editorState`, `codeEditor`, `currentTerminal`, `currentTerminalSocket`, `fitAddon`, `currentWheelsInstanceId`, `split.savedSizes`

### Key Frontend Flows
1. **Instance Creation**: Click "Add New" → empty row → fill fields → "Create" → POST `/api/instances/`
2. **Instance Update**: Edit row (dirty detection) → "Save Changes" → batched confirmation modal → sequential PUT `/api/instances/{id}`
3. **Terminal**: WebSocket to `/api/instances/{id}/terminal` → PTY fork → bidirectional data (resize as JSON control messages)
4. **Builder**: WebSocket to `/api/builder/build` → stream build logs → wheel saved automatically

---

## 7. Bugs Already Fixed (Sessions 1–6)

| # | Bug | File | Fix |
|---|---|---|---|
| 1 | `row.ok` → `response.ok` in `fetchAvailablePythonVersions()` | `api.js` | Fixed reference error |
| 2 | Duplicate `/api/system/info` endpoint | `instances.py` vs `system.py` | Removed from `instances.py`, kept pynvml version |
| 3 | `get_db()` defined locally in multiple files | `instances.py`, `system.py` | Centralized in `session.py` |
| 4 | `onerror=_on_rm_error` (deprecated) | `instances.py` | Changed to `onexc=_on_rm_error` with new signature |
| 5 | `@app.on_event("startup"/"shutdown")` deprecated | `main.py` | Replaced with `lifespan` async context manager |
| 6 | `declarative_base()` deprecated (SQLAlchemy 2.0) | `migration.py`, `session.py` | Rewrote all bases as `class Base(DeclarativeBase)` with unique subclasses |
| 7 | Binary `\|` instead of SQLAlchemy `or_()` in port conflict query | `instances.py` | Added `or_()` import and usage |
| 8 | "Save as Custom Blueprint" button had no event listener | `eventHandlers.js` | Added listener that pre-fills filename and shows modal |
| 9 | `pendingUpdates` missing from initial state | `state.js` | Added `pendingUpdates: []` |
| 10 | `cpu_percent(interval=None)` returns 0 on first call | `system.py` | Pre-seeded with `cpu_percent(interval=0.1)` |
| 8.1 | Stale DB session passed to background copy task | `crud.py` | `process_background_copy()` creates own `SessionLocal()` |
| 8.2 | DB session held open for WebSocket lifetime | `instances.py` | `db.close()` after reading instance data |
| 8.3 | Duplicate event listeners on update-confirm modal buttons | `modals.js` | Removed duplicate confirm handler |
| 8.4 | XSS via innerHTML with wheel filenames | `tools.js`, `ui.js` | Replaced with `textContent` + `createElement` |
| 8.5 | `get_available_ports` doesn't include `persistent_port` | `system.py` | Added `instance.persistent_port` to `used_ports` |
| 8.6 | Cannot delete instances in `installing` or `error` status | `instances.py` | Changed check to include those statuses |
| 8.7 | `TORCH_VISION_MAP` outdated | `builder.py` | Removed map, pip resolves versions automatically |
| 8.8 | Conda env name not sanitized → shell injection | `builder.py` | Added regex validation before using env_name |
| 8.9 | Rollback logic for directory rename is fragile | `instances.py` | Replaced `'new_dir' in locals()` with `os.path.isdir()` |
| 8.10 | `InstanceUpdate` schema missing `port` field | `schemas/instance.py` | Added `port: int \| None = None` |
| 8.11 | `INSTANCES_DIR` hardcoded in 3 separate files | Multiple | Centralized in `config.py` |
| 8.12 | `setInterval` for system stats never cleared | `main.js` | Pauses when `document.hidden`, resumes on visibility change |
| 8.13 | `shutil.rmtree` without `onexc` in `crud.py` | `crud.py` | Added `_on_rm_error` handler |
| 8.14 | Unused `import subprocess` in `instances.py` | `instances.py` | Removed |
| 8.15 | `status-error` CSS color unclear | CSS | Changed to dark red with border |
| 8.16 | `InstanceUpdate` missing `persistent_port`/`persistent_display` | `schemas/instance.py` | Added both fields |
| 8.17 | Double-commit pattern in `update_instance_details` | `instances.py` | Removed manual `setattr` loop |
| 8.18 | `stat.S_IWRITE` is Windows-only | `instances.py`, `crud.py` | Changed to `stat.S_IWUSR` |
| 8.19 | XSS in `ui.js` status cell via `innerHTML` | `ui.js` | Replaced with `createElement` + `textContent` |
| 8.20 | XSS in `tools.js` error messages via `innerHTML` | `tools.js` | Added HTML entity escaping |
| 8.21 | `pollTimeoutId` missing from `state.js` | `state.js` | Added `pollTimeoutId: null` |
| 8.22 | Duplicate comment in `state.js` | `state.js` | Removed duplicate |
| 8.23 | False dirty state on page refresh (env selects) | `ui.js` | `createEnvSelect` adds custom values; `updateTorchOptions` re-checks |
| 8.24 | View/Open buttons disabled for started satellites | `main.js` | Partial update now updates `a[data-action="open"]` |
| 8.25 | Split pane sizes not persisting | `main.js` | Changed `onEnd` to `onDragEnd` for Split.js |
| 8.26 | Builder `ModuleNotFoundError: No module named 'torch'` | `builder.py` | Reverted to `source activate` pattern |
| 8.27 | Welcome animation issues | `welcome/js/main.js` | Complete rewrite as single-file animation |
| 8.28 | `parse_blueprint_metadata()` ignores custom blueprints | `process_manager.py` | Added `_find_blueprint_path()` helper |
| 8.29 | Terminal venv activation reads blueprint instead of launch.sh | `process_manager.py` | Added `_parse_venv_from_launch_sh()` |
| 8.30 | Terminal destroyed when switching tools | `tools.js` | Persistent terminal pool (`state.terminals`) |
| 8.31 | Builder state lost when switching tools | `tools.js` | `hideAllToolViews({keepBuilder: true})` |
| 8.32b | Terminal slightly smaller than frame | `tools.css` | Changed padding to 0, added `position: relative` |
| 8.34 | Previous terminals show black screen | `tools.js`, `tools.css` | Removed innerHTML clearing; absolute positioning with visibility toggle |
| 8.35 | Wrong torchvision version mapping | `builder.py` | Removed `TORCH_VISION_MAP`, pip resolves versions |

---

## 8. Audit Report — New Bugs, Anomalies & Improvement Points

> **Methodology**: Full code review of all Python backend files, all JavaScript frontend files, Dockerfile, NGINX config, s6-overlay services, and database layer. Each finding is categorized by severity.

### 8.1 Bugs Found

#### 🔴 B-NEW-01 — `run_version_check` and `run_command_in_instance_venv` use stale venv metadata ✅ FIXED
**Files**: `process_manager.py` — `run_version_check()`, `run_command_in_instance_venv()`
**Problem**: The fix described in 8.29 added `_parse_venv_from_launch_sh()` and applied it to `start_terminal_process()`. However, `run_version_check()` and `run_command_in_instance_venv()` were **not updated** — they still call `parse_blueprint_metadata(instance.base_blueprint)` which reads from the original blueprint file, not from the instance's `launch.sh`. If a user modified `launch.sh` (e.g., via "Save as Custom Blueprint" or direct editing), the version check and venv commands will use incorrect venv metadata (wrong `venv_type` or `venv_path`).
**Impact**: Version checks and pip installs may run outside the correct virtual environment, producing wrong results or failing silently.
**Fix**: Added `_get_instance_venv_metadata()` helper that encapsulates the `_parse_venv_from_launch_sh()` → `parse_blueprint_metadata()` fallback pattern. Both `run_version_check()` and `run_command_in_instance_venv()` now call this helper instead of `parse_blueprint_metadata()` directly.

#### 🟠 B-NEW-02 — XSS in update confirmation modal via `innerHTML` ✅ FIXED
**File**: `eventHandlers.js` line 146
**Problem**: `div.innerHTML = \`<strong>[${instanceName}] ${fieldMap[key]}:</strong> ${changes[key].old} &rarr; ${changes[key].new}\`;` — instance names and field values (old/new) are inserted via `innerHTML` without HTML escaping. An instance name containing `<img onerror=...>` or `<script>` tags could inject arbitrary HTML. While instance names are user-controlled, this is a real XSS vector.
**Impact**: Potential HTML injection if instance names or blueprint names contain HTML.
**Fix**: Replaced `innerHTML` with `createElement` + `textContent` + `createTextNode`. The `→` arrow character is now a literal text node instead of an HTML entity (`&rarr;`).

#### 🟠 B-NEW-03 — `renderBuilderStatus` polls `/api/builder/info` every 2 seconds (wasteful) ✅ FIXED
**Files**: `main.js` (stats polling calls `renderBuilderStatus()`), `tools.js` (`renderBuilderStatus` fetches `/api/builder/info`), `builder.py` (`get_builder_info`)
**Problem**: `renderBuilderStatus()` is called inside the 2-second stats polling interval. It makes an HTTP request to `/api/builder/info` which calls `pynvml.nvmlInit()` + `nvmlDeviceGetHandleByIndex(0)` + `nvmlDeviceGetCudaComputeCapability()` + `nvmlShutdown()` every single time. This is wasteful and could cause NVML state issues with frequent init/shutdown cycles. Furthermore, `get_builder_info()` returns `{presets, detected_arch, gpu_name, python_path}` — **none** of which indicate build status. The function checks `info.status` and `info.is_building` which don't exist in the response. The function is effectively a no-op that wastes HTTP requests.
**Impact**: Unnecessary network traffic, NVML init/shutdown cycles every 2s, function never actually detects building state.
**Fix**: Changed `renderBuilderStatus()` from `async` (HTTP fetch) to synchronous, using the client-side `builderSocket.readyState === WebSocket.OPEN` state to determine if a build is in progress. No API call needed — the WebSocket connection state is the definitive indicator of an active build.

#### 🟠 B-NEW-04 — Blueprint metadata parsing inconsistency between `blueprint_parser.py` and `process_manager.py` ✅ FIXED
**Files**: `blueprint_parser.py` vs `process_manager.py`
**Problem**: `blueprint_parser.py` uses exact string match: `line == '### AIKORE-METADATA-START ###'` (after `.strip()`). `process_manager.py` uses substring match: `"### AIKORE-METADATA-START ###" in line`. If a blueprint has trailing whitespace or different formatting on the marker line, `blueprint_parser.py` will fail to detect the metadata block while `process_manager.py` will succeed. This means `get_blueprint_venv_path()` (used in `crud.py` for background copy) could return a different result than `parse_blueprint_metadata()` (used for terminals and version checks).
**Impact**: Inconsistent venv path resolution depending on which function is called. Could cause copy operations to ignore the wrong venv directory.
**Fix**: Changed `blueprint_parser.py` to use substring match (`in` operator) for metadata block markers, matching the behavior of `process_manager.py`.

#### 🟠 B-NEW-05 — No timeout/recovery for instances stuck in "installing" status
**Files**: `crud.py` (`process_background_copy`), `instances.py` (`copy_instance`)
**Problem**: When copying an instance, a background task is launched with `status="installing"`. If the background task fails silently (e.g., process killed, OOM, conda crash without proper exception handling), the instance stays in "installing" status indefinitely. There is no timeout mechanism to detect and recover from this state. The user cannot start, stop, or interact with the instance normally.
**Impact**: Orphaned instances in "installing" status that can only be deleted (the delete check allows `installing` status).
**Status**: Mitigated by existing startup reset (all instances → `stopped` on boot). Remaining gap: watchdog thread for intra-session recovery.

#### 🟡 B-NEW-06 — `stat.S_IEXEC` non-standard constant (same class as fixed bug 8.18) ✅ FIXED
**File**: `process_manager.py` line 469
**Problem**: `os.chmod(dest_script_path, os.stat(dest_script_path).st_mode | stat.S_IEXEC)` uses `stat.S_IEXEC` which is not a POSIX-standard constant. It works on Linux (value 0o100, same as `S_IXUSR`), but is semantically incorrect and non-portable — exactly the same class of issue as bug 8.18 which was fixed for `S_IWRITE` → `S_IWUSR`.
**Impact**: Works on Linux, but non-portable and inconsistent with the 8.18 fix.
**Fix**: Changed to `stat.S_IXUSR`.

#### 🟡 B-NEW-07 — XSS in log viewer via `insertAdjacentHTML` with unescaped content ✅ FIXED
**File**: `tools.js` line 1039
**Problem**: `DOM.logContentArea.insertAdjacentHTML('beforeend', logHtml)` where `logHtml = ansi_up.ansi_to_html(data.content)`. The `ansi_up` library converts ANSI escape codes to HTML but does **not** escape existing HTML in the content. If an application's log output contains `<script>`, `<img>`, or other HTML tags, they will be rendered as DOM elements. While the risk is limited (logs come from within the container), it's still an XSS vector if an instance outputs crafted log content.
**Impact**: Potential HTML injection from log content.
**Fix**: Escape `<` and `>` in the raw log content before passing to `ansi_up.ansi_to_html()`.

#### 🟡 B-NEW-08 — `openInstanceView` uses own zoom key instead of `welcome` ✅ FIXED
**File**: `tools.js` — `openInstanceView()`
**Problem**: `openInstanceView` calls `setToolZoom('welcome')` — the instance embedded view shares its zoom level with the welcome screen. If the user zooms in on the welcome screen, then opens an instance view, the instance view inherits the welcome screen's zoom. Changing one affects the other.
**Impact**: Confusing UX — zoom level of instance view is coupled to welcome screen.
**Fix**: Added an `instanceView` key to `state.zoom.tools` and used `setToolZoom("instanceView")` in `openInstanceView()`.

#### 🟡 B-NEW-09 — Redundant `import shutil` inside `_cleanup_instance_files` ✅ FIXED
**File**: `process_manager.py` — `_cleanup_instance_files()`
**Problem**: `import shutil` is done locally inside the function, but `shutil` is already imported at the top of the file (line 13). This is dead code — the local import is shadowed by the module-level import.
**Impact**: No functional impact, but indicates code quality issue.
**Fix**: Removed the local `import shutil`.

#### 🟡 B-NEW-10 — Terminal pool memory leak (no LRU eviction, no dead terminal cleanup) ✅ FIXED
**Files**: `modals.js` (`handleDelete`), `tools.js` (terminal pool)
**Problem**: When an instance is deleted, `closeTerminalById()` is called in `handleDelete()`. However, if the delete fails (e.g., 409 conflict → overwrite modal), the terminal is not closed. Also, if the user permanently deletes an instance without having opened its terminal, there's no issue, but if the terminal was open and the delete succeeds, the terminal WebSocket will disconnect server-side (instance directory gone) but the client-side cleanup depends on the `socket.onclose` handler which only writes a `[CLOSED]` message — the Terminal object and DOM element remain in `state.terminals` forever.
**Impact**: Memory leak — orphaned xterm.js Terminal objects and disconnected WebSockets accumulate in `state.terminals`.
**Fix**: Implemented LRU eviction with `MAX_TERMINALS = 5` limit. Each terminal tracks a `lastUsed` timestamp (refreshed on display). When opening a 6th terminal, the least recently used one is automatically closed (WebSocket + xterm.js + DOM). Dead terminals (WebSocket closed server-side) get `lastUsed = 0`, making them the highest priority for eviction. Existing cleanup on instance deletion (`closeTerminalById` in `handleDelete`) remains unchanged.

#### 🟡 B-NEW-11 — `update_nginx_config` writes NGINX configs for non-running instances ✅ FIXED
**File**: `process_manager.py` — `update_nginx_config()`
**Problem**: The function queries all instances with `status != "stopped"` and writes NGINX configs for them. This includes instances in `stalled`, `error`, and `installing` status. An instance in `error` status may have its internal port pointing to a dead process, and writing an NGINX config for it creates a proxy to nowhere.
**Impact**: NGINX may proxy to dead ports for error/stalled instances, causing 502 errors for users who try to access them.
**Fix**: Changed query filter from `status != "stopped"` to `status == "started"`. Only active, healthy instances get NGINX configs.

#### 🟡 B-NEW-12 — `state.systemInfo.gpus` never populated from API
**Files**: `api.js` (`fetchSystemInfo`), `state.js`
**Problem**: `fetchSystemInfo()` returns `{ gpu_count: N }` with no `gpus` array. But `state.systemInfo` is initialized with `gpus: []` and `renderInstanceRow` checks `state.systemInfo.gpus && Array.isArray(state.systemInfo.gpus)` — this is always true (empty array), so `state.systemInfo.gpus.length` is 0, falling back to `state.systemInfo.gpu_count || 0`. The `gpus` array in `state.systemInfo` is never populated. This is misleading code.
**Impact**: Works correctly by accident (fallback to `gpu_count`), but the `gpus` array is dead state.
**Fix**: Either remove the `gpus` array from `state.systemInfo` or populate it from `/api/system/stats` (which does return GPU details).

### 8.2 Anomalies & Design Issues

#### 🟠 A-01 — Conda environments from Module Builder never cleaned up ✅ RESOLVED (auto-cleanup after 7 days)
**File**: `builder.py`
**Problem**: Each build creates (or reuses) a Conda environment named `builder_py{ver}_{cu}{ver}_pt{ver}`. These environments are never deleted after builds. Each environment contains a full PyTorch installation (~2-5 GB). Over time, with different Python/CUDA/Torch combinations, disk usage can grow to tens of GB. There is no UI or API to list, clean up, or manage these environments.
**Impact**: Gradual disk space exhaustion. Users may not realize builder environments are accumulating.
**Fix**: Added `_mark_env_used()` which touches a `.aikore_last_used` marker file in the environment directory after every build. Added `cleanup_stale_builder_envs()` which scans all `builder_py*` environments on startup and removes those whose `.aikore_last_used` is older than 7 days (`_BUILDER_ENV_MAX_AGE_DAYS = 7`). The marker is updated on every build (not just creation), so actively reused environments are preserved indefinitely.

#### 🟠 A-02 — `monitor_instance_thread` will never mark non-HTTP instances as "started"
**File**: `process_manager.py` — `monitor_instance_thread()`
**Problem**: The monitor thread polls `http://127.0.0.1:{port}` expecting an HTTP response with status code < 500. If an instance doesn't serve HTTP (e.g., CLI-only tools, batch processing, training scripts), the monitor will never detect readiness and will mark the instance as "stalled" after 180s. This is a design limitation — the monitoring strategy assumes all instances are web servers.
**Impact**: Non-web instances are always marked as "stalled" even if running correctly.
**Recommendation**: Add a process-based health check as a fallback: if the process is still alive (PID exists) after the stall timeout, mark as "started" instead of "stalled". Or add an `aikore.health_check_type` metadata field to let blueprints declare their monitoring type (HTTP vs process).

#### 🟡 A-03 — Blueprint change confirmation uses blocking `confirm()` dialog
**File**: `ui.js` — blueprint change handler
**Problem**: The blueprint change handler uses `confirm()` which blocks the main thread and shows a browser-native dialog. This is inconsistent with the rest of the application which uses styled modal dialogs. It also doesn't match the application's dark theme.
**Impact**: UX inconsistency, jarring native dialog.
**Recommendation**: Replace with a styled modal dialog matching the application's design system.

#### 🟡 A-04 — `RequestSizeLimitMiddleware` doesn't check actual body for chunked transfers
**File**: `main.py`
**Problem**: The middleware only checks the `content-length` header. Chunked transfer encoding (no `content-length`) bypasses the 10 MB limit entirely. A client could send an arbitrarily large body via chunked encoding.
**Impact**: Low risk in a single-container application, but could be exploited if the API is exposed externally.
**Recommendation**: For robust protection, wrap the request body reading or use a streaming size check. For the current use case (single container, internal API), this is low priority.

#### 🟡 A-05 — `crud.py` `process_background_copy` uses `conda` without full path ✅ FIXED
**File**: `crud.py`
**Problem**: Uses `"conda"` without the full path `/home/abc/miniconda3/bin/conda`. Relies on PATH being set correctly. In background tasks (launched via `BackgroundTasks`), the PATH from `entry.sh` may not be inherited, depending on the ASGI server's process model. Uvicorn typically inherits the environment, but this is fragile.
**Impact**: Conda clone may fail silently if PATH is not set.
**Fix**: Changed from bare `conda` to absolute path `/home/abc/miniconda3/bin/conda`.

#### 🟡 A-06 — No CSRF protection on API endpoints
**Problem**: The API uses no CSRF tokens. Since it's a single-container application accessed through NGINX, this is less of a concern. However, if the AiKore port (9000) is exposed externally without additional protection, CSRF attacks are possible.
**Impact**: Low risk in typical deployment, higher risk if exposed externally.
**Recommendation**: Low priority for current architecture. If external exposure is planned, add CSRF tokens or restrict to same-origin.

### 8.3 Improvement Recommendations

#### I-01 — Global error handling and user feedback
**Current**: API failures in `fetchAndRenderInstances()` are silently logged to console. No user-visible feedback for network errors, 500 responses, or backend crashes.
**Recommendation**: Add a global error banner or toast notification when API calls fail. Show connection status indicator in the UI. Implement retry logic with exponential backoff.

#### I-02 — User and system documentation
**Current**: No user-facing documentation exists. Only internal context/roadmap files.
**Recommendation**: Write a user guide covering: instance creation, blueprints, builder usage, terminal access, wheel management, persistent mode, custom versions. Write a system guide covering: Docker deployment, port configuration, GPU setup, backup/restore, troubleshooting.

#### I-03 — Unify blueprint metadata parsing
**Current**: Three separate implementations parse the same metadata format:
1. `blueprint_parser.py` — `get_blueprint_venv_path()` (exact match for markers)
2. `process_manager.py` — `parse_blueprint_metadata()` (substring match)
3. `process_manager.py` — `_parse_venv_from_launch_sh()` (substring match)
4. `system.py` — `_parse_blueprint_category()` (substring match)
**Recommendation**: Create a single `parse_metadata(filepath)` function that returns a dict of all metadata fields. All callers should use this single function. This eliminates inconsistency and code duplication.

#### I-04 — Stuck instance recovery on startup
**Current**: On startup, all instances are reset to `stopped` status (except autostart ones). But if the container was killed during a copy operation, instances in `installing` status are also reset to `stopped`, which is correct. However, there's no detection of partially-copied directories or corrupted environments.
**Recommendation**: Add integrity checks on startup: detect incomplete copies (missing directories, missing launch.sh), mark them as `error` status, and provide a "repair" or "re-create" option.

#### I-05 — Builder Conda environment management
**Current**: Builder Conda environments accumulate on disk with no cleanup.
**Recommendation**: Add an API endpoint to list builder environments (`GET /api/builder/environments`) and delete them (`DELETE /api/builder/environments/{name}`). Add automatic cleanup of environments older than N days. Show disk usage in the UI.

#### I-06 — Terminal pool cleanup
**Current**: Terminal pool (`state.terminals`) accumulates entries that are never cleaned up unless explicitly closed.
**Recommendation**: Add a "Close All Terminals" button. Implement LRU eviction when pool exceeds a threshold (e.g., 5 terminals). Show active terminal count in the UI.

#### I-07 — Non-HTTP instance monitoring
**Current**: All instances are monitored via HTTP polling. Non-HTTP instances (CLI tools, training scripts) will always be marked "stalled".
**Recommendation**: Add `aikore.monitor_type` metadata to blueprints (`http` vs `process`). For `process` type, monitor PID existence instead of HTTP port. Mark as "started" when the process has been alive for >10s.

#### I-08 — Instance name validation
**Current**: Instance names are used directly in directory paths, NGINX config paths, and shell contexts. While `_slugify` is used for NGINX, the raw name is used for directory paths. Names with special characters (spaces, quotes, `$`, etc.) could cause issues.
**Recommendation**: Validate instance names on creation: allow only `[a-zA-Z0-9_-]` characters. Show a validation error in the UI if the name contains invalid characters.

#### I-09 — Log viewer improvements
**Current**: Log viewer uses `insertAdjacentHTML` with `ansi_up` which doesn't escape HTML. Logs are polled every 2s with byte offset.
**Recommendation**: Escape HTML in log content before ANSI conversion. Add a "Download Full Log" button. Add log search/filter capability. Consider WebSocket-based log streaming instead of polling.

#### I-10 — NGINX config cleanup on status changes
**Current**: NGINX configs are written when instances start and cleaned up when they stop. But `update_nginx_config()` writes configs for all non-stopped instances, including stalled/error ones.
**Recommendation**: Only write NGINX configs for `started` instances. Clean up configs when instances transition to `stopped`, `stalled`, or `error`.

---

## 9. New Features & Fixes (Session 3)

### 🔴 Bug Fix: "Save Changes" Appears on Page Refresh (False Dirty State)
**Files**: `ui.js`, `main.js`
**Problem**: When refreshing the page, the "Save Changes" button appeared with an incorrect dirty count, even though no changes had been made. Root cause: the port `<select>` for existing instances had no "Auto" option, so when an instance had no explicit port (`null`), the select defaulted to the first available port value. The comparison `normalizeStr(portSelect.value) !== row.dataset.originalPort` (where originalPort was `""`) always returned true, marking the row as dirty.
**Fix**: Always include an "Auto" option (value `""`) in the port select, for both new and existing instances. `updateInstanceRow()` now ensures the Auto option exists and sets `portSelect.value` correctly. Also fixed `updateInstanceRow()` which was removing the Auto option when a port was assigned.

### 🟡 Bug Fix: Split Pane Layout Not Persisting Across Refreshes
**File**: `main.js`
**Problem**: Split pane sizes appeared to save on drag end but were never actually persisted. Root cause: the code used `onEnd` as the Split.js drag callback, but Split.js uses `onDragEnd` — not `onEnd`. The `onEnd` option was silently ignored, so `localStorage.setItem` was never called after dragging a splitter.
**Fix**: Changed both Split.js initializations to use `onDragEnd` instead of `onEnd`.

### ✨ Feature: Per-Panel Zoom Controls
**Files**: `index.html`, `base.css`, `state.js`, `main.js`, `tools.js`
**Description**: Added `+` / `−` zoom buttons in the header of each pane (Instances Manager, Tools, System Monitoring). Each pane has its own zoom level (50%–200%, step 10%). For the Tools pane, the zoom level is saved per tool view (Welcome, Logs, Editor, Terminal, Version Check, Builder, Wheels Manager). All zoom levels are persisted in `localStorage` under key `aikoreZoomLevels`. Zoom uses the CSS `zoom` property on `.pane-content`, which scales all content including `px`-based layouts. Xterm.js terminal auto-fits after zoom changes.

### 🔴 Bug Fix: "Open" Button Detection Based on Wrong Port
**Files**: `process_manager.py`, `ui.js`
**Problem**: Two issues:
1. **Backend**: In persistent mode, `monitor_instance_thread` checked `http://127.0.0.1:{instance.port}` (internal app port) to determine "started" status, but the "Open" button pointed to `persistent_port` (VNC/Kasm port). The instance could be marked "started" before VNC was ready.
2. **Frontend**: `buildInstanceUrl()` in normal mode generated `http://hostname:{port}/` exposing the internal port directly, instead of using the nginx proxy path `/instance/{slug}/`. This was incorrect — users should access instances through the nginx reverse proxy, not directly.
3. **Backend**: In persistent mode, the internal Firefox pointed to `{internal_app_port}` which was `instance.port`, but after the fix `internal_app_port` became `persistent_port`, so Firefox would point to itself. Fixed by adding a separate `internal_web_port` parameter.
**Fix**: 
- Backend: In persistent mode, monitor `persistent_port` instead of `instance.port`. Added `internal_web_port` parameter to `monitor_instance_thread` so Firefox always points to the internal web app (`instance.port`).
- Frontend: In normal mode, always use `/instance/{slug}/` as the URL (nginx proxy), removing the direct port access path.

---

## 10. Bugs Found and Fixed in Session 4

### 🟠 8.23 — False Dirty State on Page Refresh (4 phantom modifications) ✅ FIXED
**Files**: `ui.js`
**Problem**: After a page refresh, the "Save Changes" button appeared with a dirty count even though no changes had been made. Two root causes:
1. **`createEnvSelect` didn't add custom values**: If an instance had a `python_version` or `cuda_version` that wasn't in the dropdown options list, the select defaulted to `""` while `dataset.originalPythonVersion` held the actual value → comparison `"" !== "3.12"` = dirty.
2. **Async `updateTorchOptions` timing**: The torch version select was populated asynchronously (fetched from PyTorch index). `checkRowForChanges()` ran at the end of `renderInstanceRow()` before the async fetch completed. If the instance had a `torch_version`, the select value was `""` while the original was the actual version → dirty. After the async load, `checkRowForChanges` was never re-called, so the row stayed dirty forever.
**Fix**: 
- `createEnvSelect` now adds `currentValue` as a custom `<option>` if it's not in the standard options list.
- `updateTorchOptions` now calls `checkRowForChanges(row)` after the async load completes and the value is set.

### 🟠 8.24 — View/Open Buttons Disabled for Started Satellite Instances ✅ FIXED
**Files**: `main.js`
**Problem**: The partial update mode in `fetchAndRenderInstances()` only queried `button.action-btn` when updating buttons on status change, completely missing the `<a class="action-btn">` Open link. When an instance transitioned to "started" during a polling cycle while dirty rows existed, the Open link retained its `disabled` class and `href="#"`. Additionally, Bug 8.23 caused all rows to be falsely dirty immediately on page load, forcing the partial update mode on every poll — so if an instance was already "started" at load time and the initial render set the Open link correctly, but a later status *change* on any row triggered the partial handler, the Open link update was missed.
**Fix**: Partial update mode now also queries and updates `a[data-action="open"]`, calling `buildInstanceUrl(row)` and toggling the `disabled` class. Combined with Bug 8.23 fix, rows are no longer falsely dirty, so full re-render happens on each poll.

### 🔴 8.25 — Split Pane Sizes Not Persisting After Page Refresh ✅ FIXED
**File**: `main.js`
**Problem**: Split pane sizes were never saved to `localStorage`. The code used `onEnd` as the drag-end callback, but Split.js uses `onDragEnd` — `onEnd` is not a valid option and was silently ignored.
**Fix**: Changed both `Split()` calls to use `onDragEnd` instead of `onEnd`.

### ✨ Feature: Double-Click Zoom Label to Reset to 100%
**Files**: `main.js`, `base.css`
**Description**: Double-clicking the zoom percentage label (e.g., "100%") in any pane header now resets that pane's zoom level to 100%. Added `cursor: pointer` to `.zoom-label` to indicate interactivity.

### ✨ Feature: Blueprint Category Display in Custom Dropdown
**Files**: `system.py` (backend), `ui.js` (frontend), `instances.css` (styling)
**Description**: The native `<select>` for blueprints has been replaced with a custom dropdown that shows each blueprint's name on the left and its `aikore.category` metadata value (e.g., "Image Generation", "Training", "Audio / TTS") right-aligned in a darker color. The backend (`GET /api/system/blueprints`) now returns objects `{filename, category}` instead of plain strings, parsing the `### AIKORE-METADATA ###` block from each `.sh` file. The custom dropdown exposes the same `.value`, `.disabled`, and event interface (`change`, `input`, `focus`) as a native `<select>` so all existing dirty-detection and save/revert logic works without changes. The dropdown has Stock/Custom group headers, hover highlighting, and a selected state.

**Dropdown overlay behavior**: The dropdown panel is appended to `document.body` with `position: fixed` when opened, so it overlays all panes and is not clipped by parent `overflow`. Its width matches the trigger button's width, and its `max-height` is calculated dynamically based on available viewport space (capped at 40vh) — opening below the button, or above if there's not enough space below. A transparent `backdrop` div catches outside clicks. The dropdown closes automatically when: (1) an option is clicked, (2) the backdrop is clicked, (3) Escape is pressed, (4) the trigger scrolls out of view, or (5) the wrapper is removed from the DOM (table re-render).

---

## 11. Bugs Found and Fixed in Session 5


## 11. Bugs Found and Fixed in Session 5 (SUPERSEDED — see Session 6 for corrected status)

Sections 8.26, 8.27, 8.32, 8.33 were marked as fixed in Session 5 but are still present after user testing. See Section 13 for corrected status.

---

## 12. Known Issue (Not Fixed — Report Only)

### 🟠 8.28 — `parse_blueprint_metadata()` Ignores Custom Blueprints ✅ FIXED
**Files**: `process_manager.py`
**Problem**: `parse_blueprint_metadata()` only looked in `BLUEPRINTS_DIR` (stock). Custom blueprints in `CUSTOM_BLUEPRINTS_DIR` were never found, so terminals for custom blueprint instances had no venv activation. This also affected `run_version_check()` and `run_command_in_instance_venv()`.
**Fix**: Added `_find_blueprint_path()` helper that checks custom dir first, then stock dir. `parse_blueprint_metadata()` now uses this helper.

### 🟠 8.29 — Terminal venv activation reads blueprint instead of launch.sh ✅ FIXED
**Files**: `process_manager.py`
**Problem**: The terminal activated the venv based on metadata parsed from the **original blueprint** file. If the instance's `launch.sh` had been modified (e.g., Save as Custom Blueprint), the terminal would not reflect the actual runtime venv.
**Fix**: Added `_parse_venv_from_launch_sh()` which reads the AIKORE-METADATA block directly from the instance's `launch.sh`. If `launch.sh` has no metadata, falls back to the blueprint metadata.

### 🟠 8.30 — Terminal Destroyed When Switching Tools ✅ FIXED
**Files**: `tools.js`, `state.js`, `tools.css`
**Problem**: Every time the user switched tools, `closeTerminal()` destroyed the xterm.js Terminal object and closed the WebSocket. When switching back, the user got a fresh terminal with no history.
**Fix**: Implemented a **persistent terminal pool** (`state.terminals = {}`) keyed by instance ID. Each terminal's xterm.js Terminal, FitAddon, and WebSocket are kept alive in memory. When switching tools, only the container is hidden. When reopening a terminal for the same instance, the existing terminal is re-shown with full history preserved.

### 🟠 8.31 — Builder State Lost When Switching Tools ✅ FIXED
**Files**: `tools.js`
**Problem**: Switching away from the builder view while a build was in progress destroyed the WebSocket and terminal. When returning, the user saw a blank terminal even though the build continued in the background.
**Fix**: `hideAllToolViews({keepBuilder: true})` is called when a build is in progress. The builder terminal and WebSocket are preserved. The builder container is hidden visually but the build continues.

---

## 13. Session 6 — Open Items & Corrected Status

### 🔴 8.26 — Builder: `ModuleNotFoundError: No module named 'torch'` ✅ FIXED (again, correctly this time)
**File**: `builder.py`
**Problem**: The previous fix (Session 6) replaced `source activate` with `conda run`, but `conda run` doesn't propagate CUDA environment variables correctly in subprocess contexts, causing the same `No module named 'torch'` error during builds.
**Fix**: Reverted to the original `source {CONDA_BASE_DIR}/bin/activate {env_name}` pattern which works correctly in `asyncio.create_subprocess_shell(executable='/bin/bash')` because bash sources the conda activate script directly. Kept the security improvements (env name validation, torch_is_installed check) from the previous fix.

### 🔴 8.27 — Welcome Animation ✅ REWRITTEN FROM SCRATCH
**Files**: `welcome/js/main.js`, `welcome/js/effects.js` (deleted), `welcome/js/renderer.js` (deleted), `welcome/index.html`
**Problem**: Original animation had multiple issues (glow overflow, stuttering, complex class hierarchy). Previous fixes were incremental and fragile.
**Fix**: Complete rewrite as a single-file animation in `main.js`. Removed glow layer entirely. Logo is pre-rendered on an offscreen canvas (accent-colored rectangles at alpha 0.35 + white characters at alpha 1.0). Wave effect via per-row clipping. Color cycling with smooth hex blending (7 accent colors, 1.2s transitions, 3.8s idle). Auto-fits viewport (85% of available space). No zoom controls — always scales to window. `rebuildOffscreen()` called only on color change (optimized, not per-frame). ResizeObserver + postMessage for iframe resize detection. Old `effects.js` and `renderer.js` deleted, `index.html` loads only `main.js`.

### 🟡 8.32b — Terminal Slightly Smaller Than Its Frame ✅ FIXED
**File**: `tools.css`
**Fix**: Changed `#terminal-content` padding from `0 1rem 1rem 1rem` to `0`. Added `position: relative` to `#terminal-content`.

### 🔴 8.34 — Terminal: Previous Terminals Show Black Screen ✅ FIXED
**Files**: `tools.js`, `tools.css`
**Problem**: Opening multiple terminals caused all but the last to show a black screen. Root cause: `openTerminal()` called `DOM.terminalContent.innerHTML = ''` which destroyed all existing terminal host DOM elements. The `state.terminals` objects (xterm.js Terminal, FitAddon, WebSocket) remained in memory but referenced destroyed DOM nodes. Additionally, `_showTerminalInstance()` used `display: none/''` toggling which caused xterm.js canvases to lose their dimensions.
**Fix**:
- Removed `DOM.terminalContent.innerHTML = ''` — terminal-content hosts all terminal pool elements
- Terminal hosts use `position: absolute` with `visibility: hidden/visible` (instead of `display: none/''`) so xterm.js canvases retain their dimensions
- `#terminal-content` CSS: added `position: relative` for absolute-positioned children
- `_showTerminalInstance()`: `terminal.refresh(0)` + `setTimeout(50ms)` to force re-render after visibility change
- `_createTerminalForInstance()`: initial fit deferred to `socket.onopen` with `requestAnimationFrame`

### 🔴 8.35 — Builder: Wrong Torchvision Version Mapping ✅ FIXED
**File**: `builder.py`
**Problem**: `TORCH_VISION_MAP` hardcoded torchvision versions were wrong (e.g., torch 2.11.0 → 0.22.0 instead of 0.26.0). Hardcoded maps are always stale on new releases.
**Fix**: Removed `TORCH_VISION_MAP` entirely. Install command is now `pip install torch=={ver} torchvision torchaudio --index-url {url}` — pip resolves compatible versions directly from the PyTorch wheel index. No version pin on torchvision/torchaudio.

### ✨ Feature: Builder Version Selects Are Now Dynamic & Independent
**Files**: `builder.py`, `api.js`, `state.js`, `tools.js`
**Description**:
- **Python versions**: Were hardcoded in `state.js`, now fetched dynamically from `/api/builder/versions/python` (conda search)
- **CUDA versions**: Were hardcoded in `state.js`, now fetched dynamically from new endpoint `/api/builder/versions/cuda` (scrapes PyTorch wheel index). Returns objects `{cu: "cu130", version: "13.0"}`
- **PyTorch versions**: Already dynamic, now preserves selection when changing CUDA (if version exists in new list, keeps it; otherwise defaults to latest)
- **Error reporting**: All fetch errors are displayed in the builder terminal with ANSI-colored messages (`[ERROR]`, `[WARN]`)
- **Fallbacks**: Each endpoint has a hardcoded fallback list in both backend and frontend if network is unavailable
- `state.versions.python` and `state.versions.cuda` now start empty, filled on builder view open
- Labels: Selects show "(Latest)" suffix on first option, "(offline)" on fallback versions

### 🔴 8.33 — 8-Minute Startup Delay ⚠️ STILL PRESENT, ROOT CAUSE UNKNOWN
**Status**: Unchanged from previous session.

---

## 14. CI/CD — GitHub Actions

### Architecture

Two workflows compose the CI pipeline, both targeting **self-hosted runners** and pushing to **GHCR** (`ghcr.io`):

| Workflow | Trigger | Tags Pushed | Cache | Purpose |
|---|---|---|---|---|
| `docker-build.yml` | Release `published` + manual `workflow_dispatch` | `:latest`, `:semver`, `:major.minor`, `:sha-xxx` | Local Buildx (`actions/cache@v4`) | Production build |
| `docker-build-test.yml` | Manual `workflow_dispatch` only | `:test` | Local Buildx (shared cache) | Pre-release validation |

### Cache Strategy

- **Type**: `type=local` on self-hosted runner disk (`/tmp/.buildx-cache`), managed by `actions/cache@v4`
- **Mode**: `mode=max` — caches all intermediate layers (including heavy `apt-get` and CUDA installs)
- **Rotation**: Write to `buildx-cache-new`, then swap after successful build (prevents cache corruption on failed builds)
- **Sharing**: Both workflows share the same cache via `restore-keys: buildx-` prefix
- **No-cache override**: `docker-build.yml` accepts a `no_cache` boolean input to force a full rebuild without cache

### Tag Strategy (docker-build.yml)

| Tag Pattern | Example | Purpose |
|---|---|---|
| `:latest` | `ghcr.io/grokuku/aikore:latest` | Always points to the most recent release |
| `:{{version}}` | `ghcr.io/grokuku/aikore:1.2.3` | Full semver — enables precise rollback |
| `:{{major}}.{{minor}}` | `ghcr.io/grokuku/aikore:1.2` | Minor track — latest patch of that branch |
| `:sha-xxx` | `ghcr.io/grokuku/aikore:sha-32b7c3b` | Commit SHA — absolute traceability |

### Removed Components (Cleanup Session 7)

The following intermediate build infrastructure was removed because the final `Dockerfile` is now fully standalone (wheels are compiled at runtime by the Module Builder):
- `build-flash-sage-wheels.yml` — workflow for compiling Flash/Sage wheels during CI
- `build-base-image.yml` — workflow for the intermediate `aikore-buildbase` image
- `flash-sage.Dockerfile` — Dockerfile for Flash/Sage wheel compilation
- `wheel-container.Dockerfile` — minimal scratch image for wheel distribution
- `Dockerfile.buildbase` — intermediate base image Dockerfile

### Key Design Decisions

1. **Local cache over registry cache**: Registry cache (`cache-to: type=registry`) caused upload timeouts on large CUDA layers (~5 GB) due to simultaneous image + cache uploads. Local cache eliminates network overhead entirely on self-hosted runners.
2. **Lowercase image name**: `${{ github.repository }}` preserves original case (e.g., `grokuku/AiKore`), but Docker registry refs must be lowercase. Both workflows compute `IMAGE_NAME_LOWER` at runtime.
3. **`.dockerignore`**: Excludes `.git`, `.github`, docs, screenshots, and other non-essential files from the build context, ensuring `COPY` instructions properly detect source changes and invalidate cache.
4. **Miniforge `latest` URL**: Uses `/releases/latest/download/` instead of a pinned version. Tradeoff: cache might serve an older Miniforge version, but a pinned version would never update without manual intervention. The `no_cache` workflow input provides an escape hatch for full rebuilds.
5. **Concurrency control**: `docker-build.yml` uses `cancel-in-progress: false` (don't kill a running production build), while `docker-build-test.yml` uses `cancel-in-progress: true` (test builds are disposable).
6. **Smoke test**: `docker-build.yml` runs `python3 -c "import sys; print(sys.version)"` in the built image to verify it starts correctly.

---

## 15. Pending Features (from features.md)

- [ ] Improve global error handling and status reporting across the entire application
- [ ] Write comprehensive user and system documentation

---

## 16. Voicebox Blueprint

**Status**: ✅ Created, tested, and functional

**Blueprint file**: `blueprints/Voicebox.sh`

### Blueprint Details

| Field | Value |
|---|---|
| Category | Audio / TTS |
| Repository | https://github.com/jamiepine/voicebox |
| Backend | FastAPI (uvicorn) |
| Frontend | React/Vite (built with bun) |
| venv_type | conda |
| venv_path | ./env |
| Python | 3.11 |
| Port | Dynamic (AiKore-managed) |
| Persistent mode | No (has web UI) |

### Key Implementation Details

- **Frontend build**: Strips `tauri` (desktop) and `landing` workspaces from `package.json`, installs bun if needed, builds with `bun x vite build`. One-time operation (skipped on restart if `frontend/` dir exists).
- **Dependency install order**: Voicebox's `backend/requirements.txt` is installed **first** (resolves all sub-dependencies with compatible versions), then torch/torchvision/torchaudio are **overwritten** with AiKore's CUDA 13.0 builds (`--force-reinstall` from `PYTORCH_INDEX_URL`). numpy is re-pinned to `<2.0` after (torch force-reinstall can pull numpy 2.x, breaking numba).
- **Custom TTS engines**: `chatterbox-tts` and `hume-tada` installed with `--no-deps` (they pin incompatible torch versions). Their sub-dependencies are already covered by `requirements.txt`.
- **Data directory**: Set via `--data-dir` flag to `${INSTANCE_CONF_DIR}/data`. Generations symlinked to `${INSTANCE_OUTPUT_DIR}` for AiKore access.
- **Model cache**: `VOICEBOX_MODELS_DIR` env var redirects HuggingFace cache to `${DATA_DIR}/models` for persistence.
- **Launch**: Uses `python -m backend.main` (not bare `uvicorn`) to pass `--data-dir` (argparse only available in `__main__`).

### Issues Encountered & Fixed During Development

| Issue | Cause | Fix |
|---|---|---|
| `unzip: not found` | bun install script requires unzip | Manual zip extraction via Python, later replaced with `curl` + `unzip` after unzip was added to Dockerfile |
| `bunx: command not found` | Manual bun install doesn't create `bunx` symlink | Use `bun x` instead of `bunx` |
| Trailing comma in package.json | `sed` JSON manipulation too fragile | Use Python `json.load/dump` to strip workspaces |
| `Could not load libtorchaudio.abi3.so` | torch 2.10.0 (AiKore) + torchaudio 2.7.0 (requirements) ABI mismatch | Install requirements first, then `--force-reinstall` torch ecosystem from cu130 index |
| `numba incompatible with numpy 2.x` | Torch force-reinstall upgraded numpy from 1.x to 2.x | Re-pin `numpy>=1.24.0,<2.0` after torch install