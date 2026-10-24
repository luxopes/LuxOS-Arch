#!/bin/bash
# LuxOS - zverejneni repozitaru [luxos] a [luxos-apps] na server
#
#   scripts/publish-repo.sh            nahraje out/repo a prepne aktualni vydani
#   scripts/publish-repo.sh --apps-only nahraje jen [luxos-apps] z out/repo; [luxos] prevezme
#                                      z aktualniho vydani na serveru (po ./build.sh apps)
#
# Na serveru: /srv/luxos-repo/releases/<cas>/{luxos,luxos-apps}/x86_64, odkaz current
# ukazuje na posledni vydani (Caddy: https://luxos.lux-ai.cz/repo/). Prepnuti je
# atomicke a ponechavaji se 3 posledni vydani pro pripadny navrat.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."

HOST=${LUXOS_REPO_HOST:-root@185.183.156.25}
BASE=${LUXOS_REPO_DIR:-/srv/luxos-repo}
URL=${LUXOS_REPO_URL:-https://luxos.lux-ai.cz/repo}
REPO=out/repo
KEEP=3
apps_only=0
[[ ${1:-} == --apps-only ]] && apps_only=1

repos=(luxos luxos-apps)
((apps_only)) && repos=(luxos-apps)
for r in "${repos[@]}"; do
    [[ -f $REPO/$r/x86_64/$r.db.tar.gz ]] || { echo "Missing $REPO/$r - run ./build.sh packages first" >&2; exit 1; }
done
compgen -G "$REPO/${repos[0]}/x86_64/*.pkg.tar.zst.sig" >/dev/null \
    || { echo "Packages are not signed (no key in ~/.local/share/luxos/signing)" >&2; exit 1; }

release=$(date -u +%Y%m%d-%H%M%S)
stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
if ((apps_only)); then
    # [luxos] beze zmeny z aktualniho vydani na serveru, [luxos-apps] z out/repo
    ssh "$HOST" "test -d '$BASE/current/luxos'" || { echo "No current [luxos] on $HOST" >&2; exit 1; }
    rsync -a "$HOST:$BASE/current/luxos/" "$stage/luxos/"
    ssh "$HOST" "test -d '$BASE/current/lux'" && rsync -a "$HOST:$BASE/current/lux/" "$stage/lux/"
    cp -a "$REPO/luxos-apps" "$stage/"
else
    cp -a "$REPO"/. "$stage/"
fi
# [luxos-drivers] (overene ovladace z AUR) se stavi zvlast (./build.sh drivers) - jinak zustava ze serveru
if [[ -f out/drivers-repo/luxos-drivers/x86_64/luxos-drivers.db.tar.gz ]]; then
    rm -rf "$stage/luxos-drivers"
    cp -a out/drivers-repo/luxos-drivers "$stage/"
elif ssh "$HOST" "test -d '$BASE/current/luxos-drivers'"; then
    rsync -a "$HOST:$BASE/current/luxos-drivers/" "$stage/luxos-drivers/"
fi

# Prehledova stranka repozitare (seznam aplikaci a nastaveni pacmanu)
pkglist() {  # pkglist REPO -> radky tabulky "nazev verze popis"
    local f
    for f in "$stage/$1"/x86_64/*.pkg.tar.zst; do
        [[ -e $f ]] || continue
        tar --zstd -xOf "$f" .PKGINFO | awk -F' = ' '
            $1=="pkgname"{n=$2} $1=="pkgver"{v=$2} $1=="pkgdesc"{d=$2}
            END{gsub(/&/,"\\&amp;",d); gsub(/</,"\\&lt;",d); printf "<tr><td>%s</td><td>%s</td><td>%s</td></tr>\n", n, v, d}'
    done
}
luxlist() {  # balicky ve vlastnim formatu z lux/index.json
    [[ -f $stage/lux/index.json ]] || return 0
    python3 -c '
import html, json, sys
for p in json.load(open(sys.argv[1]))["packages"]:
    print("<tr><td>%s</td><td>%s-%s</td><td>%s</td></tr>" % (html.escape(p["name"]), html.escape(p["version"]),
          p.get("release", 1), html.escape(p.get("summary", ""))))' "$stage/lux/index.json"
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
<h2>LuxOS packages <small>(.lux)</small></h2>
<table>$(luxlist)</table>
<h2>System <small>[luxos]</small></h2>
<table>$(pkglist luxos)</table>
<h2>Printer and scanner drivers <small>[luxos-drivers]</small></h2>
<p>Manufacturer drivers from the AUR, each version checked before it is built (sources only from the
manufacturer, no network access while building, every update re-checked).</p>
<table>$(pkglist luxos-drivers)</table>
<h2>Repositories</h2>
<p>LuxOS has both repositories set up already in <code>/etc/lux/lux.conf</code>. To add them again
(for example after editing the file), put this into <code>/etc/lux/conf.d/luxos.conf</code> and run
<code>lux config check</code>:</p>
<pre>repo luxos
    server  $URL/\$repo/\$arch

repo luxos-apps
    server  $URL/\$repo/\$arch

repo luxos-drivers
    server  $URL/\$repo/\$arch</pre>
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

for r in luxos luxos-apps luxos-drivers; do
    code=$(curl -s -o /dev/null -w '%{http_code}' "$URL/$r/x86_64/$r.db")
    echo "    $URL/$r/x86_64/$r.db -> HTTP $code"
done
echo "==> Done: $URL/"
