## Gemini Memories & Technical Notes

### Project Constraints & Preferences
- **Language**: Use English for all code/docs, but communicate in French.
- **Environment**: Remote server deployment via Docker.
- **Architecture**: Monolithic container (AiKore) managing subprocesses.

### Historical Debugging & Features

#### **KasmVNC / Persistent Mode Integration**
- **Objective**: Replace standard WebUI access with a full Desktop capability for tools requiring GUI (like OneTrainer or unexpected popups).
- **Implementation**:
    - `kasm_launcher.sh`: Starts `Xvnc` (Kasm server), `openbox` (Window Manager), and the target app.
    - **Port Logic**: Persistent instances consume a Public Port for VNC. The internal app uses a random ephemeral port.
    - **Dependencies**: `xvfb`, `firefox` (for internal browsing), `openbox` added to Dockerfile.

#### **Wheel Building Workflows**
- **Objective**: Speed up build times by pre-compiling heavy Python libraries (Flash Attention, Xformers, Torch).
- **Solution**:
    - Dedicated GitHub Actions workflows (`build-wheels.yml`, etc.).
    - `Dockerfile.buildbase`: Ingests these pre-built wheels.
    - **Fixes applied**:
        - `bitsandbytes`: Fixed `pyproject.toml` double-license error via inline Python script during build.
        - `xformers`: Added caching and limited CUDA architecture matrix to prevent timeouts/errors.

#### **Environment Rebuild Feature**
- **Feature**: Button to wipe and reinstall the Conda environment for an instance.
- **Mechanism**:
    - `functions.sh`: `clean_env` checks for `.rebuild-env` file.
    - `process_manager.py`: Creates the trigger file and restarts the instance.

#### **Satellite / Instantiation Architecture (V5)**
- **Goal**: Create lightweight copies of instances sharing the same codebase/venv but different runtime settings (GPU, Ports).
- **Implementation**:
    - **DB**: Added `parent_instance_id`.
    - **Frontend**: Grouped `<tbody>` rendering to treat Families (Parent + Satellites) as atomic blocks.
    - **Constraint**: Satellites cannot change `blueprint` or `output_path` (UI disabled).
    - **Filesystem**: "Lazy creation" logic. Folders are not created at DB insertion time, but at first launch by the process manager.