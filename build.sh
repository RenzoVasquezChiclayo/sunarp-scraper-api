#!/usr/bin/env bash
set -o errexit

pip install -r requirements.txt

# instalar camoufox una sola vez en el build
python -m camoufox fetch

# instalar OCR
apt-get update
apt-get install -y tesseract-ocr
