#!/usr/bin/env bash
# ==============================================================================
# check-boot-timing.sh — verrou anti-régression du temps de boot AiKore
# ==============================================================================
# Mesure l'écart entre les marques d'instrumentation émises au démarrage du
# conteneur (AIKORE_BOOT_CHRONO=1) :
#     [aikore-boot-chrono] ts=… phase=init-chown event=start
#     [aikore-boot-chrono] ts=… phase=init-chown event=end
#
# Contexte : avant le correctif de fond (chown ciblé O(1) + réparation
# conditionnelle par marqueur), cette phase durait ~96 s (chown -R de ~31 000
# fichiers d'image + copy-up overlay2). Après correctif, elle dure quelques
# centaines de millisecondes. Le seuil par défaut (20 000 ms) détecte une
# régression franche sans être sensible au bruit du runner.
#
# Modes :
#   Contre une image Docker (CI) :
#     scripts/check-boot-timing.sh [--threshold-ms N] [--timeout-s N] <image>
#   Analyse d'un fichier de logs déjà capturé (local, sans Docker) :
#     scripts/check-boot-timing.sh --logs <fichier> [--threshold-ms N]
#
# Variables d'environnement équivalentes : BOOT_TIMING_THRESHOLD_MS,
# BOOT_TIMING_TIMEOUT_S.
# ==============================================================================
set -u

THRESHOLD_MS="${BOOT_TIMING_THRESHOLD_MS:-20000}"
TIMEOUT_S="${BOOT_TIMING_TIMEOUT_S:-300}"
LOGS_FILE=""
IMAGE=""

usage() {
    awk 'NR > 1 && /^# ={5,}/ { exit } NR > 1 && /^#!/ { next } NR > 1 && /^#/ { sub(/^# ?/, ""); print }' "$0"
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --threshold-ms) THRESHOLD_MS="${2:?valeur manquante pour --threshold-ms}"; shift 2 ;;
        --timeout-s)    TIMEOUT_S="${2:?valeur manquante pour --timeout-s}"; shift 2 ;;
        --logs)         LOGS_FILE="${2:?valeur manquante pour --logs}"; shift 2 ;;
        -h|--help)      usage; exit 0 ;;
        -*)             echo "check-boot-timing: option inconnue: $1" >&2; exit 2 ;;
        *)              IMAGE="$1"; shift ;;
    esac
done

# Extraction du ts= de la première marque `phase=init-chown event=<event>`.
extract_ts() { # <fichier> <event>
    awk -v want="$2" '
        index($0, " phase=init-chown event=" want) && !found {
            for (i = 1; i <= NF; i++)
                if ($i ~ /^ts=/) { t = $i; sub(/^ts=/, "", t); print t; found = 1; exit }
        }
    ' "$1"
}

check_logs() { # <fichier de logs>
    local start end delta
    start="$(extract_ts "$1" start)"
    end="$(extract_ts "$1" end)"
    if [ -z "$start" ] || [ -z "$end" ]; then
        echo "check-boot-timing: ÉCHEC — marques 'phase=init-chown event=start/end' introuvables." >&2
        echo "  Instrumentation absente (lib aikore-boot-chrono non déployée ?) ou boot interrompu." >&2
        return 1
    fi
    delta=$((end - start))
    echo "check-boot-timing: init-chown start->end = ${delta} ms (seuil : ${THRESHOLD_MS} ms)"
    if [ "$delta" -gt "$THRESHOLD_MS" ]; then
        echo "check-boot-timing: ÉCHEC — régression du temps de boot (> ${THRESHOLD_MS} ms)." >&2
        return 1
    fi
    echo "check-boot-timing: OK"
}

# --- Mode --logs : analyse d'un fichier déjà capturé --------------------------
if [ -n "$LOGS_FILE" ]; then
    if [ ! -f "$LOGS_FILE" ]; then
        echo "check-boot-timing: fichier introuvable: $LOGS_FILE" >&2
        exit 2
    fi
    check_logs "$LOGS_FILE"
    exit $?
fi

# --- Mode Docker ---------------------------------------------------------------
if [ -z "$IMAGE" ]; then
    usage >&2
    exit 2
fi
if ! command -v docker >/dev/null 2>&1; then
    echo "check-boot-timing: docker introuvable (utiliser --logs pour un test local)." >&2
    exit 2
fi

CID=""
cleanup() {
    if [ -n "$CID" ]; then
        docker rm -f "$CID" >/dev/null 2>&1 || true
    fi
}
trap cleanup EXIT

echo "check-boot-timing: conteneur neuf sur $IMAGE (PUID=99 PGID=100, chrono actif)…"
CID="$(docker run -d \
    -e AIKORE_BOOT_CHRONO=1 \
    -e PUID=99 \
    -e PGID=100 \
    "$IMAGE")" || exit 2

LOG_TMP="$(mktemp)"
deadline=$(( $(date +%s) + TIMEOUT_S ))
while [ "$(date +%s)" -lt "$deadline" ]; do
    docker logs "$CID" > "$LOG_TMP" 2>&1 || true
    if [ -n "$(extract_ts "$LOG_TMP" end)" ]; then
        break
    fi
    if ! docker inspect -f '{{.State.Running}}' "$CID" 2>/dev/null | grep -q true; then
        echo "check-boot-timing: le conteneur s'est arrêté prématurément." >&2
        break
    fi
    sleep 2
done

check_logs "$LOG_TMP"
RC=$?
if [ "$RC" -ne 0 ]; then
    echo "--- 60 dernières lignes de logs du conteneur ---" >&2
    tail -60 "$LOG_TMP" >&2 || true
fi
rm -f "$LOG_TMP"
exit "$RC"
