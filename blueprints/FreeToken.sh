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
# REQUIRES: NVIDIA Ampere (sm_80) or newer; official FreeToken releases only
# (no source builds). Install takes ~10-15 min (release wheels + Desktop .deb).
#
# HOW THE PIECES FIT TOGETHER
#   * The .deb (pinned v0.2.0-beta.16) is only the Tauri GUI: it does NOT
#     contain the engine. If no engine is found, the app runs its bundled
#     engine/install.sh which installs the release wheels into its own
#     ~/.freetoken/venv -- a duplicate engine we must avoid. We therefore:
#       1. install the engine ourselves in the AiKore conda venv (./env),
#          from the OFFICIAL releases only (route below, sm_80+ required);
#       2. pre-position the engine where the Desktop looks for it:
#            - $HOME/.freetoken/venv/bin/ft  (canonical path, FREETOKEN_HOME)
#            - $HOME/.local/bin/ft           (PATH symlink, as install.sh does)
#            - $HOME/.config/environment.d/50-freetoken.conf (official marker)
#            - export FREETOKEN_FT_BIN for the GUI session (the app logs
#              "[ok] FREETOKEN_FT_BIN set for this session: <path>")
#         -> the app reports the engine as installed and NEVER runs its own
#            installer (which would create a duplicate engine venv).
#   * ENGINE LIFECYCLE IS HYBRID (blueprint pre-launch + supervised restart):
#     the blueprint PRE-LAUNCHES `ft serve` (default model FREETOKEN_MODEL) on
#     the loopback port BEFORE the GUI and health-waits until it is reachable
#     (run-1 topology). The engine is then SUPERVISED with RESTART (not
#     teardown): if `ft serve` dies, the supervisor restarts it with backoff
#     (5/15/30 s, 3 attempts max). Before each attempt it checks whether the
#     port was taken over by something else (e.g. the Desktop app launching
#     its own engine via FREETOKEN_FT_BIN); if so it stands down gracefully
#     and never fights over the port. If the engine stays dead after 3
#     attempts AND the port is free, it logs a final engine failure but does
#     NOT destroy the instance -- the GUI remains usable. 1919 is the
#     FreeToken + Desktop default port and should NOT be changed via FT_PORT
#     unless you accept the Desktop not finding the engine automatically.
#   * Desktop install: the blueprint runs as the unprivileged 'abc' user
#     (svc-app/run: s6-setuidgid abc), so `dpkg -i` is not possible; the .deb
#     is extracted with `dpkg -x` into a local prefix under APP_DIR + wrapper.
#     The GUI libs (libgtk-3-0, libwebkit2gtk-4.1-0, libayatana-appindicator3-1)
#     are baked into the image by the Dockerfile (apt is not usable as abc).
#     (Tauri resource dir /usr/lib/"FreeToken Desktop" is re-linked when
#     possible; the in-app engine installer is neutralized anyway, so a
#     missing resource dir only costs the bundled installer, never the GUI.)
#   * "Update engine" BLUE BANNER (engineInstall.updateAvailable):
#       - Its button runs Rust `engine_install`, which executes the bundled
#         engine/install.sh. We replace that script with a no-op (step 5b) so
#         clicking can never install a duplicate engine over the
#         blueprint-managed one.
#   * models_dir ALIGNMENT: desktop.json models_dir + FREETOKEN_MODELS_DIR both
#     point to ${APP_DIR}/hf (sl_folder -> shared /config/models/huggingface),
#     the same store HF_HOME uses, so the app and the engine share model data.
#   * Requires NVIDIA Ampere (sm_80) or newer; official FreeToken releases
#     only (no source builds). GPU detection:
#       - sm_80+ : pip freetoken==0.1.2 + pinned prebuilt kernel-cache wheel
#         (sha256 a401e8d0...c120a4f). Install takes ~10-15 min.
#       - < 8.0  : hard exit.
#   * FREETOKEN_DISABLE_JIT=1 (prebuilt kernel cache only, no JIT).
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
#   blueprint launches the engine, then the GUI, in the background and WAITS
#   on them in the foreground as a supervisor (it does NOT `exec` the GUI).
#   The engine is pre-launched by the blueprint and supervised with restart
#   (see above). On Stop the manager killpg's the whole group; this script's
#   TERM/EXIT trap then kills the GUI and the supervised engine (escalating
#   to SIGKILL) and, defensively, any residual `ft serve` on the loopback
#   port, so the port is always released even if the GUI/engine ignore
#   SIGTERM. Closing the GUI window stops the app and triggers the teardown
#   (engine killed, port 1919 reclaimed) via the EXIT trap.
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

