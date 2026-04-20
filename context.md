# AiKore: Technical Project Context & Manifest

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
│   │   ├── welcome/                    # CRT-style Welcome Screen (static HTML)
│   │   └── index.html                  # Main HTML: Split panes, all modal overlays, CDN scripts (Split.js, xterm.js, CodeMirror, SortableJS, AnsiUp), GPU stat template
│   │
│   ├── main.py                         # FastAPI entry: `lifespan` async context manager (NVML init, status reset, log cleanup, autostart), router registration, static mount
│   └── requirements.txt                # fastapi, uvicorn, sqlalchemy, pydantic, websockets, psutil, nvidia-ml-py, PyXDG
│
├── blueprints/                         # Stock installation scripts (each has AIKORE-METADATA block, sources versions.env)
├── docker/                             # Container overlay (s6 services, NGINX config)
├── entry.sh                            # Container entrypoint
├── Dockerfile                          # Neutral Image definition
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
2. Backend creates isolated Conda env `builder_py{ver}_{cu}{ver}_pt{ver}`
3. Installs exact PyTorch version from `download.pytorch.org`
4. Compiles wheel using `nvcc` (System CUDA 13.0)
5. Renames wheel with `+arch{X.Y}` suffix (e.g., `sageattention-1.0+arch8.9.whl`)
6. Stores in `/config/instances/.wheels/` with metadata in `manifest.json`

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

## 7. Bugs Already Fixed (Session 1)

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

---

## 8. Known Bugs & Issues (Remaining)

### All bugs listed below have been FIXED. This section is kept for reference.

#### 8.1 — Stale DB session passed to background copy task ✅ FIXED
**Fix**: `crud.process_background_copy()` now creates its own `SessionLocal()` context manager instead of receiving `db` as parameter. The caller in `instances.py` passes IDs only.

#### 8.2 — DB session held open for WebSocket lifetime ✅ FIXED
**Fix**: `instance_terminal_endpoint()` now calls `db.close()` immediately after reading instance data, before entering the WebSocket loop.

#### 8.3 — Duplicate event listeners on update-confirm modal buttons ✅ FIXED
**Fix**: Removed the duplicate confirm handler from `modals.js`. The cancel handler now uses `state.pendingUpdates` instead of the stale `state.instanceToUpdate`. The confirm action is handled entirely by `eventHandlers.js`.

#### 8.4 — XSS via innerHTML with wheel filenames ✅ FIXED
**Fix**: Replaced all `innerHTML` with `textContent` + `createElement` + `addEventListener` in both `tools.js` (wheels manager + builder wheels table) and `ui.js`.

### 🟠 Medium (Incorrect Behavior) — All FIXED

#### 8.5 — `get_available_ports` doesn't include `persistent_port` ✅ FIXED
**Fix**: Added `instance.persistent_port` to the `used_ports` set in `system.py`.

#### 8.6 — Cannot delete instances in `installing` or `error` status ✅ FIXED
**Fix**: Changed the check to `status not in ("stopped", "error", "installing")`.

#### 8.7 — `TORCH_VISION_MAP` outdated ✅ FIXED
**Fix**: Added versions 2.6.0→0.18.0, 2.7.0→0.19.0, 2.8.0→0.19.1, 2.9.0→0.20.0, 2.9.1→0.20.1, 2.10.0→0.21.0, 2.11.0→0.22.0.

#### 8.8 — Conda env name not sanitized → shell injection ✅ FIXED
**Fix**: Added `re.match(r'^[a-zA-Z0-9_-]+$', env_name)` validation before using `env_name` in shell commands.

#### 8.9 — Rollback logic for directory rename is fragile ✅ FIXED
**Fix**: Replaced `'new_dir' in locals()` with an actual `os.path.isdir()` check, wrapped in a try/except with logging.

#### 8.10 — `InstanceUpdate` schema missing `port` field ✅ FIXED
**Fix**: Added `port: int | None = None` to `InstanceUpdate` schema.

### 🟡 Minor (Quality / Robustness) — All FIXED

#### 8.11 — `INSTANCES_DIR` hardcoded in 3 separate files ✅ FIXED
**Fix**: Created `aikore/config.py` with centralized constants. All files now import from there.

#### 8.12 — `setInterval` for system stats never cleared ✅ FIXED
**Fix**: Stats polling now pauses when `document.hidden` is true and resumes on visibility change.

