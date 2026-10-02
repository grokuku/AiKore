#!/bin/bash
# ==============================================================================
# aikore-boot-chrono — instrumentation de chronométrage du boot AiKore
# ------------------------------------------------------------------------------
# Librairie sourceable + CLI de diagnostic.
#
# DORMANTE PAR DÉFAUT : la lib n'émet quoi que ce soit que si
# AIKORE_BOOT_CHRONO=1. Désactivée, toutes les fonctions sont des passthrough
# stricts (mêmes commandes, aucun appel externe supplémentaire, aucune sortie)
# afin de ne jamais modifier le comportement ni le coût du boot de production.
#
# Usage :
#   Sourçage   : [ -r /usr/local/bin/aikore-boot-chrono.sh ] && . /usr/local/bin/aikore-boot-chrono.sh
#   Diagnostic : /usr/local/bin/aikore-boot-chrono.sh diag
#
# Le mode diag accepte deux surcharges utiles hors conteneur :
#   AIKORE_HOME_DIR  (défaut : /home/abc)
#   AIKORE_HOME_USER (défaut : abc)
# ==============================================================================

AIKORE_BOOT_CHRONO_PREFIX="[aikore-boot-chrono]"

# Horodatage epoch en millisecondes (coreutils GNU, image Ubuntu Noble).
aikore_chrono_ts() {
    date +%s%3N
}

# aikore_chrono_mark <phase> <event> [detail...]
# Écrit UNE ligne de marque, uniquement si AIKORE_BOOT_CHRONO=1.
aikore_chrono_mark() {
    [ "${AIKORE_BOOT_CHRONO:-0}" = "1" ] || return 0
    if [ "$#" -lt 2 ]; then
        return 0
    fi
    local phase="$1" event="$2"
    shift 2
    if [ "$#" -gt 0 ]; then
        printf '%s ts=%s phase=%s event=%s %s\n' \
            "$AIKORE_BOOT_CHRONO_PREFIX" "$(aikore_chrono_ts)" "$phase" "$event" "$*"
    else
        printf '%s ts=%s phase=%s event=%s\n' \
            "$AIKORE_BOOT_CHRONO_PREFIX" "$(aikore_chrono_ts)" "$phase" "$event"
    fi
}

# aikore_chrono_run <phase> <cmd> [args...]
# Passthrough STRICT quand désactivée ; sinon marque start/end avec duration_ms
# et exit. Le code de retour de la commande est toujours propagé.
aikore_chrono_run() {
    if [ "$#" -lt 1 ]; then
        return 0
    fi
    local phase="$1"
    shift
    if [ "${AIKORE_BOOT_CHRONO:-0}" != "1" ]; then
        "$@"
        return $?
    fi
    local start end rc
    start="$(aikore_chrono_ts)"
    printf '%s ts=%s phase=%s event=start cmd=%s\n' \
        "$AIKORE_BOOT_CHRONO_PREFIX" "$start" "$phase" "$1"
    "$@"
    rc=$?
    end="$(aikore_chrono_ts)"
    printf '%s ts=%s phase=%s event=end duration_ms=%s exit=%s cmd=%s\n' \
        "$AIKORE_BOOT_CHRONO_PREFIX" "$end" "$phase" "$((end - start))" "$rc" "$1"
    return "$rc"
}

# aikore_chrono_diag — diagnostic complet de l'environnement de boot :
# identité, propriété, système de fichiers, montages, et surtout l'ampleur des
# fichiers en mismatch (le coût potentiel d'un `chown -R`).
aikore_chrono_diag() {
    local prefix="$AIKORE_BOOT_CHRONO_PREFIX"
    local home_dir="${AIKORE_HOME_DIR:-/home/abc}"
    local home_user="${AIKORE_HOME_USER:-abc}"
    local config_dir="${BASE_DIR:-/config}"
    local marker="$home_dir/.aikore_home_perms.marker"
    local t0 t1 p

    echo "${prefix} ==== diag $(date -Is 2>/dev/null || date) ===="

    # --- Identité -------------------------------------------------------------
    echo "${prefix} -- identité --"
    echo "${prefix} id($home_user): $(id "$home_user" 2>&1)"
    echo "${prefix} id(runtime): $(id 2>&1)"
    echo "${prefix} PUID=${PUID:-<unset>} PGID=${PGID:-<unset>}"

    # --- Propriété ------------------------------------------------------------
    echo "${prefix} -- propriété --"
    for p in "$home_dir" "$home_dir/miniconda3" "$home_dir/miniconda3/envs" \
             "$home_dir/miniconda3/pkgs" "$config_dir" "$marker"; do
        if [ -e "$p" ] || [ -L "$p" ]; then
            echo "${prefix} stat $(stat -c 'path=%n uid=%u gid=%g mode=%a type=%F' "$p" 2>&1)"
        else
            echo "${prefix} stat path=$p absent"
        fi
    done
    if [ -f "$marker" ]; then
        echo "${prefix} marqueur contenu='$(cat "$marker" 2>/dev/null)'"
    else
        echo "${prefix} marqueur ABSENT : le prochain boot ne fera aucune réparation -R (il l'écrira)"
    fi

    # --- Système de fichiers --------------------------------------------------
    echo "${prefix} -- système de fichiers --"
    for p in "$home_dir" "$config_dir"; do
        if [ -e "$p" ]; then
            echo "${prefix} fs $(stat -f -c 'path=%n type=%T namelen=%l blocks=%b files=%c' "$p" 2>&1)"
        fi
    done
    df -h "$home_dir" "$config_dir" 2>/dev/null | sed "s/^/${prefix} df /"

    # --- Montages (filtre home, config, overlay/vfs) --------------------------
    echo "${prefix} -- montages --"
    if [ -r /proc/self/mounts ]; then
        awk -v h="$home_dir" -v c="$config_dir" \
            'index($2,h)==1 || index($2,c)==1 || $3=="overlay" || $3=="vfs" {print}' \
            /proc/self/mounts | sed "s/^/${prefix} mount /"
    fi

    # --- Inventaire : coût potentiel d'un chown massif ------------------------
    echo "${prefix} -- inventaire de $home_dir (référence: $home_user) --"
    if [ -d "$home_dir" ]; then
        local mismatch total size
        t0="$(aikore_chrono_ts)"
        mismatch="$(find "$home_dir" ! -user "$home_user" 2>/dev/null | wc -l)"
        t1="$(aikore_chrono_ts)"
        echo "${prefix} mismatch (! -user $home_user) = $mismatch entrées (find: $((t1 - t0)) ms)"
        t0="$(aikore_chrono_ts)"
        total="$(find "$home_dir" -type f 2>/dev/null | wc -l)"
        t1="$(aikore_chrono_ts)"
        echo "${prefix} fichiers totaux = $total (find: $((t1 - t0)) ms)"
        size="$(du -sh "$home_dir" 2>/dev/null | cut -f1)"
        echo "${prefix} taille = ${size:-n/a}"
    else
        echo "${prefix} $home_dir absent"
    fi
    return 0
}

# --- Mode CLI : actif uniquement quand le script est EXÉCUTÉ (pas sourcé) -----
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    case "${1:-}" in
        diag)
            aikore_chrono_diag
            exit $?
            ;;
        ""|-h|--help)
            echo "Usage: $0 diag   (instrumentation dormante, activer avec AIKORE_BOOT_CHRONO=1)"
            exit 0
            ;;
    esac
fi
