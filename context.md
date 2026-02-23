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

AiKore is a monolithic orchestration platform designed to manage AI WebUIs inside a **single Docker container**. It relies on a "Neutral Image Architecture", meaning the base Docker image only provides the OS, the system-level CUDA Toolkit, and Conda, leaving module compilation to the backend.

### Core Stack
*   **Orchestration**: `s6-overlay` (manages backend services and NGINX).
*   **Backend**: Python 3.12 + **FastAPI** + **SQLAlchemy** (SQLite).
*   **Frontend**: Vanilla JavaScript (ES Modules). Uses `Split.js`, `xterm.js`, `CodeMirror`, `AnsiUp`.
*   **Networking**: **NGINX** (Dynamic Reverse Proxy) + **KasmVNC** (Persistent Desktop Sessions).
*   **UI Standards**: Global scaling at **80%** (via root font-size) to maximize information density.

---

## 2. Project Structure & File Tree

.
├── aikore/                             # MAIN APPLICATION PACKAGE
│   ├── api/                            # API Endpoints (Routers)
│   │   ├── __init__.py
│   │   ├── builder.py                  # BUILDER: Compiles wheels in isolated Conda envs, manages WebSockets & Downloads.
│   │   ├── instances.py                # CORE: CRUD, Actions (Start/Stop), Port Self-Healing, Websockets, Wheel Sync.
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
│   │   │   └── tools.css               # Tools layout. Handles Resizers & Grid.
│   │   ├── js/
│   │   │   ├── api.js                  # Fetch wrappers
│   │   │   ├── eventHandlers.js        # Global Save & Creation at bottom logic
│   │   │   ├── main.js                 # Entry Point: Polling & Grouped Rendering, Builder button injection
│   │   │   ├── modals.js               # Modal logic
│   │   │   ├── state.js                # Centralized State Store
│   │   │   ├── tools.js                # Tools logic. Handles WS streams, Column Resizing, Wheel Manager.
│   │   │   └── ui.js                   # DOM Manipulation (Dirty rows, Normalization)
│   │   ├── welcome/                    # "CRT Style" Welcome Screen
│   │   └── index.html                  # Main HTML Entry Point
│   │
│   ├── main.py                         # FastAPI Entry Point (Startup logic, Router registration)
│   └── requirements.txt                # Backend Python Dependencies
│
├── blueprints/                         # INSTALLATION SCRIPTS
│   └── ...
│
├── config/
│   └── instances/
│       ├── .wheels/                    # GLOBAL: Persistent storage for compiled .whl files & manifest.json
│       └── {instance_name}/
│           └── wheels/                 # LOCAL: Synced wheels specific to this instance
│
├── docker/                             # CONTAINER OVERLAY
│   └── root/etc/nginx/conf.d/aikore.conf # Main NGINX config (contains specific WS Upgrade blocks)
│
├── scripts/                            # HELPER SCRIPTS
│   └── ...
│
├── entry.sh                            # Container startup (sets --no-access-log for uvicorn)
├── Dockerfile                          # Main Neutral Image Definition (OS + System CUDA)
└── versions.env                        # Centralized Version Manifest (Torch, CUDA Archs, etc.)

---

## 3. Key Concepts & Logic

### Instance Types & Families
1.  **Standard**: Headless (NGINX proxy).
2.  **Persistent**: GUI (KasmVNC via dedicated port).
3.  **Satellite**: lightweight instance reusing Parent's venv.

### Centralized Versioning (`versions.env`)
*   To maintain consistency, all PyTorch ecosystem versions (Torch, Vision, Audio) and target CUDA architectures are stored in `versions.env`.
*   This file is injected into the Docker container and automatically sourced by bash profiles and installation blueprints.

### Module Builder & Wheel Management
*   **Purpose**: Compile heavy Python/CUDA modules (e.g., `SageAttention`, `FlashAttn`) dynamically to match the host's GPU architecture, using the system-level CUDA toolkit provided by the base image.
*   **Workflow**:
    1.  **Build**: Uses isolated Conda envs to compile wheels from builder presets into `config/instances/.wheels` (Global).
    2.  **Sync**: Users use the **"Manage Wheels"** tool to select wheels. The backend copies them to `config/instances/{name}/wheels` (Local).
    3.  **Install**: Blueprints detect files in the local `/wheels` folder and install them via `pip install /wheels/*.whl` *before* processing requirements.
*   **Conflict Prevention**: Blueprints strictly filter `requirements.txt` (via `grep -v`) to exclude packages provided by local wheels to prevent PIP from overwriting optimized versions.

### UI/UX Design Standards (Ultra-Compact)
*   **Scale**: Global **80%** scale.
*   **Table Metrics**: Rows at **28px**.
*   **Dynamic Buttons**: Secondary action buttons (like "Build Module") are injected dynamically near primary actions.

### Port Management
*   Public Pool (Docker Compose) vs Internal Ephemeral Ports.
*   Self-healing logic in `instances.py`.

### Lazy Filesystem Provisioning
*   Instance folders created only on the first `start` action.

---

## 4. Database Schema (V5)

| Column | Type | Description |
| :--- | :--- | :--- |
| `id` | Int | Primary Key. |
| `parent_instance_id` | Int | Links Satellite to Parent. |
| `name` | String | Unique name. |
| `base_blueprint` | String | Script filename. |
| `status` | String | `stopped`, `starting`, `started`, `installing`, `error`. |
| `gpu_ids` | String | `CUDA_VISIBLE_DEVICES`. |
| `port` | Int | Internal HTTP port. |
| `persistent_mode` | Bool | GUI Toggle. |
| `persistent_port` | Int | Public VNC port. |
| `persistent_display`| Int | X11 Display ID. |
| `output_path` | String | Override output folder. |
| `hostname` | String | Custom URL override. |
| `use_custom_hostname`| Bool | Toggle for hostname. |
| `autostart` | Bool | Container boot start toggle. |