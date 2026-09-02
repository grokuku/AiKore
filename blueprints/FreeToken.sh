#!/bin/bash

### AIKORE-METADATA-START ###
# aikore.name = FreeToken Desktop
# aikore.category = Chat / LLM
# aikore.description = FreeToken MoE serving engine + official FreeToken Desktop app (KasmVNC desktop)
# aikore.venv_type = conda
# aikore.venv_path = ./env
# aikore.persistent_mode = true
### AIKORE-METADATA-END ###

# ============================================================================
# FreeToken Desktop blueprint for AiKore
# ----------------------------------------------------------------------------
# Instance = FreeToken MoE serving engine (OpenAI/Anthropic-compatible API on
# loopback) + the OFFICIAL FreeToken Desktop application (Tauri GUI from the
# FlashML-org/FreeToken-Web release), shown on the persistent KasmVNC desktop.
# There is deliberately NO Open WebUI (removed): the user asked for the
# official Desktop app, not a third-party web chat.
#
# HOW THE PIECES FIT TOGETHER
#   * The .deb (pinned beta/v0.2.0-beta.15) is only the Tauri GUI: it does NOT
#     contain the engine. If no engine is found, the app runs its bundled
#     engine/install.sh which installs the RELEASE wheels (v0.1.2+g<sha>, no
#     sm_75 kernels) into ~/.freetoken/venv -- exactly the duplicate we must
#     avoid on Turing GPUs. We therefore:
#       1. install the engine ourselves in the AiKore conda venv (./env),
#          with the GPU-aware routes below (PR #24 build for sm_75);
#       2. pre-position the engine where the Desktop looks for it:
#            - $HOME/.freetoken/venv/bin/ft  (canonical path, FREETOKEN_HOME)
#            - $HOME/.local/bin/ft           (PATH symlink, as install.sh does)
#            - $HOME/.config/environment.d/50-freetoken.conf (official marker)
#            - export FREETOKEN_FT_BIN for the GUI session (the app logs
#              "[ok] FREETOKEN_FT_BIN set for this session: <path>")
#         -> the app reports the engine as installed and NEVER runs its own
#            installer (which would ship an unpatched v0.1.2).
#   * The blueprint also starts the engine as a service: `ft serve` on
#     127.0.0.1:1919 (FreeToken + Desktop default port). The Desktop handles
#     an already-running engine ("engine already running" / port-in-use paths
#     in the binary), so the GUI is expected to pick the blueprint-started
#     engine up for chat; this is the behavior to confirm on first live run.
#     1919 should NOT be changed via FT_PORT unless you accept the Desktop
#     not finding the service engine automatically.
#   * Desktop install: the blueprint runs as the unprivileged 'abc' user
#     (svc-app/run: s6-setuidgid abc), so `dpkg -i` is not possible; the .deb
#     is extracted with `dpkg -x` into a local prefix under APP_DIR + wrapper.
#     The GUI libs (libgtk-3-0, libwebkit2gtk-4.1-0, libayatana-appindicator3-1)
#     are baked into the image by the Dockerfile (apt is not usable as abc).
#     (Tauri resource dir /usr/lib/"FreeToken Desktop" is re-linked when
#     possible; the in-app engine installer is neutralized anyway, so a
#     missing resource dir only costs the bundled installer, never the GUI.)
#   * GPU detection (unchanged):
#       - sm_80+ : pip freetoken==0.1.2 + pinned prebuilt kernel-cache wheel
#         (sha256 a401e8d0...c120a4f).
#       - sm_75  : NOT covered by the 0.1.2 wheel (issue #73) -> build upstream
#         at PR #24 (Turing support), pinned head SHA
#         35668da6db1e23111f1fbcc8a552455927a70f2a, torch from the pinned
#         cu130 index, TORCH_CUDA_ARCH_LIST=7.5, then build the sm_75
#         kernel-cache. Heavy (30-90 min), no GPU needed for the build.
#       - < 7.5 : hard exit.
#   * FREETOKEN_DISABLE_JIT=1 for both routes (prebuilt kernel cache only).
#   * Model storage: HF_HOME -> /config/models/huggingface (sl_folder) so the
#     Desktop's HF downloads (hf-hub honors HF_HOME) are shared and persistent.
#     FREETOKEN_MODELS_DIR points at the instance conf dir (persisted).
#
# PROCESS MODEL (persistent/KasmVNC mode)
#   AiKore launches scripts/kasm_launcher.sh, which:
#     - starts Xvnc (KasmVNC) on the persistent_port with a DISPLAY it owns,
#     - starts openbox,
#     - runs THIS script in the background.
#   The process manager monitors Xvnc (http on persistent_port marks the
#   instance "started"; an optional firefox kiosk is opened on that port by
#   the monitor thread). So there is NO foreground web process here: the
#   blueprint starts the engine in the background (watchdog kills the process
#   group if the engine dies) and `exec`s the GUI as its foreground process.
#   Closing the GUI window does not stop the instance (the engine and the
#   desktop keep running); stopping the instance tears the whole group down.
#
# PLATFORM NOTES (documentation only, not handled here)
#   * Persistent UI: the platform does NOT read the blueprint's
#     `aikore.persistent_mode` flag when creating an instance
#     (eventHandlers.js forces it to false), so the user must tick
#     "Persistent UI" manually at instance creation for the KasmVNC desktop
#     to be shown.
#   * environment.d: the ~/.config/environment.d/50-freetoken.conf marker is
#     inert without a systemd user session (none here). The engine handoff is
#     actually carried by FREETOKEN_FT_BIN (exported for the GUI session) and
#     the absolute symlinks, which survive restarts.
# ============================================================================

