#!/bin/bash
# LuxOS installer - jine systemy v nabidce systemd-boot (setup-chroot.sh other_systems_entries) a LuxOS
# na prvnim miste BootOrder (luxos-install uefi_luxos_first). Bez roota, bez EFI promennych.
#
#   packages/luxos-installer/tests/test-boot-entries.sh   (vypis ok/FAIL, navratovy kod = pocet chyb)
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
FILES=$(cd "$HERE/../files" && pwd)
OUT=$(mktemp -d "${TMPDIR:-/tmp}/luxos-boot-test.XXXXXX")
trap 'rm -rf "$OUT"' EXIT
NPASS=0 NFAIL=0
ok()  { NPASS=$((NPASS + 1)); printf 'ok    %s\n' "$1"; }
bad() { NFAIL=$((NFAIL + 1)); printf 'FAIL  %s\n' "$1"; [[ -n ${2-} ]] && printf '      %s\n' "$2"; return 0; }
expect() { local d=$1; shift; if "$@"; then ok "$d"; else bad "$d"; fi; }

sed -n '/^other_systems_entries() {/,/^}/p' "$FILES/setup-chroot.sh" >"$OUT/entries.sh"
sed -n '/^uefi_luxos_first() {/,/^}/p' "$FILES/luxos-install" >"$OUT/order.sh"
[[ -s $OUT/entries.sh && -s $OUT/order.sh ]] || { echo "extrakce selhala"; exit 1; }

echo "## Jine systemy na sdilenem ESP"
E=$OUT/esp
mkdir -p "$E"/EFI/{debian,ubuntu,BOOT,Microsoft/Boot,systemd,LuxOS/abc,Kali,empty,fedora} "$E/loader/entries"
touch "$E"/EFI/debian/{shimx64.efi,grubx64.efi} "$E/EFI/ubuntu/grubx64.efi" "$E/EFI/BOOT/grubx64.efi" \
      "$E/EFI/Microsoft/Boot/bootmgfw.efi" "$E/EFI/systemd/systemd-bootx64.efi" "$E/EFI/Kali/GRUBX64.EFI" \
      "$E/EFI/fedora/shimx64.efi"
printf 'title   LuxOS\nlinux   /EFI/LuxOS/abc/vmlinuz-linux-luxos\n' >"$E/loader/entries/luxos-abc.conf"
# Fedora uz v nabidce (rucne psana polozka): nesmi vzniknout druha
printf 'title Moje Fedora\nefi /EFI/fedora/shimx64.efi\n' >"$E/loader/entries/fedora.conf"
n=$(bash -c ". '$OUT/entries.sh'; other_systems_entries '$E'")
expect "pocet systemu v nabidce (Debian, Ubuntu, Kali, Fedora)" test "$n" = 4
expect "Debian se shim (prednost pred grubx64)" grep -qx 'efi     /EFI/debian/shimx64.efi' "$E/loader/entries/other-debian.conf"
expect "Debian: nazev" grep -qx 'title   Debian' "$E/loader/entries/other-debian.conf"
expect "Ubuntu jen s grubx64" grep -qx 'efi     /EFI/ubuntu/grubx64.efi' "$E/loader/entries/other-ubuntu.conf"
expect "Kali: velka pismena souboru, nazev" bash -c "grep -qx 'efi     /EFI/Kali/GRUBX64.EFI' '$E/loader/entries/other-kali.conf' && grep -qx 'title   Kali Linux' '$E/loader/entries/other-kali.conf'"
expect "Fedora: rucni polozka zustala jedina" bash -c "[[ ! -e '$E/loader/entries/other-fedora.conf' ]] && grep -q 'Moje Fedora' '$E/loader/entries/fedora.conf'"
expect "BOOT, Microsoft, systemd, LuxOS ani prazdny adresar bez polozky" \
    bash -c "! ls '$E/loader/entries' | grep -qiE 'other-(boot|microsoft|systemd|luxos|empty)'"
