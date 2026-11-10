#!/bin/bash
# luxos-secureboot - ESP, zalozni zavadec, polozky UEFI, zapis klice (bez roota, bez skutecnych EFI promennych:
# efibootmgr, mokutil, sbverify, bootctl, findmnt a lsblk jsou nahrazene). Skutecny podpis a start se
# Secure Boot overuje test ve VM (docs/proposals/secure-boot.md, Testy).
#
#   packages/luxos-secureboot/tests/test-luxos-secureboot.sh   (ok/FAIL, navratovy kod = pocet chyb)
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
BIN=$(cd "$HERE/../files" && pwd)/luxos-secureboot
T=$(mktemp -d "${TMPDIR:-/tmp}/luxos-sb-test.XXXXXX")
trap 'rm -rf "$T"' EXIT
NPASS=0 NFAIL=0
ok()  { NPASS=$((NPASS + 1)); printf 'ok    %s\n' "$1"; }
bad() { NFAIL=$((NFAIL + 1)); printf 'FAIL  %s\n' "$1"; [[ -n ${2-} ]] && printf '      %s\n' "$2"; return 0; }
expect() { local d=$1; shift; if "$@"; then ok "$d"; else bad "$d"; fi; }

# --- nahrazene programy -----------------------------------------------------
M=$T/mock; mkdir -p "$M"
cat >"$M/sbverify" <<'EOF'
#!/bin/bash
# "podepsany" = soubor obsahuje znacku SIGNED-BY-LUXOS
f=${!#}; grep -qa SIGNED-BY-LUXOS "$f"
EOF
cat >"$M/efibootmgr" <<'EOF'
#!/bin/bash
echo "efibootmgr $*" >>"$T/efibootmgr.log"
if [[ $1 == -v ]]; then cat "$T/efibootmgr.out"; fi
exit 0
EOF
cat >"$M/bootctl" <<'EOF'
#!/bin/bash
[[ $1 == --print-esp-path ]] && echo "$TEST_ESP"
EOF
cat >"$M/findmnt" <<'EOF'
#!/bin/bash
case "$*" in *SOURCE*) echo /dev/nvme0n1p1 ;; *FSTYPE*) echo vfat ;; esac
EOF
cat >"$M/lsblk" <<'EOF'
#!/bin/bash
case "$*" in *PARTN*) echo 1 ;; *PKNAME*) echo nvme0n1 ;; *PARTUUID*) echo "$TEST_PARTUUID" ;; esac
EOF
cat >"$M/mokutil" <<'EOF'
#!/bin/bash
echo "mokutil $*" >>"$T/mokutil.log"
case $1 in
    --test-key) if grep -qxF "$2" "$T/mok.enrolled" 2>/dev/null; then echo "$2 is already enrolled"; else echo "$2 is not enrolled"; fi ;;
    --list-new) cat "$T/mok.new" 2>/dev/null ;;
    # jako skutecny mokutil 0.7: vyzvy na stdout pred hashem
    --generate-hash) read -r a; read -r b; printf 'input password: \ninput password again: \n'
                     [[ $a == "$b" ]] && echo "\$6\$salt\$hash-of-$a" ;;
    --import) shift; while [[ $1 != --hash-file ]]; do echo "$1" >>"$T/mok.new"; shift; done; cp "$2" "$T/hash.used" ;;
    --revoke-import) rm -f "$T/mok.new" ;;
