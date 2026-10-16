#!/bin/bash

### AIKORE-METADATA-START ###
# aikore.name = Strata LLM
# aikore.category = Chat / LLM
# aikore.description = Consumer MoE inference engine (Qwen3.8-Flash-Next 125B). Web UI + OpenAI / Anthropic compatible API.
# aikore.venv_type = conda
# aikore.venv_path = ./env
### AIKORE-METADATA-END ###

# =============================================================================
# =============================================================================
# ===                                                                       ===
# ===            COMMENT UTILISER CE BLUEPRINT (à lire une fois)            ===
# ===                                                                       ===
# =============================================================================
# =============================================================================
#
# 1) CE QU'IL FAIT
#    Ce blueprint installe puis lance l'installeur officiel de Strata LLM
#    (setup.py, piloté par ./setup.sh dans le dépôt). Il est idempotent :
#      - au 1er démarrage il télécharge le moteur + le modèle (~70 Go) ;
#      - aux démarrages suivants il relance simplement le serveur.
#    Le serveur écoute sur ${WEBUI_PORT} en interne ; AiKore le publie derrière
#    son proxy nginx (chemin /instance/<slug>/).
#
#    Ce script sait aussi DÉTECTER quand la configuration doit être réécrite :
#    il reconstruit le modèle (setup.py --setup --no-start) uniquement au 1er
#    démarrage, quand STRATA_KV (cache KV) change, ou quand un autre paramètre
#    de configuration change ; sinon il démarre directement à partir de la
#    configuration déjà écrite (branche « already installed: just start it »).
#    C'est indispensable pour STRATA_KV : un setup.py lancé sans --setup sur un
#    modèle déjà installé IGNORE --kv et ne fait que démarrer le serveur.
#
# 2) PERSONNALISER
#    -> Tout ce qui est modifiable est regroupé dans la section
#       « PARAMÈTRES UTILISATEUR » ci-dessous. C'est la SEULE section à éditer.
#       Les variables qui s'y trouvent sont commentées une par une.
#
#    ATTENTION (piège) : ne personnalise PAS via
#       ${INSTANCE_CONF_DIR}/aikore_vars.env
#    ce fichier est AUTO-GÉNÉRÉ ET ÉCRASÉ par AiKore à chaque démarrage de
#    l'instance (aikore/core/process_manager.py). Il ne sert qu'à transmettre
#    PYTHON_VERSION/CUDA_VERSION/PYTORCH_INDEX_URL/TORCH_VERSION décidés par
#    l'UI du « Builder ». Toute valeur Strata que tu y mettrais est perdue.
#    D'où la section de paramètres en tête de script à la place.
#
# 3) PIÈGE « CUSTOM vs STOCK » (blueprint fantôme)
#    AiKore cherche un blueprint, à nom de fichier identique, d'abord dans
#      /config/custom_blueprints/   (volume PERSISTANT, « custom »)
#    puis seulement dans
#      /opt/sd-install/blueprints/  (embarqué dans l'image, « stock »).
#    Un blueprint custom a donc TOUJOURS PRIORITÉ sur le stock.
#    Conséquence : si tu as copié ce script dans /config/custom_blueprints/
#    (pour l'utiliser sans reconstruire l'image), c'est CETTE copie qui est
#    exécutée. Éditer la version du dépôt (celle-ci) n'aura alors AUCUN effet,
#    et tu risques de croire à un bug alors que l'ancienne copie tourne encore.
#    -> Garde UNE SEULE SOURCE DE VÉRITÉ : édite la copie réellement utilisée
#       (celle de /config/custom_blueprints/ si elle existe), ou supprime-la
#       pour revenir à la version stock de l'image.
#
# =============================================================================

# =============================================================================
# =============================================================================
# ===                                                                       ===
# ===              PARAMÈTRES UTILISATEUR  —  À MODIFIER ICI               ===
# ===                                                                       ===
# =============================================================================
# =============================================================================
#
#  Toutes les options ci-dessous pilotent l'installeur officiel de Strata
#  (setup.py). Après modification, redémarre l'instance pour les appliquer.
#
#    Convention : une valeur "" (vide) = « laisse setup.py choisir » (recommandé).
#
# -----------------------------------------------------------------------------

