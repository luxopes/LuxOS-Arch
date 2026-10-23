#!/bin/bash
# Lux Guard - integracni test se skutecnym jadrem (fanotify) a btrfs. Jen ve VM, jako root:
#   sudo bash /usr/share/doc/luxos-guard/root-fanotify-test.sh [UZIVATEL]
# (nebo ze zdroju: sudo bash packages/luxos-guard/tests/root-fanotify-test.sh UZIVATEL)
# Predpoklad: nainstalovany balik luxos-guard, bezi luxos-guard.service. Uzivatel NESMI mit
# otevrene graficke sezeni (jinak se u rizikoveho souboru objevi dotaz - kliknete "Nespoustet").
# Testovaci "skodlive" skripty jsou neskodne: na prvnim radku je exit 0, nebezpecny prikaz za nim
# se nikdy neprovede, ani kdyby ochrana selhala.
set -u
[[ $EUID -eq 0 ]] || { echo "run as root (in the VM)"; exit 2; }
U=${1:-$(getent passwd | awk -F: '$3>=1000 && $3<60000 {print $1; exit}')}
H=$(getent passwd "$U" | cut -d: -f6)
[[ -n $U && -d $H ]] || { echo "no user"; exit 2; }
DL=$H/Downloads
T=$H/lg-test
pass=0 fail=0
ok() { echo "PASS $*"; pass=$((pass + 1)); }
bad() { echo "FAIL $*"; fail=$((fail + 1)); }
as() { runuser -u "$U" -- "$@"; }
settle() { sleep "${1:-1}"; }

systemctl is-active -q luxos-guard.service || { echo "luxos-guard.service is not running"; exit 1; }
as mkdir -p "$DL" "$T"
rm -f "$DL"/lg-* "$T"/lg-*

echo "== 1. kriticky skript ze Stazenych"
as sh -c "printf '#!/bin/sh\nexit 0\nrm -rf ~\n' > '$DL/lg-wiper.sh'; chmod +x '$DL/lg-wiper.sh'"
settle
as "$DL/lg-wiper.sh" 2>/dev/null && bad "wiper exec allowed" || ok "wiper exec denied ($?)"
as bash "$DL/lg-wiper.sh" 2>/dev/null && bad "bash wiper allowed" || ok "bash wiper denied"
as sh -c ". '$DL/lg-wiper.sh'" 2>/dev/null && bad "source wiper allowed" || ok "source wiper denied"
as cat "$DL/lg-wiper.sh" >/dev/null && ok "cat (read) allowed" || bad "cat denied"
[[ $(stat -c %a "$DL/lg-wiper.sh") != *[1357]* ]] && ok "exec bits removed" || bad "exec bits kept"
as env LANG=C LC_ALL=C luxos-guard scan "$DL/lg-wiper.sh" | grep -q CRITICAL && ok "scan shows CRITICAL" || bad "scan"
as luxos-guard allow "$DL/lg-wiper.sh" 2>/dev/null && bad "allow of critical accepted" || ok "allow of critical refused"
sh "$DL/lg-wiper.sh" 2>/dev/null && bad "root: sh wiper allowed" || ok "denied for root too"

echo "== 2. kopie kritickeho skriptu jinam"
as cp "$DL/lg-wiper.sh" "$T/lg-copy.sh"; as chmod +x "$T/lg-copy.sh"
settle 2
as "$T/lg-copy.sh" 2>/dev/null && bad "copy allowed" || ok "copy denied"

echo "== 3. vlastni skript (ne zvenku) bezi bez dotazu"
as sh -c "printf '#!/bin/sh\necho LG-OWN\n' > '$T/lg-own.sh'; chmod +x '$T/lg-own.sh'"
settle
[[ $(as "$T/lg-own.sh") == LG-OWN ]] && ok "own script runs" || bad "own script blocked"

echo "== 4. rizikovy program bez sezeni = zamitnut, po 'allow' bezi"
as sh -c "printf '#!/bin/sh\necho LG-RISKY\n' > '$DL/lg-risky.sh'; chmod +x '$DL/lg-risky.sh'"
settle
if as luxos-guard status | grep -q "session helper is not running"; then
    out=$(as "$DL/lg-risky.sh" 2>&1)
    [[ $out != *LG-RISKY* ]] && ok "risky denied without session" || bad "risky ran without asking"
    sleep 6   # pamet zamitnuti bez sezeni je 5 s
else
    echo "   (sezeni bezi: v dotazu kliknete Nespoustet)"
    as "$DL/lg-risky.sh" >/dev/null 2>&1 && bad "risky ran" || ok "risky denied in dialog"
    sleep 61
fi
as luxos-guard allow "$DL/lg-risky.sh" && ok "allow risky" || bad "allow risky"
[[ $(as "$DL/lg-risky.sh") == LG-RISKY ]] && ok "allowed risky runs" || bad "allowed risky still blocked"

