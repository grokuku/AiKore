# AiKore: Technical Project Context & Manifest
    
    ## 0. META: Interaction Rules & Protocols
    
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
    
    AiKore is a monolithic orchestration platform designed to manage AI WebUIs inside a **single Docker container**.
    
    ### Core Stack
    *   **Orchestration**: `s6-overlay` (manages backend services and NGINX).
    *   **Backend**: Python 3.12 + **FastAPI** + **SQLAlchemy** (SQLite).
    *   **Frontend**: Vanilla JavaScript (ES Modules). Uses `Split.js`, `xterm.js`, `CodeMirror`.
    *   **Networking**: **NGINX** (Dynamic Reverse Proxy) + **KasmVNC** (Persistent Desktop Sessions).
    *   **UI Standards**: Global scaling at **80%** (via root font-size) to maximize information density.
    
    ---
    
    ## 2. Project Structure & File Tree
    
    ```text
    .
    ├── aikore/                             # MAIN APPLICATION PACKAGE
    │   ├── api/                            # API Endpoints (Routers)
    │   │   ├── __init__.py
    │   │   ├── instances.py                # CORE: CRUD, Actions (Start/Stop), Port Self-Healing, Websockets
    │   │   └── system.py                   # System Stats (NVML), Blueprint listing
    │   │
    │   ├── core/                           # Business Logic
    │   │   ├── __init__.py
    │   │   ├── blueprint_parser.py         # Reads metadata headers from .sh files
    │   │   └── process_manager.py          # BRAIN: Subprocess mgmt, PTY generation, NGINX config generation
    │   │
    │   ├── database/                       # Persistence Layer
    │   │   ├── __init__.py
    │   │   ├── crud.py                     # DB Operations (Create/Read/Update/Delete)
    │   │   ├── migration.py                # Auto-migration logic on startup
    │   │   ├── models.py                   # SQLAlchemy definitions (Instances, Meta)
    │   │   └── session.py                  # SQLite connection setup
    │   │
    │   ├── schemas/                        # Pydantic Models (Validation)
    │   │   ├── __init__.py
    │   │   └── instance.py                 # Instance schemas (Base, Create, Read, Update)
    │   │
    │   ├── static/                         # FRONTEND ASSETS
    │   │   ├── css/
    │   │   │   ├── base.css                # Layout (80% Scale) & Split.js
    │   │   │   ├── components.css          # Context Menus, Compact Progress Bars
    │   │   │   ├── instances.css           # Compact Table (28px rows), Grouping logic
    │   │   │   ├── modals.css              # Popups
    │   │   │   └── tools.css               # Terminal/Editor styling
    │   │   ├── js/
    │   │   │   ├── api.js                  # Fetch wrappers
    │   │   │   ├── eventHandlers.js        # Global Save & Creation at bottom logic
    │   │   │   ├── main.js                 # Entry Point: Polling & Grouped Rendering
    │   │   │   ├── modals.js               # Modal logic
    │   │   │   ├── state.js                # Centralized State Store
    │   │   │   ├── tools.js                # Tools (Terminal, Editor, Welcome) logic
    │   │   │   └── ui.js                   # DOM Manipulation (Dirty rows, Normalization)
    │   │   ├── welcome/                    # "CRT Style" Welcome Screen
    │   │   └── index.html                  # Main HTML Entry Point
    │   │
    │   ├── main.py                         # FastAPI Entry Point (Startup logic)
    │   └── requirements.txt                # Backend Python Dependencies
    │
    ├── blueprints/                         # INSTALLATION SCRIPTS
    │   ├── legacy/                         # Old scripts archive
    │   ├── ComfyUI.sh                      # Example Blueprint
    │   ├── FluxGym.sh                      # Example Blueprint
    │   └── ...
    │
    ├── docker/                             # CONTAINER OVERLAY
    │   └── root/
    │       └── etc/
    │           ├── nginx/conf.d/aikore.conf # Main NGINX Config (Proxy & Websockets)
    │           ├── s6-overlay/             # S6 Services Definition
    │           │   ├── s6-init.d/          # Init scripts (Permissions)
    │           │   └── s6-rc.d/            # Service Run Scripts (svc-app, svc-nginx)
    │           └── sudoers.d/              # Sudo rules for 'abc' user
    │
    ├── scripts/                            # HELPER SCRIPTS
    │   ├── kasm_launcher.sh                # Orchestrates Persistent Mode (Xvnc + Openbox + App)
    │   └── version_check.sh                # Env diagnostics tool
    │
    ├── Dockerfile                          # Main Image Definition
    ├── Dockerfile.buildbase                # Builder Image (Wheels compilation)
    ├── docker-compose.yml                  # Production Deployment
    ├── docker-compose.dev.yml              # Development Deployment
    ├── entry.sh                            # Container Runtime Entrypoint (Activates Conda -> Python)
    ├── functions.sh                        # Bash Library for Blueprints (Symlinks, Git Sync)
    ├── Makefile                            # Command shortcuts
    └── requirements.txt                    # (Root reqs, usually symlinked or copied to aikore/)
    ```
    
    ---
    
    ## 3. Key Concepts & Logic
    
    ### Instance Types & Families
    1.  **Standard**: Headless (NGINX proxy).
    2.  **Persistent**: GUI (KasmVNC via dedicated port).
    3.  **Satellite**:
        *   **Concept**: A lightweight instance that reuses the Parent's installation (venv, code) but has its own Output folder and runtime config (GPU, Port).
        *   **UI Representation**: Grouped visually with the Parent in a single block (via `<tbody>` tags in `main.js`). Dragging affects the whole family.
        *   **Constraints**: `base_blueprint` and `output_path` are inherited from the Parent and **locked** (read-only) in the UI.
    
    ### UI/UX Design Standards (Ultra-Compact)
    *   **Scale**: The entire interface is scaled down to **80%** via root font-size.
    *   **Table Metrics**: Rows are compacted to a fixed height of **28px** (including inputs, status badges, and buttons).
    *   **Creation Flow**: New instance rows are inserted at the **bottom** of the table and automatically **scrolled into view** to match the natural order of new entries.
    *   **Grouping**: The visual spacer between instance groups (tbody) is removed to achieve maximum vertical density.
    
    ### Port Management
    *   **Public Pool**: Range defined in Docker Compose (`AIKORE_INSTANCE_PORT_RANGE`, default `19001-19020`).
    *   **Normal Mode**: `port` (internal app) = Public Pool Port.
    *   **Persistent Mode**: `persistent_port` (VNC) = Public Pool Port. `port` (internal app) = Ephemeral (Random).
    *   **Self-Healing**: Auto-allocation occurs in `api/instances.py` on startup if ports are missing/null.
    
    ### Lazy Filesystem Provisioning
    *   **Principle**: Creating an instance in the DB (especially Satellites) does **not** create a folder immediately in `/config/instances`.
    *   **Trigger**: The folder structure is created by `core/process_manager.py` only when the instance is **started** for the first time, to store `output.log` and the PID file.
    
    ---
    
    ## 4. Database Schema (V5)
    
    | Column | Type | Description |
    | :--- | :--- | :--- |
    | `id` | Int | Primary Key. |
    | `parent_instance_id` | Int | Links Satellite to Parent. Null for Root instances. |
    | `name` | String | Unique name (folder name). |
    | `base_blueprint` | String | Script filename (e.g., `ComfyUI.sh`). |
    | `status` | String | `stopped`, `starting`, `started`, `installing`, `error`. |
    | `gpu_ids` | String | `CUDA_VISIBLE_DEVICES` string (e.g., "0,1"). |
    | `port` | Int | Internal HTTP port for the application. |
    | `persistent_mode` | Bool | True = Launches KasmVNC stack. |
    | `persistent_port` | Int | Public VNC port (if enabled). |
    | `persistent_display`| Int | X11 Display ID (e.g., 10 for :10). |
    | `output_path` | String | Override output folder path. |
    | `hostname` | String | Custom URL override (for local DNS). |
    | `use_custom_hostname`| Bool | Toggle for hostname usage. |
    | `autostart` | Bool | (V5) Start the instance automatically when the container boots. |