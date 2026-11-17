#!/bin/bash
# Live ISO (archiso/airootfs): root se zamcenym heslem (root jen pres sudo uzivatele lux), SSH server
# vypnuty a i po zapnuti bez prazdnych hesel a bez prihlaseni roota; nouzovy shell funguje dal.
#   bash scripts/tests/test-live-hardening.sh
# Je-li nainstalovany sshd, overi i skutecne pouzite hodnoty (sshd -T) s timto doplnkem konfigurace.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
A=$HERE/../../archiso/airootfs
fail=0
ok() { if "${@:2}"; then echo "ok    $1"; else echo "FAIL  $1"; fail=1; fi; }

root_hash=$(awk -F: '$1 == "root" {print $2}' "$A/etc/shadow")
ok "root: heslo zamcene (zacina '!')" test "${root_hash:0:1}" = "!"
ok "root: ne prazdne heslo" test -n "$root_hash"
ok "root: shadow 0400 v profilu" grep -q '\["/etc/shadow"\]="0:0:400"' "$A/../profiledef.sh"
ok "lux: sudo bez hesla zustava (root pres sudo)" grep -q 'ALL=(ALL:ALL) NOPASSWD: ALL' "$A/usr/local/bin/luxos-live-setup"

drop=$A/etc/ssh/sshd_config.d/10-luxos-live.conf
ok "sshd: PermitRootLogin no" grep -qx 'PermitRootLogin no' "$drop"
ok "sshd: PermitEmptyPasswords no" grep -qx 'PermitEmptyPasswords no' "$drop"
ok "sshd: sluzba neni zapnuta" bash -c "! find '$A/etc/systemd/system' -name 'sshd*' -path '*.wants/*' | grep -q ."
ok "sshd: socket neni zapnuty" bash -c "! find '$A/etc/systemd/system' -name 'sshd.socket' | grep -q ."
for u in emergency rescue; do
    ok "$u shell i se zamcenym rootem" grep -qx 'Environment=SYSTEMD_SULOGIN_FORCE=1' "$A/etc/systemd/system/$u.service.d/luxos-live.conf"
done

if command -v sshd >/dev/null 2>&1 && [[ -r /etc/ssh/sshd_config ]]; then
    T=$(mktemp -d "${TMPDIR:-/tmp}/live-sshd.XXXXXX")
    trap 'rm -rf "$T"' EXIT
    ssh-keygen -q -t ed25519 -N '' -f "$T/key"
    # stejne poradi jako /etc/ssh/sshd_config v Arch: Include na zacatku, pak pripadne zmeny spravce
    printf 'Include %s\nHostKey %s\nPermitRootLogin yes\nPermitEmptyPasswords yes\n' "$drop" "$T/key" >"$T/sshd_config"
    eff=$(sshd -T -f "$T/sshd_config" 2>/dev/null)
    ok "sshd -T: permitrootlogin no i pri pozdejsim 'yes'" grep -qix 'permitrootlogin no' <<<"$eff"
    ok "sshd -T: permitemptypasswords no i pri pozdejsim 'yes'" grep -qix 'permitemptypasswords no' <<<"$eff"
    ok "Arch sshd_config nacita sshd_config.d" grep -q '^Include /etc/ssh/sshd_config.d/\*.conf' /etc/ssh/sshd_config
else
    echo "skip  sshd -T (sshd neni nainstalovany)"
fi
exit $fail
