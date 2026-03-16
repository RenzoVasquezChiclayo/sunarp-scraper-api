#!/usr/bin/env bash

pip install -r requirements.txt

export GH_TOKEN=$GH_TOKEN

python -m camoufox fetch

playwright install chromium