set -e

source /opt/sd-install/functions.sh
source /opt/sd-install/versions.env

# --- Load custom instance variables (may set FT_PORT, FREETOKEN_MODEL, ...) ---
if [ -f "${INSTANCE_CONF_DIR}/aikore_vars.env" ]; then
    echo "--- Loading custom environment variables ---"
    source "${INSTANCE_CONF_DIR}/aikore_vars.env"
fi

export PATH="/home/abc/miniconda3/bin:$PATH"

echo "--- Starting Blueprint: FreeToken Desktop for Instance: ${INSTANCE_NAME} ---"

# The following variables are provided by the process manager (persistent mode):
# - INSTANCE_NAME / INSTANCE_CONF_DIR / INSTANCE_OUTPUT_DIR
# - BLUEPRINT_ID
# - DISPLAY: X display owned by the KasmVNC server started by kasm_launcher.sh
# - WEBUI_PORT: still set by the platform, but UNUSED here (no web UI in this
#   blueprint; the user-facing interface is the KasmVNC desktop itself, served
#   directly on the instance persistent_port by the process manager).

mkdir -p "${INSTANCE_CONF_DIR}"
mkdir -p "${INSTANCE_OUTPUT_DIR}"

APP_DIR="${INSTANCE_CONF_DIR}/freetoken"
VENV_DIR="${INSTANCE_CONF_DIR}/env"
FT_SRC_DIR="${INSTANCE_CONF_DIR}/FreeToken-src"

# Internal FreeToken API port (loopback only). 1919 is the FreeToken engine
# default AND the port FreeToken Desktop expects: do not override unless you
# accept the Desktop not finding the blueprint-started engine automatically.
FT_PORT="${FT_PORT:-1919}"

# Default model (HF repo ID or local path). Downloaded on first serve, not at install.
FREETOKEN_MODEL="${FREETOKEN_MODEL:-Qwen/Qwen3-0.6B}"

# Health-check timeout (s). First run may download the model, so the default is
# generous. Override with FREETOKEN_HEALTH_TIMEOUT.
FREETOKEN_HEALTH_TIMEOUT="${FREETOKEN_HEALTH_TIMEOUT:-900}"

# Pinned versions (engine)
FREETOKEN_VERSION="0.1.2"
FREE_TOKEN_WHEEL="freetoken==${FREETOKEN_VERSION}"
KERNEL_CACHE_WHEEL_URL="https://github.com/FlashML-org/FreeToken/releases/download/v${FREETOKEN_VERSION}/freetoken_kernel_cache-${FREETOKEN_VERSION}%2Bcu130-py3-none-linux_x86_64.whl"
KERNEL_CACHE_WHEEL_SHA256="a401e8d0fb80405e99e120f20c43b207662110b2ba7a3b93c84e04887c120a4f"
# PR #24 head (Turing support). Pinned by SHA from the PR branch fix/sm75-turing.
FT_TURING_PR_SHA="35668da6db1e23111f1fbcc8a552455927a70f2a"