# STRATA_FAMILY : famille de modèle à installer.
#   "qwen"  (défaut) : Qwen3 125B (le plus testé / recommandé).
#   "swift"          : famille alternative.
STRATA_FAMILY="qwen"

# STRATA_MODEL : quantification / variante du modèle.
#   ""        (défaut) : setup.py choisit la variante recommandée pour ta machine.
#   Sinon une des valeurs acceptées par setup.py :
#     Q2_0, IQ2_XS, IQ3_XXS, IQ3_S, ... (voir `setup.py --help`).
STRATA_MODEL=""

# STRATA_CONTEXT : taille de contexte (« fenêtre ») en tokens.
#   ""        (défaut) : auto (dépend du modèle / de la mémoire GPU).
#   Exemple : "32768".
STRATA_CONTEXT=""

# STRATA_VISION : support des entrées « vision » (images) du modèle.
#   ""    (défaut) : auto.
#   "yes" : activer.
#   "no"  : désactiver.
STRATA_VISION=""

# STRATA_GPUS : GPU(s) à utiliser, index séparés par des virgules.
#   ""      (défaut) : tous les GPU visibles.
#   Exemples : "0" (un seul GPU) ou "0,1" (deux GPU).
STRATA_GPUS=""

# STRATA_KV : précision / compression du CACHE KV (la « mémoire » de la
#   conversation côté modèle). C'est LE canal dédié à ce réglage.
#
#   Valeurs :
#     ""     (défaut) : ne rien imposer -> Strata choisit tout seul (fp16
#                       jusqu'à 8K de contexte, int8 au-delà).
#     "int8"          : 8 bits. C'est la RÉFÉRENCE : toutes les mesures
#                       publiées de Strata sont prises avec int8.
#     "k8v4"          : hybride (clés 8 bits + valeurs 4 bits, rotation).
#                       ~23 % de mémoire KV en moins que int8, à qualité quasi
#                       identique (tests « needle » au même niveau) ; RECOMMANDÉ
#                       pour tenir un grand contexte sur une VRAM juste.
#     "q4_0"          : 4 bits (rotation de Hadamard). ~2x moins de mémoire que
#                       int8 (÷3,7 au total), un peu plus rapide sur longs
#                       prompts, MAIS nettement moins précis sur de longs
#                       documents (+8-12 % de perplexité ; les tests « needle »
#                       passent encore). À réserver au cas où la mémoire est LE
#                       facteur limitant.
#     "fp16"          : valeur de référence « pleine précision » de Strata.
#                       ATTENTION : dans la version de Strata utilisée ici,
#                       --kv n'accepte QUE int8 | k8v4 | q4_0 ; fp16 est son
#                       défaut AUTOMATIQUE (jusqu'à 8K) et ne peut pas être
#                       imposé. Mettre "fp16" revient donc à laisser "".
#
#   Recommandation : "" (défaut) ou "k8v4" si le contexte est grand et la VRAM
#   juste ; "q4_0" seulement si la mémoire est le facteur limitant.
#
#   ⚠ Ce réglage n'a d'effet QUE sur la famille "qwen" (chemin Flash-Next) :
#     sur les autres familles, Strata l'IGNORE (le script l'avertit au
#     démarrage).
#   ⚠ Changer cette valeur INVALIDE les sessions sauvegardées (l'empreinte de
#     configuration du modèle inclut --kv).
#   ⚠ Ne mettez PAS --kv dans STRATA_EXTRA_ARGS : conflit. STRATA_KV est le
#     canal prévu et il est prioritaire (le script le signale dans le log).
#
#   Comment ça marche : --kv est un flag de setup.py, écrit dans le tableau
#   "args" de strata-<model>.json puis relu par serve/server.py au démarrage.
#   Il persiste donc dans la configuration du modèle — mais sur un modèle DÉJÀ
#   installé, un setup.py sans --setup ne fait que démarrer le serveur et
#   IGNORE --kv. Ce script mémorise la valeur réellement appliquée dans
#   ${INSTANCE_CONF_DIR}/strata_kv.applied (répertoire PERSISTANT de l'instance)
#   et repasse automatiquement par "setup.py --setup --no-start" dès que la
#   valeur demandée diffère de celle mémorisée.
STRATA_KV=""

