#!/bin/bash
# LuxOS - zverejneni repozitaru [luxos] a [luxos-apps] na server
#
#   scripts/publish-repo.sh            nahraje out/repo a prepne aktualni vydani
#
# Na serveru: /srv/luxos-repo/releases/<cas>/{luxos,luxos-apps}/x86_64, odkaz current
# ukazuje na posledni vydani (Caddy: https://lsl.lux-ai.cz/luxos/). Prepnuti je
# atomicke a ponechavaji se 3 posledni vydani pro pripadny navrat.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."

HOST=${LUXOS_REPO_HOST:-root@185.183.156.25}
BASE=${LUXOS_REPO_DIR:-/srv/luxos-repo}
URL=${LUXOS_REPO_URL:-https://lsl.lux-ai.cz/luxos}
REPO=out/repo
KEEP=3

for r in luxos luxos-apps; do
    [[ -f $REPO/$r/x86_64/$r.db.tar.gz ]] || { echo "Missing $REPO/$r - run ./build.sh packages first" >&2; exit 1; }
done
compgen -G "$REPO/luxos/x86_64/*.pkg.tar.zst.sig" >/dev/null \
    || { echo "Packages are not signed (no key in ~/.local/share/luxos/signing)" >&2; exit 1; }

release=$(date -u +%Y%m%d-%H%M%S)
stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
cp -a "$REPO"/. "$stage/"

# Prehledova stranka repozitare (seznam aplikaci a nastaveni pacmanu)
pkglist() {  # pkglist REPO -> radky tabulky "nazev verze popis"
    local f
    for f in "$REPO/$1"/x86_64/*.pkg.tar.zst; do
        [[ -e $f ]] || continue
        tar --zstd -xOf "$f" .PKGINFO | awk -F' = ' '
            $1=="pkgname"{n=$2} $1=="pkgver"{v=$2} $1=="pkgdesc"{d=$2}
            END{gsub(/&/,"\\&amp;",d); gsub(/</,"\\&lt;",d); printf "<tr><td>%s</td><td>%s</td><td>%s</td></tr>\n", n, v, d}'
    done
}
cat >"$stage/index.html" <<EOF
<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>LuxOS packages</title>
<style>
body{font:15px/1.55 Inter,system-ui,sans-serif;max-width:860px;margin:40px auto;padding:0 16px;color:#1d1d2b;background:#f5f6fb}
h1{font-weight:600}h2{margin-top:2em}code,pre{font-family:ui-monospace,monospace;background:#e8eaf5;border-radius:6px}
pre{padding:12px 14px;overflow-x:auto}code{padding:1px 5px}table{border-collapse:collapse;width:100%}
td{padding:6px 10px;border-bottom:1px solid #dde0ee;vertical-align:top}td:first-child{font-weight:600;white-space:nowrap}
@media (prefers-color-scheme:dark){body{background:#12131f;color:#e8e9f3}code,pre{background:#24263a}td{border-color:#2c2f45}}
</style></head><body>
<h1>&#10022; LuxOS packages</h1>
<p>Signed package repositories for LuxOS. Install apps with <code>lux install NAME</code>.
Last update: $(date -u '+%Y-%m-%d %H:%M UTC').</p>
<h2>Apps <small>[luxos-apps]</small></h2>
<table>$(pkglist luxos-apps)</table>
<h2>System <small>[luxos]</small></h2>
<table>$(pkglist luxos)</table>
<h2>pacman.conf</h2>
<pre>[luxos]
Server = $URL/\$repo/\$arch

[luxos-apps]
Server = $URL/\$repo/\$arch</pre>
<p>Signing key: <a href="luxos.gpg">luxos.gpg</a> (package <code>luxos-keyring</code>).</p>
</body></html>
EOF
cp packages/luxos-keyring/files/luxos.gpg "$stage/luxos.gpg"
chmod -R u=rwX,go=rX "$stage"

echo "==> Uploading release $release to $HOST:$BASE"
ssh "$HOST" "mkdir -p '$BASE/releases' && chmod 755 '$BASE' '$BASE/releases'"
link=()
ssh "$HOST" "test -d '$BASE/current'" && link=(--link-dest="$BASE/current/")
rsync -a --delete "${link[@]}" "$stage/" "$HOST:$BASE/releases/$release/"

echo "==> Switching current -> $release"
ssh "$HOST" "set -e
    cd '$BASE'
    ln -sfn 'releases/$release' current.new && mv -T current.new current
    ls -1d releases/* | sort | head -n -$KEEP | xargs -r rm -rf"

for r in luxos luxos-apps; do
    code=$(curl -s -o /dev/null -w '%{http_code}' "$URL/$r/x86_64/$r.db")
    echo "    $URL/$r/x86_64/$r.db -> HTTP $code"
done
echo "==> Done: $URL/"
