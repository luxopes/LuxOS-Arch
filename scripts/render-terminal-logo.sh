#!/bin/bash
# LuxOS - logo pro fastfetch: logo LuxOS (barevne SVG) vykreslene znaky (chafa, barvy 24 bit)
# Spoustet po zmene ikony; vystup se commituje (beh terminalu tak nepotrebuje chafa).
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
engine=$(command -v podman || command -v docker)
"$engine" run --rm -v "$PWD:/luxos:z" luxos-builder bash -c '
    pacman -S --noconfirm --needed chafa >/dev/null
    rsvg-convert -w 512 -h 512 /luxos/packages/luxos-branding/files/logo/luxos-logo.svg -o /tmp/logo.png
    chafa --format symbols --symbols block+border+space+diagonal --colors full --size 24x12 \
        --bg "#1c1c22" --animate off /tmp/logo.png |
        sed "s/\x1b\[?25[lh]//g" >/luxos/packages/luxos-shell/files/fastfetch/logo.ans'
