#!/bin/bash
# Posta LuxOS <-> server LuxAI: prihlaseni do schranek uctem LuxAI (SASL OAUTHBEARER/XOAUTH2).
# Bezi NA SERVERU jako root; spousti ho server/mail-oauth/deploy.sh (nahraje celou slozku do
# /root/mail-oauth-<cas>/ a zavola "bash remote-apply.sh <cas> [--no-submission]").
#
# Kroky (kazdy idempotentni, zaloha predem do /root/mail-oauth-backup-<cas>/, navrat: remote-rollback.sh):
#   1. kontrola predpokladu (Dovecot 2.4, certifikat, volne porty, server uctu bezi)
#   2. tajemstvi introspekce (nove jen kdyz chybi; nikdy se nevypisuje)
#   3. mapovani ucet -> schranka /etc/lux-account-mailboxes.json (z konfigurace Roundcube luxai_sso)
#   4. server uctu: uprava server.js (mail_oauth_patch.py), drop-in s EnvironmentFile, restart, kontrola
#   5. Dovecot: luxai-oauth2.conf + luxai-public.conf, kontrola doveconf, restart, kontrola 993 a TLS
#   6. lux-mail-sync-cert: po obnoveni certifikatu i "systemctl reload dovecot"
#   7. Postfix submission 587 + submissions 465 (SASL pres Dovecot, jen prihlaseni) - vynecha --no-submission
#   8. fail2ban: filtry pro Dovecot 2.4 a Postfix SASL (vcetne XOAUTH2/OAUTHBEARER)
#   9. firewall naposled: porty 993 (+465, 587) v /etc/nftables.d/lux-filter.nft a zive pravidlo
#
# ROOT=/cesta umozni test nanecisto v docasne slozce (server/mail-oauth/tests/test_deploy_scripts.py,
# prikazy systemctl/nft/... jsou tam nahrazene); na serveru je ROOT prazdne.
set -euo pipefail
umask 077

STAMP=${1:?usage: remote-apply.sh STAMP [--no-submission]}
shift
SUBMISSION=1
for arg in "$@"; do
    case "$arg" in
        --no-submission) SUBMISSION=0 ;;
        *) echo "unknown option: $arg" >&2; exit 2 ;;
    esac
done

HERE=$(cd "$(dirname "$0")" && pwd)
R=${ROOT:-}
BACKUP="$R/root/mail-oauth-backup-$STAMP"
ACC_JS="$R/opt/lux-account/server.js"
ACC_ENV="$R/etc/lux-account-mail-oauth.env"
ACC_DROPIN="$R/etc/systemd/system/lux-account.service.d/mail-oauth.conf"
MAILBOXES="$R/etc/lux-account-mailboxes.json"
DOVE="$R/etc/dovecot"
NFT="$R/etc/nftables.d/lux-filter.nft"
SYNC="$R/usr/local/sbin/lux-mail-sync-cert"
F2B="$R/etc/fail2ban"
PF="$R/etc/postfix"
TLS_CERT="$R/etc/lux-mail/tls/fullchain.pem"
MARK="luxai-mail-oauth"