# Pinned Desktop app. The "beta" tag is a MOVING release tag, so the asset is
# pinned by its sha256 instead: if FlashML re-publishes a different binary
# under the same URL, the checksum below fails and this blueprint refuses to
# install it. To adopt a newer Desktop build, update SHA + version explicitly.
DESKTOP_DEB_URL="https://github.com/FlashML-org/FreeToken-Web/releases/download/beta/freetoken-desktop-amd64.deb"
DESKTOP_DEB_SHA256="d00347868ae1f2447294a6df31530d72576117c6361e6980cb9df56d740abc65"
DESKTOP_DEB_VERSION="0.2.0-beta.15"
DESKTOP_PACKAGE="free-token-desktop"

# Marker written after the FreeToken runtime is installed (records GPU arch used).
# Placed inside ${VENV_DIR}: clean_env removes only the venv on a "Rebuild
# Environment" (see functions.sh), so this marker is carried away with it and a
# rebuilt (empty) env is never wrongly treated as already installed.
FT_INSTALL_MARKER="${VENV_DIR}/.freetoken_installed"

# ============================================================================
# 1. Isolated HOME (the "fake home" pattern, same strategy as LMStudio)
# ----------------------------------------------------------------------------
# FreeToken Desktop persists state in $HOME (config: .config/freetoken/, engine
# home: .freetoken/, tool symlinks: .local/bin/, caches: .cache/). Redirecting
# HOME into INSTANCE_CONF_DIR keeps every instance isolated and persistent
# without polluting /home/abc. XDG_* vars are re-pointed too: the app (Rust
# `dirs`/Tauri + WebKitGTK) honors them and they default to $HOME only when
# unset -- the image sets XDG_CONFIG_HOME=/home/abc globally.
# ============================================================================
FAKE_HOME="${INSTANCE_CONF_DIR}/internal_home"
mkdir -p "${FAKE_HOME}"
export HOME="${FAKE_HOME}"
export XDG_CONFIG_HOME="${FAKE_HOME}/.config"
export XDG_DATA_HOME="${FAKE_HOME}/.local/share"
export XDG_CACHE_HOME="${FAKE_HOME}/.cache"
mkdir -p "${XDG_CONFIG_HOME}" "${XDG_DATA_HOME}" "${XDG_CACHE_HOME}"
echo "Instance Home Directory set to: ${FAKE_HOME}"

# ============================================================================
# 2. Conda environment
# ============================================================================
echo "--- Setting up Conda environment ---"
conda clean -ya
clean_env "${VENV_DIR}"

if [ ! -d "${VENV_DIR}" ]; then
    echo "Creating Conda environment with Python ${PYTHON_VERSION:-3.12}..."
    conda create -p "${VENV_DIR}" python="${PYTHON_VERSION:-3.12}" pip -y
fi

source activate "${VENV_DIR}"

if [ ! -f "${VENV_DIR}/bin/pip" ]; then
    echo "--- pip not found in environment, installing via conda ---"
    conda install -p "${VENV_DIR}" pip -y
fi

