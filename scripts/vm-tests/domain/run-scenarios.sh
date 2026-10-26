#!/bin/bash
# LuxOS - laborator AD: automaticke scenare (plan v README.md). Bezi na HOSTITELI a ovlada obe VM
# pres scripts/vmctl.py (guest agent + QMP). Predpoklad: obe VM bezi (vm-ad.sh dc / client),
# provision-dc.sh probehl na DC a setup-client.sh na klientovi.
#
#   scripts/vm-tests/domain/run-scenarios.sh [CISLA...]   napr. 1 3 5; bez argumentu vse
#
# Vysledek: radky PASS/FAIL, snimky obrazovky do out/test-ad/shots, souhrn na konci (exit 1 = chyba).
set -uo pipefail
cd "$(dirname "$(readlink -f "$0")")/../../.."

LAB=${LUXOS_AD_LAB:-out/test-ad}
HERE=scripts/vm-tests/domain
SHOTS=$LAB/shots
mkdir -p "$SHOTS"
pass=0 fail=0

dc()     { LUXOS_VM_DIR=$LAB/dc python3 scripts/vmctl.py exec "$1" "${2:-600}"; }
cl()     { LUXOS_VM_DIR=$LAB/client python3 scripts/vmctl.py exec "$1" "${2:-600}"; }
clvm()   { LUXOS_VM_DIR=$LAB/client python3 scripts/vmctl.py "$@"; }
link()   { python3 "$HERE/vmlink.py" "$LAB/client" net1 "$1"; }   # on|off: laboratorni sit klienta
shot()   { clvm shot "$SHOTS/$1.png" >/dev/null; }
check()  {  # check POPIS PRIKAZ...   (prikaz na hostiteli, 0 = PASS)
    local what=$1; shift
    if "$@" >/dev/null 2>&1; then echo "PASS  $what"; pass=$((pass + 1)); else echo "FAIL  $what"; fail=$((fail + 1)); fi
}
has()    { grep -q -- "$2" <<<"$1"; }
hasnt()  { ! grep -q -- "$2" <<<"$1"; }
put()    { LUXOS_VM_DIR=$LAB/client python3 scripts/vmctl.py put "$1" "$2"; }

ADMIN=Administrator ADMINPASS=Lab-Admin-2026 USERPASS=Lab-User-2026 DOMAIN=luxtest.lan

prepare() {
    put "$HERE/pam-auth.py" /root/pam-auth.py
    cl "chmod +x /root/pam-auth.py; lux domain status --json" >/dev/null
}

join_ok() {
    cl "printf '%s\n' '$ADMINPASS' | lux domain join $DOMAIN -U $ADMIN --password-stdin --yes --progress" 900
}

s1() {  # discover a join (chybne heslo, posunute hodiny, OU, existujici ucet)
    local out
    out=$(cl "lux domain discover $DOMAIN --json")
    check "1a discover finds dc1" has "$out" '"dc1.luxtest.lan"'
    out=$(cl "printf 'wrong\n' | lux domain join $DOMAIN -U $ADMIN --password-stdin --yes --progress")
    check "1b wrong password -> @@ERROR password" has "$out" "@@ERROR password"
    check "1b nothing changed (no sssd.conf)" cl "test ! -e /etc/sssd/sssd.conf"
    cl "timedatectl set-ntp false; date -s '+10 min'" >/dev/null
    out=$(cl "printf '%s\n' '$ADMINPASS' | lux domain join $DOMAIN -U $ADMIN --password-stdin --yes --progress")
    check "1c clock skew -> @@ERROR clock" has "$out" "@@ERROR clock"
    # sync-time bez pripojeni: hodiny z radice primo (stejna funkce jako tlacitko v Nastaveni)
    cl "python3 -c 'import sys; sys.path.insert(0,\"/usr/lib/luxos/python\"); import luxos_domain as d; print(d.sync_time_from([\"dc1.luxtest.lan\"]))'"
    out=$(cl "printf '%s\n' 'Lab-Join-2026' | lux domain join $DOMAIN -U joiner --ou OU=LuxOS,DC=luxtest,DC=lan --password-stdin --yes --progress" 900)
    check "1d join as joiner into OU=LuxOS" has "$out" "@@DONE"
    out=$(dc "samba-tool computer show LUXPC1 --attributes=distinguishedName")
    check "1d computer account in OU=LuxOS" has "$out" "OU=LuxOS"
    cl "lux domain leave --yes" >/dev/null
    out=$(join_ok)
    check "1e re-join with an existing computer account" has "$out" "@@DONE"
    check "1f password never stored" cl "! grep -rqs -- '$ADMINPASS' /etc /var/lib/luxos /var/log /root"
}

