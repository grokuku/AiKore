# AiKore Feature Implementation Tracker

This document tracks the progress of feature implementation based on the roadmap outlined in `project_context.md`.

## Phase 1: Foundation

- [x] Establish the new project structure.
- [x] Create the minimal FastAPI backend skeleton.
- [x] Modify the container `entry.sh` to launch the AiKore backend.
- [x] Confirm the backend runs successfully inside the container.

## Phase 2: Core Logic

- [x] Implement the database layer (SQLite + SQLAlchemy).
- [x] Create API endpoints for basic instance CRUD (Create, Read, Delete).
- [x] Implement the `process_manager` for subprocess management.

## Phase 3: Frontend & Basic Management

- [x] Refactor instance paths for dynamic configurations and outputs.
- [x] Implement the final resizable multi-pane dashboard layout.
- [x] Create backend endpoint for real-time system statistics (CPU, RAM, GPU).
- [x] Implement frontend panel for system monitoring with auto-refresh.
- [x] Create backend endpoint to serve instance-specific log files.
- [x] Implement frontend log viewer with intelligent live-refresh and auto-scroll.
- [x] Harden blueprints (`ComfyUI.sh`) and shared functions (`functions.sh`).
- [x] Harden `Dockerfile` to handle permissions and line endings.
- [x] Implement instance script editing from the web UI (`launch.sh` convention).
- [ ] Implement the `Update` functionality for saving changes to existing instances.

## Phase 4: Advanced Features & UX

- [x] Integrate NGINX reverse proxy for unique instance URLs (`/app/<instance_name>`).
- [x] Harden NGINX configuration to support both standard and path-aware (Gradio) applications.
- [x] Implement Persistent Session (VNC) launch mode with isolated per-instance servers.
- [ ] Resolve "502 Bad Gateway" error on persistent VNC sessions.

## Phase 5: Refinement

- [ ] Improve global error handling and status reporting.
- [ ] Write comprehensive user and system documentation.