# Internal FreeToken API port (loopback only). 1919 is the FreeToken engine
# default AND the port FreeToken Desktop expects: do not override unless you
# accept the Desktop not finding the blueprint-started engine automatically.
FT_PORT="${FT_PORT:-1919}"

# Default model (HF repo ID or local path). The Desktop downloads it on first
# load (not at install); it is also the model used by the pre-launched
# `ft serve` (section 6).
FREETOKEN_MODEL="${FREETOKEN_MODEL:-Qwen/Qwen3-0.6B}"

# Health-wait timeout for the pre-launched engine (seconds). The engine must
# become reachable on the loopback port before the GUI is launched.
FREETOKEN_HEALTH_TIMEOUT="${FREETOKEN_HEALTH_TIMEOUT:-900}"

# Pinned versions (engine)
FREETOKEN_VERSION="0.1.2"
FREE_TOKEN_WHEEL="freetoken==${FREETOKEN_VERSION}"
KERNEL_CACHE_WHEEL_URL="https://github.com/FlashML-org/FreeToken/releases/download/v${FREETOKEN_VERSION}/freetoken_kernel_cache-${FREETOKEN_VERSION}%2Bcu130-py3-none-linux_x86_64.whl"
KERNEL_CACHE_WHEEL_SHA256="a401e8d0fb80405e99e120f20c43b207662110b2ba7a3b93c84e04887c120a4f"

# Desktop download mode (TWO MODES, see also the header above):
#   * DEFAULT (DESKTOP_PIN_VERSION empty): "always latest" rolling beta. The
#     .deb is fetched from the MOVING "beta" release tag, so every new beta
#     FlashML cuts is picked up automatically. Because the Desktop and the
#     engine are released independently, a brand-new Desktop build is NOT
#     guaranteed to be tested against the blueprint-managed engine; the
#     blueprint therefore logs a WARNING whenever the build changes since the
#     last run (see section 5). To freeze a version, set DESKTOP_PIN_VERSION.
#   * PINNED (DESKTOP_PIN_VERSION=<tag>): the .deb is fetched from the
#     immutable versioned tag v<tag>. The version stays frozen forever. An
#     optional DESKTOP_DEB_SHA256 enables strict integrity verification
#     (mismatch -> hard exit); if left empty the version is accepted with a
#     warning (still frozen, just not sha-verified).
#
# RE-PIN PROCEDURE (to adopt a newer Desktop build in PINNED mode):
#   1. List the versioned releases and pick the newest tag:
#        curl -fsSL https://api.github.com/repos/FlashML-org/FreeToken-Web/releases \
#          | jq -r '.[].tag_name' | grep -v '^beta$' | head -n1
#   2. Download that tag's .deb and compute its real sha256 + version:
#        curl -fsSL -o /tmp/freetoken-desktop-amd64.deb \
#          "https://github.com/FlashML-org/FreeToken-Web/releases/download/<TAG>/freetoken-desktop-amd64.deb"
#        sha256sum /tmp/freetoken-desktop-amd64.deb
#        dpkg-deb -f /tmp/freetoken-desktop-amd64.deb Version
#   3. Set DESKTOP_PIN_VERSION=<TAG> (without the leading 'v') and, optionally,
#      DESKTOP_DEB_SHA256=<sha256> below.
#   4. Sanity-check the internal structure still matches our patches (see
#      section 5b): the engine installer must be at
#      usr/lib/"FreeToken Desktop"/engine/install.sh and the binary at
#      usr/bin/freetoken-desktop. If either moved, adapt the paths in
#      install_desktop_app / neutralize_engine_installer (they now WARN and
#      continue instead of failing, so a moved path degrades gracefully).
DESKTOP_PIN_VERSION="${DESKTOP_PIN_VERSION:-}"
DESKTOP_DEB_SHA256="${DESKTOP_DEB_SHA256:-}"
DESKTOP_DEB_VERSION="${DESKTOP_DEB_VERSION:-}"
DESKTOP_PACKAGE="free-token-desktop"

# Marker written after the FreeToken runtime is installed (records GPU arch used).
# Placed inside ${VENV_DIR}: clean_env removes only the venv on a "Rebuild
# Environment" (see functions.sh), so this marker is carried away with it and a
# rebuilt (empty) env is never wrongly treated as already installed.
FT_INSTALL_MARKER="${VENV_DIR}/.freetoken_installed"

# ============================================================================
# 0. GitHub connectivity guard
# ----------------------------------------------------------------------------
# Fail fast with a clear message if GitHub is unreachable instead of a cryptic
# crash mid-download: the release downloads below (engine kernel-cache wheel,
# Desktop .deb) are served from github.com / codeload.github.com.
# ============================================================================