#### 8.13 — `shutil.rmtree` without `onexc` in `crud.py` ✅ FIXED
**Fix**: Added `_on_rm_error` handler and `onexc=_on_rm_error` to all `shutil.rmtree` calls in `crud.py`.

#### 8.14 — Unused `import subprocess` in `instances.py` ✅ FIXED
**Fix**: Removed the import.

#### 8.15 — `status-error` CSS color may be unclear ✅ FIXED
**Fix**: Changed from Bootstrap red (`#dc3545`, same as delete button) to dark red (`#8b0000`) with light red text (`#ffcccc`) and a `1px solid #dc3545` border for distinction.

---

## 8.16–8.22 — Bugs Found and Fixed in Session 2 (Full Code Review Pass)

### 🟠 Medium

#### 8.16 — `InstanceUpdate` schema missing `persistent_port` and `persistent_display` ✅ FIXED
**Files**: `schemas/instance.py`, `instances.py`
**Problem**: `InstanceUpdate` had `port` but not `persistent_port` or `persistent_display`. When switching from persistent to normal mode, `final_update_data` contained `persistent_port: None` and `persistent_display: None`, but Pydantic silently dropped them because the schema didn't declare those fields. The switch to normal mode never actually cleared the VNC ports in DB.
**Fix**: Added `persistent_port: int | None = None` and `persistent_display: int | None = None` to `InstanceUpdate`.

#### 8.17 — Double-commit pattern in `update_instance_details` ✅ FIXED
**File**: `instances.py`
**Problem**: The code did `setattr(db_instance, field, value)` in a loop, then separately called `crud.update_instance()` which does `setattr` + `commit` again. This double-commit was prone to race conditions and could overwrite the manually-set fields if `InstanceUpdate` didn't include them (which was the case for `persistent_port`/`persistent_display` before fix 8.16).
**Fix**: Removed the manual `setattr` loop. `crud.update_instance()` is now the single source of truth for the commit.

### 🟡 Minor

#### 8.18 — `stat.S_IWRITE` is Windows-only, should be `stat.S_IWUSR` ✅ FIXED
**Files**: `instances.py`, `crud.py`
**Problem**: `stat.S_IWRITE` is a Windows-specific constant (value 128). On Linux it happens to work because `S_IWRITE == S_IWUSR == 128`, but using `S_IWRITE` is non-portable and semantically incorrect.
**Fix**: Changed to `stat.S_IWUSR` (POSIX standard) in both files.

#### 8.19 — XSS in `ui.js` status cell via `innerHTML` ✅ FIXED
**File**: `ui.js`
**Problem**: `row.insertCell().innerHTML = '<span ...>${instance.status}</span>'` — while `status` comes from the backend and is constrained to known values, using `innerHTML` with dynamic data is inconsistent with the XSS fixes in 8.4.
**Fix**: Replaced with `createElement('span')` + `textContent`.

#### 8.20 — XSS in `tools.js` error messages via `innerHTML` ✅ FIXED
**File**: `tools.js`
**Problem**: Error messages like `Error: ${e.message}` were inserted via `innerHTML`. A crafted error message containing HTML tags could inject markup.
**Fix**: Added `.replace(/</g, '&lt;').replace(/>/g, '&gt;')` sanitization on `e.message`.

#### 8.21 — `pollTimeoutId` missing from `state.js` initialization ✅ FIXED
**File**: `state.js`
**Problem**: `state.pollTimeoutId` is used in `main.js` (`scheduleNextPoll`) but never initialized in `state.js`. Works by accident (undefined is falsy) but is fragile.
**Fix**: Added `pollTimeoutId: null` to `state` export.

#### 8.22 — Duplicate comment in `state.js` ✅ FIXED
**File**: `state.js`
**Problem**: `// --- NEW: Custom Versions Configuration ---` was duplicated on consecutive lines.
**Fix**: Removed the duplicate comment.

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