s2() {  # prihlaseni domenovym uctem: PAM (lightdm), domovska slozka ze skel
    local out
    out=$(cl "printf '%s\n' '$USERPASS' | /root/pam-auth.py lightdm eva")
    check "2a PAM lightdm eva online" has "$out" "result: Success"
    out=$(cl "getent passwd eva")
    check "2b short name eva, home /home/eva, shell lsh" has "$out" "eva:\*:.*:/home/eva:/usr/bin/lsh"
    # greeter: Jiny uzivatel -> jmeno -> heslo (snimek pro kontrolu vzhledu)
    clvm click 640 600; sleep 2; shot 2-greeter-other
    clvm keys "eva"; clvm key ret; sleep 2; clvm keys "$USERPASS"; clvm key ret; sleep 15; shot 2-eva-desktop
    check "2c /home/eva created from skel" cl "test -d /home/eva/.config && stat -c %a /home/eva | grep -q 700"
}

s3() {  # offline prihlaseni, chybne heslo offline, vyprseni cache
    local out
    link off; sleep 5
    cl "systemctl start luxos-domain-refresh.service" >/dev/null
    out=$(cl "cat /run/luxos/domain/status.json")
    check "3a offline detected for the greeter" has "$out" '"online": false'
    out=$(cl "printf '%s\n' '$USERPASS' | /root/pam-auth.py lightdm eva")
    check "3b offline sign-in from cache" has "$out" "result: Success"
    check "3b message cached credentials" has "$out" "cached"
    out=$(cl "printf 'wrong\n' | /root/pam-auth.py lightdm eva")
    check "3c wrong password offline refused" has "$out" "Authentication failure"
    shot 3-greeter-offline
    cl "lux domain set offline-days 1; date -s '+3 days'" >/dev/null
    out=$(cl "printf '%s\n' '$USERPASS' | /root/pam-auth.py lightdm eva")
    check "3d cache expired after offline-days" hasnt "$out" "result: Success"
    cl "date -s '-3 days'; lux domain set offline-days 30" >/dev/null
    link on; sleep 10
}

s4() {  # vyprsele heslo, vypnuty ucet
    local out
    out=$(cl "printf '%s\nNew-Pass-2026x\nNew-Pass-2026x\n' '$USERPASS' | /root/pam-auth.py lightdm expired --chauthtok")
    check "4a expired password -> change at sign-in" has "$out" "new password required"
    check "4a change succeeded" has "$out" "result: Success"
    out=$(cl "printf '%s\n' '$USERPASS' | /root/pam-auth.py lightdm locked")
    check "4b disabled account refused" hasnt "$out" "result: Success"
}

s5() {  # sudo a polkit pro LuxOS Admins, R5 offline limit
    local out
    out=$(cl "sudo -l -U itadmin")
    check "5a itadmin (LuxOS Admins) may sudo" has "$out" "(ALL : ALL) ALL"
    out=$(cl "sudo -l -U eva")
    check "5b eva may not sudo" has "$out" "not allowed"
    check "5c polkit rule lists luxos admins" cl "grep -q 'luxos admins' /etc/polkit-1/rules.d/49-luxos-domain-admins.rules"
    # R5: 8 dni bez spojeni -> prava spravcu vypnuta, po spojeni zpet
    link off; sleep 5
    cl "python3 - <<'P'
import json; p='/var/lib/luxos/domain/state.json'; s=json.load(open(p))
import datetime; s['last_online']=(datetime.datetime.now().astimezone()-datetime.timedelta(days=8)).isoformat(timespec='seconds')
json.dump(s, open(p,'w'))
P
systemctl start luxos-domain-refresh.service" >/dev/null
    out=$(cl "sudo -l -U itadmin")
    check "5d admin rights suspended after 8 days offline" hasnt "$out" "(ALL : ALL) ALL"
    link on; sleep 10
    cl "systemctl start luxos-domain-refresh.service" >/dev/null
    out=$(cl "sudo -l -U itadmin")
    check "5e admin rights back when online" has "$out" "(ALL : ALL) ALL"
}