# STRATA_ENABLE_API_KEY : protéger l'API / le Web UI Strata par une clé.
#   "1" (défaut) : utilise/génère une clé API Strata. NÉCESSAIRE derrière le
#                  proxy nginx d'AiKore : une clé Strata désactive la
#                  protection anti-DNS-rebinding qui, sinon, rejette les
#                  requêtes car le proxy transmet le Host du navigateur (et non
#                  127.0.0.1). C'est le comportement par défaut recommandé.
#   "0"          : aucune clé. Le Web UI ne demande rien à coller, mais l'accès
#                  via un domaine peut être refusé par Strata (contrôle Host).
STRATA_ENABLE_API_KEY="1"

# STRATA_API_KEY : clé API Strata à utiliser si tu veux la fixer toi-même.
#   ""              (défaut) : AiKore en génère une et la persiste dans
#                              ${INSTANCE_CONF_DIR}/strata_api.key, puis la
#                              réutilise aux démarrages suivants.
#   "ma-super-cle"           : clé imposée. (Ignorée si STRATA_ENABLE_API_KEY="0".)
STRATA_API_KEY=""

# STRATA_EXTRA_ARGS : arguments supplémentaires libres ajoutés à la fin de la
#   ligne de commande de setup.py. Chaîne séparée par des espaces, transmise
#   telle quelle (même mécanisme que ${INSTANCE_CONF_DIR}/launch_args.txt).
#   Exemple : "--setup" pour forcer un (re)setup des dépendances.
STRATA_EXTRA_ARGS=""

# =============================================================================
# ===                                                                       ===
# ===          FIN DES PARAMÈTRES UTILISATEUR — NE PAS TOUCHER             ===
# ===              AU RESTE DU SCRIPT SANS SAVOIR CE QUE TU FAIS           ===
# ===                                                                       ===
# =============================================================================
# =============================================================================

# Exit immediately if a command exits with a non-zero status.
set -e

source /opt/sd-install/functions.sh
source /opt/sd-install/versions.env

# --- Load custom instance versions if they exist ---
# WARNING: this file (${INSTANCE_CONF_DIR}/aikore_vars.env) is AUTO-GENERATED
# and OVERWRITTEN by AiKore on every instance start (see
# aikore/core/process_manager.py). It only carries the PYTHON_VERSION /
# CUDA_VERSION / PYTORCH_INDEX_URL / TORCH_VERSION chosen in the Builder UI.
# Do NOT use it for user customisation - anything you add here is lost.
# Use the "PARAMÈTRES UTILISATEUR" section at the top of this script instead.
if [ -f "${INSTANCE_CONF_DIR}/aikore_vars.env" ]; then
    echo "--- Loading custom environment variables ---"
    source "${INSTANCE_CONF_DIR}/aikore_vars.env"
fi

export PATH="/home/abc/miniconda3/bin:$PATH"

# The following variables are provided by the process manager:
# - INSTANCE_NAME: The unique user-defined name for this instance.
# - INSTANCE_CONF_DIR: The dedicated directory for this instance's configuration.
# - INSTANCE_OUTPUT_DIR: The dedicated directory for this instance's generated outputs.
# - WEBUI_PORT: The internal port assigned to this instance.
# - SUBFOLDER: The AiKore reverse-proxy path for this instance (/instance/<slug>/).

echo "--- Starting Blueprint: Strata LLM for Instance: ${INSTANCE_NAME} ---"

# Ensure instance-specific directories exist
mkdir -p "${INSTANCE_CONF_DIR}"
mkdir -p "${INSTANCE_OUTPUT_DIR}"

