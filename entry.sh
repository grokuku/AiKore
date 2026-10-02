#!/bin/bash

# --- AiKore boot instrumentation (dormante sauf AIKORE_BOOT_CHRONO=1) ---------
# Fallback no-op si la lib est absente : mêmes commandes, aucune sortie ajoutée.
if [ -r /usr/local/bin/aikore-boot-chrono.sh ]; then
    . /usr/local/bin/aikore-boot-chrono.sh
else
    aikore_chrono_mark() { return 0; }
    aikore_chrono_run() {
        if [ "$#" -lt 1 ]; then
            return 0
        fi
        shift
        "$@"
        return $?
    }
fi

# Set environment variables to include conda
export PATH="/home/abc/miniconda3/bin:$PATH"

# Activate the base conda environment which will host AiKore
# This ensures all subsequent python/pip commands use the correct environment.
source activate base

echo "--- Installing/Updating AiKore dependencies ---"
# NOTE: `pip install --upgrade pip` a été retiré du runtime : redondant avec le
# build (le Dockerfile installe déjà les requirements dans cet environnement) et
# il réécrivait site-packages à chaque boot (copy-up overlay2 inutile). Pour
# mettre pip à jour, le faire au build (Dockerfile), pas au démarrage.
aikore_chrono_run entry/pip-requirements pip install -r /opt/sd-install/aikore/requirements.txt

echo "--- Starting AiKore Backend ---"
# Change to the application's root directory
cd /opt/sd-install

aikore_chrono_mark entry/uvicorn start

# Launch the FastAPI application using uvicorn on the internal port 8000
# Added --no-access-log to reduce console spam
exec python -u -m uvicorn aikore.main:app --host 0.0.0.0 --port 8000 --no-access-log