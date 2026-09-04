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
# FreeToken Desktop blueprint for AiKore -- OFFICIAL PROCESS, PURE FORM
# ----------------------------------------------------------------------------
# Official FreeToken Desktop experience in AiKore: the app installs and
# manages its own engine (official process). Requires Ampere (sm_80+).
# First model load downloads the engine (~5.5 GB) via the app UI.
#
# IMAGE PREREQUISITES (baked into the Dockerfile):
#   * GUI libs: libgtk-3-0, libwebkit2gtk-4.1-0, libayatana-appindicator3-1
#     (Tauri/WebKitGTK Desktop GUI).
#   * python3-venv (ensurepip): the Desktop's bundled engine installer creates
#     ~/.freetoken/venv with the SYSTEM python. Without python3-venv the venv
#     is created but bin/ comes out EMPTY and the engine never installs.
#
# WHAT THIS BLUEPRINT DOES (and ONLY this):
#   1. Guards: NVIDIA GPU with compute capability >= 8.0 (Ampere) and GitHub
#      reachability (the Desktop .deb is served from github.com).
#   2. MINIMAL conda environment (python only): the platform expects a venv
#      for the instance terminal. The ENGINE IS NOT INSTALLED HERE.
#   3. Fake home (INSTANCE_CONF_DIR/internal_home) + XDG redirection, so the
#      app's state (.config/freetoken/desktop.json) AND ITS ENGINE VENV
#      (~/.freetoken/venv, ~5.5 GB) stay isolated and persistent per
#      instance, without polluting /home/abc.
#   4. Shared model storage: desktop.json models_dir + FREETOKEN_MODELS_DIR +
#      HF_HOME all point to ${APP_DIR}/hf (sl_folder -> the shared persistent
#      /config/models/huggingface), so models downloaded by the app (or by
#      its engine) land in the shared store, not in a throwaway dir.
#   5. FreeToken Desktop .deb: rolling "beta" release by default
#      (DESKTOP_PIN_VERSION to freeze), dpkg -i with dpkg -x fallback, GUI
#      libraries checked fail-fast BEFORE the download.
#   6. Launch: wait for the X socket, start the GUI on the KasmVNC display
#      with the WebKit software-rendering flags, then WAIT on it in the
#      foreground as a supervisor and tear everything down on EXIT/INT/TERM
#      (GUI + any residual engine left on the loopback port 1919).
#
# WHAT THE APP DOES ITSELF (official process -- the blueprint must NOT
# interfere, and no longer does):
#   * On first model load, the Desktop runs its BUNDLED engine installer
#     (engine/install.sh shipped inside the .deb), which creates
#     ~/.freetoken/venv (i.e. internal_home/.freetoken/venv, ~5.5 GB,
#     persistent) and installs the official engine from the app's own
#     release channel. Engine logs are visible in the app's "Logs" tab.
#   * The app then starts/stops/supervises its engine (`ft serve`) on
#     127.0.0.1:1919 itself.
#   * Consequently this blueprint deliberately does NOT:
#       - export FREETOKEN_FT_BIN (would make the app skip its own install),
#       - create ~/.freetoken/venv/bin/ft or ~/.local/bin/ft symlinks,
#       - write ~/.config/environment.d/50-freetoken.conf,
#       - pip-install any freetoken wheel (no kernel-cache wheel either),
#       - pre-launch `ft serve`, health-wait it, or supervise/restart it,
#       - neutralize the bundled engine/install.sh (it is left EXACTLY as
#         shipped -- the app NEEDS it for the official self-install).
#     Any of the above would prevent the app from performing its official
#     engine install. A one-shot migration (section 4b) cleans these
#     artifacts if they were left behind by an older AiKore version.
#
# OPTIONAL HEADLESS USAGE (manual, NOT automated by this blueprint):
#   FREETOKEN_MODEL / freetoken_serve_args are intentionally unused: the
#   Desktop owns the engine lifecycle. If you ever want to drive the engine
#   manually from the instance terminal (after the app has installed it
#   once), you can serve a model headless:
#       FREETOKEN_MODEL="Qwen/Qwen3-0.6B"
#       ${INSTANCE_CONF_DIR}/internal_home/.freetoken/venv/bin/ft serve \
#           --model "${FREETOKEN_MODEL}" --host 127.0.0.1 --port 1919
#
# DESKTOP INSTALL MODES (section 6):
#   * DEFAULT (DESKTOP_PIN_VERSION empty): "always latest" rolling beta. The
#     .deb is fetched from the MOVING "beta" release tag, so every new beta
#     FlashML cuts is picked up automatically. Because the Desktop and the
#     engine are released independently, a brand-new Desktop build is NOT
#     guaranteed to be tested against the engine builds it installs itself;
#     a WARNING is logged whenever the build changes since the last run.
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
#   4. Sanity-check the internal structure still matches what we rely on:
#      the binary at usr/bin/freetoken-desktop and the bundled engine
#      installer at usr/lib/"FreeToken Desktop"/engine/install.sh (the app
#      runs that installer itself on first model load -- it must stay
#      pristine). If either moved, adapt the paths in install_desktop_app
#      (they WARN and continue instead of failing, so a moved path degrades
#      gracefully).
#
# PROCESS MODEL (persistent/KasmVNC mode)
#   AiKore launches scripts/kasm_launcher.sh, which:
#     - starts Xvnc (KasmVNC) on the persistent_port with a DISPLAY it owns,
#     - starts openbox,
#     - runs THIS script in the background.
#   The process manager monitors Xvnc (http on persistent_port marks the
#   instance "started"; an optional firefox kiosk is opened on that port by
#   the monitor thread). So there is NO foreground web process here: the
#   blueprint launches the GUI in the background and WAITS on it in the
#   foreground as a supervisor (it does NOT `exec` the GUI). On Stop the
#   manager killpg's the whole group; this script's TERM/EXIT trap kills the
#   GUI and, defensively, any residual engine bound to the loopback port
#   (1919 is the FreeToken + Desktop default port: do not change FT_PORT
#   unless you accept the Desktop not finding its engine). Closing the GUI
#   window exits the supervisor and triggers the same teardown via the EXIT
#   trap.
#
# PLATFORM NOTES (documentation only, not handled here)
#   * Persistent UI: the platform does NOT read the blueprint's
#     `aikore.persistent_mode` flag when creating an instance
#     (eventHandlers.js forces it to false), so the user must tick
#     "Persistent UI" manually at instance creation for the KasmVNC desktop
#     to be shown.
# ============================================================================