APP_DIR="${INSTANCE_CONF_DIR}/Strata"
VENV_DIR="${INSTANCE_CONF_DIR}/env"
# Strata stores its engine + model files (~70-120 GB) in a dedicated data folder.
# We keep it inside the instance's persistent config dir so it survives reboots
# and blueprint re-runs (this is Strata's --data-dir; its own default is
# "Strata-data" next to the repository).
DATA_DIR="${INSTANCE_CONF_DIR}/Strata-data"

# --- 1. Repository Management ---
if [ ! -d "${APP_DIR}/.git" ]; then
    echo "Cloning Strata repository..."
    git clone https://github.com/Niko1221/Strata.git "${APP_DIR}"
else
    echo "Existing Strata repository found. Synchronizing..."
    cd "${APP_DIR}"
    check_remote "STRATA_GIT_REF"
fi

# --- 2. Environment Setup ---
echo "--- Setting up Conda environment ---"

# Clean conda cache to prevent metadata errors (same as ComfyUI)
conda clean -ya

# Clean the Conda environment if a rebuild was requested by the user
clean_env "${VENV_DIR}"

# Strata requires Python 3.10+ (repository docs/INSTALL.md). We default to
# 3.10 (its documented minimum) but honour the user's Builder choice via
# PYTHON_VERSION (set by AiKore in aikore_vars.env, sourced above).
if [ ! -d "${VENV_DIR}" ]; then
    echo "Creating Conda environment with Python ${PYTHON_VERSION:-3.10}..."
    conda create -p "${VENV_DIR}" python="${PYTHON_VERSION:-3.10}" pip -y
fi

# REQUIRED: activate the environment so python/pip resolve to the venv, not the base
source activate "${VENV_DIR}"

# Ensure pip is available inside the environment
if [ ! -f "${VENV_DIR}/bin/pip" ]; then
    echo "--- pip not found in environment, installing via conda ---"
    conda install -p "${VENV_DIR}" pip -y
fi

# --- 3. Dependency Installation ---
# NOTE: unlike the image/training blueprints, Strata does NOT use PyTorch. Its
# inference engine is a pre-built native binary (CUDA 13 on NVIDIA, HIP on AMD)
# and the Python side is only the serve/ layer. We therefore do NOT install
# AiKore's torch wheels, and we skip the AiKore pre-built wheels (WHEELS_DIR:
# xformers/flash-attn/sageattention target PyTorch, not this engine).
cd "${APP_DIR}"

if [ -f "${APP_DIR}/requirements.txt" ]; then
    echo "--- Installing Strata Python requirements ---"
    pip install -r "${APP_DIR}/requirements.txt"
fi

# The NVIDIA CUDA runtime libraries the engine loads (nvidia-cublas,
# nvidia-cuda-runtime) are installed by setup.py itself on the first run.
echo "--- Engine / model files and CUDA libraries are handled by setup.py on first start ---"

# Install custom user requirements if specified (AiKore standard hook)
if [ -f "${INSTANCE_CONF_DIR}/requirements.txt" ]; then
    echo "--- Installing user requirements ---"
    pip install -r "${INSTANCE_CONF_DIR}/requirements.txt"
fi

# --- 4. API key & reverse-proxy compatibility ---
# AiKore serves each instance behind its own nginx location (/instance/<slug>/)
# and already protects every route with the AiKore API key middleware. Strata
# additionally refuses requests whose Host header it does not recognise (DNS
# rebinding protection) - and the proxy forwards the browser's Host, not
# 127.0.0.1. A Strata API key turns that Host check off (Strata's documented
# solution for proxies/tunnels), so we generate one by default. This behaviour
# is driven by the STRATA_ENABLE_API_KEY / STRATA_API_KEY parameters above.
#
# The key is required once in the Strata Web UI (About > Settings > API key) and
# by any external client (Authorization: Bearer <key>). It is printed below and
# stored in ${INSTANCE_CONF_DIR}/strata_api.key. Set STRATA_ENABLE_API_KEY="0"
# above to run without a key - the Web UI then needs no paste, but access
# through a custom domain may be refused by Strata's Host/Origin check.
API_KEY=""
if [ "${STRATA_ENABLE_API_KEY}" = "1" ]; then
    if [ -n "${STRATA_API_KEY}" ]; then
        API_KEY="${STRATA_API_KEY}"
        echo "--- Using Strata API key from the STRATA_API_KEY parameter ---"
    else
        API_KEY_FILE="${INSTANCE_CONF_DIR}/strata_api.key"
        if [ -f "${API_KEY_FILE}" ]; then
            API_KEY=$(cat "${API_KEY_FILE}")
            echo "--- Reusing existing Strata API key from ${API_KEY_FILE} ---"
        else
            API_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(24))")
            echo "${API_KEY}" > "${API_KEY_FILE}"
            echo "--- Generated new Strata API key: ${API_KEY} ---"
            echo "--- Key saved to ${API_KEY_FILE} ---"
        fi
    fi
