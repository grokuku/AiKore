# AiKore: Technical Project Context & Manifest

## 0. META: File Purpose & Update Protocols

### Purpose
This file serves as the **primary source of truth** and **cognitive map** for the Large Language Model (LLM) working on AiKore. Its goal is to provide a complete architectural understanding without requiring the LLM to read the source code of every file in every session. It bridges the gap between the raw file tree and the high-level business logic.

### Protocol for Updates
When the user requests a "context update" or when a major feature is implemented, the following information MUST be integrated/updated in this file:
1.  **Structural Changes**: If files are created, renamed, moved, or deleted, update **Section 2 (File Structure)** to reflect the new tree and the responsibility of the new files.
2.  **Schema Evolutions**: If `models.py` or `migration.py` changes, update **Section 4 (Database Schema)** to reflect the current V-version and columns.
3.  **Logic Shifts**: If the core way the backend handles processes, ports, saving, or networking changes, update **Section 3 (Key Concepts)**.
4.  **New Dependencies**: If `Dockerfile` or `requirements.txt` changes significantly (new tools like KasmVNC, new libs), update **Section 1 (Stack)**.

**Golden Rule**: Never paste raw code blocks in this file. Use concise, high-level functional descriptions to minimize token usage while maximizing understanding.

---

## 1. System Overview

AiKore is a monolithic orchestration platform designed to manage AI WebUIs inside a **single Docker container**. It acts as a process supervisor, a reverse proxy manager, and a persistent configuration layer.

### Core Stack
*   **Orchestration**: `s6-overlay` (manages backend services and NGINX).
*   **Backend**: Python 3.12 + **FastAPI** + **SQLAlchemy** (SQLite).
*   **Frontend**: Vanilla JavaScript (ES Modules). No framework. Uses `Split.js` for layout, `xterm.js` for terminal, `CodeMirror` for editing.
*   **Networking**: **NGINX** (Dynamic Reverse Proxy) + **KasmVNC** (Persistent Desktop Sessions).

---

## 2. File Structure & Responsibilities

This section details every file in the project to provide a complete understanding of the architecture without needing to read the content of every file.

### Root Directory
*   `Dockerfile` : The main build script. Sets up system deps (CUDA, tools), installs KasmVNC/Firefox, copies the app, and configures permissions (s6-overlay).
*   `Dockerfile.buildbase` : Specialized builder image that compiles heavy Python wheels (Flash Attention, Torch, etc.) to speed up the main build.
*   `docker-compose.yml` : Production deployment config. Defines ports, volumes, and GPU access.
*   `docker-compose.dev.yml` : Development config (maps local source to container).
*   `entry.sh` : The container's payload script. Activates Conda environment and launches the Uvicorn (FastAPI) server.
*   `functions.sh` : Library of bash functions used by Blueprints. Handles `sl_folder` (symlinking models/outputs), `sync_repo` (git management), and `clean_env`.
*   `main.py` : FastAPI entry point. Initializes the DB, runs migrations, clears old logs, handles autostart instances, and mounts static files/routers.
*   `Makefile` : Shortcuts for docker-compose commands (up, down, logs).
*   `requirements.txt` : Python dependencies for the **AiKore Backend** (FastAPI, SQLAlchemy, psutil, etc.), not the AI apps.

### 📁 aikore/ (The Application)
#### `api/` (API Endpoints)
*   `__init__.py` : Package marker.
*   `instances.py` : **Core Logic**. Handles CRUD for instances, start/stop/restart/copy actions, websocket terminal connection, and file editing. Contains the "Self-Healing" logic for ports.
*   `system.py` : Read-only endpoints. System stats (GPU/CPU/RAM), listing blueprints, debug NGINX.

#### `core/` (Business Logic)
*   `__init__.py` : Package marker.
*   `blueprint_parser.py` : Reads metadata headers (e.g., `# aikore.venv_type`) from `.sh` blueprint files.
*   `process_manager.py` : **The Brain**.
    *   Manages `subprocess.Popen` for instances.
    *   Handles PTY (Pseudo-terminal) generation for xterm.js.
    *   Generates dynamic NGINX configs in `/etc/nginx/locations.d/`.
    *   Monitors instance health via background threads.

#### `database/` (Persistence)
*   `__init__.py` : Package marker.
*   `crud.py` : Database abstraction layer. Functions to Create, Read, Update, Delete instances in SQLite. Handles Satellite creation logic.
*   `migration.py` : **Critical**. automatically migrates DB schema on startup (e.g., V4 -> V5). Checks schema version in `aikore_meta` table.
*   `models.py` : SQLAlchemy definitions for the `instances` and `aikore_meta` tables.
*   `session.py` : Database connection setup (`sqlite:////config/aikore.db`).

