#!/bin/bash

# Set environment variables to include conda
export PATH="/home/abc/miniconda3/bin:$PATH"

# Activate the base conda environment which will host AiKore
# This ensures all subsequent python/pip commands use the correct environment.
source activate base

echo "--- Installing/Updating AiKore dependencies ---"
pip install --upgrade pip
pip install -r /opt/sd-install/aikore/requirements.txt

echo "--- Starting AiKore Backend ---"
# Change to the application's root directory
cd /opt/sd-install

# Launch the FastAPI application using uvicorn on the internal port 8000
# Added --no-access-log to reduce console spam
exec uvicorn aikore.main:app --host 0.0.0.0 --port 8000 --no-access-log