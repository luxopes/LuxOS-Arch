#!/bin/bash
# LuxOS - prihlaseni otiskem se skutecnymi moduly PAM Arch Linuxu (pam_faillock, pam_nologin,
# pam_shells, pam_unix account). Spousti se JEN v jednorazovem kontejneru (meni /etc/pam.d,
# zaklada uzivatele), nikdy na pocitaci:
#
#   podman run --rm -v "$PWD:/src:ro" archlinux bash /src/packages/luxos-desktop/tests/fingerprint/container-pam-test.sh
#
# pam_fprintd nahradi maly modul (FAKE_FP=match -> otisk rozpoznan, jinak "bez ctecky"),
# /etc/security/faillock.conf dostane hodnoty LuxOS (luxos-faillock-setup: 20 chyb / 30 s -> 1 min).
set -euo pipefail
[[ -f /run/.containerenv || -f /.dockerenv ]] || { echo "only inside a throwaway container" >&2; exit 2; }
SRC=${SRC:-/src}
W=$(mktemp -d)
command -v gcc >/dev/null || pacman -Sy --noconfirm --needed gcc >/dev/null
[[ -f /usr/include/security/pam_appl.h ]] || pacman -Sy --noconfirm --needed pam >/dev/null
[[ -f /etc/pam.d/sudo ]] || pacman -Sy --noconfirm --needed sudo >/dev/null

cat >"$W/fprintd.c" <<'EOF'
#include <stdlib.h>
#include <string.h>
#include <security/pam_modules.h>
int pam_sm_authenticate(pam_handle_t *h, int f, int c, const char **v)
{ const char *m = getenv("FAKE_FP"); return (m && !strcmp(m, "match")) ? PAM_SUCCESS : PAM_AUTHINFO_UNAVAIL; }
int pam_sm_setcred(pam_handle_t *h, int f, int c, const char **v) { return PAM_SUCCESS; }
EOF
cat >"$W/pamcheck.c" <<'EOF'
/* pamcheck SLUZBA UZIVATEL -> "auth=N acct=N" (heslo z PW, bez cekani po chybe) */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <security/pam_appl.h>
static int conv(int n, const struct pam_message **m, struct pam_response **r, void *d)
{
    struct pam_response *a = calloc(n, sizeof *a);
    for (int i = 0; i < n; i++)
        if (m[i]->msg_style == PAM_PROMPT_ECHO_OFF || m[i]->msg_style == PAM_PROMPT_ECHO_ON)
            a[i].resp = strdup(getenv("PW") ? getenv("PW") : "");
        else
            fprintf(stderr, "  pam: %s\n", m[i]->msg);
    *r = a;
    return PAM_SUCCESS;
}
static void nodelay(int s, unsigned u, void *p) { (void)s; (void)u; (void)p; }
int main(int argc, char **argv)
{
    struct pam_conv c = { conv, NULL };
    pam_handle_t *h;
    if (pam_start(argv[1], argv[2], &c, &h) != PAM_SUCCESS) return 3;
    pam_set_item(h, PAM_FAIL_DELAY, (const void *)nodelay);
    int a = pam_authenticate(h, 0);
    int b = a == PAM_SUCCESS ? pam_acct_mgmt(h, 0) : -1;
    printf("auth=%d acct=%d\n", a, b);
    pam_end(h, a);
    return (a == PAM_SUCCESS && b == PAM_SUCCESS) ? 0 : 1;
}
EOF
gcc -shared -fPIC -o /usr/lib/security/pam_fprintd.so "$W/fprintd.c" -lpam
gcc -o "$W/pamcheck" "$W/pamcheck.c" -lpam

# LightDM jako v Arch Linuxu (balik lightdm v kontejneru neni)
cat >/etc/pam.d/lightdm <<'EOF'
#%PAM-1.0
auth        include     system-login
-auth       optional    pam_gnome_keyring.so
account     include     system-login
password    include     system-login
-password   optional    pam_gnome_keyring.so use_authtok
session     include     system-login
-session    optional    pam_gnome_keyring.so auto_start
EOF
bash "$SRC/packages/luxos-tweaks/files/security/luxos-faillock-setup" /etc/security/faillock.conf
grep -E '^(deny|fail_interval|unlock_time)' /etc/security/faillock.conf
id anna >/dev/null 2>&1 || useradd -m -s /bin/bash anna
echo 'anna:secret' | chpasswd
faillock --user anna --reset