# ============================================================================
# 2b. GUI system libraries (fail-fast BEFORE the heavy engine build)
# ----------------------------------------------------------------------------
# The Desktop is a Tauri GUI: it needs libgtk-3, libwebkit2gtk-4.1 and the
# ayatana appindicator libs at runtime. These are baked into the image by the
# Dockerfile. The blueprint runs as the unprivileged 'abc' user
# (svc-app/run: s6-setuidgid abc), so apt is NOT usable at runtime; if the
# image is obsolete and libwebkit2gtk-4.1 is missing, we fail fast here --
# BEFORE the 30-90 min sm_75 source build -- instead of discovering a dead
# GUI at the end.
# ============================================================================
ensure_gui_libraries() {
    local missing=()
    ldconfig -p 2>/dev/null | grep -q "libgtk-3.so.0" || missing+=(libgtk-3-0)
    ldconfig -p 2>/dev/null | grep -q "libwebkit2gtk-4.1.so.0" || missing+=(libwebkit2gtk-4.1-0)
    ldconfig -p 2>/dev/null | grep -q "libayatana-appindicator3.so.1" || missing+=(libayatana-appindicator3-1)

    if [ "${#missing[@]}" -gt 0 ]; then
        echo "--- Missing GUI libraries: ${missing[*]} ---"
        # The blueprint runs as 'abc', so apt is a no-op in practice; keep the
        # root-only attempt for completeness (e.g. manual root runs).
        if [ "$(id -u)" = "0" ] && command -v apt-get >/dev/null 2>&1; then
            echo "--- Installing via apt-get (no-install-recommends) ---"
            apt-get update -y || true
            DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${missing[@]}" || true
        fi
        # Hard requirement for the Tauri GUI (WebKitGTK).
        if ! ldconfig -p 2>/dev/null | grep -q "libwebkit2gtk-4.1.so.0"; then
            echo "=============================================================="
            echo "ERROR: libwebkit2gtk-4.1.so.0 is missing from this image."
            echo "The FreeToken Desktop GUI (Tauri/WebKitGTK) cannot start."
            echo "This image is OBSOLETE: rebuild it with the updated Dockerfile"
            echo "(adds libgtk-3-0, libwebkit2gtk-4.1-0, libayatana-appindicator3-1)"
            echo "via the CI GitHub workflow, then restart the instance."
            echo "=============================================================="
            exit 1
        fi
        echo "[WARN] Some optional GUI libraries are missing (${missing[*]});"
        echo "[WARN] the engine will still run, but the Desktop may lack tray/"
        echo "[WARN] indicator support. Rebuild the image to get them."
    fi
}

ensure_gui_libraries

# ============================================================================
# 3. GPU detection + FreeToken engine install (idempotent: skipped if installed)
# ============================================================================
detect_gpu_compute_cap() {
    if command -v nvidia-smi >/dev/null 2>&1; then
        nvidia-smi --query-gpu=compute_cap --format=csv,noheader 2>/dev/null | head -n1 | tr -d '[:space:]'
    fi
}

build_turing_source() {
    # FreeToken v0.1.2 official wheels ship no sm_75 kernels (issue #73). Build
    # upstream at PR #24 which adds Turing support (_supports_sm80 + sm_75).
    echo "--- Building FreeToken from source (PR #24, Turing sm_75) ---"
    echo "--- NOTE: this can take 30-90 min and needs the system CUDA 13 toolkit. ---"

    if [ ! -d "${FT_SRC_DIR}/.git" ]; then
        echo "--- Cloning FreeToken repository ---"
        git clone https://github.com/FlashML-org/FreeToken.git "${FT_SRC_DIR}"
    fi
    cd "${FT_SRC_DIR}"
    git fetch origin pull/24/head:refs/remotes/origin/turing-sm75
    git checkout "${FT_TURING_PR_SHA}"   # pinned PR head (verified 2026-08-22)

    # Pre-install torch from the pinned cu130 index (PYTORCH_INDEX_URL from
    # versions.env) + tvm-ffi so the C++ extension and kernel-cache builds can
    # run with --no-build-isolation against the sys nvcc.
    pip install "torch>=2.11,<2.12" --index-url "${PYTORCH_INDEX_URL}"
    pip install "apache-tvm-ffi==0.1.13.post3"

    echo "--- Building/installing FreeToken (python package + C++ extensions) ---"
    # Export the CUDA toolkit (bin/nvcc + lib64) and pin the arch list to sm_75
    # (Turing) so the build and the kernel-cache target the right architecture.
    export CUDA_HOME="/usr/local/cuda"
    export PATH="${CUDA_HOME}/bin:${PATH}"
    export LD_LIBRARY_PATH="${CUDA_HOME}/lib64:${LD_LIBRARY_PATH}"
    export TORCH_CUDA_ARCH_LIST="7.5"
    pip install --no-build-isolation -e .

    echo "--- Building sm_75 kernel cache (nvcc via system CUDA 13) ---"
    cd "${FT_SRC_DIR}/freetoken-kernel-cache"
    FREETOKEN_KERNEL_CACHE_ARCHES="7.5" \
        pip install --no-build-isolation .
    cd "${INSTANCE_CONF_DIR}"
}

