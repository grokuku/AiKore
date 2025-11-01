# AiKore Project

## Project Overview

AiKore is a web-based application designed to manage and run various AI web UI instances, such as Stable Diffusion. It provides a centralized interface to start, stop, and monitor these instances.

The project is architected as a containerized application using Docker and Docker Compose. The backend is a FastAPI application written in Python, which communicates with a frontend built with HTML, CSS, and JavaScript. Nginx is used as a reverse proxy to manage access to the different AI instances.

The application uses a Conda-managed Python environment and relies on SQLAlchemy for database interactions. Process supervision within the container is handled by `s6-overlay`.

## Building and Running

The project is managed using `make` commands that wrap `docker-compose` for easier management of the application stack.

### Key Commands

*   **Start the application:**
    ```bash
    make up [profile]
    ```
    Replace `[profile]` with the name of the AI instance you want to run (e.g., `fooocus`).

*   **Stop the application:**
    ```bash
    make down [profile]
    ```

*   **Start in detached mode:**
    ```bash
    make start [profile]
    ```

*   **View logs:**
    ```bash
    make logs [profile]
    ```

### Available Profiles

The available profiles for the AI instances are dynamically loaded from the `docker-compose.yml` file. Refer to this file for a list of supported profiles.

## Development Conventions

*   **Containerized Development:** The entire development environment is containerized using Docker. The `Dockerfile` and `docker-compose.yml` files define the services, dependencies, and environment.
*   **Multi-stage Docker Build:** The use of a `buildbase` image suggests a multi-stage build process to create a lean production image.
*   **Directory Structure:** The project follows a clear directory structure:
    *   `aikore/`: Contains the main FastAPI application source code.
    *   `docker/`: Holds Docker-related configurations, including Nginx and `s6-overlay` setups.
    *   `blueprints/`: Contains scripts and configuration files for the different AI instances.
*   **Process Supervision:** `s6-overlay` is used for managing processes within the container, ensuring that services like Nginx and the main application are running correctly.
*   **Database Migrations:** The application automatically checks for and applies database migrations on startup.
