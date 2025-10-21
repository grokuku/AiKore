# AiKore Project Context

## 1. Project Tree

This document outlines the structure and purpose of each file within the AiKore project.

```
/
├── .github/                 # Contains GitHub Actions workflows for CI/CD.
├── aikore/                  # The AiKore backend application (Python/FastAPI).
│   ├── api/                 # FastAPI routers for different API sections.
│   │   ├── __init__.py
│   │   ├── instances.py     # API routes related to instance management.
│   │   └── system.py        # API routes related to system monitoring.
│   ├── core/                # Core business logic and process management.
│   │   ├── __init__.py
│   │   └── process_manager.py # Handles the lifecycle (start/stop) of WebUI instances as subprocesses.
│   ├── database/            # Database configuration, models, and operations.
│   │   ├── __init__.py
│   │   ├── crud.py          # Contains CRUD (Create, Read, Update, Delete) database operations.
│   │   ├── models.py        # Defines the SQLAlchemy ORM models (database tables).
│   │   └── session.py       # Configures the SQLAlchemy engine and database session.
│   ├── schemas/             # Pydantic schemas for API data validation and serialization.
│   │   ├── __init__.py
│   │   └── instance.py
│   ├── static/              # Frontend files (HTML, CSS, JavaScript).
│   │   ├── app.js
│   │   ├── index.html
│   │   └── style.css
│   ├── __init__.py          # Makes the 'aikore' directory a Python package.
│   ├── main.py              # FastAPI application entrypoint, defines all API routes.
│   └── requirements.txt     # Lists Python dependencies for the AiKore backend.
├── blueprints/              # Contains template scripts and default parameters for each supported AI tool.
│   ├── legacy/              # Older, non-dynamic blueprint scripts awaiting refactoring.
│   │   └── ...
│   ├── ComfyUI.parameters.txt
│   ├── ComfyUI.sh
│   └── 99-test-logs.sh      # A simple script for testing the logging system.
├── docker/                  # Holds Docker-specific configuration files.
│   └── root/                # Files to be copied into the root of the container's filesystem.
│       └── etc/
│           ├── nginx/
│           └── s6-overlay/
├── .gitignore               # Specifies files and directories for Git to ignore.
├── Dockerfile               # Main Dockerfile to build the final AiKore application image.
├── Dockerfile.buildbase     # Dockerfile for a base image with pre-compiled dependencies.
├── Makefile                 # Provides convenient `make` commands to manage docker-compose.
├── docker-compose.yml       # Defines the AiKore service for easy launch with Docker Compose.
├── entry.sh                 # The main script executed when the container starts.
├── functions.sh             # A library of shared shell functions used by the blueprint scripts.
├── project_context.md       # (This file) The central document explaining the project structure and vision.
└── features.md              # A document to track the implementation of new features.

## 2. Project Plan & Vision

### Mission

To transform the existing multi-script project into **AiKore**, a unified, web-based management platform for launching, managing, and monitoring AI/Stable Diffusion WebUIs and tools.

The primary goal is to provide a single, simple, and powerful control panel that abstracts away the complexity of manual configuration, offering a robust and user-friendly experience, especially for users with multi-GPU setups or long-running tasks like model training.

### Guiding Principles

1.  **Single Docker Container:** The entire system—backend, frontend, proxy, and all WebUI subprocesses—must run within a single, self-contained Docker container for maximum installation simplicity.
2.  **User-Centric Design:** The interface should be intuitive, requiring no manual file editing for day-to-day operations. All management tasks should be performed through the web UI.
3.  **Dynamic & Flexible:** The system must move from a static configuration (one folder per UI) to a dynamic one where users can create, configure, and manage multiple, independent "instances" of any given WebUI.
4.  **Robust & Persistent:** Long-running tasks (training, generation queues) must be persistent and survive browser closures or client disconnections.

### System Architecture

AiKore is a multi-component application running inside a single container, orchestrated by the `s6-overlay` process supervisor.

**Flow:** `[User] <-> [Docker Port] <-> [NGINX Reverse Proxy] <-> [AiKore Backend / WebUI Instances]`

#### Backend (The Core)
*   **Technology:** Python with the **FastAPI** framework.
*   **Responsibilities:**
    *   Serves the AiKore frontend (the main dashboard).
    *   Provides a REST API for all management actions (`/api/...`).
    *   Manages the lifecycle of WebUI instances (start/stop/monitor) as subprocesses.
    *   Dynamically starts and manages isolated KasmVNC sessions for "Persistent Mode" instances.
    *   Interacts with the SQLite database to persist instance configurations.
    *   Dynamically updates the NGINX configuration when an instance is started or stopped.
    *   Collects and serves system monitoring data (CPU, RAM, GPU stats).

#### Frontend (The Dashboard)
*   **Technology:** Standard HTML, CSS, and JavaScript (Single Page Application).
*   **Responsibilities:**
    *   Provides the main user interface.
    *   Communicates with the backend via the REST API.
    *   Features two main views:
        1.  **Instance Management Dashboard:** For creating and controlling WebUI instances.
        2.  **System Monitoring Dashboard:** For real-time resource visualization.

#### Reverse Proxy (The Router)
*   **Technology:** **NGINX**.
*   **Responsibilities:**
    *   Listens on the main container port (e.g., 9000).
    *   Routes traffic based on the URL path.

#### Database (The Memory)
*   **Technology:** **SQLite**.
*   **Responsibilities:**
    *   Stores all user-created instance configurations in a single file (`/config/aikore.db`).
    *   Ensures that the user's setup is persistent across container restarts.

### Data Model (Database Schema)

A single table `instances` will be created in the `aikore.db` SQLite database.

| Column Name       | Data Type | Nullable | Description                                                              |
|-------------------|-----------|----------|--------------------------------------------------------------------------|
| `id`              | INTEGER   | No       | Primary Key                                                              |
| `name`            | TEXT      | No       | User-defined unique name for the instance                                |
| `base_blueprint`  | TEXT      | No       | Filename of the source script (e.g., "comfyui.sh")                       |
| `gpu_ids`         | TEXT      | Yes      | Comma-separated string of GPU IDs (e.g., "0,1")                          |
| `autostart`       | BOOLEAN   | No       | If true, start on AiKore launch                                          |
| `persistent_mode` | BOOLEAN   | No       | If true, use the KasmVNC session mode                                    |
| `status`          | TEXT      | No       | Current state: "stopped", "running", etc.                                |
| `pid`             | INTEGER   | Yes      | Stores the PID of the main process group leader                          |
| `port`            | INTEGER   | Yes      | The internal port of the web application itself                          |
| `vnc_port`        | INTEGER   | Yes      | The internal port for the isolated VNC web client (`websockify`)         |
| `vnc_display`     | INTEGER   | Yes      | The internal X display number for the isolated VNC session (e.g., 1, 2)  |

## 3. Dependencies Researched

| Dependency | Version  | Date Checked | Notes                                                                                                  |
|------------|----------|--------------|--------------------------------------------------------------------------------------------------------|
| `gradio`   | `3.50.2` | 2025-10-19   | Downgraded from v4. `fill_width` argument removed in v4, breaking FluxGym. v3.50.2 is the last compatible version. |

## 4. Phased Implementation Roadmap

1.  **Phase 1: Foundation (Completed)**
    *   Establish the new project structure.
    *   Create the minimal FastAPI backend skeleton.
    *   Modify the container `entry.sh` to launch the AiKore backend.

2.  **Phase 2: Core Logic (Completed)**
    *   Implement the database layer (SQLite + SQLAlchemy).
    *   Create API endpoints for basic CRUD (Create, Read, Delete) of instances.
    *   Implement the `process_manager` to start/stop blueprints as subprocesses.

3.  **Phase 3: Frontend & Basic Management (In Progress)**
    *   Refactored instance management to use dynamic paths for configurations and outputs.
    *   Built the final, resizable multi-pane dashboard layout and applied a polished visual style.
    *   Implemented the System Monitoring feature (backend endpoint and frontend panel).
    *   Re-architected the instance logging system for perfect chronological order.
    *   Implemented Script Editing from the web UI.
    *   Simplified Configuration Management by removing `parameters.txt`.
    *   Hardened Reverse Proxy Configuration to be universally compatible.

4.  **Phase 4: Advanced Features & UX (In Progress)**
    *   **Completed in this Phase:**
        *   Architected and implemented a "Persistent Session (VNC)" mode.
        *   Conducted an in-depth debugging investigation of the `ERR_SSL_PROTOCOL_ERROR`.
        *   Through systematic testing (`curl`, `ps aux`, log analysis, permissions checks), successfully eliminated multiple false leads (browser cache, NGINX configuration logic, websockify functionality).
        *   **Identified the definitive root cause:** A fundamental permissions conflict. The AiKore backend process runs as a non-privileged user (`abc`), while the NGINX service requires its configuration files and directories to be owned by `root` for security reasons. NGINX was silently ignoring the configuration generated by AiKore because its parent directory (`/etc/nginx/locations.d`) was owned by `abc`.

    *   **Current Blocker:**
        *   An attempt to fix the issue by having the Python code change file ownership using `os.chown` failed with `[Errno 1] Operation not permitted`. This definitively confirms that the AiKore backend process does not have root privileges, which, while good security practice, prevents it from managing NGINX configuration ownership directly.

    *   **Next Steps for Resolution:**
        1.  **Stabilize the Code:** Revert the last changes in `aikore/core/process_manager.py` to remove the failing `os.chown` calls. This will restore the ability to start instances, though the original VNC access issue will persist.
        2.  **Implement Privileged Execution via `sudo`:** This is the standard and secure solution for this type of problem.
            *   **A) Dockerfile:** Modify the `Dockerfile` to install the `sudo` package.
            *   **B) Sudoers Configuration:** Add a new file in the `docker/root/etc/sudoers.d/` directory to grant the `abc` user passwordless permission to execute *only* the `chown root:root` command on the `/etc/nginx/locations.d` directory and the files within it.
            *   **C) Python Code:** Update `process_manager.py` to use `subprocess.run(['sudo', 'chown', ...])` to change ownership of the directory and the generated configuration file. This will allow the non-privileged process to perform this specific administrative task securely.

5.  **Phase 5: Refinement (Planned)**
    *   Implement the `Update` functionality for saving changes to existing instances (Name, GPU IDs, etc.).
    *   Improve error handling and status reporting.
    *   Write comprehensive documentation for the new `AiKore` system.