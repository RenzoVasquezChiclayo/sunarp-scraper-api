#!/usr/bin/env bash
set -o errexit

pip install -r requirements.txt
export CAMOUFOX_PATH=/opt/render/project/src/.camoufox
# usar token para evitar rate limit
export GH_TOKEN=$GH_TOKEN
# descargar navegador camoufox
python -m camoufox fetch
