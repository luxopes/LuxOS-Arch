#!/bin/bash
# LuxOS - zverejneni webu https://luxos.lux-ai.cz (stranka, dokumentace, zmeny, release.json)
#
#   scripts/publish-site.sh       sestavi out/site (scripts/build-site.py) a nahraje ho na server
#
# Na serveru: /srv/luxos-site (Caddy, blok luxos.lux-ai.cz). ISO, podpisy a SHA256SUMS
# v /srv/luxos-site/download/ se nemazou ani neprepisuji (nahrava je vydani ISO).
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
SERVER=${LUXOS_SERVER:-root@185.183.156.25}
DEST=/srv/luxos-site

python3 scripts/build-site.py
rsync -rlt --delete --chmod=D755,F644 \
    --exclude '/download/*.iso' --exclude '/download/*.iso.sig' --exclude '/download/SHA256SUMS*' \
    out/site/ "$SERVER:$DEST/"
ssh "$SERVER" "chown -R root:root $DEST"
for u in / /release.json /docs/ /zmeny/ /assets/shots/desktop-dark.webp; do
    printf '    https://luxos.lux-ai.cz%s -> HTTP %s\n' "$u" "$(curl -s -o /dev/null -w '%{http_code}' "https://luxos.lux-ai.cz$u")"
done
echo "==> Done: https://luxos.lux-ai.cz/"
