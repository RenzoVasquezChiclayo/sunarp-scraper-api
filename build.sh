#!/usr/bin/env bash
set -o errexit

pip install -r requirements.txt
# usar token para evitar rate limit
export GH_TOKEN=$GH_TOKEN
# descargar navegador camoufox
python -m camoufox fetch