install_freetoken() {
    local cap
    cap="$(detect_gpu_compute_cap || true)"
    if [ -z "${cap}" ]; then
        echo "=============================================================="
        echo "ERROR: No NVIDIA GPU detected (nvidia-smi unavailable or empty)."
        echo "FreeToken requires an NVIDIA GPU with compute capability >= 7.5"
        echo "(min Turing sm_75)."
        echo "=============================================================="
        exit 1
    fi

    local major="${cap%%.*}"
    local minor="${cap##*.}"
    local capnum=$((10#${major} * 10 + 10#${minor}))
    echo "--- Detected GPU compute capability: ${cap} (capnum ${capnum}) ---"

    if [ "${capnum}" -ge 80 ]; then
        echo "--- GPU supports sm_80+ : installing prebuilt FreeToken ${FREETOKEN_VERSION} ---"
        pip install "${FREE_TOKEN_WHEEL}"
        echo "--- Installing prebuilt kernel-cache wheel (pinned) ---"
        local kc_wheel="/tmp/freetoken_kernel_cache-${FREETOKEN_VERSION}+cu130-py3-none-linux_x86_64.whl"
        wget -q --show-progress -O "${kc_wheel}" "${KERNEL_CACHE_WHEEL_URL}"
        echo "${KERNEL_CACHE_WHEEL_SHA256}  ${kc_wheel}" | sha256sum -c -
        pip install "${kc_wheel}"
    elif [ "${capnum}" -eq 75 ]; then
        echo "--- GPU is Turing (sm_75): using source build route (PR #24) ---"
        build_turing_source
    else
        echo "=============================================================="
        echo "ERROR: compute capability ${cap} is unsupported. FreeToken needs"
        echo "at least Turing (sm_75 / compute_cap 7.5)."
        echo "The Desktop GUI would still start, but no engine can serve on"
        echo "this GPU, so the instance is stopped here."
        echo "=============================================================="
        exit 1
    fi

    echo "${cap}" > "${FT_INSTALL_MARKER}"
}

if [ -f "${FT_INSTALL_MARKER}" ] && [ -d "${VENV_DIR}" ] && command -v ft >/dev/null 2>&1; then
    echo "--- FreeToken already installed (marker present, ft on PATH), skipping install ---"
    cat "${FT_INSTALL_MARKER}"
else
    echo "--- FreeToken not installed yet (or environment rebuilt), installing ---"
    install_freetoken
fi

# ============================================================================
# 3b. Hand the engine over to FreeToken Desktop (neutralize its auto-install)
# ----------------------------------------------------------------------------
# The Desktop treats the engine as installed when it can resolve an `ft`
# binary. We wire ALL the mechanisms it knows about (reverse-engineered from
# the 0.2.0-beta.15 binary + the bundled engine/install.sh):
#   1. FREETOKEN_FT_BIN env var for the GUI session (explicit, most reliable);
#   2. $FREETOKEN_HOME/venv/bin/ft  (canonical install path of install.sh);
#   3. ~/.local/bin/ft on PATH (install.sh's symlink);
#   4. ~/.config/environment.d/50-freetoken.conf (official marker file).
# With all four in place the app reports the engine as installed and its
# in-app installer (which would fetch v0.1.2+g<sha> wheels WITHOUT sm_75
# kernels) is never triggered. The symlinks are absolute -> they survive
# across instance restarts; they are re-created here on every run so a
# "Rebuild Environment" (venv wiped) heals them automatically.
# ============================================================================
echo "--- Wiring FreeToken Desktop to the blueprint-managed engine ---"
FT_HOME_DIR="${FAKE_HOME}/.freetoken"
mkdir -p "${FT_HOME_DIR}/venv/bin" "${FAKE_HOME}/.local/bin" "${FAKE_HOME}/.config/environment.d"
ln -sfn "${VENV_DIR}/bin/ft" "${FT_HOME_DIR}/venv/bin/ft"
ln -sfn "${VENV_DIR}/bin/ft" "${FAKE_HOME}/.local/bin/ft"
printf 'FREETOKEN_FT_BIN=%s\n' "${VENV_DIR}/bin/ft" > "${FAKE_HOME}/.config/environment.d/50-freetoken.conf"
# Session-level env for the GUI (and any ft the Desktop spawns):
export FREETOKEN_FT_BIN="${VENV_DIR}/bin/ft"
export FREETOKEN_DISABLE_JIT=1

# ============================================================================
# 4. Shared model storage (HF_HOME -> /config/models/huggingface)
# ============================================================================
echo "--- Setting up shared Hugging Face model storage ---"
mkdir -p "${APP_DIR}/hf"
sl_folder "${APP_DIR}" "hf" "/config/models" "huggingface"
export HF_HOME="${APP_DIR}/hf"
export HF_HUB_DISABLE_TELEMETRY=1

# Where the Desktop stores converted/downloaded models (FTW checkpoints).
# Honored by the Desktop app (FREETOKEN_MODELS_DIR); kept inside the
# persistent instance conf dir.
mkdir -p "${INSTANCE_CONF_DIR}/freetoken/models"
export FREETOKEN_MODELS_DIR="${INSTANCE_CONF_DIR}/freetoken/models"

# ============================================================================
# 5. FreeToken Desktop app (.deb, pinned)
# ----------------------------------------------------------------------------
# The Desktop is a Tauri GUI: it needs libgtk-3, libwebkit2gtk-4.1 and the
# ayatana appindicator libs at runtime. These are baked into the image by the
# Dockerfile (the blueprint runs as the unprivileged 'abc' user, so apt is not
# usable at runtime; ensure_gui_libraries above fail-fasts if the image is
# obsolete). The .deb itself is installed with dpkg -i (installs to /usr/bin);
# as 'abc' that will fail, so we fall back to dpkg -x into a local prefix and
# wrap the binary (Tauri bundles its web assets inside the binary, so only the
# bundled engine installer resource is lost -- which we neutralize anyway).
# ============================================================================
install_desktop_app() {
    local installed_version
    installed_version="$(dpkg-query -W -f='${Version}' "${DESKTOP_PACKAGE}" 2>/dev/null || true)"

    if [ "${installed_version}" = "${DESKTOP_DEB_VERSION}" ]; then
        echo "--- FreeToken Desktop ${DESKTOP_DEB_VERSION} already installed via dpkg, skipping ---"
        DESKTOP_BIN="/usr/bin/freetoken-desktop"
        return 0
    fi

    # Fallback idempotence: when dpkg-query does not know the package (e.g. the
    # .deb was extracted with dpkg -x into ${debroot}), read the version marker
    # written there on the previous run and skip if it matches.
    local debroot="${APP_DIR}/debroot"
    if [ -f "${debroot}/.installed_version" ] && \
       [ "$(cat "${debroot}/.installed_version")" = "${DESKTOP_DEB_VERSION}" ] && \
       [ -x "${debroot}/usr/bin/freetoken-desktop" ]; then
        echo "--- FreeToken Desktop ${DESKTOP_DEB_VERSION} already installed locally (dpkg -x), skipping ---"
        DESKTOP_BIN="${debroot}/usr/bin/freetoken-desktop"
        return 0
    fi

    local deb_path="${INSTANCE_CONF_DIR}/freetoken-desktop-amd64.deb"
    if [ ! -f "${deb_path}" ] || ! echo "${DESKTOP_DEB_SHA256}  ${deb_path}" | sha256sum -c --status -; then
        echo "--- Downloading FreeToken Desktop ${DESKTOP_DEB_VERSION} (.deb) ---"
        wget -q --show-progress -O "${deb_path}" "${DESKTOP_DEB_URL}"
        echo "${DESKTOP_DEB_SHA256}  ${deb_path}" | sha256sum -c - || {
            echo "=============================================================="
            echo "ERROR: the downloaded freetoken-desktop-amd64.deb does not"
            echo "match the pinned sha256. The 'beta' tag was probably"
            echo "re-published with a new build. Review it, then update"
            echo "DESKTOP_DEB_SHA256/DESKTOP_DEB_VERSION in this blueprint."
            echo "=============================================================="
            rm -f "${deb_path}"
            return 1
        }
    fi

    if command -v dpkg >/dev/null 2>&1; then
        echo "--- Installing .deb with dpkg -i ---"
        if DEBIAN_FRONTEND=noninteractive dpkg -i "${deb_path}"; then
            echo "--- FreeToken Desktop installed system-wide (dpkg) ---"
            DESKTOP_BIN="/usr/bin/freetoken-desktop"
            return 0
        fi
        echo "[WARN] dpkg -i failed; falling back to local extraction (dpkg -x)."
    else
        echo "[WARN] dpkg not available; falling back to local extraction (dpkg -x)."
    fi

    # Fallback: extract into a local prefix (no root / broken deps / no dpkg).
    if ! command -v dpkg >/dev/null 2>&1; then
        echo "ERROR: neither dpkg -i nor dpkg -x is possible (no dpkg)."
        return 1
    fi
    local debroot="${APP_DIR}/debroot"
    rm -rf "${debroot}"
    mkdir -p "${debroot}"
    dpkg -x "${deb_path}" "${debroot}"
    chmod +x "${debroot}/usr/bin/freetoken-desktop"
    echo "${DESKTOP_DEB_VERSION}" > "${debroot}/.installed_version"
    # Menu/icons integration inside the isolated HOME.
    mkdir -p "${XDG_DATA_HOME}/applications"
    # The .desktop's Exec points at /usr/bin/freetoken-desktop, which does not
    # exist in the dpkg -x fallback; rewrite it to the local binary so the menu
    # entry actually launches the GUI.
    if [ -f "${debroot}/usr/share/applications/FreeToken Desktop.desktop" ]; then
        sed "s|^Exec=.*|Exec=${DESKTOP_BIN}|" \
            "${debroot}/usr/share/applications/FreeToken Desktop.desktop" \
            > "${XDG_DATA_HOME}/applications/FreeToken Desktop.desktop" 2>/dev/null || true
    fi
    if [ -d "${debroot}/usr/share/icons" ]; then
        cp -r "${debroot}/usr/share/icons/." "${XDG_DATA_HOME}/icons/" 2>/dev/null || true
    fi
    # If we happen to be root, link the Tauri resource dir so the (already
    # neutralized) in-app engine installer would still be findable.
    if [ "$(id -u)" = "0" ]; then
        ln -sfn "${debroot}/usr/lib/FreeToken Desktop" "/usr/lib/FreeToken Desktop" 2>/dev/null || true
    fi
    DESKTOP_BIN="${debroot}/usr/bin/freetoken-desktop"
    echo "--- FreeToken Desktop installed locally: ${DESKTOP_BIN} ---"
    return 0
}

echo "--- Setting up FreeToken Desktop GUI ---"
if ! install_desktop_app; then
    echo "ERROR: FreeToken Desktop could not be installed. The engine would run,"
    echo "but without the requested GUI the instance is stopped here."
    exit 1
fi

# ============================================================================
# 6. Launch the FreeToken engine (background service on loopback)
# ============================================================================
echo "--- Launching FreeToken engine on 127.0.0.1:${FT_PORT} ---"

# Build the server command as an array so arguments stay correctly quoted (no eval).
FT_ARGS=(serve --model "${FREETOKEN_MODEL}" --host 127.0.0.1 --port "${FT_PORT}")

# Allow extra engine args via INSTANCE_CONF_DIR/freetoken_serve_args.txt
if [ -f "${INSTANCE_CONF_DIR}/freetoken_serve_args.txt" ]; then
    for user_arg in $(cat "${INSTANCE_CONF_DIR}/freetoken_serve_args.txt"); do
        FT_ARGS+=( "${user_arg}" )
    done
fi

echo "FreeToken command: ft ${FT_ARGS[*]}"
nohup ft "${FT_ARGS[@]}" > "${INSTANCE_CONF_DIR}/ft_serve.log" 2>&1 &
FT_PID=$!
echo "FreeToken engine PID: ${FT_PID}"

# Cleanup handler: kill the background engine on exit so the process group
# (already set by the process manager) and the engine both stop together.
# NOTE: the `exec` of the GUI below replaces this shell, so EXIT traps no
# longer fire afterwards; from that point the engine lifetime is bound to the
# instance process group (killed by the manager on stop) and to the watchdog.
cleanup() {
    kill "${FT_PID}" 2>/dev/null || true
}
trap cleanup EXIT SIGINT SIGTERM

# --- Health-check loop. /health always returns HTTP 200 ({"status": loading|ok|error}),
# so a successful curl means the HTTP server is accepting connections. First run
# downloads the model (up to ~10 min), hence the generous timeout.
echo "--- Waiting for FreeToken /health on port ${FT_PORT} (timeout ${FREETOKEN_HEALTH_TIMEOUT}s) ---"
HEALTH_URL="http://127.0.0.1:${FT_PORT}/health"
WAITED=0
until curl -sf -o /dev/null "${HEALTH_URL}"; do
    WAITED=$((WAITED + 1))
    if [ $((WAITED % 30)) -eq 0 ]; then
        echo "... still waiting for FreeToken (${WAITED}s, first run may be downloading the model)..."
    fi
    if [ "${WAITED}" -ge "${FREETOKEN_HEALTH_TIMEOUT}" ]; then
        echo "ERROR: FreeToken did not become healthy within ${FREETOKEN_HEALTH_TIMEOUT}s. Aborting."
        kill "${FT_PID}" 2>/dev/null || true
        exit 1
    fi
    # If the engine died early (e.g. wrong arch), fail fast instead of waiting.
    if ! kill -0 "${FT_PID}" 2>/dev/null; then
        echo "ERROR: FreeToken engine process exited during startup. See ${INSTANCE_CONF_DIR}/ft_serve.log"
        exit 1
    fi
    sleep 1
done
echo "--- FreeToken engine is up. ---"

# --- Watchdog: if the engine dies, tear down the whole process group so we
# don't leave a GUI pointed at a dead backend. The process-group leader is
# kasm_launcher.sh (setsid on its Popen in process_manager.py), NOT this
# blueprint, so `kill -TERM -- -$$` would target the wrong group (ESRCH).
# Resolve the actual PGID of this shell and signal that group; fall back to
# the engine PID alone. ---
(
    while kill -0 "${FT_PID}" 2>/dev/null; do
        sleep 2
    done
    echo "--- FreeToken engine (PID ${FT_PID}) exited. Tearing down instance. ---"
    PGID="$(ps -o pgid= -p $$ | tr -d '[:space:]')"
    if [ -n "${PGID}" ] && [ "${PGID}" != "0" ]; then
        kill -TERM -- "-${PGID}" 2>/dev/null || kill -TERM "${FT_PID}" 2>/dev/null || true
    else
        kill -TERM "${FT_PID}" 2>/dev/null || true
    fi
) &

# ============================================================================
# 7. Launch the FreeToken Desktop GUI on the KasmVNC display
# ----------------------------------------------------------------------------
# DISPLAY is allocated by the process manager and owned by the Xvnc started by
# kasm_launcher.sh (persistent mode). Wait for the X socket, then exec the GUI
# as this script's foreground process. WebKitGTK software-rendering flags are
# set because KasmVNC runs a plain Xvnc with no GPU-accelerated GL.
# ============================================================================
export DISPLAY="${DISPLAY:-:1}"
SOCKET_FILE="/tmp/.X11-unix/X${DISPLAY#:}"
echo "Waiting for X socket at ${SOCKET_FILE}..."
MAX_RETRIES=30
count=0
while [ ! -e "${SOCKET_FILE}" ]; do
    sleep 1
    count=$((count+1))
    if [ "${count}" -ge "${MAX_RETRIES}" ]; then
        echo "ERROR: X socket ${SOCKET_FILE} not found after ${MAX_RETRIES}s. Aborting."
        exit 1
    fi
done

# WebKitGTK in an Xvnc/software-GL environment: disable DMABUF + compositing
# to avoid the well-known blank-window / crash behavior without real GL.
export WEBKIT_DISABLE_DMABUF_RENDERER=1
export WEBKIT_DISABLE_COMPOSITING_MODE=1
export GDK_BACKEND=x11

echo "--- Launching FreeToken Desktop GUI: ${DESKTOP_BIN} ---"
exec "${DESKTOP_BIN}"