else
    echo "--- STRATA_ENABLE_API_KEY=0 : running WITHOUT a Strata API key ---"
fi

# Belt and suspenders: also answer any Host name, so the proxy keeps working even
# if the key is disabled. (Read by serve/server.py as $STRATA_ALLOWED_HOSTS.)
export STRATA_ALLOWED_HOSTS="*"

# --- 5. Launch ---
# setup.py has two modes, and we use both:
#   * (re)configure : "--setup [--no-start]" walks the questions and writes the
#     model's run config (strata-<model>.json). With --no-start it returns AFTER
#     writing it, without starting the server; a non-zero exit makes `set -e`
#     abort this script (so the KV memo below is never written on failure).
#   * start : with none of --setup/--family/--model/--check/--no-start, setup.py
#     takes its "already installed: just start it" branch and starts the server
#     from the config as written. --host/--port/--api-key/--gpus are still read.
# We therefore build TWO commands: SETUP_CMD (reconfiguration, carries the
# setup-only flags and --kv) and CMD (plain start). The KV-cache block below
# decides which one(s) to run.
#
# We run setup.py directly (not ./setup.sh) so it uses this instance's Conda
# environment, and with --yes so it never blocks on an interactive prompt.
#
# Flags and their origin (repository setup.py --help / docs/INSTALL.md):
#   --yes            accept the recommended model/size/context answers
#   --no-browser     do not try to open a browser (none in the container)
#   --host 0.0.0.0   bind beyond localhost (Strata's default is 127.0.0.1);
#                    required for the nginx reverse proxy
#   --port           AiKore-assigned internal port (Strata's default is 8080)
#   --data-dir       where the model/engine files are stored
#   --setup          (re)configure instead of just starting
#   --no-start       configure only, do not start (two-phase setup)
BASE_CMD=(python "${APP_DIR}/setup.py" --yes --no-browser --host 0.0.0.0 --port "${WEBUI_PORT}" --data-dir "${DATA_DIR}")

# Flags valid in BOTH modes (start too): --gpus saves/uses the cards, --host and
# --api-key are kept, --port/--data-dir are read.
COMMON_ARGS=()
if [ -n "${STRATA_GPUS}" ]; then
    COMMON_ARGS+=(--gpus "${STRATA_GPUS}")
fi
if [ -n "${API_KEY}" ]; then
    COMMON_ARGS+=(--api-key "${API_KEY}")
fi

# Flags that belong to the (re)configuration phase ONLY. Any of them makes
# setup.py leave the "just start it" branch (setup.py: a.family/a.model/... ),
# so they must NEVER appear on the start command - otherwise every start would
# silently rewrite the config and drop our --kv.
SETUP_ARGS=()
if [ -n "${STRATA_FAMILY}" ]; then
    SETUP_ARGS+=(--family "${STRATA_FAMILY}")
fi
if [ -n "${STRATA_MODEL}" ]; then
    SETUP_ARGS+=(--model "${STRATA_MODEL}")
fi
if [ -n "${STRATA_CONTEXT}" ]; then
    SETUP_ARGS+=(--context "${STRATA_CONTEXT}")
fi
if [ -n "${STRATA_VISION}" ]; then
    SETUP_ARGS+=(--vision "${STRATA_VISION}")
