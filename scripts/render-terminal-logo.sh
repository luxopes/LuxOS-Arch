#!/bin/bash
# LuxOS - logo pro fastfetch: ikona LuxOS vykreslena znaky (chafa, barvy 24 bit)
# Spoustet po zmene ikony; vystup se commituje (beh terminalu tak nepotrebuje chafa).
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
engine=$(command -v podman || command -v docker)
"$engine" run --rm -v "$PWD:/luxos:z" luxos-builder bash -c '
    pacman -S --noconfirm --needed chafa >/dev/null
    chafa --format symbols --symbols block+border+space --colors full --size 24x12 \
        --bg "#1c1c22" --animate off /luxos/packages/luxos-branding/files/icons/luxos-app.png |
        sed "s/\x1b\[?25[lh]//g" >/luxos/packages/luxos-shell/files/fastfetch/logo.ans'