s6() {  # GPO: Deny log on locally
    local out
    out=$(cl "sssctl user-checks denied -a acct -s lightdm 2>&1")
    check "6a GPO deny log on locally -> refused" hasnt "$out" "pam_acct_mgmt: Success"
    out=$(cl "sssctl user-checks eva -a acct -s lightdm 2>&1")
    check "6b eva allowed" has "$out" "pam_acct_mgmt: Success"
    cl "lux domain login allow 'Účtárna'" >/dev/null
    out=$(cl "sssctl user-checks jan@luxtest.lan -a acct -s lightdm 2>&1")
    check "6c login allow Účtárna -> jan refused" hasnt "$out" "pam_acct_mgmt: Success"
    cl "lux domain login deny 'Účtárna'" >/dev/null
}

s7() {  # SMB sdileni a tiskarna s Kerberos
    local out
    out=$(cl "runuser -u eva -- sh -c 'printf \"%s\\n\" \"$USERPASS\" | kinit eva@LUXTEST.LAN && smbclient --use-kerberos=required //dc1.luxtest.lan/data -c ls'")
    check "7a share listed with Kerberos (no password)" has "$out" "README.txt"
    cl "lux domain printer add pdf smb://dc1.luxtest.lan/pdf" >/dev/null
    out=$(cl "lpstat -v pdf; lpoptions -p pdf | tr ' ' '\n' | grep auth-info")
    check "7b printer queue with negotiate" has "$out" "negotiate"
    cl "lux domain share add smb://dc1.luxtest.lan/data 'Lab data'" >/dev/null
    check "7c share in state" cl "lux domain share list | grep -q dc1.luxtest.lan/data"
}

s8() {  # leave + rollback, hook po aktualizaci
    local out
    cl "lux reinstall -y filesystem" >/dev/null
    check "8a nsswitch keeps sss after filesystem reinstall" cl "grep -q '^passwd:.* sss' /etc/nsswitch.conf"
    out=$(cl "printf '%s\n' '$ADMINPASS' | lux domain leave -U $ADMIN --password-stdin --yes --progress" 600)
    check "8b leave done" has "$out" "@@DONE"
    check "8c home of eva kept" cl "test -d /home/eva"
    check "8d sss removed from nsswitch" cl "! grep -q ' sss' /etc/nsswitch.conf"
    out=$(dc "samba-tool computer list")
    check "8e computer account deleted" hasnt "$out" "LUXPC1"
    check "8f local admin still works" cl "sudo -l -U lux | grep -q ALL"
    out=$(join_ok)
    check "8g join again after leave" has "$out" "@@DONE"
}

s9() {  # kolize jmen: mistni jan vs domenovy jan (R4)
    local out
    cl "systemctl start luxos-domain-refresh.service; sleep 3" >/dev/null
    out=$(cl "getent passwd jan")
    check "9a 'jan' is the local account (uid 1000+)" has "$out" "jan:x:"
    out=$(cl "getent passwd jan@luxtest.lan")
    check "9b domain jan has full name and own home" has "$out" "jan@luxtest.lan:\*:.*:/home/jan@luxtest.lan:"
    out=$(cl "printf '%s\n' '$USERPASS' | /root/pam-auth.py lightdm jan@luxtest.lan")
    check "9c domain jan signs in as jan@luxtest.lan" has "$out" "result: Success"
    out=$(cl "printf '%s\n' 'Local-Jan-2026' | /root/pam-auth.py lightdm jan")
    check "9d local jan still signs in" has "$out" "result: Success"
}

prepare
want=("$@")
((${#want[@]})) || want=(1 2 3 4 5 6 7 9 8)
for n in "${want[@]}"; do
    echo "== scenario $n =="
    "s$n"
done
echo "== $pass passed, $fail failed (screenshots: $SHOTS) =="
((fail == 0))
