#!/bin/bash
# LuxOS - logo pro fastfetch (znaky Unicode, barvy 24 bit); vlastni generator je render-terminal-logo.py.
# Spoustet po zmene ikony; vystup se commituje (beh terminalu tak nepotrebuje Python).
# Potreba: python3, python-cairo (pycairo), python-numpy, python-pillow.
set -euo pipefail
exec python3 "$(dirname "$(readlink -f "$0")")/render-terminal-logo.py" "$@"