#### `schemas/` (Pydantic Models)
*   `__init__.py` : Package marker.
*   `instance.py` : Data validation models for API requests/responses (Create, Update, Read schemas).

#### `static/` (Frontend Assets)
*   `index.html` : The single HTML entry point. Contains the layout skeleton and modal templates.
*   **`css/`** :
    *   `base.css` : Global layout, split-pane logic.
    *   `components.css` : Context menus, monitoring bars, toasts.
    *   `instances.css` : Styling for the Instance Table and Status badges.
    *   `modals.css` : Styling for popups.
    *   `tools.css` : Styling for Terminal, Editor, Log viewer.
*   **`js/`** :
    *   `api.js` : Wrapper functions for all `fetch` calls to the backend.
    *   `eventHandlers.js` : Connects DOM events (clicks) to logic. Handles the "Tools Menu" and "Global Save".
    *   `main.js` : Entry point. Initializes state, sets up Split.js, runs the **Polling Loop** for instance updates.
    *   `modals.js` : Logic for showing/hiding modals and executing their confirmed actions.
    *   `state.js` : Centralized state management (DOM references, active instance IDs, config).
    *   `tools.js` : Logic for initializing/destroying xterm.js, CodeMirror, and Log Viewers.
    *   `ui.js` : Rendering logic. Builds the Instance Table rows, updates Progress Bars, handles "Dirty Row" detection.

### 📁 blueprints/ (The Scripts)
*   `*.sh` (e.g., `ComfyUI.sh`, `FluxGym.sh`) : Installation and Launch scripts for specific AI tools. They define how to clone, install deps, and run the app.
*   `legacy/` : Old scripts kept for reference.

### 📁 docker/ (Container Overlay)
*   `root/` : Files copied to the container root `/`.
    *   `etc/nginx/conf.d/aikore.conf` : Main NGINX config. Sets up the Reverse Proxy and WebSocket handling.
    *   `etc/s6-overlay/...` : Service definitions.
        *   `99-base-perms.sh` : Fixes permissions on `/config` at startup.
        *   `svc-app` : The service that runs `entry.sh` (AiKore Backend).
        *   `svc-nginx` : The service that runs NGINX.
        *   `svc-nginx-reloader` : A loop that watches for a flag file to reload NGINX config dynamically.

### 📁 scripts/ (Helpers)
*   `kasm_launcher.sh` : Orchestrates **Persistent Mode**. Starts Xvnc (virtual screen), Openbox (Window Manager), and the target Application script together.
*   `version_check.sh` : Script run by the "Version Check" tool to gather env info (Python libs, CUDA version).

---

## 3. Key Concepts & Logic

### Instance Types
1.  **Standard**: Headless. Accessed via NGINX proxy (`/instance/name/`).
2.  **Persistent**: GUI (X11). Accessed via KasmVNC on a dedicated public port.
3.  **Satellite**: Links to a Parent Instance. Shares files/env but has unique runtime config (port, logs).

### Port Management Logic
*   **Public Pool**: Defined in Docker Compose (default `19001-19020`).
*   **Normal Mode**: `port` (internal) = Public Pool Port. `persistent_port` = None.
*   **Persistent Mode**: `persistent_port` = Public Pool Port. `port` (internal) = Random Ephemeral Port (for VNC to connect to).
*   **Self-Healing**: On start, if an instance has no ports, `api/instances.py` automatically allocates them.

### Frontend Update Logic (Global Save)
*   Changing an input (Name, GPU, etc.) does **not** trigger an API call.
*   It marks the row as `row-dirty` (yellow highlight).
*   The "Save Changes" button collects all dirty rows and sends batch updates.
*   Logic handles "Hot Swap" (metadata changes) vs "Cold Swap" (restart required).

---

## 4. Database Schema (V5)

| Column | Type | Description |
| :--- | :--- | :--- |
| `id` | Int | PK |
| `name` | String | Instance name (folder name). |
| `base_blueprint` | String | Script filename. |
| `parent_instance_id` | Int | **(V5)** ID of parent if Satellite. |
| `status` | String | `stopped`, `starting`, `stalled`, `started`, `installing`, `error`. |
| `gpu_ids` | String | `CUDA_VISIBLE_DEVICES` value. |
| `port` | Int | Internal HTTP port. |
| `persistent_mode` | Bool | True = KasmVNC. |
| `persistent_port` | Int | Public VNC port. |
| `persistent_display`| Int | X11 Display ID (:10). |
| `output_path` | String | Override output folder. |
| `hostname` | String | Custom URL override. |