echo "== 5. ELF program stazeny prohlizecem (podvrzeno: xattr user.xdg.origin.url mimo Stazene)"
as cp /usr/bin/true "$T/lg-true"
as python3 -c "import os,sys; os.setxattr(sys.argv[1], 'user.xdg.origin.url', b'https://example.com/true')" "$T/lg-true"
as cp /usr/bin/true "$T/lg-true2"   # zapis po nastaveni xattr: znovu CLOSE_WRITE s puvodem
as sh -c "cat /usr/bin/true > '$T/lg-true'"
settle
as "$T/lg-true" 2>/dev/null && bad "downloaded ELF ran without asking" || ok "downloaded ELF denied (no session)"
as "$T/lg-true2" && ok "own copy of /usr/bin/true runs" || bad "own ELF blocked"

echo "== 6. restart sluzby: znacky se obnovi"
systemctl restart luxos-guard.service; settle 2
as "$DL/lg-wiper.sh" 2>/dev/null && bad "after restart wiper allowed" || ok "after restart still denied"
[[ $(as "$DL/lg-risky.sh") == LG-RISKY ]] && ok "allowed file still allowed" || bad "allowed file blocked after restart"

echo "== 7. USB (obraz vfat pripojeny do /run/media)"
img=$(mktemp /var/tmp/lg-usb.XXXX); truncate -s 16M "$img"; mkfs.vfat "$img" >/dev/null
mp=/run/media/$U/LGTEST; mkdir -p "$mp"
mount -o loop,uid="$(id -u "$U")",gid="$(id -g "$U")",fmask=0022,dmask=0022 "$img" "$mp" && {
    settle 2
    printf '#!/bin/sh\nexit 0\ndd if=/dev/zero of=/dev/sda\n' > "$mp/lg-usb-wiper.sh"
    printf 'hello\n' > "$mp/lg-notes.txt"
    sync; umount "$mp"; mount -o loop,uid="$(id -u "$U")",gid="$(id -g "$U")",fmask=0022,dmask=0022 "$img" "$mp"
    settle 2
    as "$mp/lg-usb-wiper.sh" 2>/dev/null && bad "usb wiper allowed" || ok "usb wiper denied"
    as cat "$mp/lg-notes.txt" >/dev/null && ok "usb text readable" || bad "usb read blocked"
    umount "$mp"
}
rm -f "$img"; rmdir "$mp" 2>/dev/null

echo "== 8. snimky /home"
if luxos-guard snapshot; then
    s=$(ls -1d /home/.luxos-guard-snapshots/*/ 2>/dev/null | tail -1)
    if [[ -n $s ]]; then
        ok "snapshot $s"
        as touch "$s/$U/lg-x" 2>/dev/null && bad "snapshot writable" || ok "snapshot read-only"
        as rm -rf "$s" 2>/dev/null; [[ -d $s ]] && ok "user cannot delete snapshot" || bad "user deleted snapshot"
        as btrfs subvolume delete "$s" >/dev/null 2>&1; [[ -d $s ]] && ok "user cannot delete subvolume" || bad "subvolume deleted"
        as sh -c "echo keep > '$T/lg-keep.txt'"; sleep 61; luxos-guard snapshot >/dev/null
        as rm -f "$T/lg-keep.txt"
        as luxos-guard restore "$T/lg-keep.txt" && [[ $(cat "$T/lg-keep.txt") == keep ]] &&
            ok "restore of deleted file" || bad "restore failed"
    else
        echo "   (not btrfs subvolume /home - snapshots skipped)"
    fi
fi

echo "== 9. rezie (Lux Guard vypnuty / zapnuty)"
bench() {
    local t0 t1 t2
    t0=$(date +%s%N)
    as bash -c 'for i in $(seq 2000); do /usr/bin/true; done'
    t1=$(date +%s%N)
    as bash -c 'd=$(mktemp -d ~/lg-bench.XXXX); for i in $(seq 3000); do echo $i > "$d/f$i"; done; rm -rf "$d"'
    t2=$(date +%s%N)
    echo "$(( (t1 - t0) / 2000 / 1000 )) $(( (t2 - t1) / 3000 / 1000 ))"
}
bench >/dev/null   # zahrati
systemctl stop luxos-guard.service; off1=$(bench); off2=$(bench)
systemctl start luxos-guard.service; sleep 2; on1=$(bench); on2=$(bench)
echo "   exec /usr/bin/true [us]: off ${off1% *} ${off2% *}  on ${on1% *} ${on2% *}"
echo "   write small file in ~ [us]: off ${off1#* } ${off2#* }  on ${on1#* } ${on2#* }"
echo "   service memory: $(systemctl show -p MemoryCurrent --value luxos-guard.service) B"

rm -f "$DL"/lg-* "$T"/lg-*; rmdir "$T" 2>/dev/null
echo
echo "PASS $pass  FAIL $fail"
journalctl -t luxos-guard -n 15 --no-pager
((fail == 0))