check_github_connectivity() {
    echo "--- Checking GitHub connectivity ---"
    # Both hosts serve parts of the release downloads (kernel-cache wheel,
    # Desktop .deb). Test both.
    if ! curl -fsI --max-time 10 https://codeload.github.com/ >/dev/null 2>&1; then
        echo "=============================================================="
        echo "ERROR: GitHub is inaccessible from this container."
        echo "codeload.github.com did not respond within 10s."
        echo "This is usually a filtered/restricted network."
        echo "Configure a proxy (HTTPS_PROXY / HTTP_PROXY) or fix the network,"
        echo "then restart the instance."
        echo "=============================================================="
        exit 1
    fi
    if ! curl -fsI --max-time 10 https://github.com/ >/dev/null 2>&1; then
        echo "=============================================================="
        echo "ERROR: github.com is inaccessible from this container."
        echo "The FreeToken release downloads (kernel-cache wheel, Desktop .deb)"
        echo "are served from github.com and cannot be reached."
        echo "Configure a proxy (HTTPS_PROXY / HTTP_PROXY) or fix the network,"
        echo "then restart the instance."
        echo "=============================================================="
        exit 1
    fi
    echo "--- GitHub reachable. ---"
}

check_github_connectivity

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
# BEFORE the engine install (~10-15 min) -- instead of discovering a dead
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

