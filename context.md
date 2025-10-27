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
    
    | Column Name              | Data Type | Nullable | Description                                                              |
    |--------------------------|-----------|----------|--------------------------------------------------------------------------|
    | `id`                     | INTEGER   | No       | Primary Key                                                              |
    | `name`                   | TEXT      | No       | User-defined unique name for the instance                                |
    | `base_blueprint`         | TEXT      | No       | Filename of the source script (e.g., "comfyui.sh")                       |
    | `gpu_ids`                | TEXT      | Yes      | Comma-separated string of GPU IDs (e.g., "0,1")                          |
    | `autostart`              | BOOLEAN   | No       | If true, start on AiKore launch                                          |
    | `persistent_mode`        | BOOLEAN   | No       | If true, use the KasmVNC session mode                                    |
    | `is_comfyui_active_slot` | BOOLEAN   | No       | If true, this instance is mapped to the static `/comfyui/` endpoint      |
    | `status`                 | TEXT      | No       | Current state: "stopped", "starting", "stalled", "started", "error"      |
    | `pid`                    | INTEGER   | Yes      | Stores the PID of the main process group leader                          |
    | `port`                   | INTEGER   | Yes      | The internal port of the web application itself                          |
    | `vnc_port`               | INTEGER   | Yes      | The internal port for the isolated VNC web client (`websockify`)         |
    | `vnc_display`            | INTEGER   | Yes      | The internal X display number for the isolated VNC session (e.g., 1, 2)  |
    
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
    
    3.  **Phase 3: Frontend & Basic Management (Completed)**
        *   Refactored instance management to use dynamic paths for configurations and outputs.
        *   Built the final, resizable multi-pane dashboard layout and applied a polished visual style.
        *   Implemented the System Monitoring feature (backend endpoint and frontend panel).
        *   Re-architected the instance logging system for perfect chronological order.
        *   Implemented Script Editing from the web UI.
        *   Simplified Configuration Management by removing `parameters.txt`.
        *   Hardened Reverse Proxy Configuration to be universally compatible.
    
    4.  **Phase 4: Advanced Features & UX (In Progress)**
        
        *   **Robust State Management Implementation:** In addressing a UI launch issue in Persistent Mode, a major re-architecture of the instance lifecycle management was completed. This provides a significantly more robust and user-friendly experience.
            *   **Backend-Driven State:** The logic for determining an instance's status has been moved from shell scripts into the Python backend. The backend now actively monitors the application's port in a background thread.
            *   **New Statuses:** Introduced a clear state machine for instances: `stopped` -> `starting` -> `stalled` (if startup is long) -> `started`.
            *   **Real-Time UI:** The frontend now polls the backend every 2 seconds, providing a real-time view of the instance status, including visual feedback (colors, disabled buttons) for each state. This eliminates guesswork for the user during long installations.
            *   **VNC Automation (Issue Resolved):** The backend now remotely triggers the launch of Firefox *after* the target application is confirmed to be running. This completely resolves the previous issue where Firefox would start but fail to navigate to the correct URL.
        *   **System Hardening & Bug Fixes:** A series of stability improvements were implemented to refine the user experience.
            *   **State Integrity:** Instance statuses are now correctly reset to "stopped" on application startup, ensuring the UI always reflects the true state.
            *   **Log Lifecycle:** All instance logs are automatically cleared on application startup to provide a clean slate for each session.
            *   **VNC Reliability:** The VNC launcher script was made more robust to prevent race conditions during startup.
            *   **Autostart Functionality Implemented:** The application's startup event was modified to query the database for instances flagged with `autostart=True`. It now correctly launches these instances upon system initialization, ensuring user-defined services are automatically restored.
        *   **UI/UX Refinement & Feature Hardening:** Further enhancements have been made to improve usability and add features.
            *   **Trash Can Feature:** Implemented a safe-delete mechanism. When an instance is deleted, its configuration directory is now moved to a `/config/trashcan` folder instead of being permanently removed, allowing for data recovery.
            *   **Persistent Layout:** The dashboard's pane sizes are now saved to the browser's `localStorage`, so the user's layout preferences persist across page reloads.
            *   **Polished UI:** The entire user interface has been refined with consistent vertical spacing for a cleaner, more professional aesthetic. This includes the instance table rows and all components of the System Monitoring panel.
            *   **Enhanced UI Consistency:** The "Add New Instance" flow was improved to be visually identical to existing rows, and several minor bugs were fixed. Placeholders for future "Tool" and "View" actions were added.
            *   **Robust Context Menu for Tools:** Re-architected the instance actions by converting the 'Tool' and 'Script' buttons into a unified 'Tools' dropdown menu. This was implemented using a global context menu (`position: fixed`) that is dynamically positioned relative to the clicked button. This approach overcomes all container `overflow` limitations, ensuring the menu is always visible and never clipped by other UI panes. The new menu provides organized access to actions like 'Edit Script' and includes placeholders for future tools.
            *   **Embedded Instance View:** Implemented the "View" button functionality, allowing a running instance's user interface to be embedded directly into the main dashboard via an iframe. This included several CSS hardening steps to ensure the embedded view correctly fills the available space without layout issues, providing a seamless user experience.
            *   **Synchronized Terminal Resizing:** Implemented full two-way communication for the embedded terminal's dimensions. The frontend now detects pane resizes and sends the new column/row count to the backend via a WebSocket message. The backend then issues a system call to adjust the server-side PTY, ensuring that full-screen terminal applications (like `top` or editors) render correctly and adapt dynamically to UI layout changes.
        *   **ComfyUI Proxy Solution:** Resolved long-standing reverse proxy issues for ComfyUI by implementing a robust "Active Slot" mechanism. A database migration system was implemented to upgrade the schema seamlessly.
        *   **Refined User Interaction:** Reinstated the "Open" button to allow all running instances to be opened in a new, dedicated browser tab. This complements the embedded "View" feature by providing a full-screen option essential for focused work. The button's URL is dynamically updated: standard instances link to `/app/<name>/`, while the active ComfyUI instance links to the special `/comfyui/` endpoint.
        *   **ComfyUI Proxy Hardening (Completed):** The initial "Active Slot" implementation was significantly hardened to correctly handle all of ComfyUI's absolute API paths. This involved a two-file NGINX configuration system (`upstream` and `locations`) dynamically managed by the Python backend, with runtime permission fixes applied at container startup. The core functionality (UI, WebSocket, image generation) is now stable. A minor issue persists with the "Save Workflow" feature (see "Known Issues").
    
    5.  **Phase 5: Refinement (Planned)**
        *   Implement the `Update` functionality for saving changes to existing instances (Name, GPU IDs, etc.).
        *   Improve error handling and status reporting.
        *   Write comprehensive documentation for the new `AiKore` system.
    
    ## 5. Known Issues & Investigation Logs
    
    ### 5.1. ComfyUI Reverse Proxy Integration Issues
    
    *   **Date:** 2025-10-26
    *   **Status:** **Completed (with known issue)**
    *   **Summary:** The "Active Slot" mechanism is a success and has fixed all critical proxying issues. The UI loads, WebSockets connect, and image generation works. A non-critical issue remains where saving a workflow fails.
    *   **Resolved Symptoms:**
        1.  **UI State:** The ComfyUI web interface now updates its state correctly. WebSocket connection is stable.
        2.  **Image Generation:** `POST` requests to `/prompt` are correctly routed, allowing image generation to function.
    *   **Outstanding Symptom:**
        1.  **Save Action:** Attempting to save a workflow via `POST /workflows/test.json` results in an HTTP `405 Method Not Allowed`. This indicates the request is incorrectly routed to the AiKore backend instead of the ComfyUI instance.
    
    *   **Implemented Architecture: The "Active Slot" Mechanism**
        A robust solution has been implemented to address the core architectural conflict:
        1.  **Dynamic Two-File NGINX Config:** When an "active" ComfyUI instance starts, the backend generates two configuration files:
            *   `/etc/nginx/conf.d/aikore-comfyui-upstream.conf`: Defines an `upstream` block pointing to the instance's port.
            *   `/etc/nginx/locations.d/00-comfyui-active-slot.conf`: Defines all the necessary `location` blocks (for `/comfyui/`, `/ws`, `/prompt`, etc.) that use the `upstream`.
        2.  **Runtime Permissions:** A command was added to the container's `s6-overlay` startup script to `chown` the `/etc/nginx` directory. This solves permission errors when the non-root application process needs to write the dynamic configuration files.
        3.  **Cleanup on Stop:** The backend logic correctly removes both configuration files when the active instance is stopped, deactivating the proxy routes.
    
    *   **Investigation Log:**
        Multiple attempts to create a `location` block to correctly capture the `/workflows/` path have failed, including using broad regex matches and specific prefix matches (`location /workflows/`). Despite being defined in a file included before the main `location /` block, NGINX is not giving these directives priority. This suggests a subtle and complex interaction in the NGINX location matching logic that requires a dedicated deep-dive debugging session, which is outside the scope of the current implementation effort. The core functionality is deemed stable enough for release.