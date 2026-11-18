#!/bin/bash
# LuxOS - nahled odkazu pro web (og:image, twitter:image): site/assets/og-image.jpg (anglicky)
# a og-image-cs.jpg (cesky), 1200x630 JPEG, ze sablony scripts/site-og/og.html.
#
#   scripts/site-og/render-og.sh
#
# Chromium bezi headless s docasnym profilem a domovem; prostredi skutecne relace (DISPLAY, D-Bus,
# XAUTHORITY, Wayland) se mu neposila. JPEG (ne WebP), nektere aplikace WebP v nahledech neukazi.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/../.."
command -v chromium >/dev/null || { echo "chybi chromium" >&2; exit 1; }
command -v vips >/dev/null || { echo "chybi vips (libvips)" >&2; exit 1; }
tmp=$(mktemp -d -t luxos-og-XXXXXX)
trap 'rm -rf "$tmp"' EXIT
for lang in en cs; do
    out=site/assets/og-image.jpg
    [ "$lang" = cs ] && out=site/assets/og-image-cs.jpg
    env -u DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u XAUTHORITY -u WAYLAND_DISPLAY HOME="$tmp" \
        chromium --headless=new --disable-gpu --hide-scrollbars --user-data-dir="$tmp/profile" \
        --allow-file-access-from-files --window-size=1200,630 --virtual-time-budget=3000 \
        --screenshot="$tmp/og-$lang.png" "file://$PWD/scripts/site-og/og.html?lang=$lang" 2>/dev/null
    vips copy "$tmp/og-$lang.png" "$out[Q=86,strip,optimize_coding]" 2>/dev/null
    echo "$out: $(stat -c %s "$out") B"
done