install_freetoken() {
    local cap
    cap="$(detect_gpu_compute_cap || true)"
    if [ -z "${cap}" ]; then
        echo "=============================================================="
        echo "ERROR: No NVIDIA GPU detected (nvidia-smi unavailable or empty)."
        echo "FreeToken requires an Ampere (RTX 30) or newer GPU"
        echo "(compute capability >= 8.0)."
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
    else
        echo "=============================================================="
        echo "ERROR: FreeToken requires an Ampere (RTX 30) or newer GPU"
        echo "(compute capability >= 8.0). Found: ${cap}"
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
# the 0.2.0-beta.16 binary + the bundled engine/install.sh):
#   1. FREETOKEN_FT_BIN env var for the GUI session (explicit, most reliable);
#   2. $FREETOKEN_HOME/venv/bin/ft  (canonical install path of install.sh);
#   3. ~/.local/bin/ft on PATH (install.sh's symlink);
#   4. ~/.config/environment.d/50-freetoken.conf (official marker file).
# With all four in place the app reports the engine as installed and its
# in-app installer (which would create a duplicate engine venv in the fake
# home) is never triggered. The symlinks are absolute -> they survive
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

# Where the Desktop stores converted/downloaded models (FTW checkpoints), and
# where the engine stores its HF downloads. We ALIGN them to the SAME shared
# /config/models/huggingface store (${APP_DIR}/hf via sl_folder) so the app and
# the engine can never diverge. The Desktop keeps its own registry in the fake
# home's .config/freetoken/desktop.json; the field is literally 'models_dir'
# (confirmed in the 0.2.0-beta.16 binary: desktop.json holds models_dir,
# daemon_url/port/token, hf_endpoint, ...). We honour BOTH the env var the Rust
# runtime reads (FREETOKEN_MODELS_DIR) and desktop.json, both -> ${APP_DIR}/hf.
export FREETOKEN_MODELS_DIR="${APP_DIR}/hf"

# ----------------------------------------------------------------------------
# Align the Desktop's own models_dir to the shared HF store. Idempotent: merges
# models_dir into an existing desktop.json (if the app already persisted one)
# without clobbering any other settings, and creates it otherwise.
# ----------------------------------------------------------------------------
write_desktop_config() {
    local djson="${XDG_CONFIG_HOME}/freetoken/desktop.json"
    mkdir -p "${XDG_CONFIG_HOME}/freetoken"
    python3 - "${djson}" "${APP_DIR}/hf" <<'PY'
import json, os, sys
path, mdl = sys.argv[1], sys.argv[2]
data = {}
if os.path.exists(path):
    try:
        with open(path) as f:
            data = json.load(f)
    except Exception:
        data = {}
data["models_dir"] = mdl
with open(path, "w") as f:
    json.dump(data, f, indent=2)
PY
    echo "--- FreeToken Desktop models_dir -> ${APP_DIR}/hf (shared /config/models/huggingface) ---"
    echo "--- wrote ${XDG_CONFIG_HOME}/freetoken/desktop.json ---"
}
write_desktop_config

# ============================================================================
# 5. FreeToken Desktop app (.deb, rolling beta by default / pinned optional)
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
# Download + verify the Desktop .deb and set DESKTOP_DEB_VERSION / DESKTOP_DEB_SHA256
# to the ACTUAL downloaded build. Two modes (see header):
#   * rolling (DESKTOP_PIN_VERSION empty): always-latest "beta" tag; the real
#     sha256 is compared to the state file ${INSTANCE_CONF_DIR}/.desktop_build
#     and a WARNING is logged whenever the build changes since the last run.
#   * pinned (DESKTOP_PIN_VERSION=<tag>): immutable versioned tag v<tag>; strict
#     sha256 check when DESKTOP_DEB_SHA256 is set, warning-only otherwise.
download_desktop_deb() {
    local deb_path="${INSTANCE_CONF_DIR}/freetoken-desktop-amd64.deb"
    local state_file="${INSTANCE_CONF_DIR}/.desktop_build"
    local url mode

    if [ -n "${DESKTOP_PIN_VERSION}" ]; then
        # Basic anti-traversal guard: refuse '/' or '..' in the pin.
        case "${DESKTOP_PIN_VERSION}" in
            */*|*..*)
                echo "=============================================================="
                echo "ERROR: DESKTOP_PIN_VERSION='${DESKTOP_PIN_VERSION}' contains"
                echo "'/' or '..' (invalid). Refusing to build a download URL."
                echo "=============================================================="
                return 1 ;;
        esac
        url="https://github.com/FlashML-org/FreeToken-Web/releases/download/v${DESKTOP_PIN_VERSION}/freetoken-desktop-amd64.deb"
        mode="pinned"
    else
        url="https://github.com/FlashML-org/FreeToken-Web/releases/download/beta/freetoken-desktop-amd64.deb"
        mode="rolling"
    fi

    # Rolling-mode short-circuit: if the .deb already on disk matches the last
    # accepted build, skip the download and just report "unchanged".
    if [ "${mode}" = "rolling" ] && [ -f "${deb_path}" ] && [ -f "${state_file}" ]; then
        local state_sha disk_sha ver
        state_sha="$(sed -n 's/^sha256=//p' "${state_file}")"
        disk_sha="$(sha256sum "${deb_path}" 2>/dev/null | awk '{print $1}')"
        if [ -n "${state_sha}" ] && [ "${disk_sha}" = "${state_sha}" ]; then
            ver="$(sed -n 's/^version=//p' "${state_file}")"
            echo "--- Desktop build unchanged (${ver}, ${disk_sha:0:8}) ---"
            DESKTOP_DEB_VERSION="${ver}"
            DESKTOP_DEB_SHA256="${disk_sha}"
            return 0
        fi
    fi

    echo "--- Downloading FreeToken Desktop (.deb) [${mode} mode] ---"
    wget -q --show-progress -O "${deb_path}" "${url}"

    local real_sha real_sha8 version
    real_sha="$(sha256sum "${deb_path}" | awk '{print $1}')"
    real_sha8="${real_sha:0:8}"
    version="$(dpkg-deb -f "${deb_path}" Version 2>/dev/null || echo "unknown")"

    if [ "${mode}" = "pinned" ]; then
        if [ -n "${DESKTOP_DEB_SHA256}" ]; then
            if [ "${real_sha}" != "${DESKTOP_DEB_SHA256}" ]; then
                echo "=============================================================="
                echo "ERROR: the downloaded freetoken-desktop-amd64.deb does not"
                echo "match the pinned sha256 for version ${DESKTOP_PIN_VERSION}."
                echo "The pinned versioned tag was probably re-published, or the"
                echo "URL/sha256 are out of sync. Review DESKTOP_PIN_VERSION and"
                echo "DESKTOP_DEB_SHA256 in this blueprint (see RE-PIN PROCEDURE)."
                echo "=============================================================="
                rm -f "${deb_path}"
                return 1
            fi
            echo "--- Pinned sha256 verified for version ${DESKTOP_PIN_VERSION} (${real_sha8}) ---"
        else
            echo "[WARN] no sha256 pinned for version ${DESKTOP_PIN_VERSION}; accepting (version stays frozen)."
        fi
    else
        local old_sha="" old_ver=""
        if [ -f "${state_file}" ]; then
            old_sha="$(sed -n 's/^sha256=//p' "${state_file}")"
            old_ver="$(sed -n 's/^version=//p' "${state_file}")"
        fi
        if [ -z "${old_sha}" ]; then
            echo "--- Desktop build ${version} (${real_sha8}) accepted (first run, rolling beta) ---"
        elif [ "${old_sha}" = "${real_sha}" ]; then
            echo "--- Desktop build unchanged (${version}, ${real_sha8}) ---"
        else
            local old_sha8="${old_sha:0:8}"
            echo "=============================================================="
            echo "WARNING: Desktop build CHANGED since last run: ${old_ver}/${old_sha8} -> ${version}/${real_sha8}."
            echo "The Desktop/engine pairing is not guaranteed tested. Set"
            echo "DESKTOP_PIN_VERSION to freeze a version."
            echo "=============================================================="
        fi
        printf 'sha256=%s\nversion=%s\n' "${real_sha}" "${version}" > "${state_file}"
    fi

    DESKTOP_DEB_SHA256="${real_sha}"
    DESKTOP_DEB_VERSION="${version}"
    return 0
}

install_desktop_app() {
    local deb_path="${INSTANCE_CONF_DIR}/freetoken-desktop-amd64.deb"

    # Download + verify + set DESKTOP_DEB_VERSION / DESKTOP_DEB_SHA256.
    if ! download_desktop_deb; then
        return 1
    fi

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

    if command -v dpkg >/dev/null 2>&1; then
        echo "--- Installing .deb with dpkg -i ---"
        if DEBIAN_FRONTEND=noninteractive dpkg -i "${deb_path}"; then
            echo "--- FreeToken Desktop ${DESKTOP_DEB_VERSION} installed system-wide (dpkg) ---"
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
    rm -rf "${debroot}"
    mkdir -p "${debroot}"
    dpkg -x "${deb_path}" "${debroot}"

    # Locate the Desktop binary, tolerant to build layout changes: if the
    # expected path is gone, WARN and search for it instead of failing.
    local bin
    if [ -x "${debroot}/usr/bin/freetoken-desktop" ]; then
        bin="${debroot}/usr/bin/freetoken-desktop"
    else
        bin="$(find "${debroot}" -type f -name 'freetoken-desktop' -perm -u+x 2>/dev/null | head -n1)"
        if [ -z "${bin}" ]; then
            echo "[WARN] Desktop binary not found under ${debroot}; the GUI may not launch."
            bin="${debroot}/usr/bin/freetoken-desktop"
        else
            echo "[WARN] Desktop binary found at unexpected path: ${bin}"
        fi
    fi
    chmod +x "${bin}" 2>/dev/null || true
    echo "${DESKTOP_DEB_VERSION}" > "${debroot}/.installed_version"
    # Menu/icons integration inside the isolated HOME.
    mkdir -p "${XDG_DATA_HOME}/applications"
    # The .desktop's Exec points at /usr/bin/freetoken-desktop, which does not
    # exist in the dpkg -x fallback; rewrite it to the local binary so the menu
    # entry actually launches the GUI.
    if [ -f "${debroot}/usr/share/applications/FreeToken Desktop.desktop" ]; then
        sed "s|^Exec=.*|Exec=${bin}|" \
            "${debroot}/usr/share/applications/FreeToken Desktop.desktop" \
            > "${XDG_DATA_HOME}/applications/FreeToken Desktop.desktop" 2>/dev/null || true
    else
        echo "[WARN] Desktop .desktop entry not found; menu shortcut skipped."
    fi
    if [ -d "${debroot}/usr/share/icons" ]; then
        cp -r "${debroot}/usr/share/icons/." "${XDG_DATA_HOME}/icons/" 2>/dev/null || true
    else
        echo "[WARN] Desktop icons dir not found; icon copy skipped."
    fi
    # If we happen to be root, link the Tauri resource dir so the (already
    # neutralized) in-app engine installer would still be findable.
    if [ "$(id -u)" = "0" ]; then
        ln -sfn "${debroot}/usr/lib/FreeToken Desktop" "/usr/lib/FreeToken Desktop" 2>/dev/null || true
    fi
    DESKTOP_BIN="${bin}"
    echo "--- FreeToken Desktop ${DESKTOP_DEB_VERSION} installed locally: ${DESKTOP_BIN} ---"
    return 0
}

echo "--- Setting up FreeToken Desktop GUI ---"
if ! install_desktop_app; then
    echo "ERROR: FreeToken Desktop could not be installed. The engine would run,"
    echo "but without the requested GUI the instance is stopped here."
    exit 1
fi

# ============================================================================
# 5b. Neutralize the in-app engine installer ("Update engine"/"Install engine")
# ----------------------------------------------------------------------------
# The Desktop shows a blue banner "A newer FreeToken engine build is available"
# with an "Update engine" button (frontend key engineInstall.updateAvailable ->
# Rust command `engine_install` -> runs the bundled engine/install.sh). If the
# user clicked it, the bundled installer would create a second engine venv in
# the fake home, duplicating (and possibly shadowing) the blueprint-managed
# engine. We therefore replace the bundled installer (extracted by
# dpkg -x into ${debroot}) with a no-op that only logs. Even if the banner is
# shown and the button is clicked, nothing harmful can happen. Idempotent: the
# no-op carries an "AiKore" marker so a re-run (or a fresh dpkg -x after a
# rebuild) re-applies cleanly.
# ============================================================================
neutralize_engine_installer() {
    local debroot="${APP_DIR}/debroot"
    local engine_dir="${debroot}/usr/lib/FreeToken Desktop/engine"
    if [ ! -d "${engine_dir}" ]; then
        echo "[WARN] Desktop engine resource dir not found; skipping installer neutralization."
        return 0
    fi
    if [ -f "${engine_dir}/install.sh" ] && grep -q "AiKore" "${engine_dir}/install.sh" 2>/dev/null; then
        echo "--- engine installers already neutralized (no-op present), skipping ---"
        return 0
    fi
    echo "--- Neutralizing FreeToken Desktop engine installer (Update/Install -> no-op) ---"
    cat > "${engine_dir}/install.sh" <<'SH'
#!/usr/bin/env bash
# AiKore no-op: the FreeToken engine is managed by the AiKore blueprint
# (official v0.1.2 wheel + pinned kernel-cache, FREETOKEN_DISABLE_JIT=1).
# This intercepts "Update engine" / "Install engine" / "Reinstall engine" so
# the Desktop can never install a duplicate engine over the managed one.
echo "$(date -u +%FT%TZ) [freetoken-desktop] engine install/update requested but blocked by AiKore (engine managed by blueprint: official v0.1.2)." >> /tmp/freetoken_engine_install.log
exit 0
SH
    chmod +x "${engine_dir}/install.sh"
    # Windows-only bundle; make it inert too (not used on this Linux image).
    echo "# AiKore no-op; see engine/install.sh" > "${engine_dir}/install.ps1"
    echo "--- engine installers neutralized ---"
}
neutralize_engine_installer

# ============================================================================
# 6. Engine lifecycle: HYBRID (blueprint pre-launch + supervised restart)
# ----------------------------------------------------------------------------
# The blueprint PRE-LAUNCHES `ft serve` (default model FREETOKEN_MODEL) on the
# loopback port BEFORE the GUI, exactly like the run that worked, and health-
# waits until the engine is reachable. The engine is then SUPERVISED with
# RESTART (not teardown): if `ft serve` dies, the supervisor restarts it with
# backoff (5/15/30 s, 3 attempts max). Before each attempt it checks whether
# the port was taken over by something else (e.g. the Desktop app launching
# its own engine via FREETOKEN_FT_BIN); if so it stands down gracefully and
# never fights over the port. If the engine stays dead after 3 attempts AND
# the port is free, the supervisor logs a final engine failure but does NOT
# destroy the instance -- the GUI remains usable.
#
# The Desktop app is wired to the same engine via the 4 handoff mechanisms
# (section 3b): FREETOKEN_FT_BIN, $FREETOKEN_HOME/venv/bin/ft, ~/.local/bin/ft
# and environment.d/50-freetoken.conf. Because the blueprint already owns the
# port, the app detects "engine already running" and attaches to it instead of
# spawning a duplicate.
# ============================================================================

# --- Reclaim an orphaned engine on the loopback port (defensive) ---
# If a previous Stop left an engine alive, the port is still bound. Detect it,
# kill the orphan with a clear message, then start fresh. Re-attaching to an
# unknown orphan is fragile (its model/state are not ours), so we always
# reclaim.
free_ft_port() {
    if python3 -c "import socket; s=socket.socket(); s.bind(('127.0.0.1', ${FT_PORT})); s.close()" 2>/dev/null; then
        return 0
    fi
    echo "=============================================================="
    echo "WARNING: Port ${FT_PORT} is already in use (orphaned engine from"
    echo "a previous run that survived the last Stop). Reclaiming it..."
    echo "=============================================================="
    local pids=""
    pids="$(ss -tlnp 2>/dev/null | awk -v p=":${FT_PORT} " '$0 ~ p { for(i=1;i<=NF;i++) if($i ~ /^pid=/) { gsub(/pid=/,"",$i); gsub(/,.*/,"",$i); print $i } }' | sort -u)"
    if [ -z "${pids}" ]; then
        pids="$(fuser "${FT_PORT}/tcp" 2>/dev/null || true)"
    fi
    if [ -n "${pids}" ]; then
        echo "--- Killing orphaned process(es) on port ${FT_PORT}: ${pids} ---"
        kill -KILL ${pids} 2>/dev/null || true
        sleep 1
    fi
    if python3 -c "import socket; s=socket.socket(); s.bind(('127.0.0.1', ${FT_PORT})); s.close()" 2>/dev/null; then
        echo "--- Port ${FT_PORT} reclaimed. ---"
    else
        echo "ERROR: Port ${FT_PORT} is still in use and could not be freed."
        echo "Check for a lingering process manually and stop it."
        exit 1
    fi
}
free_ft_port

