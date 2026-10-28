#!/bin/bash
# LuxOS - zverejneni repozitaru [luxos] a [luxos-apps] na server
#
#   scripts/publish-repo.sh            nahraje out/repo a prepne aktualni vydani
#   scripts/publish-repo.sh --apps-only nahraje jen [luxos-apps] z out/repo; [luxos] prevezme
#                                      z aktualniho vydani na serveru (po ./build.sh apps)
#   LUXOS_REPO_CHANNEL=staging scripts/publish-repo.sh [--apps-only]
#                                      totez do testovaciho kanalu: prepne odkaz staging misto current
#                                      (systemy s [general] channel = "staging" v /etc/lux/lux.conf);
#                                      do current ho pozdeji prevede scripts/promote-staging.sh
#
# Na serveru: /srv/luxos-repo/releases/<cas>/{luxos,luxos-apps}/x86_64, odkaz current
# ukazuje na posledni vydani (Caddy: https://luxos.lux-ai.cz/repo/), odkaz staging na posledni
# testovaci vydani (https://luxos.lux-ai.cz/staging/). Prepnuti je atomicke; ponechavaji se
# 3 posledni vydani a vzdy obe vydani, na ktera ukazuji current a staging.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."

HOST=${LUXOS_REPO_HOST:-root@185.183.156.25}
BASE=${LUXOS_REPO_DIR:-/srv/luxos-repo}
case ${LUXOS_REPO_CHANNEL:-current} in
    current|stable) LINK=current; URL=${LUXOS_REPO_URL:-https://luxos.lux-ai.cz/repo} ;;
    staging)        LINK=staging; URL=${LUXOS_REPO_URL:-https://luxos.lux-ai.cz/staging} ;;
    *) echo "LUXOS_REPO_CHANNEL must be current or staging, not '$LUXOS_REPO_CHANNEL'" >&2; exit 2 ;;
esac
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
    || { echo "Packages are not signed: unlock the Safe (luxos-safe unlock) with the key in" \
              "/safe/$USER/luxos-signing (or ~/.local/share/luxos/signing) and run ./build.sh packages again" >&2; exit 1; }

release=$(date -u +%Y%m%d-%H%M%S)
stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
# Zdroj nezmenenych casti (--apps-only, [luxos-drivers]): vydani stejneho kanalu, jinak current
# (prvni zverejneni do staging vychazi z current)
FROM=current
[[ $LINK == staging ]] && ssh "$HOST" "test -d '$BASE/staging/'" && FROM=staging
echo "==> Channel $LINK ($URL), unchanged parts from $FROM"
if ((apps_only)); then
    # [luxos] beze zmeny z vydani na serveru, [luxos-apps] z out/repo
    ssh "$HOST" "test -d '$BASE/$FROM/luxos'" || { echo "No $FROM [luxos] on $HOST" >&2; exit 1; }
    rsync -a "$HOST:$BASE/$FROM/luxos/" "$stage/luxos/"
    if ssh "$HOST" "test -d '$BASE/$FROM/lux'"; then rsync -a "$HOST:$BASE/$FROM/lux/" "$stage/lux/"; fi
    cp -a "$REPO/luxos-apps" "$stage/"
else
    cp -a "$REPO"/. "$stage/"
fi
# [luxos-drivers] (overene ovladace z AUR) se stavi zvlast (./build.sh drivers) - jinak zustava ze serveru
if [[ -f out/drivers-repo/luxos-drivers/x86_64/luxos-drivers.db.tar.gz ]]; then
    rm -rf "$stage/luxos-drivers"
    cp -a out/drivers-repo/luxos-drivers "$stage/"
elif ssh "$HOST" "test -d '$BASE/$FROM/luxos-drivers'"; then
    rsync -a "$HOST:$BASE/$FROM/luxos-drivers/" "$stage/luxos-drivers/"
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
<h1>&#10022; LuxOS packages$([[ $LINK == staging ]] && echo ' <small>(staging - test builds before a release)</small>')</h1>
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
<pre>[repo.luxos]
server = "$URL/\$repo/\$arch"

[repo.luxos-apps]
server = "$URL/\$repo/\$arch"

[repo.luxos-drivers]
server = "$URL/\$repo/\$arch"</pre>
<p>Signing key: <a href="luxos.gpg">luxos.gpg</a> (package <code>luxos-keyring</code>).</p>
</body></html>
EOF
cp packages/luxos-keyring/files/luxos.gpg "$stage/luxos.gpg"
chmod -R u=rwX,go=rX "$stage"

echo "==> Uploading release $release to $HOST:$BASE"
ssh "$HOST" "mkdir -p '$BASE/releases' && chmod 755 '$BASE' '$BASE/releases'"
link=()
ssh "$HOST" "test -d '$BASE/$FROM'" && link=(--link-dest="$BASE/$FROM/")
rsync -a --delete "${link[@]}" "$stage/" "$HOST:$BASE/releases/$release/"

echo "==> Switching $LINK -> $release"
ssh "$HOST" "set -e
    cd '$BASE'
    ln -sfn 'releases/$release' '$LINK.new' && mv -T '$LINK.new' '$LINK'
    # stara vydani pryc: krome $KEEP nejnovejsich a tech, na ktera ukazuji current a staging
    keep=\$(for l in current staging; do [ -L \"\$l\" ] && readlink \"\$l\"; done; true)
    ls -1d releases/* | sort | head -n -$KEEP | while read -r r; do
        case \" \$(echo \$keep) \" in *\" \$r \"*) continue ;; esac
        rm -rf \"\$r\"
    done"

for r in luxos luxos-apps luxos-drivers; do
    code=$(curl -s -o /dev/null -w '%{http_code}' "$URL/$r/x86_64/$r.db")
    echo "    $URL/$r/x86_64/$r.db -> HTTP $code"
done
echo "==> Done: $URL/"