fail=0
check() {  # check POPIS OCEKAVANI(ok|refused) SLUZBA FAKE_FP HESLO
    local out rc=0
    out=$(FAKE_FP=$4 PW=$5 "$W/pamcheck" "$3" anna 2>&1) || rc=$?
    local got=ok; [[ $rc -eq 0 ]] || got=refused
    if [[ $got == "$2" ]]; then echo "PASS  $1 [$3]: $got"; else echo "FAIL  $1 [$3]: $got, expected $2"; fail=1; fi
    sed 's/^/      /' <<<"$out"
}
lock_anna() {  # 20 spatnych hesel (bez otisku) -> pam_faillock zamkne ucet
    local i
    for i in $(seq 20); do FAKE_FP=none PW=wrong "$W/pamcheck" sudo anna >/dev/null 2>&1 || true; done
}

mode=${1:-new}
if [[ $mode == old ]]; then
    # puvodni rozlozeni (pred opravou): otisk "sufficient" pred celou sluzbou - reprodukce problemu
    for s in lightdm sudo; do
        { head -n1 "/etc/pam.d/$s"; echo "-auth      sufficient  pam_fprintd.so max-tries=3 timeout=10"; tail -n +2 "/etc/pam.d/$s"; } >"$W/$s"
        cp "$W/$s" "/etc/pam.d/$s"
    done
else
    bash "$SRC/packages/luxos-desktop/files/fingerprint/luxos-fingerprint-pam" apply
    bash "$SRC/packages/luxos-desktop/files/fingerprint/luxos-fingerprint-pam" status
fi
echo "--- layout ($mode): lightdm"; cat /etc/pam.d/lightdm; echo "---"

for s in lightdm sudo; do
    check "fingerprint, wrong password" ok "$s" match wrong
    check "no reader, correct password" ok "$s" none secret
    check "no reader, wrong password" refused "$s" none wrong
done

lock_anna
faillock --user anna | tail -n +2 | wc -l | sed 's/^/failures recorded: /'
for s in lightdm sudo; do
    check "locked account + fingerprint" refused "$s" match x
    check "locked account + correct password" refused "$s" none secret
done
faillock --user anna --reset

# uspesny otisk vynuluje pocitadlo (authsucc), neuspesne pokusy se pocitaji dal
for i in 1 2 3; do FAKE_FP=none PW=wrong "$W/pamcheck" sudo anna >/dev/null 2>&1 || true; done
check "fingerprint after 3 failures" ok sudo match x
n=$(faillock --user anna | grep -c ' V$' || true)
if [[ $mode == old || $n -eq 0 ]]; then echo "PASS  counter after fingerprint: $n"; else echo "FAIL  counter after fingerprint: $n"; fail=1; fi
faillock --user anna --reset

touch /etc/nologin
check "/etc/nologin + fingerprint (login)" refused lightdm match x
check "/etc/nologin + fingerprint (sudo is not a login)" ok sudo match x
rm -f /etc/nologin

usermod -s /usr/bin/false-shell anna
check "shell not in /etc/shells + fingerprint" refused lightdm match x
usermod -s /bin/bash anna

chage -E 0 anna
for s in lightdm sudo; do check "expired account + fingerprint" refused "$s" match x; done
chage -E -1 anna

if [[ $mode != old ]]; then
    bash "$SRC/packages/luxos-desktop/files/fingerprint/luxos-fingerprint-pam" remove
    if grep -q pam_fprintd /etc/pam.d/lightdm /etc/pam.d/sudo; then echo "FAIL  remove left the block"; fail=1
    else echo "PASS  remove restores the services"; fi
    check "after remove: correct password" ok sudo none secret
fi
echo "RESULT ($mode): $([[ $fail -eq 0 ]] && echo all passed || echo FAILURES)"
exit $fail