# --- Instance diagnostics log directory ---
LOGS_DIR="${INSTANCE_CONF_DIR}/logs"
mkdir -p "${LOGS_DIR}"
FT_SERVE_LOG="${LOGS_DIR}/ft-serve.log"
GUI_LOG="${LOGS_DIR}/freetoken-desktop.log"

# --- Port helper: returns 0 when the loopback port is free (bind succeeds) ---
port_free() {
    python3 -c "import socket; s=socket.socket(); s.bind(('127.0.0.1', ${FT_PORT})); s.close()" 2>/dev/null
}

# --- Start the engine (background, output appended to ft-serve.log) ---
start_engine() {
    echo "$(date -u +%FT%TZ) [supervisor] starting ft serve --model ${FREETOKEN_MODEL} --host 127.0.0.1 --port ${FT_PORT}"
    "${VENV_DIR}/bin/ft" serve --model "${FREETOKEN_MODEL}" --host 127.0.0.1 --port "${FT_PORT}" >> "${FT_SERVE_LOG}" 2>&1 &
    ENGINE_PID=$!
    engine_dead_handled=0
    echo "$(date -u +%FT%TZ) [supervisor] FreeToken engine PID: ${ENGINE_PID}"
}

# --- Health-wait: block until the engine is reachable on the loopback port ---
wait_engine_healthy() {
    local deadline=$(( $(date +%s) + FREETOKEN_HEALTH_TIMEOUT ))
    echo "--- Waiting for FreeToken engine to become healthy on 127.0.0.1:${FT_PORT} (timeout ${FREETOKEN_HEALTH_TIMEOUT}s) ---"
    while [ "$(date +%s)" -lt "${deadline}" ]; do
        if ! kill -0 "${ENGINE_PID}" 2>/dev/null; then
            echo "ERROR: FreeToken engine process died during startup."
            return 1
        fi
        if python3 -c "import socket; s=socket.create_connection(('127.0.0.1', ${FT_PORT}), timeout=2); s.close()" 2>/dev/null; then
            echo "--- FreeToken engine is healthy on 127.0.0.1:${FT_PORT} ---"
            return 0
        fi
        sleep 2
    done
    echo "ERROR: FreeToken engine did not become healthy within ${FREETOKEN_HEALTH_TIMEOUT}s."
    return 1
}