fi

# Free-form arguments (STRATA_EXTRA_ARGS + launch_args.txt) carry setup-oriented
# flags (e.g. "--model IQ2_XS --context 32768 --vision no --gpus 0,1"), so they
# are applied to the (re)configuration phase. Putting "--setup" there forces a
# reconfiguration; putting "--kv" there is a mistake (see below).
FREE_ARGS=()
if [ -n "${STRATA_EXTRA_ARGS}" ]; then
    echo "--- Appending STRATA_EXTRA_ARGS (applied to the (re)configuration): ${STRATA_EXTRA_ARGS} ---"
    # shellcheck disable=SC2206
    FREE_ARGS+=(${STRATA_EXTRA_ARGS})
fi
if [ -f "${INSTANCE_CONF_DIR}/launch_args.txt" ]; then
    USER_ARGS=$(cat "${INSTANCE_CONF_DIR}/launch_args.txt")
    echo "--- Appending launch_args.txt (applied to the (re)configuration): ${USER_ARGS} ---"
    # shellcheck disable=SC2206
    FREE_ARGS+=(${USER_ARGS})
fi

# The whole free-form argument string, recorded so that editing it (as well as
# STRATA_FAMILY/MODEL/CONTEXT/VISION) still triggers a reconfiguration.
FREE_JOINED="${STRATA_EXTRA_ARGS}"
if [ -f "${INSTANCE_CONF_DIR}/launch_args.txt" ]; then
    FREE_JOINED="${FREE_JOINED} ${USER_ARGS}"
fi

# --- KV cache: remember what was applied, reconfigure only when it changes ---
# `--kv` is a setup.py flag written into the "args" array of strata-<model>.json,
# which serve/server.py reads at start: it therefore persists in the model
# config. But a plain setup.py run on an already-installed model just starts the
# server and would DROP our --kv (a setup run rewrites "args"; see setup.py's
# args_dropped). So: memorise the value we really applied under the instance's
# PERSISTENT config dir, and repass through setup.py only when the requested
# value differs (or when nothing is recorded yet).
STRATA_KV_FILE="${INSTANCE_CONF_DIR}/strata_kv.applied"

# Validate STRATA_KV and reduce it to what setup.py's --kv accepts here
# (choices in this Strata version: int8 | q4_0 | k8v4). "fp16" is Strata's
# reference default - automatic up to 8K of context - and is NOT an accepted
# --kv value here, so it is treated like "" (with a note).
KV_EFFECTIVE="${STRATA_KV}"
case "${KV_EFFECTIVE}" in
    int8|k8v4|q4_0|"")
        ;;
    fp16)
        echo "--- STRATA_KV=fp16 : valeur de référence, mais cette version de Strata n'accepte pas '--kv fp16' ; traitée comme \"\" (Strata choisit : fp16 jusqu'à 8K, int8 au-delà). ---"
        KV_EFFECTIVE=""
        ;;
    *)
        echo "!!! STRATA_KV='${STRATA_KV}' invalide (attendu : fp16, int8, k8v4, q4_0 ou vide) - ignoré. ---"
        KV_EFFECTIVE=""
        ;;
esac

# --kv only has an effect on the qwen (Flash-Next) family path: say it loudly
# otherwise, so the setting is never silently ignored.
if [ -n "${KV_EFFECTIVE}" ] && [ "${STRATA_FAMILY}" != "qwen" ]; then
    echo "!!! AVERTISSEMENT : STRATA_KV='${KV_EFFECTIVE}' mais STRATA_FAMILY='${STRATA_FAMILY}' (≠ qwen)."
    echo "!!!   --kv n'a d'effet QUE sur la famille qwen (chemin Flash-Next) : sur cette famille, Strata l'IGNORE."
fi