esac
EOF
chmod +x "$M"/*
export PATH="$M:$PATH" T TEST_PARTUUID=aaaa-1111

# --- prostredi: balik, ESP, EFI promenne ------------------------------------
setup() {  # setup [unsigned]
    rm -rf "${T:?}/lib" "$T/share" "$T/esp" "$T/vars" "$T/state" "$T"/*.log "$T/mok."* "$T/hash.used"
    mkdir -p "$T/lib" "$T/share" "$T/esp/EFI/systemd" "$T/esp/EFI/BOOT" "$T/esp/loader/entries" "$T/vars" "$T/boot"
    echo SHIM-FEDORA >"$T/lib/shimx64.efi"
    echo MOKMANAGER >"$T/lib/mmx64.efi"
    if [[ ${1-} == unsigned ]]; then echo 'SDBOOT #### LoaderInfo: systemd-boot 262' >"$T/lib/systemd-bootx64.efi"
    else echo 'SDBOOT #### LoaderInfo: systemd-boot 262 SIGNED-BY-LUXOS LUXOS-CERT-DER' >"$T/lib/systemd-bootx64.efi"; fi
    echo PEM >"$T/share/luxos-secureboot.pem"
    printf 'LUXOS-CERT-DER' >"$T/share/luxos-secureboot.cer"
    # systemd-boot z bootctl install: prima cesta i zalozni BOOTX64.EFI
    echo 'OLD #### LoaderInfo: systemd-boot 257' >"$T/esp/EFI/systemd/systemd-bootx64.efi"
    cp "$T/esp/EFI/systemd/systemd-bootx64.efi" "$T/esp/EFI/BOOT/BOOTX64.EFI"
    printf 'title LuxOS\nlinux /vmlinuz-linux-luxos\n' >"$T/esp/loader/entries/luxos.conf"
    : >"$T/efibootmgr.out"
}
export LUXOS_SB_I18N=/nonexistent
export LUXOS_SB_LIB=$T/lib LUXOS_SB_SHARE=$T/share LUXOS_SB_EFIVARS=$T/vars LUXOS_SB_STATE=$T/state \
       LUXOS_SB_BOOT=$T/boot LUXOS_SB_DKMS_KEY=$T/dkms-mok.pub TEST_ESP=$T/esp
efivar() {  # efivar NAZEV-GUID BAJTY... | efivar_utf16 NAZEV-GUID TEXT
    printf '\x07\x00\x00\x00' >"$T/vars/$1"; shift_name=$1; shift
    local b; for b in "$@"; do printf "\\x$b" >>"$T/vars/$shift_name"; done
}
efivar_utf16() { { printf '\x07\x00\x00\x00'; printf '%s\0' "$2" | iconv -f UTF-8 -t UTF-16LE; } >"$T/vars/$1"; }
LOADER=4a67b082-0a4c-41cf-b6c7-440b29bb8c4f GLOBAL=8be4df61-93ca-11d2-aa0d-00e098032b8c

echo "## Bez UEFI, bez systemd-boot, nepodepsany systemd-boot: nic se nemeni"
setup; rm -rf "$T/vars"
out=$(LUXOS_SB_EFIVARS=$T/novars "$BIN" sync 2>&1); rc=$?
expect "BIOS: kod 0 a zprava" bash -c "[[ $rc == 0 && '$out' == *'Not started in UEFI mode'* ]]"
setup unsigned
out=$("$BIN" sync 2>&1); rc=$?
expect "nepodepsany systemd-boot: kod 0, zprava" bash -c "[[ $rc == 0 && '$out' == *'not signed'* ]]"
expect "nepodepsany: ESP beze zmeny (zadny EFI/LuxOS)" test ! -e "$T/esp/EFI/LuxOS"
expect "nepodepsany: BOOTX64.EFI beze zmeny" grep -q 'OLD' "$T/esp/EFI/BOOT/BOOTX64.EFI"
expect "nepodepsany: zadna polozka UEFI" test ! -s "$T/efibootmgr.log"
setup; echo 'SDBOOT #### LoaderInfo: systemd-boot 262 SIGNED-BY-LUXOS (cizi koren v podpisu)' >"$T/lib/systemd-bootx64.efi"
out=$("$BIN" sync 2>&1)
expect "sbverify OK, ale certifikat LuxOS v podpisu neni: bere se jako nepodepsany" \
    bash -c "[[ '$out' == *'not signed'* && ! -e '$T/esp/EFI/LuxOS' ]]"
setup; rm -f "$T/esp/loader/entries/luxos.conf"
out=$("$BIN" sync 2>&1)
expect "jiny zavadec nez systemd-boot LuxOS: nic" bash -c "[[ '$out' == *'does not start with systemd-boot'* && ! -e '$T/esp/EFI/LuxOS' ]]"

echo "## Instalace na ESP"
setup
out=$("$BIN" sync 2>&1); rc=$?
expect "kod 0" test "$rc" = 0
expect "EFI/LuxOS/shimx64.efi = shim" cmp -s "$T/lib/shimx64.efi" "$T/esp/EFI/LuxOS/shimx64.efi"
expect "EFI/LuxOS/mmx64.efi = MokManager" cmp -s "$T/lib/mmx64.efi" "$T/esp/EFI/LuxOS/mmx64.efi"
expect "EFI/LuxOS/grubx64.efi = podepsany systemd-boot" cmp -s "$T/lib/systemd-bootx64.efi" "$T/esp/EFI/LuxOS/grubx64.efi"
expect "certifikat pro Enroll key from disk" cmp -s "$T/share/luxos-secureboot.cer" "$T/esp/EFI/LuxOS/luxos-secureboot.cer"
expect "zalozni BOOTX64.EFI (byl systemd-boot) = shim" cmp -s "$T/lib/shimx64.efi" "$T/esp/EFI/BOOT/BOOTX64.EFI"
expect "zalozni grubx64.efi a mmx64.efi" bash -c "cmp -s '$T/lib/systemd-bootx64.efi' '$T/esp/EFI/BOOT/grubx64.efi' && cmp -s '$T/lib/mmx64.efi' '$T/esp/EFI/BOOT/mmx64.efi'"
expect "prima cesta EFI/systemd zustala (zaloha bez Secure Boot)" grep -q OLD "$T/esp/EFI/systemd/systemd-bootx64.efi"
expect "zadne docasne soubory .luxos-new" bash -c "! find '$T/esp' -name '*.luxos-new' | grep -q ."
out2=$("$BIN" sync 2>&1)
expect "druhe spusteni: nic nezapise (zadna zprava o zmene)" bash -c "[[ '$out2' != *updated* && '$out2' != *Fallback* ]]"
echo 'SDBOOT #### LoaderInfo: systemd-boot 263 SIGNED-BY-LUXOS LUXOS-CERT-DER' >"$T/lib/systemd-bootx64.efi"
"$BIN" sync --quiet >/dev/null 2>&1
expect "novy systemd-boot v baliku: obe kopie aktualizovane" bash -c "grep -q 263 '$T/esp/EFI/LuxOS/grubx64.efi' && grep -q 263 '$T/esp/EFI/BOOT/grubx64.efi'"

setup; mkdir -p "$T/esp/EFI/luxos"; rmdir "$T/esp/EFI/luxos" 2>/dev/null
mv "$T/esp/EFI/BOOT" "$T/esp/EFI/Boot"; mv "$T/esp/EFI/Boot/BOOTX64.EFI" "$T/esp/EFI/Boot/bootx64.efi"
"$BIN" sync >/dev/null 2>&1
expect "FAT bez ohledu na velikost pismen: EFI/Boot/bootx64.efi nahrazen, zadny druhy adresar" \
    bash -c "cmp -s '$T/lib/shimx64.efi' '$T/esp/EFI/Boot/bootx64.efi' && [[ ! -e '$T/esp/EFI/BOOT' ]]"

setup; echo 'Windows Boot Manager bootmgfw' >"$T/esp/EFI/BOOT/BOOTX64.EFI"
"$BIN" sync >/dev/null 2>&1
expect "cizi BOOTX64.EFI (Windows/jiny shim) se neprepisuje" grep -q 'Windows Boot Manager' "$T/esp/EFI/BOOT/BOOTX64.EFI"
expect "... a do EFI/BOOT se nic nepridava" bash -c "[[ ! -e '$T/esp/EFI/BOOT/grubx64.efi' && ! -e '$T/esp/EFI/BOOT/mmx64.efi' ]]"
expect "... ale EFI/LuxOS je nainstalovany" test -f "$T/esp/EFI/LuxOS/shimx64.efi"

setup; rm -f "$T/esp/EFI/BOOT/BOOTX64.EFI"
"$BIN" sync >/dev/null 2>&1
expect "chybejici zalozni zavadec: doplneny shim" cmp -s "$T/lib/shimx64.efi" "$T/esp/EFI/BOOT/BOOTX64.EFI"

setup; rm -f "$T/esp/loader/entries/luxos.conf"; printf 'title LuxOS\n' >"$T/esp/loader/entries/luxos-1a2b3c4d.conf"
"$BIN" sync --esp "$T/esp" --no-nvram >/dev/null 2>&1
expect "sdileny ESP (luxos-ID.conf), --esp --no-nvram (instalator v chrootu): ESP ano" test -f "$T/esp/EFI/LuxOS/grubx64.efi"
expect "... polozky UEFI ne" test ! -s "$T/efibootmgr.log"

echo "## Polozky UEFI"
setup
cat >"$T/efibootmgr.out" <<'EOF'
BootCurrent: 0003
BootOrder: 0003,0000,0001
Boot0000* Windows Boot Manager	HD(1,GPT,AAAA-1111,0x800,0x32000)/File(\EFI\Microsoft\Boot\bootmgfw.efi)
Boot0001* UEFI USB	PciRoot(0x0)/Pci(0x14,0x0)
Boot0003* LuxOS	HD(1,GPT,aaaa-1111,0x800,0x32000)/File(\EFI\systemd\systemd-bootx64.efi)
EOF
"$BIN" sync >/dev/null 2>&1
expect "chybi polozka shim: efibootmgr --create LuxOS -> \\EFI\\LuxOS\\shimx64.efi na disku a oddilu ESP" \
    grep -qF 'efibootmgr -q --create --disk /dev/nvme0n1 --part 1 --label LuxOS --loader \EFI\LuxOS\shimx64.efi --unicode' "$T/efibootmgr.log"
expect "stara prima polozka se pred prvnim startem pres shim nemaze" bash -c "! grep -q -- '-B' '$T/efibootmgr.log'"

setup
cat >"$T/efibootmgr.out" <<'EOF'
BootCurrent: 0004
BootOrder: 0004,0003,0000,0005,0006
Boot0000* Windows Boot Manager	HD(1,GPT,aaaa-1111,0x800,0x32000)/File(\EFI\Microsoft\Boot\bootmgfw.efi)
Boot0003* LuxOS	HD(1,GPT,aaaa-1111,0x800,0x32000)/File(\EFI\systemd\systemd-bootx64.efi)
Boot0004* LuxOS	HD(1,GPT,AAAA-1111,0x800,0x32000)/File(\EFI\LuxOS\shimx64.efi)
Boot0005* Linux Boot Manager	HD(1,GPT,aaaa-1111,0x800,0x32000)/File(\EFI\systemd\systemd-bootx64.efi)
Boot0006* LuxOS	HD(1,GPT,bbbb-2222,0x800,0x32000)/File(\EFI\systemd\systemd-bootx64.efi)
EOF
efivar_utf16 "LoaderImageIdentifier-$LOADER" '\EFI\systemd\systemd-bootx64.efi'
"$BIN" sync >/dev/null 2>&1
expect "start primo (ne pres shim): nic se nemaze ani nepridava" bash -c "! grep -qE -- '-B|--create' '$T/efibootmgr.log'"
: >"$T/efibootmgr.log"
efivar_utf16 "LoaderImageIdentifier-$LOADER" '\EFI\LuxOS\grubx64.efi'
out=$("$BIN" sync 2>&1)
expect "po startu pres shim: smazana stara prima polozka LuxOS (Boot0003)" grep -qF 'efibootmgr -q -B -b 0003' "$T/efibootmgr.log"
expect "... polozka shim, Windows, cizi systemd-boot (Linux Boot Manager) a LuxOS na jinem disku zustavaji" \
    bash -c "! grep -qE -- '-B -b (0004|0000|0005|0006)' '$T/efibootmgr.log'"
expect "... zadna nova polozka" bash -c "! grep -q -- '--create' '$T/efibootmgr.log'"
: >"$T/efibootmgr.log"
efivar_utf16 "LoaderImageIdentifier-$LOADER" '/EFI/BOOT/grubx64.efi'
"$BIN" sync >/dev/null 2>&1
expect "start zaloznim shim (EFI/BOOT, lomitka /): taky uklid" grep -qF -- '-B -b 0003' "$T/efibootmgr.log"

echo "## Zapis klice (enroll), stav"
setup
if [[ $EUID == 0 ]]; then
    ok "enroll (bezi jako root - kontrola roota se preskakuje)"
else
    out=$("$BIN" enroll 2>&1); rc=$?
    expect "enroll bez roota: chyba se zpravou" bash -c "[[ $rc != 0 && '$out' == *'run as root'* ]]"
fi
# zbytek enroll jako "root": EUID nejde zmenit, kontrolu obejde kopie skriptu
sed 's/\[\[ \$EUID == 0 \]\] || die/true || die/' "$BIN" >"$T/sb-root"; chmod +x "$T/sb-root"
echo DKMSKEY >"$T/dkms-mok.pub"
out=$("$T/sb-root" enroll 2>&1); rc=$?
pin=$(cat "$T/state/enroll-pin" 2>/dev/null)
expect "enroll: kod 0" test "$rc" = 0
expect "jednorazove heslo = 8 cislic (stejne na kazde klavesnici v MokManageru)" bash -c "[[ '$pin' =~ ^[0-9]{8}$ ]]"
expect "heslo jen pro roota (0600)" test "$(stat -c %a "$T/state/enroll-pin")" = 600
expect "heslo se vypise s postupem" bash -c "[[ '$out' == *'Password: $pin'* && '$out' == *'Enroll MOK'* ]]"
expect "import: klic LuxOS i klic DKMS v jedne zadosti" bash -c "grep -qxF '$T/share/luxos-secureboot.cer' '$T/mok.new' && grep -qxF '$T/dkms-mok.pub' '$T/mok.new'"
expect "heslo ne v argumentech procesu (jen hash ze stdin)" bash -c "! grep -q '$pin' '$T/mokutil.log' && grep -q 'hash-of-$pin' '$T/hash.used'"
expect "MokManager ceka 60 s misto 10 s (mokutil --timeout 60)" grep -qx 'mokutil --timeout 60' "$T/mokutil.log"
expect "v souboru s hashem jen hash (bez vyzev mokutil)" bash -c "[[ \$(cat '$T/hash.used') == '\$6\$salt\$hash-of-'$pin ]]"
out=$("$T/sb-root" status 2>&1)
expect "status: zapis ceka + heslo znovu" bash -c "[[ '$out' == *'luxos_key=pending'* && '$out' == *'enroll_password=$pin'* ]]"
"$BIN" sync >/dev/null 2>&1
expect "sync behem cekajici zadosti: heslo zustava" test -f "$T/state/enroll-pin"
echo "$T/share/luxos-secureboot.cer" >"$T/mok.enrolled"
out=$("$T/sb-root" status 2>&1)
expect "klic LuxOS uz zapsany, ceka jen klic DKMS: status ukaze heslo" \
    bash -c "[[ '$out' == *luxos_key=enrolled* && '$out' == *enroll_pending=yes* && '$out' == *enroll_password=$pin* ]]"
printf '%s\n%s\n' "$T/share/luxos-secureboot.cer" "$T/dkms-mok.pub" >"$T/mok.enrolled"; rm -f "$T/mok.new"
out=$("$T/sb-root" enroll 2>&1)
expect "uz zapsano: nic dalsiho, zprava" bash -c "[[ '$out' == *'already enrolled'* ]] && ! grep -q -- '--import' <(tail -n 3 '$T/mokutil.log')"
"$BIN" sync >/dev/null 2>&1
expect "sync po zapsani: jednorazove heslo smazane" test ! -e "$T/state/enroll-pin"
efivar "SecureBoot-$GLOBAL" 01; efivar "SetupMode-$GLOBAL" 00
efivar_utf16 "LoaderImageIdentifier-$LOADER" '\EFI\LuxOS\grubx64.efi'
echo 'VMLINUZ SIGNED-BY-LUXOS LUXOS-CERT-DER' >"$T/boot/vmlinuz-linux-luxos"
out=$("$BIN" status 2>&1)
expect "status: secure_boot=enabled, boot_path=shim, kernel=signed, loader=installed, klic enrolled" bash -c "[[ '$out' == *secure_boot=enabled* && '$out' == *boot_path=shim* && '$out' == *kernel=signed* && '$out' == *loader=installed* && '$out' == *luxos_key=enrolled* ]]"
efivar "SecureBoot-$GLOBAL" 00
expect "status: secure_boot=disabled" bash -c "'$BIN' status | grep -qx secure_boot=disabled"
efivar "SetupMode-$GLOBAL" 01
expect "status: setup mode" bash -c "'$BIN' status | grep -qx secure_boot=setup"
out=$(LUXOS_SB_EFIVARS=$T/novars "$BIN" status)
expect "status bez UEFI: firmware=bios" bash -c "[[ '$out' == *firmware=bios* ]]"

echo
echo "luxos-secureboot: $NPASS ok, $NFAIL failed"
exit "$NFAIL"
