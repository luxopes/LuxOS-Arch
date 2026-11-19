#!/bin/bash
# Nasazeni Discord bota LuxOS na server (spousti spravce ze sveho pocitace, ne na serveru).
#
#   server/discord-bot/deploy.sh [ssh-cil]        (vychozi cil: $DISCORD_BOT_SSH, napr. root@server)
#
# Kroky: 1) vytvori index dokumentace knowledge.json z tohoto repozitare, 2) pusti mistni testy
# (falesny Discord, lux-api a SMTP - nic se nikam neposila), 3) nahraje aplikaci do
# /opt/luxos-discord-bot.new, na serveru npm ci --omit=dev podle package-lock.json, prohodi
# adresare (predchozi verze zustane v /opt/luxos-discord-bot.old), 4) nainstaluje systemd unit,
# 5) zkontroluje, ze existuji soubory s tokenem a klicem (obsah nevypisuje), a sluzbu restartuje.
# Na serveru je potreba: Node 20+, npm, rsync, systemd. Token a klic uklada vlastnik (README).
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../.." && pwd)
TARGET=${1:-${DISCORD_BOT_SSH:?set DISCORD_BOT_SSH=user@host or pass the ssh target}}
APP=/opt/luxos-discord-bot
TMPD=$(mktemp -d)
cleanup() { rm -rf "$TMPD"; }
trap cleanup EXIT

echo "== index dokumentace"
node "$HERE/scripts/build-index.js" --repo "$REPO" --out "$TMPD/knowledge.json"

echo "== testy"
(cd "$HERE" && npm ci --ignore-scripts --no-audit --no-fund --loglevel=error && nice -n 10 npm test --silent)

echo "== nahravam na $TARGET"
NODE=$(ssh "$TARGET" 'command -v node' || true)
[ -n "$NODE" ] || { echo "node not found on $TARGET"; exit 1; }
ssh "$TARGET" "$NODE -e 'process.exit(Number(process.versions.node.split(\".\")[0]) >= 20 ? 0 : 1)'" ||
    { echo "Node 20+ required on $TARGET"; exit 1; }
ssh "$TARGET" "rm -rf $APP.new && mkdir -p $APP.new"
rsync -r --chmod=D755,F644 "$HERE/package.json" "$HERE/package-lock.json" "$HERE/src" "$TMPD/knowledge.json" "$TARGET:$APP.new/"
sed "s#^ExecStart=/usr/bin/node #ExecStart=$NODE #" "$HERE/luxos-discord-bot.service" >"$TMPD/luxos-discord-bot.service"
rsync --chmod=F644 "$TMPD/luxos-discord-bot.service" "$TARGET:/etc/systemd/system/luxos-discord-bot.service"
ssh "$TARGET" "set -e
    cd $APP.new && npm ci --omit=dev --ignore-scripts --no-audit --no-fund --loglevel=error
    chmod -R a+rX,go-w $APP.new
    rm -rf $APP.old
    if [ -d $APP ]; then mv $APP $APP.old; fi
    mv $APP.new $APP
    install -d -m 700 /etc/luxos-discord
    systemctl daemon-reload"

echo "== tajne udaje (jen kontrola, ze existuji)"
if ! ssh "$TARGET" "test -s /etc/luxos-discord/token && test -s /etc/luxos-discord/luxai-key"; then
    cat <<EOF
   /etc/luxos-discord/token or /etc/luxos-discord/luxai-key is missing on $TARGET.
   Store them first (README, "Store the token"), then run this script again.
   The new version is installed; the service was not started.
EOF
    exit 1
fi
ssh "$TARGET" "chmod 600 /etc/luxos-discord/token /etc/luxos-discord/luxai-key"

echo "== spoustim"
ssh "$TARGET" "systemctl enable --quiet luxos-discord-bot && systemctl restart luxos-discord-bot"
ssh "$TARGET" "for i in 1 2 3 4 5 6 7 8 9 10; do
                   journalctl -u luxos-discord-bot --since -1min -o cat | grep -q '^ready as ' && break; sleep 1; done
               systemctl is-active luxos-discord-bot && journalctl -u luxos-discord-bot -n 8 --no-pager -o cat"

cat <<EOF

== hotovo. Log: ssh $TARGET journalctl -u luxos-discord-bot -f
   Navrat na predchozi verzi: ssh $TARGET 'mv $APP $APP.bad && mv $APP.old $APP && systemctl restart luxos-discord-bot'
   Jednorazove nastaveni serveru (jen poprve, bot musi mit Administrator - README):
     ssh $TARGET 'node $APP/src/setup.js'
EOF
