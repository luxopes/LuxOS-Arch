#!/bin/bash
# LuxOS - zverejneni webu https://luxos.lux-ai.cz (stranka en + cs, dokumentace, zmeny, sitemap, release.json)
#
#   scripts/publish-site.sh       sestavi out/site (scripts/build-site.py), zkontroluje ho
#                                 (scripts/check-site.py) a nahraje ho na server
#
# Na serveru: /srv/luxos-site (Caddy, blok luxos.lux-ai.cz). ISO, podpisy a SHA256SUMS
# v /srv/luxos-site/download/ se nemazou ani neprepisuji (nahrava je vydani ISO).
# Bez rsync na tomto pocitaci: web se predava pres tar na server do /srv/luxos-stage/site
# a tam se synchronizuje vzdalenym rsync (stejna pravidla); pred tim se zalohuje stavajici web.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
SERVER=${LUXOS_SERVER:-root@185.183.156.25}
DEST=/srv/luxos-site
STAGE=/srv/luxos-stage/site
EXCL=(--exclude '/download/*.iso' --exclude '/download/*.iso.sig' --exclude '/download/SHA256SUMS*')

python3 scripts/build-site.py
python3 scripts/check-site.py

if command -v rsync >/dev/null; then
    rsync -rlt --delete --chmod=D755,F644 "${EXCL[@]}" out/site/ "$SERVER:$DEST/"
else
    echo "==> rsync neni k dispozici, pouziji tar + vzdaleny rsync"
    ssh "$SERVER" "tar czf /root/luxos-site-backup-\$(date +%Y%m%d-%H%M%S).tgz --exclude=download -C /srv luxos-site"
    tar czf - -C out/site . | ssh "$SERVER" "rm -rf $STAGE && mkdir -p $STAGE && tar xzf - -C $STAGE"
    echo "==> Co by se zmenilo (smazani mimo /download/ zkontrolujte):"
    ssh "$SERVER" "rsync -rltn --delete --itemize-changes ${EXCL[*]@Q} $STAGE/ $DEST/" | grep -v '^\.' || true
    if [ "${LUXOS_DRY_RUN:-0}" = 1 ]; then echo "(suchy beh, nic se nenahrava)"; exit 0; fi
    ssh "$SERVER" "rsync -rlt --delete --chmod=D755,F644 ${EXCL[*]@Q} $STAGE/ $DEST/"
fi
ssh "$SERVER" "chown -R root:root $DEST"
for u in / /cs/ /docs/ /sitemap.xml /robots.txt /release.json; do
    printf '    https://luxos.lux-ai.cz%s -> HTTP %s\n' "$u" "$(curl -s -o /dev/null -w '%{http_code}' "https://luxos.lux-ai.cz$u")"
done
echo "==> Done: https://luxos.lux-ai.cz/"