### 🔴 8.26 — Builder: `ModuleNotFoundError: No module named 'torch'` ⚠️ STILL PRESENT
**File**: `builder.py`
**Problem**: When building a module (e.g., SageAttention), `setup.py` fails with `import torch: No module named 'torch'`. The build command prefixes everything with `source {CONDA_BASE_DIR}/bin/activate {env_path}` where `env_path` is the **full path** (e.g., `/home/abc/miniconda3/envs/builder_py312_cu130_pt251`). However, the legacy conda `activate` script at `/home/abc/miniconda3/bin/activate` expects an **environment name**, not a full path. Passing a full path silently fails or does nothing, so `python -u` resolves to the system Python which has no torch.
**Root cause**: `source activate` with a full path doesn't work. The script expects a name like `builder_py312_cu130_pt251`.
**Note**: `process_manager.py` uses `source activate {full_venv_path}` for INSTANCE environments at paths like `/config/instances/{name}/env` — these work because they're not conda-named envs. The builder creates conda-named envs under `/home/abc/miniconda3/envs/`.
**Required fix**: Revert `activate_prefix` to use env NAME: `source {CONDA_BASE_DIR}/bin/activate {env_name}`. Revert env existence check to use conda CLI instead of `os.path.isdir`.

### 🔴 8.27 — Welcome Animation: Glow/BG Fill Overflow on Zoom-Out ⚠️ STILL PRESENT
**Files**: `welcome/js/renderer.js`, `welcome/js/effects.js`, `welcome/js/main.js`, `welcome/style.css`
**User clarification**: The ASCII characters render correctly. The bug is the **colored background glow/fill** that bleeds out and creates a solid colored block when zooming out. This is the semi-transparent layer behind the characters (`globalAlpha: 0.4` rectangles + blurred glow with `globalCompositeOperation: 'screen'`).
**Root cause**: The glow blur radius is fixed at 6px regardless of font size. When the canvas is small (zoom-out, font ~4-6px), a 6px blur creates a massive colored wash that overwhelms the tiny characters and merges into a solid block. Per-row clip-based wave draws the ENTIRE glow canvas per row — overlapping clipped glows accumulate.
**What works**: Pre-rendered offscreen canvas architecture (no per-frame fillText). ResizeObserver + postMessage for iframe resize. Stuttering is resolved.
**What needs fixing**:
1. Glow blur radius must scale with font size (e.g., `blur = max(1, fontSize * 0.4)`)
2. Glow alpha must decrease at small sizes to prevent overwhelming the text
3. Consider disabling glow entirely below a threshold font size (e.g., < 10px)
4. Per-row clip wave may need glow accumulation prevention

### 🟡 8.32b — Terminal Slightly Smaller Than Its Frame
**Files**: `tools.css`
**Problem**: Terminal xterm.js instance fills most of the container but leaves a small gap at edges due to container `padding: 0 1rem 1rem 1rem`. Terminal already resized correctly before the CSS changes. The small gap is a minor cosmetic issue from intentional padding.
**Note**: Can be removed specifically for terminal view if desired.

### 🔴 8.33 — 8-Minute Startup Delay ⚠️ STILL PRESENT, ROOT CAUSE UNKNOWN
**Files**: `builder.py`, `main.py`, `entry.sh`, `docker/`
**Problem**: 8-minute delay between "Waiting for application startup" and "Application startup complete". `import torch` was removed from module level (valid optimization, but not the cause on NVMe/ZFS). User reports **zero timing messages appear in logs** despite timing logging being added to `main.py`, suggesting the delay is not in the Python process.
**Key insight**: The bottleneck is almost certainly **outside the Python process** — likely in s6-overlay service orchestration, `entry.sh`, or a blocking service dependency (waiting for NVIDIA driver, KasmVNC daemon, X11 socket). Alternatively, the modified code was not rebuilt into the Docker image.
**Actions taken**:
- Removed `import torch` from `builder.py` module level (valid optimization regardless)
- Added timing logging to `main.py` (may not execute if delay is before Python starts)
**Next steps**:
- Check `entry.sh` and s6-overlay service scripts for `sleep`, `until`, or blocking waits
- Add `PYTHONUNBUFFERED=1` to container environment
- Examine s6-overlay service definitions for sequential blocking services
- Confirm the Docker image is actually rebuilt with the modified code

### ✅ Confirmed working (user-tested this session)
- 8.28/8.29: `parse_blueprint_metadata()` finds custom blueprints + terminal reads `launch.sh`
- 8.30: Persistent terminals — switching tools no longer destroys terminal state
- 8.31: Builder state persists during build when switching tools
- Animation stuttering resolved (pre-rendered offscreen canvas)
- Terminal auto-resizes on split pane drag (was already working before changes)

---

## 14. Pending Features (from features.md)

- [ ] Improve global error handling and status reporting across the entire application
- [ ] Write comprehensive user and system documentation