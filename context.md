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
    │   │   ├── 01-easy-diffusion.parameters.txt
    │   │   ├── 01-easy-diffusion.sh
    │   │   ├── 02-automatic1111.parameters.txt
    │   │   ├── 02-automatic1111.sh
    │   │   ├── 02.forge.parameters.txt
    │   │   ├── 02.forge.sh
    │   │   ├── 03-invokeai.parameters.txt
    │   │   ├── 03-invokeai.sh
    │   │   ├── 04-sdnext.parameters.txt
    │   │   ├── 04-sdnext.sh
    │   │   ├── 06-fooocus.parameters.txt
    │   │   ├── 06-fooocus.sh
    │   │   ├── 07-swarmui.parameters.txt
    │   │   ├── 07-swarmui.sh
    │   │   ├── 50-iopaint.parameters.txt
    │   │   ├── 50-iopaint.sh
    │   │   ├── 51-facefusion.parameters.txt
    │   │   ├── 51-facefusion.sh
    │   │   ├── 70-kohya.parameters.txt
    │   │   ├── 70-kohya.sh
    │   │   ├── 71-fluxgym.parameters.txt
    │   │   ├── 71-fluxgym.sh
    │   │   ├── 72-onetrainer.parameters.txt
    │   │   ├── 72-onetrainer.sh
    │   │   ├── 73-aitoolkit.parameters.txt
    │   │   ├── 73-aitoolkit.sh
    │   │   └── custom-sample.sh
    │   ├── comfyui.parameters.txt # Default parameters for ComfyUI (refactored).
    │   └── comfyui.sh             # Startup script for ComfyUI (refactored).
    ├── docker/                  # Holds Docker-specific configuration files.
    │   └── root/                # Files to be copied into the root of the container's filesystem.
    │       └── etc/
    │           ├── nginx/
    │           │   └── conf.d/
    │           │       └── aikore.conf
    │           └── s6-overlay/  # s6-overlay process supervisor configuration.
    │               └── s6-rc.d/
    │                   ├── init-chown/
    │                   │   └── run
    │                   └── ... (other s6 services)
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
    
    ### Data Model (Database Schema)
    
    A single table `instances` will be created in the `aikore.db` SQLite database.
    
    | Column Name       | Data Type | Nullable | Description                                           |
    |-------------------|-----------|----------|-------------------------------------------------------|
    | `id`              | INTEGER   | No       | Primary Key                                           |
    | `name`            | TEXT      | No       | User-defined unique name for the instance             |
    | `base_blueprint`  | TEXT      | No       | Filename of the source script (e.g., "comfyui.sh")    |
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
    │   └── legacy/              # Old scripts awaiting refactoring
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
        *   **Completed:** Refactored instance management to use dynamic, instance-name-based paths for configurations and outputs (`/config/instances/<name>`, `/config/outputs/<name>`). This makes blueprints truly reusable templates.
        *   **Completed:** Built the core frontend functionality (display, start/stop, delete, add).
        *   **Completed:** Established the final, resizable multi-pane dashboard layout (Instance Manager, Tools/Logs, Monitoring) and applied a polished visual style to the instance table.
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