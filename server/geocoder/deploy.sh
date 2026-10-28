#!/bin/bash
# Nasazeni geocoderu LuxOS na server (spousti spravce ze sveho pocitace, ne na serveru).
#
#   server/geocoder/deploy.sh DB.sqlite[.zst] [ssh-cil]        (vychozi cil: $GEOCODER_SSH, napr. root@server)
#   server/geocoder/deploy.sh --service-only [ssh-cil]         (jen kod sluzby a unit, bez dat)
#
# Kroky: 1) overi databazi mistne (schema, pocet mist, zkusebni dotaz), 2) nahraje ji rsyncem do
# /var/lib/luxos-geocoder/releases/<datum>/ (.partial, pak prejmenovani), 3) nainstaluje
# /opt/luxos-geocoder/luxos_geocoder.py a /etc/systemd/system/luxos-geocoder.service,
# 4) atomicky prepne symlink current -> nove vydani (bezici sluzba si ho do 30 s sama otevre;
# pri prvni instalaci se sluzba zapne), 5) overi /health na 127.0.0.1:8765, 6) smaze starsi vydani
# (necha 2), 7) vypise blok pro Caddy (vlozit rucne, viz Caddyfile.snippet).
# Na serveru je potreba: python3 (>= 3.9, sqlite3 s FTS5 - Debian 11+ ma), rsync, systemd, Caddy.
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
SERVICE_ONLY=0
if [ "${1:-}" = "--service-only" ]; then
    SERVICE_ONLY=1
    shift
fi
DB=""
if [ "$SERVICE_ONLY" = 0 ]; then
    DB=${1:?usage: deploy.sh DB.sqlite[.zst] [ssh-target] | deploy.sh --service-only [ssh-target]}
    shift
fi
TARGET=${1:-${GEOCODER_SSH:?set GEOCODER_SSH=user@host or pass the ssh target}}
BASE=/var/lib/luxos-geocoder
PORT=8765
STAMP=$(date -u +%Y%m%d-%H%M%S)
TMPD=""
cleanup() { [ -n "$TMPD" ] && rm -rf "$TMPD"; return 0; }
trap cleanup EXIT

if [ "$SERVICE_ONLY" = 0 ]; then
    if [[ "$DB" == *.zst ]]; then
        TMPD=$(mktemp -d)
        echo "== rozbaluji $DB"
        zstd -q -d "$DB" -o "$TMPD/geocoder.sqlite"
        DB="$TMPD/geocoder.sqlite"
    fi
    echo "== overuji $DB"
    python3 -I - "$DB" "$HERE/luxos_geocoder.py" <<'EOF'
import importlib.util, sys
spec = importlib.util.spec_from_file_location("g", sys.argv[2])
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)
s = g.Searcher(sys.argv[1])
n = int(s.meta.get("features") or 0)
assert s.meta.get("schema") == "1", "schema"
assert n > 1000, f"only {n} features"
res = s.search(g.Query("praha", 50.08, 14.42))
assert res and res[0]["properties"].get("name") == "Praha", res[:1]
print(f"   ok: {n} features, data {s.meta.get('data')}, built {s.meta.get('built')}")
EOF
    SUM=$(sha256sum "$DB" | cut -d' ' -f1)
    REL="$BASE/releases/$STAMP"
    echo "== nahravam do $TARGET:$REL ($(du -h "$DB" | cut -f1))"
    ssh "$TARGET" "mkdir -p '$REL' && chmod 755 '$BASE' '$BASE/releases' '$REL'"
    rsync -z --partial --info=progress2 "$DB" "$TARGET:$REL/geocoder.sqlite.partial"
    ssh "$TARGET" "set -e; cd '$REL'; echo '$SUM  geocoder.sqlite.partial' | sha256sum -c --quiet;
                   chmod 644 geocoder.sqlite.partial; mv geocoder.sqlite.partial geocoder.sqlite"
fi

echo "== instaluji sluzbu"
ssh "$TARGET" "mkdir -p /opt/luxos-geocoder"
rsync "$HERE/luxos_geocoder.py" "$TARGET:/opt/luxos-geocoder/luxos_geocoder.py"
rsync "$HERE/luxos-geocoder.service" "$TARGET:/etc/systemd/system/luxos-geocoder.service"
ssh "$TARGET" "chmod 644 /opt/luxos-geocoder/luxos_geocoder.py /etc/systemd/system/luxos-geocoder.service &&
               chmod 755 /opt/luxos-geocoder && systemctl daemon-reload"

if [ "$SERVICE_ONLY" = 0 ]; then
    echo "== prepinam current -> releases/$STAMP"
    ssh "$TARGET" "set -e; cd '$BASE'; ln -sfn 'releases/$STAMP' current.new; mv -T current.new current"
fi
# prvni instalace: zapnout; jinak restart jen kvuli novemu kodu (data si sluzba prepne sama)
ssh "$TARGET" "systemctl enable --quiet luxos-geocoder && systemctl restart luxos-geocoder"

echo "== kontrola"
ssh "$TARGET" "for i in 1 2 3 4 5 6 7 8 9 10; do
                   curl -fsS http://127.0.0.1:$PORT/health && exit 0; sleep 1; done;
               systemctl status --no-pager luxos-geocoder; exit 1"
echo
ssh "$TARGET" "curl -fsS -o /dev/null -w '   /api praha: %{http_code} %{time_total}s\n' \
               'http://127.0.0.1:$PORT/api?q=praha&lat=50.08&lon=14.42&limit=5'"

if [ "$SERVICE_ONLY" = 0 ]; then
    echo "== mazu stara vydani (zustanou 2)"
    ssh "$TARGET" "cd '$BASE/releases' && ls -1d */ | sed 's#/##' | sort | head -n -2 |
                   while read -r d; do [ \"\$d\" != '$STAMP' ] && rm -rf -- \"\$d\"; done; ls -1 '$BASE/releases'"
fi

cat <<EOF

== Caddy (jednou, rucne): do bloku luxos.lux-ai.cz { ... } v /etc/caddy/Caddyfile vlozit
$(cat "$HERE/Caddyfile.snippet")

   pak: caddy validate --config /etc/caddy/Caddyfile && systemctl reload caddy
   test: curl -s 'https://luxos.lux-ai.cz/geocode/api?q=namesti%20miru&lat=50.08&lon=14.42&limit=3'
EOF