set -e

source /opt/sd-install/functions.sh
source /opt/sd-install/versions.env

# --- Load custom instance variables ---
# NOTE: unlike older AiKore versions, FREETOKEN_FT_BIN / FREETOKEN_MODEL /
# freetoken_serve_args have NO effect on the blueprint anymore (official
# process: the app manages its engine). FT_PORT is only used to reclaim the
# loopback port defensively (see section 7).
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

# Internal FreeToken engine port (loopback only), used for the defensive
# reclaim/cleanup below. 1919 is the FreeToken + Desktop default port and
# should NOT be changed unless you accept the Desktop not finding its engine.
FT_PORT="${FT_PORT:-1919}"

# Desktop download mode (TWO MODES, see the header above):
#   * rolling (DESKTOP_PIN_VERSION empty): always-latest "beta" tag.
#   * pinned (DESKTOP_PIN_VERSION=<tag>): immutable versioned tag v<tag>;
#     strict sha256 check when DESKTOP_DEB_SHA256 is set, warning-only
#     otherwise. See the RE-PIN PROCEDURE in the header.
DESKTOP_PIN_VERSION="${DESKTOP_PIN_VERSION:-}"
DESKTOP_DEB_SHA256="${DESKTOP_DEB_SHA256:-}"
DESKTOP_DEB_VERSION="${DESKTOP_DEB_VERSION:-}"
DESKTOP_PACKAGE="free-token-desktop"