# --- Copy the most recent Desktop internal logs for autodiagnosis ---
copy_app_logs() {
    echo "--- Copying recent FreeToken Desktop internal logs for autodiagnosis ---"
    local dirs=("${FAKE_HOME}/.config/freetoken" "${FAKE_HOME}/.freetoken")
    local d newest
    for d in "${dirs[@]}"; do
        if [ -d "${d}" ]; then
            newest="$(find "${d}" -maxdepth 2 -name '*.log' -type f -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -n1 | cut -d' ' -f2-)"
            if [ -n "${newest}" ] && [ -f "${newest}" ]; then
                echo "--- Last 50 lines of ${newest} ---"
                tail -n 50 "${newest}" 2>/dev/null || true
            fi
        fi
    done
}

# --- Supervisor teardown (no `exec` of the GUI) ---
# This script stays alive as the supervisor: it launches the GUI in the
# background and waits on it in the foreground. On any exit or signal
# (TERM/INT from the manager's killpg, or the GUI closing) it kills the GUI
# and the supervised engine, escalating to SIGKILL after a short grace period.
# It also defensively kills any residual `ft serve` on the loopback port so the
# port is ALWAYS released even if the GUI/engine ignore SIGTERM.
cleanup() {
    echo "--- FreeToken teardown: stopping GUI (PID ${GUI_PID:-none}) and engine (PID ${ENGINE_PID:-none}) on port ${FT_PORT} ---"
    if [ -n "${GUI_PID:-}" ]; then
        kill "${GUI_PID}" 2>/dev/null || true
    fi
    if [ -n "${ENGINE_PID:-}" ]; then
        kill "${ENGINE_PID}" 2>/dev/null || true
    fi
    # Kill any residual `ft serve` the Desktop daemon may have left running.
    local engine_pids=""
    if [ -f "${FAKE_HOME}/.freetoken/engine.pid" ]; then
        engine_pids="$(cat "${FAKE_HOME}/.freetoken/engine.pid" 2>/dev/null || true)"
    fi
    if [ -z "${engine_pids}" ]; then
        engine_pids="$(ss -tlnp 2>/dev/null | awk -v p=":${FT_PORT} " '$0 ~ p { for(i=1;i<=NF;i++) if($i ~ /^pid=/) { gsub(/pid=/,"",$i); gsub(/,.*/,"",$i); print $i } }' | sort -u)"
    fi
    if [ -z "${engine_pids}" ]; then
        engine_pids="$(fuser "${FT_PORT}/tcp" 2>/dev/null || true)"
    fi
    if [ -n "${engine_pids}" ]; then
        echo "--- Stopping residual engine process(es): ${engine_pids} ---"
        kill ${engine_pids} 2>/dev/null || true
    fi
    local i=0
    while [ "${i}" -lt 10 ]; do
        local alive=0
        if [ -n "${GUI_PID:-}" ] && kill -0 "${GUI_PID}" 2>/dev/null; then alive=1; fi
        if [ -n "${ENGINE_PID:-}" ] && kill -0 "${ENGINE_PID}" 2>/dev/null; then alive=1; fi
        if [ -n "${engine_pids}" ]; then
            for ep in ${engine_pids}; do
                if kill -0 "${ep}" 2>/dev/null; then alive=1; fi
            done
        fi
        if [ "${alive}" = "0" ]; then break; fi
        sleep 1
        i=$((i+1))
    done
    if [ -n "${GUI_PID:-}" ]; then kill -KILL "${GUI_PID}" 2>/dev/null || true; fi
    if [ -n "${ENGINE_PID:-}" ]; then kill -KILL "${ENGINE_PID}" 2>/dev/null || true; fi
    if [ -n "${engine_pids}" ]; then kill -KILL ${engine_pids} 2>/dev/null || true; fi
}
trap cleanup EXIT SIGINT SIGTERM

