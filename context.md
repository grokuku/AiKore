# AiKore Project Context

    ## 1. Project Tree

    This document outlines the structure and purpose of each file within the AiKore project.

    ```
    /
    ├── .github/                 # Contains GitHub Actions workflows for CI/CD.
    ├── OLD/                     # Contains old/legacy files for historical reference.
    │   ├── CHANGELOG.md         # Legacy changelog.
    │   ├── entry.sh             # Old container entrypoint script.
    │   ├── LICENSE              # Project license file.
    │   └── README.md            # Old project README file.
    ├── aikore/                  # The AiKore backend application (Python/FastAPI).
    │   ├── __init__.py          # Makes the 'aikore' directory a Python package.
    │   ├── crud.py              # Contains CRUD (Create, Read, Update, Delete) database operations.
    │   ├── database.py          # Configures the SQLAlchemy engine and database session.
    │   ├── main.py              # FastAPI application entrypoint, defines all API routes.
    │   ├── models.py            # Defines the SQLAlchemy ORM models (database tables).
    │   ├── process_manager.py   # Handles the lifecycle (start/stop) of WebUI instances as subprocesses.
    │   ├── requirements.txt     # Lists Python dependencies for the AiKore backend.
    │   └── schemas.py           # Defines Pydantic schemas for API data validation and serialization.
    ├── blueprints/              # Contains template scripts and default parameters for each supported AI tool.
    │   ├── 01-easy-diffusion.parameters.txt   # Default parameters for Easy Diffusion.
    │   ├── 01-easy-diffusion.sh             # Startup script for Easy Diffusion.
    │   ├── 02-automatic1111.parameters.txt  # Default parameters for AUTOMATIC1111.
    │   ├── 02-automatic1111.sh            # Startup script for AUTOMATIC1111.
    │   ├── 02.forge.parameters.txt          # Default parameters for SD WebUI Forge.
    │   ├── 02.forge.sh                    # Startup script for SD WebUI Forge.
    │   ├── 03-invokeai.parameters.txt       # Default parameters for InvokeAI.
    │   ├── 03-invokeai.sh                 # Startup script for InvokeAI.
    │   ├── 04-sdnext.parameters.txt         # Default parameters for SD.Next.
    │   ├── 04-sdnext.sh                   # Startup script for SD.Next.
    │   ├── 05-comfyui.parameters.txt        # Default parameters for ComfyUI.
    │   ├── 05-comfyui.sh                  # Startup script for ComfyUI.
    │   ├── 06-fooocus.parameters.txt        # Default parameters for Fooocus.
    │   ├── 06-fooocus.sh                  # Startup script for Fooocus.
    │   ├── 07-swarmui.parameters.txt        # Default parameters for SwarmUI.
    │   ├── 07-swarmui.sh                  # Startup script for SwarmUI.
    │   ├── 50-iopaint.parameters.txt        # Default parameters for IOPaint.
    │   ├── 50-iopaint.sh                  # Startup script for IOPaint.
    │   ├── 51-facefusion.parameters.txt     # Default parameters for FaceFusion.
    │   ├── 51-facefusion.sh               # Startup script for FaceFusion.
    │   ├── 70-kohya.parameters.txt          # Default parameters for Kohya's SS GUI.
    │   ├── 70-kohya.sh                    # Startup script for Kohya's SS GUI.
    ├── 71-fluxgym.parameters.txt        # Default parameters for Fluxgym.
    ├── 71-fluxgym.sh                  # Startup script for Fluxgym.
    ├── 72-onetrainer.parameters.txt     # Default parameters for OneTrainer.
    ├── 72-onetrainer.sh               # Startup script for OneTrainer.
    ├── 73-aitoolkit.parameters.txt      # Default parameters for AI Toolkit.
    ├── 73-aitoolkit.sh                # Startup script for AI Toolkit.
    │   └── custom-sample.sh               # A sample script for users to create their own custom blueprints.
    ├── docker/                  # Holds Docker-specific configuration files.
    │   └── root/                # Files to be copied into the root of the container's filesystem.
    │       └── etc/s6-overlay/  # s6-overlay process supervisor configuration.
    │           └── s6-rc.d/
    │               ├── init-chown/
    │               │   ├── dependencies.d/
    │               │   │   └── init-config
    │               │   ├── run
    │               │   ├── type
    │               │   └── up
    │               ├── svc-app/
    │               │   ├── dependencies.d/
    │               │   │   ├── init-chown
    │               │   │   └── init-services
    │               │   ├── run
    │               │   └── type
    │               └── user/
    │                   └── contents.d/
    │                       └── svc-app
    ├── .gitignore               # Specifies files and directories for Git to ignore.
    ├── Dockerfile               # Main Dockerfile to build the final AiKore application image.
    ├── Dockerfile.buildbase     # Dockerfile for a base image with pre-compiled dependencies.
    ├── Makefile                 # Provides convenient `make` commands to manage docker-compose.
    ├── docker-compose.yml       # Defines the AiKore service for easy launch with Docker Compose.
    ├── entry.sh                 # The main script executed when the container starts; it launches the AiKore backend.
    ├── functions.sh             # A library of shared shell functions used by the blueprint scripts.
    ├── project_context.md       # (This file) The central document explaining the project structure and vision.
    └── features.md              # A document to track the implementation of new features.
    ```

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
        *   Routes traffic based on the URL path:
            *   `/` -> Serves the AiKore Frontend.
            *   `/api/*` -> Forwards requests to the AiKore Backend (running on an internal port, e.g., 8000).
            *   `/app/<instance_name>/*` -> Forwards traffic to the corresponding running WebUI instance's internal port.

    #### Database (The Memory)
    *   **Technology:** **SQLite**.
    *   **Responsibilities:**
        *   Stores all user-created instance configurations in a single file (`/config/aikore.db`).
        *   Ensures that the user's setup is persistent across container restarts.

    ### Feature Specification

    #### Instance Management Dashboard
    A table-based interface inspired by the provided screenshot, allowing users to manage all their WebUI instances.

    *   **"Add New Instance" Button:** Opens a form to create a new instance.
    *   **Instance Table Columns:**
        *   `Name`: A user-defined name for the instance (e.g., "ComfyUI_SDXL_Training").
        *   `Base Blueprint`: A dropdown to select the base script (e.g., "05-comfyui.sh").
        *   `GPU IDs`: A text field to specify which GPU(s) the instance can use (e.g., "0" or "0,1,3"). Mapped to `CUDA_VISIBLE_DEVICES`.
        *   `Autostart`: A checkbox to automatically start this instance when the AiKore container starts.
        *   `Persistent Mode`: A checkbox to launch the instance within a persistent KasmVNC session.
        *   `Status`: A visual indicator of the instance's state (`Stopped`, `Starting`, `Running`, `Error`).
        *   `PID`: The Process ID of the running instance.
    *   **Instance Actions (Buttons per row):**
        *   `Start / Stop`: Toggles the state of the instance.
        *   `Open`: Opens the WebUI in a new browser tab using its unique URL (`/app/<instance_name>/`).
        *   `Edit Script`: Allows advanced users to view and modify the specific script file for this instance.
        *   `Update`: Saves any changes made to the configuration fields.
        *   `Logs`: Displays the real-time console output of the instance.
        *   `Delete`: Removes the instance and its configuration.

    #### System Monitoring Dashboard
    A real-time view of system resources, inspired by the provided screenshot.

    *   **Metrics Displayed:**
        *   Overall CPU Utilization (%).
        *   Overall RAM Utilization (% and GB/GB).
        *   Per-GPU Utilization (%), VRAM Usage (% and MB/MB), and GPU Name.
    *   **Functionality:**
        *   Data is fetched from the backend API periodically.
        *   A refresh interval control (`+ / -`) allows the user to adjust the update frequency.

    #### Persistent Session Mode (via KasmVNC)
    A solution for WebUIs that do not maintain their UI state across browser sessions.

    *   When an instance is launched in "Persistent Mode":
        1.  The WebUI process starts normally.
        2.  A browser is launched *inside* the container's VNC session, pointing to the WebUI's internal address.
        3.  The "Open" button for this instance will launch the KasmVNC web client instead of the direct WebUI URL.
    *   This ensures the WebUI session is never closed, and the user can connect/disconnect from the VNC at will to check on long-running tasks.

    ### Data Model (Database Schema)

    A single table `instances` will be created in the `aikore.db` SQLite database.

    | Column Name       | Data Type | Nullable | Description                                           |
    |-------------------|-----------|----------|-------------------------------------------------------|
    | `id`              | INTEGER   | No       | Primary Key                                           |
    | `name`            | TEXT      | No       | User-defined unique name for the instance             |
    | `base_blueprint`  | TEXT      | No       | Filename of the source script (e.g., "05-comfyui.sh") |
    | `gpu_ids`         | TEXT      | Yes      | Comma-separated string of GPU IDs (e.g., "0,1")       |
    | `autostart`       | BOOLEAN   | No       | If true, start on AiKore launch                       |
    | `persistent_mode` | BOOLEAN   | No       | If true, use the KasmVNC session mode                 |
    | `status`          | TEXT      | No       | Current state: "stopped", "running", etc.             |
    | `pid`             | INTEGER   | Yes      | Stores the PID of the running process                 |

    ## 3. Project Directory Structure

    The project will be reorganized for clarity and maintainability.

    ```
    /
    ├── aikore/                  # The AiKore backend application
    ├── blueprints/              # Template scripts and their default parameters
    ├── docker/                  # Docker-specific configurations (s6-overlay)
    ├── .github/                 # CI/CD workflows
    ├── Dockerfile               # Main application Dockerfile
    ├── Dockerfile.buildbase     # Base image with pre-compiled dependencies
    ├── docker-compose.yml       # Simplified compose file for launching AiKore
    └── ...                      # Other project files (README, Makefile, etc.)
    ```

    ## 4. Phased Implementation Roadmap

    1.  **Phase 1: Foundation (Completed)**
        *   Establish the new project structure.
        *   Create the minimal FastAPI backend skeleton.
        *   Modify the container `entry.sh` to launch the AiKore backend.
        *   Confirm the backend runs successfully inside the container.

    2.  **Phase 2: Core Logic (Completed)**
        *   Implement the database layer (SQLite + SQLAlchemy), including the `persistent_mode` column.
        *   Create API endpoints for basic CRUD (Create, Read, Update, Delete) of instances.
        *   Implement the `process_manager` to start/stop blueprints as subprocesses.

    3.  **Phase 3: Frontend & Basic Management (In Progress)**
        *   Build the frontend for the Instance Management Dashboard, transitioning to inline editing.
        *   Connect the frontend to the API to display and manage instances.
        *   Implement the `Start`/`Stop`/`Delete` functionality.
        *   Implement the "Add New Instance" functionality with inline row creation.
        *   Define the visual style for the table, editable fields, and action buttons.
        *   **TODO:** Implement the `Update` functionality for existing instances.

    4.  **Phase 4: Advanced Features & UX (Planned)**
        *   Implement the System Monitoring backend endpoint (`/api/system_stats`).
        *   Build the System Monitoring dashboard on the frontend.
        *   Integrate the NGINX reverse proxy for unique URL routing (`/app/...`).
        *   Implement the "Persistent Session (VNC)" launch mode.

    5.  **Phase 5: Refinement (Planned)**
        *   Implement remaining actions (Logs, Edit Script).
        *   Improve error handling and status reporting.
        *   Write comprehensive documentation for the new `AiKore` system.