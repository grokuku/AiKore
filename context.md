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
            | `port`                   | INTEGER   | Yes      | The **public-facing** port assigned by the user for direct access.       |
            | `vnc_port`               | INTEGER   | Yes      | The internal port for the isolated VNC web client (`websockify`)         |
            | `vnc_display`            | INTEGER   | Yes      | The internal X display number for the isolated VNC session (e.g., 1, 2)  |
            | `access_pattern`         | TEXT      | No       | Defines URL style for 'Open' button: `port` or `subdomain`. Default: `port`. |
            
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
                
                *   **Robust State Management Implementation:** ... (Completed)
                *   **UI/UX Refinement & Feature Hardening (Completed):** Resolved UI regressions by restoring missing elements (Logs/Update buttons, Autostart/Persistent checkboxes) and correcting the action button layout. The "Access URL" display was enhanced to show the full, clickable URL for better user feedback.
                *   **System Hardening & Bug Fixes (Completed):** Investigated and resolved a critical `500 Internal Server Error` occurring during instance port activation. The root cause was identified as the `socat` dependency missing from the Docker environment. The fix involved hardening the Python backend to provide clearer error reporting for missing commands and updating the `Dockerfile` to install the required package.
                *   **ComfyUI Proxy Hardening (Completed):** ... (Completed)
                *   **Dynamic Port Management & Hybrid Access Model (Completed):** To overcome the inherent limitations and fragility of reverse-proxying applications through sub-paths (like the ComfyUI "Active Slot"), a fundamental architectural shift was implemented. The system now exposes instances on dedicated host ports, giving the user full control over network access.
                    *   **User-Defined Public Ports:** At creation, each instance is assigned a stable, user-defined public port (e.g., `50001`). This port is stored permanently in the database.
                    *   **Dynamic Port Activation:** A new `Activate`/`Deactivate` mechanism allows users to dynamically map (or unmap) an instance's public port to its running process via an internal NAT (`socat`). This action does not require restarting the instance, allowing for instant switching.
                    *   **Conflict Management:** The UI now intelligently handles port conflicts. If a user tries to activate an instance on a port that is already in use, a confirmation dialog appears, allowing for a forced takeover.
                    *   **Configurable Access URLs:** A new `access_pattern` setting (`port` or `subdomain`) allows users to define how the `Open` button URL is constructed, providing an elegant solution for users with custom reverse proxy and DNS configurations.
                    *   **Backend Refactoring:** The backend was significantly refactored to support this new model. This included a database migration (V2 to V3 to add the `access_pattern` column) and the creation of new API endpoints for activating, deactivating, and configuring instances. The old `socat` logic in the process starter was replaced by this more flexible, on-demand system.
            
            5.  **Phase 5: Refinement (Planned)**
                *   Implement the `Update` functionality for saving changes to existing instances (Name, GPU IDs, etc.).
                *   Improve error handling and status reporting.
                *   Write comprehensive documentation for the new `AiKore` system.
            
            ## 5. Known Issues & Investigation Logs
            
            ### 5.1. ComfyUI Reverse Proxy Integration Issues
            
            *   **Status:** **Obsolete.** The "Active Slot" mechanism is now a legacy feature, superseded by the more robust Dynamic Port Management system. The original issue (405 on save) is resolved by accessing ComfyUI directly via its activated port.
            
            ## 6. Feature Test Protocols
            
            ### 6.1. Dynamic Port Management (2025-10-27)
            
            This protocol validates the new architecture for instance network exposure.
            
            1.  **System Preparation & Migration Verification:**
                *   Rebuild the Docker image (`docker-compose build` or `make build`).
                *   Start the AiKore container.
                *   Check the container logs for the message: `INFO:__main__:Successfully added 'access_pattern' column and updated DB version to 3.` This confirms the database migration was successful.
            
            2.  **Instance Creation:**
                *   In the UI, click "Add New Instance".
                *   Fill in the `Name` and `Base Blueprint`.
                *   In the new `Public Port` field, enter a port from your exposed range (e.g., `50001`).
                *   Click `Save`. The instance should be created and appear in the list with the specified port.
            
            3.  **Lifecycle & Activation:**
                *   Start the new instance. The status should change to `starting` and then `started`. The `Activate` button should become enabled.
                *   Click `Activate`. The button should change to `Deactivate` (and turn green).
                *   Click `Open`. A new browser tab should open to the correct URL (e.g., `http://<your-host>:50001`), and the instance's UI should load and be functional.
                *   Click `View`. The instance's UI should be embedded in the AiKore dashboard.
                *   Click `Deactivate`. The button should revert to `Activate`. The browser tab opened via `Open` should now refuse connection.
            
            4.  **Port Conflict Handling:**
                *   Create a second instance, assigning it the **same Public Port** as the first (e.g., `50001`).
                *   Start this second instance.
                *   Ensure the first instance is currently `Activated`.
                *   Click `Activate` on the **second** instance.
                *   **Expected:** A confirmation dialog should appear, warning that the port is in use by the first instance and asking for confirmation to proceed.
                *   Click "Cancel". Nothing should change. The first instance should remain active.
                *   Click `Activate` on the second instance again. This time, click "OK" in the confirmation dialog.
                *   **Expected:** The first instance's button should change to `Activate` (no longer active), and the second instance's button should change to `Deactivate` (now active). The `Open` URL should now point to the second instance.
            
            5.  **Access Pattern Switching:**
                *   Select an active instance. In the `Access Method` column, change the dropdown from `Hostname:Port` to `Subdomain`.
                *   The `Open` button's link should immediately update to reflect the new pattern (e.g., from `http://<host>:50001` to `http://<instance-name>.<host>`).
                *   Switch it back to `Hostname:Port` and verify the link reverts.