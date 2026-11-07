#!/bin/bash
# Nasazeni countme LuxOS na server (spousti spravce ze sveho pocitace, ne na serveru).
#
#   server/countme/deploy.sh [ssh-cil]          (vychozi cil: $COUNTME_SSH, napr. root@server)
#
# Kroky: 1) prelozi luxos_countme.lsl mistne na statickou binarku (lsl compile, LSL na serveru neni),
# 2) pusti mistni testy proti teto binarce, 3) nahraje /opt/luxos-countme/luxos-countme (0755)
# a /etc/systemd/system/luxos-countme.service, 4) daemon-reload, enable + restart (pri restartu
# sluzba citace zapise; stav v /var/lib/luxos-countme zustava), 5) overi /health a /stats/usage.json
# na 127.0.0.1:8766 (nic nezapocita), 6) vypise blok pro Caddy (vlozit rucne, viz Caddyfile.snippet).
# Na serveru je potreba: systemd, rsync, curl, Caddy.
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
TARGET=${1:-${COUNTME_SSH:?set COUNTME_SSH=user@host or pass the ssh target}}
PORT=8766
TMPD=$(mktemp -d)
cleanup() { rm -rf "$TMPD"; }
trap cleanup EXIT

echo "== prekladam luxos_countme.lsl"
nice -n 10 lsl compile "$HERE/luxos_countme.lsl" "$TMPD/luxos-countme" >"$TMPD/compile.log" 2>&1 || {
    cat "$TMPD/compile.log"; exit 1; }
if command -v file >/dev/null; then
    file -b "$TMPD/luxos-countme" | grep -q 'statically linked' || {
        echo "binary is not statically linked: $(file -b "$TMPD/luxos-countme")"; exit 1; }
fi
echo "   ok: $(du -h "$TMPD/luxos-countme" | cut -f1), sha256 $(sha256sum "$TMPD/luxos-countme" | cut -c1-16)"

echo "== testy"
COUNTME_BIN="$TMPD/luxos-countme" nice -n 10 python3 -I "$HERE/tests/test_countme.py"

echo "== instaluji na $TARGET"
ssh "$TARGET" "mkdir -p /opt/luxos-countme && chmod 755 /opt/luxos-countme"
rsync "$TMPD/luxos-countme" "$TARGET:/opt/luxos-countme/luxos-countme.new"
rsync "$HERE/luxos-countme.service" "$TARGET:/etc/systemd/system/luxos-countme.service"
ssh "$TARGET" "set -e; chmod 755 /opt/luxos-countme/luxos-countme.new;
               mv -f /opt/luxos-countme/luxos-countme.new /opt/luxos-countme/luxos-countme;
               chmod 644 /etc/systemd/system/luxos-countme.service; systemctl daemon-reload;
               systemctl enable --quiet luxos-countme && systemctl restart luxos-countme"

echo "== kontrola"
ssh "$TARGET" "for i in 1 2 3 4 5 6 7 8 9 10; do
                   curl -fsS http://127.0.0.1:$PORT/health && exit 0; sleep 1; done;
               systemctl status --no-pager luxos-countme; exit 1"
# neplatny pozadavek (400) nic nezapocita; platny by pridal falesnou instalaci
ssh "$TARGET" "curl -s -o /dev/null -w '   /countme (invalid, expect 400): %{http_code}\n' \
                   'http://127.0.0.1:$PORT/countme?v=0&arch=x86_64&ch=stable&age=1';
               curl -fsS -o /dev/null -w '   /stats/usage.json: %{http_code} %{size_download} B\n' \
                   http://127.0.0.1:$PORT/stats/usage.json;
               ls -la /var/lib/private/luxos-countme/ 2>/dev/null || true"

cat <<EOF

== Caddy (jednou, rucne): do bloku luxos.lux-ai.cz { ... } v /etc/caddy/Caddyfile vlozit
$(cat "$HERE/Caddyfile.snippet")

   pak: caddy validate --config /etc/caddy/Caddyfile && systemctl reload caddy
   test: curl -s -o /dev/null -w '%{http_code}\n' 'https://luxos.lux-ai.cz/countme?v=0&arch=x86_64&ch=stable&age=1'   (400)
         curl -s https://luxos.lux-ai.cz/stats/usage.json | head -c 300
         journalctl -u caddy --since -5min | grep -c countme   (0 = /countme se neloguje)
EOF