# ============================================================================
# 7. Pre-launch engine, then launch the GUI, then supervise both
# ----------------------------------------------------------------------------
# DISPLAY is allocated by the process manager and owned by the Xvnc started by
# kasm_launcher.sh (persistent mode). Wait for the X socket, then pre-launch
# the engine and health-wait, then launch the GUI in the background and
# supervise both in the foreground. WebKitGTK software-rendering flags are set
# because KasmVNC runs a plain Xvnc with no GPU-accelerated GL.
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

# --- Pre-launch the engine and health-wait BEFORE the GUI (run-1 topology) ---
start_engine
if ! wait_engine_healthy; then
    echo "ERROR: FreeToken engine failed to become healthy. The GUI will not be launched."
    exit 1
fi

# --- Launch the FreeToken Desktop GUI (output appended to the instance log) ---
echo "--- Launching FreeToken Desktop GUI: ${DESKTOP_BIN} ---"
"${DESKTOP_BIN}" >> "${GUI_LOG}" 2>&1 &
GUI_PID=$!
echo "FreeToken Desktop GUI PID: ${GUI_PID}"

# --- Supervisor loop: monitor GUI + engine ---
# The supervisor stays alive (no exec) so its EXIT/TERM traps keep working.
# If the GUI dies, log its exit code, copy the app's internal logs for
# autodiagnosis, then teardown (cleanup kills the engine and reclaims 1919).
# If the engine dies, restart it with backoff (5/15/30 s, 3 attempts max),
# standing down if the port is taken over by the Desktop app's own engine.
restart_attempts=0
backoff=(5 15 30)
engine_standing_down=0
engine_dead_handled=0