say() { printf '== %s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

# ---- 1. predpoklady ---------------------------------------------------------------------------------------------
say "1/9 checks"
dovecot --version | grep -q '^2\.4\.' || die "Dovecot 2.4 required (found $(dovecot --version))"
[[ -s $TLS_CERT ]] || die "missing $TLS_CERT (Caddy + lux-mail-sync-cert)"
[[ -f $ACC_JS ]] || die "missing $ACC_JS"
[[ -f $DOVE/local.conf ]] || die "missing $DOVE/local.conf"
[[ -f $NFT ]] || die "missing $NFT"
curl -fsS -m 5 http://127.0.0.1:3020/health >/dev/null || die "account server (127.0.0.1:3020) is not healthy"
for port in 993 465 587; do
    if ss -Hltn "sport = :$port" | grep -q LISTEN && ! grep -q "$MARK" "$DOVE/local.conf" 2>/dev/null; then
        die "port $port is already in use"
    fi
done

# ---- zaloha -----------------------------------------------------------------------------------------------------
mkdir -p "$BACKUP"
chmod 700 "$BACKUP"
backup() {
    local f=$1
    if [[ -e $f && ! -e $BACKUP/files$f.orig ]]; then
        mkdir -p "$BACKUP/files$(dirname "$f")"
        cp -a "$f" "$BACKUP/files$f.orig"
    elif [[ ! -e $f ]]; then
        mkdir -p "$BACKUP/files$(dirname "$f")"
        : > "$BACKUP/files$f.absent"
    fi
}
for f in "$ACC_JS" "$ACC_ENV" "$ACC_DROPIN" "$MAILBOXES" "$DOVE/local.conf" "$DOVE/luxai-oauth2.conf" \
         "$DOVE/luxai-public.conf" "$DOVE/luxai-oauth2-secret.conf" "$NFT" "$SYNC" "$PF/master.cf" "$PF/main.cf" \
         "$PF/luxai_sender_login" "$F2B/filter.d/luxai-dovecot.conf" "$F2B/filter.d/luxai-postfix-sasl.conf" \
         "$F2B/jail.d/luxai-mail.local"; do
    backup "$f"
done
echo "$STAMP" > "$BACKUP/stamp"
say "backup: $BACKUP"

# ---- 2. tajemstvi -----------------------------------------------------------------------------------------------
say "2/9 introspection secret"
if [[ -s $ACC_ENV ]] && grep -q '^MAIL_INTROSPECTION_SECRET=[0-9a-f]\{64\}$' "$ACC_ENV"; then
    SECRET=$(sed -n 's/^MAIL_INTROSPECTION_SECRET=//p' "$ACC_ENV")
else
    SECRET=$(openssl rand -hex 32)
    {
        echo "# Posta LuxOS: introspekce tokenu schranek pro Dovecot (stejne tajemstvi je v /etc/dovecot/luxai-oauth2-secret.conf)"
        echo "MAIL_INTROSPECTION_SECRET=$SECRET"
        echo "MAIL_MAILBOXES_FILE=/etc/lux-account-mailboxes.json"
    } > "$ACC_ENV.new"
    chmod 600 "$ACC_ENV.new"
    mv -f "$ACC_ENV.new" "$ACC_ENV"
fi
{
    echo "# LuxAI: adresa introspekce s klientem lux-dovecot (HTTP Basic). Tajne - 0600 root."
    echo "oauth2 {"
    echo "  introspection_url = http://lux-dovecot:$SECRET@127.0.0.1:3020/oauth/introspect"
    echo "}"
} > "$DOVE/luxai-oauth2-secret.conf.new"
chmod 600 "$DOVE/luxai-oauth2-secret.conf.new"
mv -f "$DOVE/luxai-oauth2-secret.conf.new" "$DOVE/luxai-oauth2-secret.conf"
unset SECRET

# ---- 3. mapovani ucet -> schranka -------------------------------------------------------------------------------
say "3/9 mailbox mapping"
if [[ ! -s $MAILBOXES ]]; then
    # stejna pravidla jako webmail (Roundcube luxai_sso): e-maily + skupina luxai-admin, navic id uctu
    RC_SSO="${RC_SSO:-$R/etc/roundcube/luxai-sso.inc.php}" php -r '
        $c = include getenv("RC_SSO");
        $m = ["imap" => ["host" => "mail.lux-ai.cz", "port" => 993, "security" => "ssl"],
              "smtp" => ["host" => "mail.lux-ai.cz", "port" => 465, "security" => "ssl"],
              "mailboxes" => [["address" => strtolower($c["mailbox"]), "display_name" => "LuxAI",
                               "emails" => array_values(array_map("strtolower", $c["allowed_emails"])),
                               "users" => isset($c["allowed_subject"]) ? [$c["allowed_subject"]] : [],
                               "require_group" => "luxai-admin"]]];
        echo json_encode($m, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES), "\n";' > "$MAILBOXES.new"
    python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d["mailboxes"][0]["address"].count("@")==1' "$MAILBOXES.new" \
        || die "could not build $MAILBOXES from Roundcube config"
    chgrp luxaccount "$MAILBOXES.new" 2>/dev/null || true
    chmod 640 "$MAILBOXES.new"
    mv -f "$MAILBOXES.new" "$MAILBOXES"
fi
python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print("   mailboxes:", ", ".join(m["address"] for m in d["mailboxes"]))' "$MAILBOXES"

# ---- 4. server uctu ---------------------------------------------------------------------------------------------
say "4/9 account server"
python3 "$HERE/account-server/mail_oauth_patch.py" "$ACC_JS"
cp "$ACC_JS" "$BACKUP/check.cjs"
node --check "$BACKUP/check.cjs"
rm -f "$BACKUP/check.cjs"
mkdir -p "$(dirname "$ACC_DROPIN")"
printf '[Service]\n# Posta LuxOS: /api/mail/* a /oauth/introspect (Dovecot)\nEnvironmentFile=/etc/lux-account-mail-oauth.env\n' > "$ACC_DROPIN"
chmod 644 "$ACC_DROPIN"
systemctl daemon-reload
systemctl restart lux-account
for i in $(seq 1 20); do curl -fsS -m 2 http://127.0.0.1:3020/health >/dev/null 2>&1 && break; sleep 0.5; done
curl -fsS -m 5 http://127.0.0.1:3020/health >/dev/null || die "account server did not come back (journalctl -u lux-account)"
code=$(curl -s -o /dev/null -w '%{http_code}' -m 5 -H 'X-Lux-Client: luxos' http://127.0.0.1:3020/api/mail/mailboxes)
[[ $code == 401 ]] || die "/api/mail/mailboxes without a session answered $code (expected 401)"
code=$(curl -s -o /dev/null -w '%{http_code}' -m 5 http://127.0.0.1:3020/api/mail/mailboxes)
[[ $code == 403 ]] || die "/api/mail/mailboxes without X-Lux-Client answered $code (expected 403)"
# introspekce s neplatnym tokenem: tajemstvi jde curl jen pres config na stdin (ne v argumentech)
answer=$(sed -n 's/^MAIL_INTROSPECTION_SECRET=//p' "$ACC_ENV" | { read -r s; printf 'user = "lux-dovecot:%s"\n' "$s"; } \
         | curl -s -m 5 -K - --data 'token=invalid-token-check' http://127.0.0.1:3020/oauth/introspect)
[[ $answer == '{"active":false}' ]] || die "introspection check failed: $answer"
echo "   /api/mail/* and /oauth/introspect answer as expected"

# ---- 5. Dovecot -------------------------------------------------------------------------------------------------
say "5/9 dovecot"
install -m 644 "$HERE/dovecot/luxai-oauth2.conf" "$DOVE/luxai-oauth2.conf"
install -m 644 "$HERE/dovecot/luxai-public.conf" "$DOVE/luxai-public.conf"
if ! grep -q "$MARK" "$DOVE/local.conf"; then
    printf '\n# %s: Posta LuxOS - prihlaseni uctem LuxAI a verejny IMAPS (server/mail-oauth v repozitari LuxOS)\n!include_try luxai-oauth2.conf\n!include_try luxai-public.conf\n' "$MARK" >> "$DOVE/local.conf"
fi
# vystup doveconf -n obsahuje adresu introspekce s tajemstvim -> jen navratovy kod a chyby bez nej
if ! doveconf -n > /dev/null 2> "$BACKUP/doveconf.err"; then
    grep -v introspection_url "$BACKUP/doveconf.err" >&2
    die "doveconf rejected the configuration (run remote-rollback.sh $STAMP)"
fi
doveconf -h auth_mechanisms | grep -q oauthbearer || die "auth_mechanisms without oauthbearer"
systemctl restart dovecot
for i in $(seq 1 20); do ss -Hltn 'sport = :993' | grep -q LISTEN && break; sleep 0.5; done
ss -Hltn 'sport = :993' | grep -q LISTEN || die "dovecot does not listen on 993"
ss -Hltn 'sport = :143' | grep -v -q '127.0.0.1\|\[::1\]' && die "port 143 is no longer loopback-only"
greeting=$(printf 'a CAPABILITY\r\na LOGOUT\r\n' | timeout 10 openssl s_client -quiet -verify_return_error \
           -connect 127.0.0.1:993 -servername mail.lux-ai.cz -verify_hostname mail.lux-ai.cz 2>/dev/null || true)
grep -q 'AUTH=OAUTHBEARER' <<<"$greeting" || die "IMAPS 993 greeting without AUTH=OAUTHBEARER or certificate not valid"
echo "   IMAPS 993: valid certificate for mail.lux-ai.cz, OAUTHBEARER/XOAUTH2 offered"

# ---- 6. obnoveni certifikatu ------------------------------------------------------------------------------------
say "6/9 certificate sync"
if [[ -f $SYNC ]] && ! grep -q "$MARK" "$SYNC"; then
    printf '# %s: Dovecot (IMAPS 993) pouziva stejny certifikat\nif systemctl is-active --quiet dovecot; then systemctl reload dovecot; fi\n' "$MARK" >> "$SYNC"
fi

# ---- 7. Postfix submission --------------------------------------------------------------------------------------
if [[ $SUBMISSION == 1 ]]; then
    say "7/9 postfix submission 587 + submissions 465"
    python3 -c 'import json,sys; [print(m["address"], m["address"]) for m in json.load(open(sys.argv[1]))["mailboxes"]]' "$MAILBOXES" > "$PF/luxai_sender_login"
    chmod 644 "$PF/luxai_sender_login"
    postmap "$PF/luxai_sender_login"
    common=(
        "smtpd_tls_auth_only=yes" "smtpd_sasl_auth_enable=yes" "smtpd_sasl_type=dovecot" "smtpd_sasl_path=private/auth"
        "smtpd_sasl_security_options=noanonymous" "smtpd_sasl_authenticated_header=no"
        "smtpd_sender_login_maps=hash:/etc/postfix/luxai_sender_login"
        "smtpd_client_restrictions=permit_sasl_authenticated,reject"
        "smtpd_sender_restrictions=reject_non_fqdn_sender,reject_sender_login_mismatch,permit_sasl_authenticated,reject"
        "smtpd_recipient_restrictions=reject_non_fqdn_recipient,permit_sasl_authenticated,reject"
        "smtpd_relay_restrictions=permit_sasl_authenticated,reject" "milter_macro_daemon_name=ORIGINATING"
    )
    postconf -M "submission/inet=submission inet n - y - - smtpd"
    postconf -P "submission/inet/syslog_name=postfix/submission" "submission/inet/smtpd_tls_security_level=encrypt"
    postconf -M "submissions/inet=submissions inet n - y - - smtpd"
    postconf -P "submissions/inet/syslog_name=postfix/submissions" "submissions/inet/smtpd_tls_wrappermode=yes"
    for opt in "${common[@]}"; do
        postconf -P "submission/inet/$opt" "submissions/inet/$opt"
    done
    postfix check
    systemctl reload postfix
    for i in $(seq 1 20); do ss -Hltn 'sport = :465' | grep -q LISTEN && break; sleep 0.5; done
    ss -Hltn 'sport = :465' | grep -q LISTEN || die "postfix does not listen on 465"
    ss -Hltn 'sport = :587' | grep -q LISTEN || die "postfix does not listen on 587"
    echo "   465/587 listening; AUTH only after TLS, relay only after SASL login, sender = login"
else
    say "7/9 postfix submission skipped (--no-submission)"
fi

# ---- 8. fail2ban ------------------------------------------------------------------------------------------------
say "8/9 fail2ban"
install -m 644 "$HERE/fail2ban/luxai-dovecot.conf" "$F2B/filter.d/luxai-dovecot.conf"
install -m 644 "$HERE/fail2ban/luxai-postfix-sasl.conf" "$F2B/filter.d/luxai-postfix-sasl.conf"
install -m 644 "$HERE/fail2ban/luxai-mail.local" "$F2B/jail.d/luxai-mail.local"
if [[ $SUBMISSION == 0 ]]; then
    sed -i '/^\[luxai-postfix-sasl\]/,/^$/ s/^enabled = true/enabled = false/' "$F2B/jail.d/luxai-mail.local"
fi
fail2ban-client -t > /dev/null || die "fail2ban configuration test failed"
fail2ban-client reload > /dev/null
fail2ban-client status luxai-dovecot > /dev/null || die "jail luxai-dovecot is not running"

# ---- 9. firewall ------------------------------------------------------------------------------------------------
say "9/9 firewall"
ports="993"
[[ $SUBMISSION == 1 ]] && ports="465, 587, 993"
if ! grep -q "$MARK" "$NFT"; then
    # trvale (po restartu): vlastni radek za verejnymi porty; banovane IP (lux_guard) zahodi uz retez vyse
    python3 - "$NFT" "$ports" "$MARK" <<'PY'
import sys
path, ports, mark = sys.argv[1:4]
text = open(path).read()
anchor = "\t\ttcp dport { 22, 25, 80, 443, 8085 } ct state new accept\n"
if text.count(anchor) != 1:
    sys.exit("firewall anchor not found in " + path)
text = text.replace(anchor, anchor + "\t\ttcp dport { %s } ct state new accept comment \"%s\"\n" % (ports, mark), 1)
open(path, "w").write(text)
PY
fi
nft -c -f "$R/etc/nftables.conf" || die "nft rejected $NFT"
# zive bez "nft -f" (flush ruleset by smazal bany fail2ban a LUX Guard)
if ! nft -a list chain inet lux_filter input | grep -q "$MARK"; then
    nft add rule inet lux_filter input tcp dport "{ $ports }" ct state new accept comment "\"$MARK\""
fi
nft -a list chain inet lux_filter input | grep "$MARK"

say "done. Rollback: bash $HERE/remote-rollback.sh $STAMP"
