#!/usr/bin/env bash
set -o errexit

pip install -r requirements.txt

# instalar navegador en el entorno virtual
python -m playwright install chromium

# instalar OCR
apt-get update
apt-get install -y tesseract-ocr