while true; do
    # GUI died -> teardown
    if ! kill -0 "${GUI_PID}" 2>/dev/null; then
        set +e
        wait "${GUI_PID}"
        GUI_EXIT_CODE=$?
        set -e
        echo "--- FreeToken Desktop GUI exited with code ${GUI_EXIT_CODE} ---"
        copy_app_logs
        break
    fi

    # Engine died -> supervised restart (handle each death exactly once)
    if ! kill -0 "${ENGINE_PID}" 2>/dev/null; then
        if [ "${engine_dead_handled}" = "0" ]; then
            engine_dead_handled=1
            wait "${ENGINE_PID}" 2>/dev/null || true
            echo "$(date -u +%FT%TZ) [supervisor] FreeToken engine (PID ${ENGINE_PID}) died."
            if [ "${engine_standing_down}" = "1" ]; then
                echo "$(date -u +%FT%TZ) [supervisor] engine standing down; not restarting."
            elif [ "${restart_attempts}" -ge 3 ]; then
                echo "$(date -u +%FT%TZ) [supervisor] engine failed after 3 restart attempts; leaving it down (GUI remains usable)."
                engine_standing_down=1
            elif ! port_free; then
                echo "$(date -u +%FT%TZ) [supervisor] engine port now managed by Desktop app, standing down."
                engine_standing_down=1
            else
                sleep "${backoff[restart_attempts]}"
                restart_attempts=$((restart_attempts+1))
                echo "$(date -u +%FT%TZ) [supervisor] restarting engine (attempt ${restart_attempts}/3)..."
                start_engine
            fi
        fi
    fi

    sleep 1
done