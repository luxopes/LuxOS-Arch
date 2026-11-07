#!/bin/bash
# Nasazeni prihlaseni do schranek uctem LuxAI (Posta LuxOS) na server LuxAI. Spousti spravce ze sveho
# pocitace, ne na serveru:
#
#   server/mail-oauth/deploy.sh [ssh-cil] [--no-submission]      (vychozi cil root@185.183.156.25)
#
# 1) mistni kontroly skriptu (a testy, kdyz jsou nastavene LUX_ACCOUNT_SERVER_JS / LUX_DOVECOT_ROOT),
# 2) nahraje server/mail-oauth (bez tests/) do /root/mail-oauth-<cas>/ na serveru,
# 3) spusti tam remote-apply.sh <cas> (zaloha, server uctu, Dovecot, Postfix, fail2ban, firewall),
# 4) vypise prikaz pro navrat (remote-rollback.sh <cas>). Podrobnosti a rucni overeni: README.md.
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
TARGET=root@185.183.156.25
OPTS=()
for arg in "$@"; do
    case "$arg" in
        --no-submission) OPTS+=("$arg") ;;
        -*) echo "unknown option: $arg" >&2; exit 2 ;;
        *) TARGET=$arg ;;
    esac
done
STAMP=$(date +%Y%m%d%H%M%S)
REMOTE=/root/mail-oauth-$STAMP

echo "== local checks"
bash -n "$HERE/remote-apply.sh"
bash -n "$HERE/remote-rollback.sh"
python3 -m py_compile "$HERE/account-server/mail_oauth_patch.py"
if [[ -n ${LUX_ACCOUNT_SERVER_JS:-} ]]; then
    (cd "$HERE/tests" && nice -n 10 python3 -m unittest -q test_account_server test_deploy_scripts test_fail2ban)
    [[ -n ${LUX_DOVECOT_ROOT:-} ]] && (cd "$HERE/tests" && nice -n 10 python3 -m unittest -q test_dovecot_oauth)
else
    (cd "$HERE/tests" && nice -n 10 python3 -m unittest -q test_deploy_scripts)
    echo "   (server tests skipped: set LUX_ACCOUNT_SERVER_JS to a local copy of /opt/lux-account/server.js)"
fi

echo "== upload to $TARGET:$REMOTE"
ssh "$TARGET" "mkdir -m 700 $REMOTE"
tar -C "$HERE" --exclude=tests --exclude=__pycache__ -cf - . | ssh "$TARGET" "tar -C $REMOTE -xf -"

echo "== apply"
ssh -t "$TARGET" "bash $REMOTE/remote-apply.sh $STAMP ${OPTS[*]:-}"

cat <<EOF

== deployed ($STAMP). Rollback if needed:
   ssh $TARGET bash $REMOTE/remote-rollback.sh $STAMP
Manual checks (README.md "After deployment"): sign in to webmail (Roundcube) once, then add the
mailbox in LuxOS Mail with "Continue as …" on a LuxOS computer signed in to the LuxAI account.
EOF