expect "LuxOS polozka beze zmeny" grep -qx 'title   LuxOS' "$E/loader/entries/luxos-abc.conf"
expect "bez sort-key (LuxOS zustava v nabidce prvni)" bash -c "! grep -q sort-key '$E'/loader/entries/other-*.conf"
printf 'title   Debian vlastni\nefi     /EFI/debian/shimx64.efi\n' >"$E/loader/entries/other-debian.conf"
n=$(bash -c ". '$OUT/entries.sh'; other_systems_entries '$E'")
expect "druhe spusteni: nic se neprepise ani nezdvoji" bash -c "[[ $n == 4 ]] && grep -q 'Debian vlastni' '$E/loader/entries/other-debian.conf' && [[ \$(ls '$E/loader/entries' | wc -l) == 5 ]]"
E2=$OUT/esp2; mkdir -p "$E2/EFI/BOOT" "$E2/EFI/Microsoft/Boot"
n=$(bash -c ". '$OUT/entries.sh'; other_systems_entries '$E2'")
expect "jen Windows: zadna polozka (systemd-boot ho najde sam)" bash -c "[[ $n == 0 ]] && [[ -z \$(ls '$E2/loader/entries') ]]"

echo "## LuxOS na prvni misto BootOrder"
order_case() {  # order_case NAZEV PARTUUID < vystup efibootmgr -v ; zapise prikazy do $OUT/NAZEV
    local name=$1 pu=$2
    cat >"$OUT/$name.in"
    (
        . "$OUT/order.sh"
        efibootmgr() { if [[ $1 == -v ]]; then cat "$OUT/$name.in"; else echo "efibootmgr $*" >>"$OUT/$name.cmds"; fi; }
        lsblk() { echo "$pu"; }
        run() { "$@"; }
        info() { echo "info $*" >>"$OUT/$name.cmds"; }
        T() { printf -- "$@"; }
        uefi_luxos_first /dev/nvme0n1p1
    )
    touch "$OUT/$name.cmds"
}
GAB='BootCurrent: 0000
Timeout: 0 seconds
BootOrder: 0000,0002,2001,0003,2002,2003
Boot0000* Linpus lite	HD(1,GPT,aa636640-a04e-4c1d-b408-c25880321fe8,0x800,0x1e8000)/File(\EFI\Boot\grubx64.efi)RC
Boot0002* debian	HD(1,GPT,aa636640-a04e-4c1d-b408-c25880321fe8,0x800,0x1e8000)/File(\EFI\debian\shimx64.efi)
Boot0003* LuxOS	HD(1,GPT,aa636640-a04e-4c1d-b408-c25880321fe8,0x800,0x1e8000)/File(\EFI\systemd\systemd-bootx64.efi)
Boot2001* EFI USB Device	RC
Boot2002* EFI DVD/CDROM	RC
Boot2003* EFI Network	RC'
order_case gab aa636640-a04e-4c1d-b408-c25880321fe8 <<<"$GAB"
expect "Acer jako u uzivatele: LuxOS dopredu, zbytek ve stejnem poradi" grep -qx 'efibootmgr -q -o 0003,0000,0002,2001,2002,2003' "$OUT/gab.cmds"
order_case first aa636640-a04e-4c1d-b408-c25880321fe8 <<<"${GAB/BootOrder: 0000,0002,2001,0003,2002,2003/BootOrder: 0003,0000,0002}"
expect "uz prvni: beze zmeny" test ! -s "$OUT/first.cmds"
order_case none aa636640-a04e-4c1d-b408-c25880321fe8 <<<"$(grep -v '^Boot0003' <<<"$GAB")"
expect "bez polozky LuxOS: beze zmeny" test ! -s "$OUT/none.cmds"
order_case otherdisk 11111111-2222-3333-4444-555555555555 <<<"$GAB"
expect "systemd-boot na jinem ESP se nebere" test ! -s "$OUT/otherdisk.cmds"
order_case nolabel aa636640-a04e-4c1d-b408-c25880321fe8 <<<"${GAB/Boot0003\* LuxOS/Boot0003* Linux Boot Manager}"
expect "systemd-boot na nasem ESP i bez nazvu LuxOS" grep -qx 'efibootmgr -q -o 0003,0000,0002,2001,2002,2003' "$OUT/nolabel.cmds"
order_case noefi "" <<<""
expect "bez EFI promennych: nic" test ! -s "$OUT/noefi.cmds"

echo
echo "Vysledek: $NPASS ok, $NFAIL FAIL"
exit "$NFAIL"