# A --kv in the free-form args conflicts with STRATA_KV (the dedicated channel).
# Retained behaviour: STRATA_KV wins - it is appended LAST on the setup command,
# and argparse keeps the last occurrence of an option.
if printf '%s\n%s\n' "${STRATA_EXTRA_ARGS}" "${USER_ARGS:-}" | grep -Eq '(^|[[:space:]])--kv([[:space:]]|$)'; then
    echo "!!! --kv trouvé dans les arguments libres (STRATA_EXTRA_ARGS / launch_args.txt)."
    echo "!!!   STRATA_KV est LE canal dédié : retirez --kv des arguments libres."
    echo "!!!   Comportement retenu : la valeur de STRATA_KV (ou son absence) est prioritaire."
fi

# Read the value really applied last time (first line of the memo file).
KV_APPLIED=""
KV_KNOWN="0"
if [ -f "${STRATA_KV_FILE}" ]; then
    KV_KNOWN="1"
    KV_APPLIED=$(head -n 1 "${STRATA_KV_FILE}" 2>/dev/null | tr -d '\r\n')
fi

# Did another setup parameter change since the last (re)configuration? The memo
# file also records them, so editing STRATA_FAMILY/MODEL/CONTEXT/VISION (or the
# free-form args) still triggers a reconfiguration - they are setup-only flags
# and a plain start would otherwise ignore them.
MEMO_CHANGED="0"
if [ "${KV_KNOWN}" = "1" ]; then
    for key in family model context vision extra; do
        grep -q "^${key}=" "${STRATA_KV_FILE}" 2>/dev/null || continue
        recorded=$(sed -n "s/^${key}=//p" "${STRATA_KV_FILE}" | head -n 1)
        case "${key}" in
            family)  current="${STRATA_FAMILY}" ;;
            model)   current="${STRATA_MODEL}" ;;
            context) current="${STRATA_CONTEXT}" ;;
            vision)  current="${STRATA_VISION}" ;;
            extra)   current="${FREE_JOINED}" ;;
        esac
        if [ "${recorded}" != "${current}" ]; then
            MEMO_CHANGED="1"
            echo "--- Paramètre de (re)configuration modifié : ${key} '${recorded}' -> '${current}' ---"
        fi
    done
fi

# Is a model config present at all? setup keeps them as strata-<model>.json in
# the repository dir. If none exists, we must (re)configure: a plain start would
# let setup.py install with its own defaults and drop STRATA_KV.
KV_CONF_MISSING="0"
if ! compgen -G "${APP_DIR}/strata-*.json" > /dev/null 2>&1; then
    KV_CONF_MISSING="1"
fi

# "--setup" in the free-form args is the documented way to force a reconfiguration.
KV_FORCE="0"
if printf '%s\n%s\n' "${STRATA_EXTRA_ARGS}" "${USER_ARGS:-}" | grep -Eq '(^|[[:space:]])--setup([[:space:]]|$)'; then
    KV_FORCE="1"
    echo "--- --setup présent dans les arguments libres : (re)configuration forcée ---"
fi

# Pure decision function (easy to read and to test on its own):
#   $1 requested KV (may be empty)   $2 applied KV (may be empty)
#   $3 memo file exists? ("1"/"0")   $4 another setup parameter changed? ("1"/"0")
#   $5 forced by a --setup in the free args? ("1"/"0")
#   $6 no model config present? ("1"/"0")
# Echoes "setup" (two-phase reconfiguration) or "start" (start as configured).
strata_kv_plan() {
    local requested="$1" applied="$2" known="$3" changed="$4" force="$5" conf_missing="${6:-0}"
    if [ "${force}" = "1" ] || [ "${changed}" = "1" ] || [ "${conf_missing}" = "1" ] || [ "${known}" != "1" ]; then
        echo "setup"
        return 0
    fi
    if [ "${requested}" = "${applied}" ]; then
        echo "start"
    else
        echo "setup"
    fi
}

ACTION=$(strata_kv_plan "${KV_EFFECTIVE}" "${KV_APPLIED}" "${KV_KNOWN}" "${MEMO_CHANGED}" "${KV_FORCE}" "${KV_CONF_MISSING}")

