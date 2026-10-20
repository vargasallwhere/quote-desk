#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

# Install into Replit's writable project prefix, never the immutable Nix runtime.
python3 -m pip install --prefix "$PWD/.pythonlibs" --no-input --disable-pip-version-check -r requirements.txt

python3 -m unittest discover -s tests
node tests/order_status_refresh.js
node tests/confirmation_load.js
node tests/catalog_display.js
node tests/warranty_display.js
node tests/alternative_picker.js
