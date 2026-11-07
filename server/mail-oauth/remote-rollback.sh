#!/bin/bash
# Navrat zmen remote-apply.sh NA SERVERU (root): bash remote-rollback.sh STAMP [--purge]
# Obnovi soubory ze zalohy /root/mail-oauth-backup-STAMP/ (co pred nasazenim neexistovalo, smaze),
# odebere zive pravidlo firewallu a restartuje dotcene sluzby. --purge smaze i tajemstvi introspekce
# a mapovani schranek (jinak zustanou pro pristi nasazeni; bez drop-inu je server uctu nepouziva).
# Vydane tokeny jsou jen v pameti serveru uctu - restartem zmizi.
set -uo pipefail

STAMP=${1:?usage: remote-rollback.sh STAMP [--purge]}
PURGE=0
[[ ${2:-} == --purge ]] && PURGE=1
R=${ROOT:-}
BACKUP="$R/root/mail-oauth-backup-$STAMP"
MARK="luxai-mail-oauth"
[[ -d $BACKUP/files ]] || { echo "no backup $BACKUP" >&2; exit 1; }
fail=0
say() { printf '== %s\n' "$*"; }

say "firewall"
handles=$(nft -a list chain inet lux_filter input 2>/dev/null | sed -n "s/.*comment \"$MARK\" # handle \([0-9]*\).*/\1/p")
for h in $handles; do
    nft delete rule inet lux_filter input handle "$h" || fail=1
done

say "files"
keep=("$R/etc/lux-account-mail-oauth.env" "$R/etc/lux-account-mailboxes.json")
while IFS= read -r -d '' saved; do
    rel=${saved#"$BACKUP/files"}
    case "$rel" in
        *.orig) target=${rel%.orig}; cp -a "$saved" "$target" || fail=1 ;;
        *.absent)
            target=${rel%.absent}
            skip=0
            for k in "${keep[@]}"; do [[ $target == "$k" && $PURGE == 0 ]] && skip=1; done
            [[ $skip == 1 ]] && continue
            rm -f "$target" "$target.db"
            ;;
    esac
done < <(find "$BACKUP/files" -type f \( -name '*.orig' -o -name '*.absent' \) -print0)

say "postfix"
postconf -MX submission/inet submissions/inet 2>/dev/null || true
if [[ -f $BACKUP/files$R/etc/postfix/master.cf.orig ]]; then
    cp -a "$BACKUP/files$R/etc/postfix/master.cf.orig" "$R/etc/postfix/master.cf"
fi
postfix check && systemctl reload postfix || fail=1

say "dovecot"
doveconf -n > /dev/null 2>&1 || { echo "doveconf still fails - check /etc/dovecot/local.conf" >&2; fail=1; }
systemctl restart dovecot || fail=1

say "account server"
systemctl daemon-reload
systemctl restart lux-account || fail=1
for i in $(seq 1 20); do curl -fsS -m 2 http://127.0.0.1:3020/health >/dev/null 2>&1 && break; sleep 0.5; done
curl -fsS -m 5 http://127.0.0.1:3020/health >/dev/null || fail=1

say "fail2ban"
fail2ban-client reload > /dev/null || fail=1

if [[ $fail == 0 ]]; then
    say "rollback done"
else
    say "rollback finished WITH ERRORS - check the messages above"
fi
exit $fail