# ============================================================================
# 1. GPU guard: FreeToken requires an Ampere (sm_80) or newer GPU
# ----------------------------------------------------------------------------
# The official FreeToken engine only supports compute capability >= 8.0.
# Fail fast with a clean message instead of letting the user discover it
# inside the app after a multi-GB engine download.
# ============================================================================
check_gpu() {
    local cap major minor capnum
    if command -v nvidia-smi >/dev/null 2>&1; then
        cap="$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader 2>/dev/null | head -n1 | tr -d '[:space:]')"
    fi
    if [ -z "${cap}" ]; then
        echo "=============================================================="
        echo "ERROR: No NVIDIA GPU detected (nvidia-smi unavailable or empty)."
        echo "FreeToken requires an Ampere (RTX 30) or newer GPU"
        echo "(compute capability >= 8.0)."
        echo "=============================================================="
        exit 1
    fi

    major="${cap%%.*}"
    minor="${cap##*.}"
    capnum=$((10#${major} * 10 + 10#${minor}))
    echo "--- Detected GPU compute capability: ${cap} (sm_${cap}) ---"

    if [ "${capnum}" -lt 80 ]; then
        echo "=============================================================="
        echo "ERROR: FreeToken requires an Ampere (RTX 30) or newer GPU"
        echo "(compute capability >= 8.0). Found: ${cap}"
        echo "The engine cannot serve on this GPU, so the instance is"
        echo "stopped here (nothing was downloaded)."
        echo "=============================================================="
        exit 1
    fi
}
check_gpu

# ============================================================================
# 2. GitHub connectivity guard
# ----------------------------------------------------------------------------
# Fail fast with a clear message if GitHub is unreachable instead of a cryptic
# crash mid-download: the Desktop .deb release download below is served from
# github.com (assets redirect via objects.githubusercontent.com, release
# archives come from codeload.github.com).
# ============================================================================

check_github_connectivity() {
    echo "--- Checking GitHub connectivity ---"
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
        echo "The FreeToken Desktop .deb release download is served from"
        echo "github.com and cannot be reached."
        echo "Configure a proxy (HTTPS_PROXY / HTTP_PROXY) or fix the network,"
        echo "then restart the instance."
        echo "=============================================================="
        exit 1
    fi
    echo "--- GitHub reachable. ---"
}

check_github_connectivity

# ============================================================================
# 3. Minimal Conda environment (python only)
# ----------------------------------------------------------------------------
# The platform expects a venv in the instance (terminal integration, "Rebuild
# Environment", ...). The FreeToken ENGINE IS NOT INSTALLED HERE: the Desktop
# app installs its own engine in its own venv (official process). This env is
# just a usable python for the instance terminal and helper scripts.
# ============================================================================
echo "--- Setting up minimal Conda environment (python only; NO engine here) ---"
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
# 4. Isolated HOME (the "fake home" pattern, same strategy as LMStudio)
# ----------------------------------------------------------------------------
# FreeToken Desktop persists state in $HOME (config: .config/freetoken/,
# engine home + ITS OWN ENGINE VENV: .freetoken/venv (~5.5 GB), tool
# symlinks: .local/bin/, caches: .cache/). Redirecting HOME into
# INSTANCE_CONF_DIR keeps every instance isolated and persistent without
# polluting /home/abc, and makes the app's self-installed engine persist
# across restarts. XDG_* vars are re-pointed too: the app (Rust `dirs`/Tauri
# + WebKitGTK) honors them and they default to $HOME only when unset -- the
# image sets XDG_CONFIG_HOME=/home/abc globally.
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
# 4a. Self-healing: remove a broken partial engine venv
# ----------------------------------------------------------------------------
# The FreeToken Desktop engine installer creates ~/.freetoken/venv (i.e.
# internal_home/.freetoken/venv) using the SYSTEM python. Older images lacked
# python3-venv/ensurepip, so the venv was created but bin/ came out EMPTY
# (no bin/ft, no bin/python) and the engine never installed. Now that the
# image ships python3-venv, the app can reinstall cleanly -- but only if we
# first remove the broken partial venv. Tolerant: if the internal home (or
# the venv) does not exist yet, this is a silent no-op.
# ============================================================================
INTERNAL_HOME="${FAKE_HOME}"
self_heal_broken_engine_venv() {
    local venv="${INTERNAL_HOME}/.freetoken/venv"
    if [ ! -d "${venv}" ]; then
        return 0
    fi
    if [ -x "${venv}/bin/ft" ] || [ -x "${venv}/bin/python" ]; then
        echo "--- Engine venv present and complete (${venv}), keeping it. ---"
        return 0
    fi
    echo "--- broken partial engine install detected, removing for clean reinstall by the app ---"
    rm -rf "${venv}"
    echo "--- Removed broken engine venv ${venv}; the app will recreate it cleanly. ---"
}
self_heal_broken_engine_venv

# ============================================================================
# 4b. Migration cleanup: remove handoff artifacts from OLD AiKore versions
# ----------------------------------------------------------------------------
# Older versions of this blueprint pre-installed the engine themselves and
# "handed it over" to the app (FREETOKEN_FT_BIN marker, ft symlinks,
# environment.d marker, no-op engine/install.sh). With the official process
# any leftover of that scheme would make the app believe an engine is
# already installed and SKIP its own official install. Clean them up
# (idempotent, no-op on fresh instances).
# ============================================================================
migrate_remove_engine_handoff() {
    local debroot="${APP_DIR}/debroot"
    echo "--- Checking for legacy engine-handoff artifacts (old AiKore scheme) ---"
    # 1. Session env: never hand an ft binary to the app.
    if [ -n "${FREETOKEN_FT_BIN:-}" ]; then
        echo "--- Unsetting legacy FREETOKEN_FT_BIN (${FREETOKEN_FT_BIN}) ---"
        unset FREETOKEN_FT_BIN
    fi
    # 2. environment.d marker (inert without systemd, but remove it anyway).
    rm -f "${XDG_CONFIG_HOME}/environment.d/50-freetoken.conf" 2>/dev/null || true
    # 3. ft symlinks pointing at the old blueprint-managed venv. Only remove
    #    SYMLINKS: a real ft binary would be the app's own official install.
    if [ -L "${FAKE_HOME}/.freetoken/venv/bin/ft" ]; then
        echo "--- Removing legacy symlink ${FAKE_HOME}/.freetoken/venv/bin/ft ---"
        rm -f "${FAKE_HOME}/.freetoken/venv/bin/ft"
    fi
    if [ -L "${FAKE_HOME}/.local/bin/ft" ]; then
        echo "--- Removing legacy symlink ${FAKE_HOME}/.local/bin/ft ---"
        rm -f "${FAKE_HOME}/.local/bin/ft"
    fi
    # 4. Old no-op engine installer (AiKore-marked): wipe the extracted tree
    #    so the app gets a PRISTINE bundled installer (the .deb is kept, a
    #    fresh dpkg -x below restores the original install.sh).
    if [ -f "${debroot}/usr/lib/FreeToken Desktop/engine/install.sh" ] && \
       grep -q "AiKore" "${debroot}/usr/lib/FreeToken Desktop/engine/install.sh" 2>/dev/null; then
        echo "--- Legacy no-op engine installer detected; wiping ${debroot} for a pristine re-extract ---"
        rm -rf "${debroot}"
    fi
}
migrate_remove_engine_handoff

# ============================================================================
# 4c. Shared model storage (desktop.json models_dir + HF_HOME -> shared HF)
# ----------------------------------------------------------------------------
# Model storage: HF_HOME -> /config/models/huggingface (sl_folder) so the
# Desktop's HF downloads (hf-hub honors HF_HOME) are shared and persistent.
# We ALIGN the Desktop's own models_dir (desktop.json) and the engine-side
# FREETOKEN_MODELS_DIR to the SAME shared store (${APP_DIR}/hf via
# sl_folder), so models downloaded by the app or its engine can never
# diverge. The Desktop keeps its registry in the fake home's
# .config/freetoken/desktop.json (field 'models_dir').
# ============================================================================
echo "--- Setting up shared Hugging Face model storage ---"
mkdir -p "${APP_DIR}/hf"
sl_folder "${APP_DIR}" "hf" "/config/models" "huggingface"
export HF_HOME="${APP_DIR}/hf"
export HF_HUB_DISABLE_TELEMETRY=1
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
# 5. GUI system libraries (fail-fast BEFORE downloading the Desktop .deb)
# ----------------------------------------------------------------------------
# The Desktop is a Tauri GUI: it needs libgtk-3, libwebkit2gtk-4.1 and the
# ayatana appindicator libs at runtime. These are baked into the image by the
# Dockerfile. The blueprint runs as the unprivileged 'abc' user
# (svc-app/run: s6-setuidgid abc), so apt is NOT usable at runtime; if the
# image is obsolete and libwebkit2gtk-4.1 is missing, we fail fast here --
# BEFORE the .deb download -- instead of discovering a dead GUI at the end.
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
        echo "[WARN] the Desktop may lack tray/indicator support."
        echo "[WARN] Rebuild the image to get them."
    fi
}

ensure_gui_libraries

# ============================================================================
# 6. FreeToken Desktop app (.deb, rolling beta by default / pinned optional)
# ----------------------------------------------------------------------------
# The Desktop is a Tauri GUI: it needs libgtk-3, libwebkit2gtk-4.1 and the
# ayatana appindicator libs at runtime. These are baked into the image by the
# Dockerfile (the blueprint runs as the unprivileged 'abc' user, so apt is not
# usable at runtime; ensure_gui_libraries above fail-fasts if the image is
# obsolete). The .deb itself is installed with dpkg -i (installs to /usr/bin);
# as 'abc' that will fail, so we fall back to dpkg -x into a local prefix and
# wrap the binary (Tauri bundles its web assets inside the binary, so only
# absolute paths are lost; Tauri resolves its resource dir relative to the
# binary, so the bundled engine/install.sh stays reachable from the local
# prefix too). NOTE: the bundled engine/install.sh is LEFT PRISTINE -- the
# app runs it itself on first model load (official self-install).
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
    mkdir -p "${XDG_DATA_HOME}/applications" "${XDG_DATA_HOME}/icons"
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
    # If we happen to be root, link the Tauri resource dir (which contains the
    # bundled engine/install.sh the app needs for its official self-install)
    # so the app finds it at the absolute path it expects.
    if [ "$(id -u)" = "0" ]; then
        ln -sfn "${debroot}/usr/lib/FreeToken Desktop" "/usr/lib/FreeToken Desktop" 2>/dev/null || true
    fi
    DESKTOP_BIN="${bin}"
    echo "--- FreeToken Desktop ${DESKTOP_DEB_VERSION} installed locally: ${DESKTOP_BIN} ---"
    return 0
}

