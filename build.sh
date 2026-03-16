#!/usr/bin/env bash
set -o errexit

pip install -r requirements.txt

# descargar navegador camoufox
python -m camoufox fetch