if [ "${ACTION}" = "start" ]; then
    if [ -n "${KV_EFFECTIVE}" ]; then
        echo "--- KV cache inchangé (${KV_EFFECTIVE}) : démarrage direct, aucun --setup. ---"
    else
        echo "--- KV cache : défaut Strata (inchangé) : démarrage direct, aucun --setup. ---"
    fi
elif [ "${KV_KNOWN}" != "1" ]; then
    echo "--- KV cache : aucune valeur mémorisée -> ${KV_EFFECTIVE:-défaut Strata} : reconfiguration (setup.py --setup --no-start)... ---"
elif [ -z "${KV_EFFECTIVE}" ] && [ -n "${KV_APPLIED}" ]; then
    echo "--- KV cache : ${KV_APPLIED} -> défaut Strata : STRATA_KV a été vidé."
    echo "---   Comportement retenu (honnête) : on ne laisse PAS l'ancienne valeur en place ; on repasse par"
    echo "---   setup.py --setup --no-start SANS --kv pour revenir au défaut de Strata, puis on vide la mémorisation. ---"
else
    echo "--- KV cache : ${KV_APPLIED:-défaut Strata} -> ${KV_EFFECTIVE:-défaut Strata} : reconfiguration (setup.py --setup --no-start)... ---"
fi

if [ "${ACTION}" = "setup" ]; then
    SETUP_CMD=("${BASE_CMD[@]}" --setup --no-start "${SETUP_ARGS[@]}" "${COMMON_ARGS[@]}" "${FREE_ARGS[@]}")
    # --kv LAST: STRATA_KV wins over any --kv coming from the free-form args.
    if [ -n "${KV_EFFECTIVE}" ]; then
        SETUP_CMD+=(--kv "${KV_EFFECTIVE}")
    fi
    echo "--- Reconfiguration :"
    printf '  %q' "${SETUP_CMD[@]}"
    echo ""
    "${SETUP_CMD[@]}"
    # Only reached on success (set -e aborts on failure), so the memo below always
    # reflects a configuration that really happened.
    #
    # The memo file keeps the applied KV on its FIRST line (so `cat` shows
    # e.g. "k8v4") and records the other setup parameters on the following lines.
    # When STRATA_KV is emptied, the first line is written EMPTY rather than the
    # file being deleted: deleting it would make the next start reconfigure again
    # (loop) and would lose the other parameters. An empty value IS the
    # "forgotten" state, and the log above states it plainly.
    {
        printf '%s\n' "${KV_EFFECTIVE}"
        printf 'family=%s\n' "${STRATA_FAMILY}"
        printf 'model=%s\n' "${STRATA_MODEL}"
        printf 'context=%s\n' "${STRATA_CONTEXT}"
        printf 'vision=%s\n' "${STRATA_VISION}"
        printf 'extra=%s\n' "${FREE_JOINED}"
    } > "${STRATA_KV_FILE}"
    if [ -n "${KV_EFFECTIVE}" ]; then
        echo "--- Valeur appliquée mémorisée dans ${STRATA_KV_FILE} : ${KV_EFFECTIVE} ---"
    else
        echo "--- Mémorisation mise à jour dans ${STRATA_KV_FILE} : défaut Strata (valeur vide). ---"
    fi
fi

# The start command carries NONE of --family/--model/--context/--vision/--setup/
# --kv: it takes setup.py's "already installed: just start it" branch, so the
# config written above (including our --kv) is used exactly as written.
CMD=("${BASE_CMD[@]}" "${COMMON_ARGS[@]}")

echo "---"
echo "Launching Strata LLM:"
printf '  %q' "${CMD[@]}"
echo ""
echo "Internal Web UI / OpenAI API: http://0.0.0.0:${WEBUI_PORT}/v1"
echo "AiKore proxy path: ${SUBFOLDER:-<unset>}"
if [ -n "${API_KEY}" ]; then
    echo "Strata API key: ${API_KEY}"
    echo "  (paste it once in the Web UI under About > Settings, or send it as 'Authorization: Bearer ${API_KEY}')"
fi
echo "Note: the FIRST start downloads ~70 GB and can take a long time before the port opens."
echo "---"

exec "${CMD[@]}"