echo "--- Setting up FreeToken Desktop GUI ---"
if ! install_desktop_app; then
    echo "ERROR: FreeToken Desktop could not be installed. The instance is"
    echo "stopped here (without the GUI there is no usable FreeToken)."
    exit 1
fi

# ============================================================================
# 7. Reclaim an orphaned engine on the loopback port (defensive)
# ----------------------------------------------------------------------------
# If a previous run (or a crashed Stop) left an engine alive, the loopback
# port is still bound. Detect it, kill the orphan with a clear message, then
# let the app start its own engine cleanly. Re-attaching to an unknown orphan
# is fragile (its model/state are not ours), so we always reclaim. This is
# pure residual safety: normally the previous teardown already freed the port.
# ============================================================================
free_ft_port() {
    if python3 -c "import socket; s=socket.socket(); s.bind(('127.0.0.1', ${FT_PORT})); s.close()" 2>/dev/null; then
        echo "--- Port ${FT_PORT} is free (no orphaned engine). ---"
        return 0
    fi
    echo "=============================================================="
    echo "WARNING: Port ${FT_PORT} is already in use (orphaned engine from"
    echo "a previous run that survived the last Stop). Reclaiming it..."
    echo "=============================================================="
    local pids=""
    pids="$(ss -tlnp 2>/dev/null | awk -v p=":${FT_PORT} " '$0 ~ p { for(i=1;i<=NF;i++) if($i ~ /^pid=/) { gsub(/pid=/,"",$i); gsub(/,.*/,"",$i); print $i } }' | sort -u || true)"
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

# --- Instance diagnostics log directory (GUI output) ---
LOGS_DIR="${INSTANCE_CONF_DIR}/logs"
mkdir -p "${LOGS_DIR}"
GUI_LOG="${LOGS_DIR}/freetoken-desktop.log"

# ============================================================================
# 8. Teardown handler: kill the GUI + any residual engine on the loopback port
# ----------------------------------------------------------------------------
# This script stays alive as the supervisor: it launches the GUI in the
# background and waits on it in the foreground. On any exit or signal
# (TERM/INT from the manager's killpg, or the GUI closing) it kills the GUI
# and, defensively, any residual engine process the Desktop daemon may have
# left bound to the loopback port, so the port is ALWAYS released even if the
# GUI/engine ignore SIGTERM. The engine itself is app-managed: we do not own
# it, we only free its port on the way out.
# ============================================================================
cleanup() {
    echo "--- FreeToken teardown: stopping GUI (PID ${GUI_PID:-none}), reclaiming port ${FT_PORT} ---"
    if [ -n "${GUI_PID:-}" ]; then
        kill "${GUI_PID}" 2>/dev/null || true
    fi
    local engine_pids=""
    engine_pids="$(ss -tlnp 2>/dev/null | awk -v p=":${FT_PORT} " '$0 ~ p { for(i=1;i<=NF;i++) if($i ~ /^pid=/) { gsub(/pid=/,"",$i); gsub(/,.*/,"",$i); print $i } }' | sort -u || true)"
    if [ -z "${engine_pids}" ]; then
        engine_pids="$(fuser "${FT_PORT}/tcp" 2>/dev/null || true)"
    fi
    if [ -n "${engine_pids}" ]; then
        echo "--- Stopping residual engine process(es) on port ${FT_PORT}: ${engine_pids} ---"
        kill ${engine_pids} 2>/dev/null || true
    fi
    local i=0
    while [ "${i}" -lt 10 ]; do
        local alive=0
        if [ -n "${GUI_PID:-}" ] && kill -0 "${GUI_PID}" 2>/dev/null; then alive=1; fi
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
    if [ -n "${engine_pids}" ]; then kill -KILL ${engine_pids} 2>/dev/null || true; fi
    echo "--- Teardown complete: GUI stopped, port ${FT_PORT} released. ---"
}
trap cleanup EXIT SIGINT SIGTERM

# ============================================================================
# 9. Wait for the X socket, then launch the GUI (foreground supervision)
# ----------------------------------------------------------------------------
# DISPLAY is allocated by the process manager and owned by the Xvnc started by
# kasm_launcher.sh (persistent mode). Wait for the X socket, then launch the
# GUI in the background and supervise it in the foreground. WebKitGTK
# software-rendering flags are set because KasmVNC runs a plain Xvnc with no
# GPU-accelerated GL.
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

# --- Launch the FreeToken Desktop GUI (output appended to the instance log) ---
echo "--- Launching FreeToken Desktop GUI: ${DESKTOP_BIN} ---"
"${DESKTOP_BIN}" >> "${GUI_LOG}" 2>&1 &
GUI_PID=$!
echo "FreeToken Desktop GUI PID: ${GUI_PID}"

# --- Final log: the engine lifecycle belongs to the app (official process) ---
echo "=============================================================="
echo " FreeToken Desktop is starting on the KasmVNC display (${DISPLAY})."
echo " The engine is NOT installed by this blueprint: it will be installed"
echo " on first model load inside the app (see its Logs tab)."
echo "=============================================================="

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

# --- Supervisor loop: wait on the GUI in the foreground (no exec) ---
# The supervisor stays alive (no exec) so its EXIT/TERM traps keep working.
# If the GUI dies (user closed the window or it crashed), log its exit code,
# copy the app's internal logs for autodiagnosis, then exit: the EXIT trap
# reclaims the loopback port and the manager sees the instance as stopped.
while true; do
    if ! kill -0 "${GUI_PID}" 2>/dev/null; then
        set +e
        wait "${GUI_PID}"
        GUI_EXIT_CODE=$?
        set -e
        echo "--- FreeToken Desktop GUI exited with code ${GUI_EXIT_CODE} ---"
        copy_app_logs
        break
    fi
    sleep 1
done

echo "--- FreeToken Desktop closed. ---"
exit 0