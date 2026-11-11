#!/bin/bash
# luxos-secureboot - ESP, zalozni zavadec, polozky UEFI, zapis klice (bez roota, bez skutecnych EFI promennych:
# efibootmgr, mokutil, sbverify, bootctl, findmnt, lsblk, systemd-detect-virt a notify-send jsou nahrazene).
# efibootmgr je model NVRAM se stavem (polozky, BootOrder, BootNext, BootCurrent) a "firmware" (fw_boot)
# simuluje start: BootNext, pak BootOrder, a vlastni hlavu firmwaru - Acer/Insyde (polozka "Linpus lite"
# pro \EFI\Boot\grubx64.efi na prvnim miste), HP/Lenovo (Windows Boot Manager zase prvni), firmware, ktery
# zapis BootOrder ignoruje, ale BootNext dodrzi. Skutecny podpis a start se Secure Boot overuje test ve VM
# (docs/proposals/secure-boot.md, Testy).
#
#   packages/luxos-secureboot/tests/test-luxos-secureboot.sh   (ok/FAIL, navratovy kod = pocet chyb)
set -uo pipefail
HERE=${TEST_HERE:-$(cd "$(dirname "$0")" && pwd)}
BIN=$(cd "$HERE/../files" && pwd)/luxos-secureboot
T=$(mktemp -d "${TMPDIR:-/tmp}/luxos-sb-test.XXXXXX")
trap 'chmod -R u+rwx "$T" 2>/dev/null; [[ -n ${KEEP-} ]] || rm -rf "$T"' EXIT
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
# Model NVRAM: $T/nv/entries (CISLO|NAZEV|CESTA), order, next, current; ignore-order = firmware zapis
# BootOrder "prijme", ale nezmeni; fail-create = zalozeni polozky selze
cat >"$M/efibootmgr" <<'EOF'
#!/bin/bash
NV=$T/nv
echo "efibootmgr $*" >>"$T/efibootmgr.log"
show=0 o="" nx="" del=0 num="" create=0 part=1 label="" loader=""
while (($#)); do
    case $1 in
        -v) show=1 ;; -q|-u|--unicode) ;; -N) rm -f "$NV/next" ;;
        -o) o=$2; shift ;; -n) nx=$2; shift ;; -B) del=1 ;; -b) num=$2; shift ;;
        -c|--create) create=1 ;; -d|--disk) shift ;; -p|--part) part=$2; shift ;;
        -L|--label) label=$2; shift ;; -l|--loader) loader=$2; shift ;;
        *) echo "efibootmgr mock: unknown $1" >&2; exit 2 ;;
    esac
    shift
done
order=$(cat "$NV/order" 2>/dev/null)
if ((create)); then
    [[ -f $NV/fail-create ]] && exit 5
    for i in $(seq 0 255); do n=$(printf '%04X' "$i"); grep -q "^$n|" "$NV/entries" || break; done
    echo "$n|$label|HD($part,GPT,$TEST_PARTUUID,0x800,0x200000)/$loader" >>"$NV/entries"
    echo "$n${order:+,$order}" >"$NV/order"
fi
if ((del)); then
    grep -q "^$num|" "$NV/entries" || exit 3
    grep -v "^$num|" "$NV/entries" >"$NV/e.new"; mv "$NV/e.new" "$NV/entries"
    sed -e "s/\(^\|,\)$num\(,\|$\)/\1\2/; s/,,/,/; s/^,//; s/,$//" <<<"$order" >"$NV/order"
fi
[[ -n $o && ! -f $NV/ignore-order ]] && echo "$o" >"$NV/order"
[[ -n $nx ]] && echo "$nx" >"$NV/next"
if ((show)); then
    [[ -s $NV/current ]] && echo "BootCurrent: $(cat "$NV/current")"
    [[ -s $NV/next ]] && echo "BootNext: $(cat "$NV/next")"
    echo "Timeout: 0 seconds"
    echo "BootOrder: $(cat "$NV/order")"
    while IFS='|' read -r n l p; do printf 'Boot%s* %s\t%s\n' "$n" "$l" "$p"; done <"$NV/entries"
fi
exit 0
EOF
# Plny ESP: $T/esp-avail = volne bajty pro df (jinak 1 GB); $T/cp-enospc = cp do ESP zapise jen tolik
# bajtu, kolik je v souboru (prazdny = 0), a skonci "No space left on device" - presne jako na plnem FAT
cat >"$M/df" <<'EOF'
#!/bin/bash
# jako skutecny df: -P a --output nejdou spolu
[[ " $* " == *" -P "* && " $* " == *--output* ]] && { echo "df: options -P and --output are mutually exclusive" >&2; exit 1; }
echo "Avail"; if [[ -f $T/esp-avail ]]; then cat "$T/esp-avail"; else echo 1073741824; fi
EOF
cat >"$M/cp" <<'EOF'
#!/bin/bash
args=(); for a; do [[ $a == -- ]] || args+=("$a"); done
dst=${args[-1]}
if [[ -f $T/cp-enospc && $dst == "$T/esp/"* ]]; then
    n=$(cat "$T/cp-enospc"); head -c "${n:-0}" "${args[-2]}" >"$dst"
    echo "cp: error writing '$dst': No space left on device" >&2; exit 1
fi
exec /usr/bin/cp "$@"
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
cat >"$M/systemd-detect-virt" <<'EOF'
#!/bin/bash
[[ -f $T/in-chroot ]]
EOF
cat >"$M/notify-send" <<'EOF'
#!/bin/bash
echo "notify-send $*" >>"$T/notify.log"
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
LOADER=4a67b082-0a4c-41cf-b6c7-440b29bb8c4f GLOBAL=8be4df61-93ca-11d2-aa0d-00e098032b8c
SHIM_GUID=605dab50-e046-4300-abb6-3dd810dd8b23
setup() {  # setup [unsigned|nofallback]
    chmod -R u+rwx "$T" 2>/dev/null
    rm -rf "${T:?}/lib" "$T/share" "$T/esp" "$T/vars" "$T/state" "$T/run" "$T/nv" "$T/ustate" "$T/boot" "$T"/*.log \
        "$T/mok."* "$T/hash.used" "$T/in-chroot" "$T/esp-avail" "$T/cp-enospc"
    mkdir -p "$T/lib" "$T/share" "$T/esp/EFI/systemd" "$T/esp/EFI/BOOT" "$T/esp/loader/entries" "$T/vars" "$T/boot" "$T/nv"
    echo "MZ SHIM-FEDORA $(head -c 3000 /dev/zero | tr "\0" s)" >"$T/lib/shimx64.efi"
    echo "MZ MOKMANAGER $(head -c 2000 /dev/zero | tr "\0" m)" >"$T/lib/mmx64.efi"
    if [[ ${1-} != nofallback ]]; then
        echo "MZ FALLBACK" >"$T/lib/fbx64.efi"
        printf 'CSV shimx64.efi,LuxOS' >"$T/lib/BOOTX64.CSV"
    fi
    if [[ ${1-} == unsigned ]]; then echo 'MZ SDBOOT #### LoaderInfo: systemd-boot 262' >"$T/lib/systemd-bootx64.efi"
    else echo 'MZ SDBOOT #### LoaderInfo: systemd-boot 262 SIGNED-BY-LUXOS LUXOS-CERT-DER' >"$T/lib/systemd-bootx64.efi"; fi
    echo PEM >"$T/share/luxos-secureboot.pem"
    printf 'LUXOS-CERT-DER' >"$T/share/luxos-secureboot.cer"
    # systemd-boot z bootctl install: prima cesta i zalozni BOOTX64.EFI
    echo 'MZ OLD #### LoaderInfo: systemd-boot 257' >"$T/esp/EFI/systemd/systemd-bootx64.efi"
    cp "$T/esp/EFI/systemd/systemd-bootx64.efi" "$T/esp/EFI/BOOT/BOOTX64.EFI"
    printf 'title LuxOS\nlinux /vmlinuz-linux-luxos\n' >"$T/esp/loader/entries/luxos.conf"
    : >"$T/nv/entries"; : >"$T/nv/order"; : >"$T/efibootmgr.log"
}
export LUXOS_SB_I18N=/nonexistent
export LUXOS_SB_LIB=$T/lib LUXOS_SB_SHARE=$T/share LUXOS_SB_EFIVARS=$T/vars LUXOS_SB_STATE=$T/state \
       LUXOS_SB_BOOT=$T/boot LUXOS_SB_DKMS_KEY=$T/dkms-mok.pub TEST_ESP=$T/esp LUXOS_SB_RUN=$T/run \
       LUXOS_SB_USER_STATE=$T/ustate
efivar() {  # efivar NAZEV-GUID BAJTY...
    local name=$1 b; shift
    printf '\x07\x00\x00\x00' >"$T/vars/$name"
    for b in "$@"; do printf "\\x$b" >>"$T/vars/$name"; done
}
efivar_utf16() { { printf '\x07\x00\x00\x00'; printf '%s\0' "$2" | iconv -f UTF-8 -t UTF-16LE; } >"$T/vars/$1"; }

# nv_load < vypis efibootmgr -v  -> model NVRAM
nv_load() {
    local l n rest
    : >"$T/nv/entries"; : >"$T/nv/order"; rm -f "$T/nv/next" "$T/nv/current"
    while IFS= read -r l; do
        case $l in
            BootCurrent:*) echo "${l#BootCurrent: }" >"$T/nv/current" ;;
            BootNext:*) echo "${l#BootNext: }" >"$T/nv/next" ;;
            BootOrder:*) echo "${l#BootOrder: }" >"$T/nv/order" ;;
            Boot[0-9A-F][0-9A-F][0-9A-F][0-9A-F]*)
                n=${l:4:4}; rest=${l:10}
                printf '%s|%s|%s\n' "$n" "${rest%%$'\t'*}" "${rest#*$'\t'}" >>"$T/nv/entries" ;;
        esac
    done
}
nv_order() { cat "$T/nv/order"; }
nv_next() { cat "$T/nv/next" 2>/dev/null; }
nv_has() { grep -q "^$1|" "$T/nv/entries"; }
nv_path() { grep "^$1|" "$T/nv/entries" | cut -d'|' -f3; }

# fw_boot [acer] [windows-first] - "firmware" nastartuje: vlastni hlava firmwaru, pak BootNext (jednorazove),
# jinak prvni polozka BootOrder. Podle spustene polozky nastavi promenne, ktere by zapsal shim a systemd-boot.
# FW_MOKMANAGER=1, kdyz by se ukazal MokManager (start pres shim a cekajici zadost).
fw_boot() {
    local q cur p n
    for q in "$@"; do
        case $q in
            acer)  # Insyde/Acer: kazdy \EFI\Boot\grubx64.efi dostane polozku "Linpus lite" na prvnim miste
                if [[ -n $(find "$T/esp/EFI" -maxdepth 2 -ipath '*/boot/grubx64.efi' 2>/dev/null) ]] &&
                        ! grep -qi 'efi\\boot\\grubx64.efi' "$T/nv/entries"; then
                    for n in 0001 0002 0005 0007 0008 0009; do nv_has "$n" || break; done
                    echo "$n|Linpus lite|HD(1,GPT,$TEST_PARTUUID,0x800,0x200000)/\\EFI\\Boot\\grubx64.efi RC" >>"$T/nv/entries"
                    echo "$n,$(nv_order)" >"$T/nv/order"
                fi ;;
            windows-first)  # HP/Lenovo (po aktualizaci Windows): Windows Boot Manager zase prvni
                n=$(grep '|Windows Boot Manager|' "$T/nv/entries" | head -n1 | cut -d'|' -f1)
                [[ -n $n ]] && echo "$n,$(nv_order | sed "s/\(^\|,\)$n\(,\|$\)/\1\2/; s/,,/,/; s/^,//; s/,$//")" >"$T/nv/order" ;;
        esac
    done
    if [[ -s $T/nv/next ]]; then cur=$(nv_next); rm -f "$T/nv/next"; else cur=$(nv_order | cut -d, -f1); fi
    echo "$cur" >"$T/nv/current"
    p=$(nv_path "$cur" | tr '[:upper:]' '[:lower:]')
    rm -f "$T/vars/SbatLevelRT-$SHIM_GUID" "$T/vars/LoaderImageIdentifier-$LOADER"
    FW_MOKMANAGER=0
    case $p in
        *'\efi\luxos\shimx64.efi'*)
            efivar "SbatLevelRT-$SHIM_GUID" 73
            [[ -s $T/mok.new ]] && FW_MOKMANAGER=1
            efivar_utf16 "LoaderImageIdentifier-$LOADER" '\EFI\LuxOS\grubx64.efi' ;;
        *'\efi\boot\grubx64.efi'*) efivar_utf16 "LoaderImageIdentifier-$LOADER" '\EFI\Boot\grubx64.efi' ;;
        *systemd-bootx64.efi*) efivar_utf16 "LoaderImageIdentifier-$LOADER" '\EFI\systemd\systemd-bootx64.efi' ;;
    esac
}
# zapis klice v MokManageru potvrzen
mok_confirm() { [[ -s $T/mok.new ]] && cat "$T/mok.new" >>"$T/mok.enrolled"; rm -f "$T/mok.new"; }

# Stav EFI oddilu po luxos-secureboot 1.0.0-1: EFI/BOOT = shim + kopie systemd-boot jako grubx64.efi
old_layout() {
    mkdir -p "$T/esp/EFI/LuxOS"
    cp "$T/lib/shimx64.efi" "$T/lib/mmx64.efi" "$T/esp/EFI/LuxOS/"
    cp "$T/lib/systemd-bootx64.efi" "$T/esp/EFI/LuxOS/grubx64.efi"
    cp "$T/share/luxos-secureboot.cer" "$T/esp/EFI/LuxOS/"
    cp "$T/lib/shimx64.efi" "$T/esp/EFI/BOOT/BOOTX64.EFI"
    cp "$T/lib/systemd-bootx64.efi" "$T/esp/EFI/BOOT/grubx64.efi"
    cp "$T/lib/mmx64.efi" "$T/esp/EFI/BOOT/mmx64.efi"
}

# Vypis z Aceru majitele (Insyde) po luxos-secureboot enroll: start sel pres starou primou polozku 0000,
# "Linpus lite" (firmware ji zalozil pro EFI/BOOT/grubx64.efi) prvni, polozka shim 0003 az za USB
ACER='BootCurrent: 0000
Timeout: 0 seconds
BootOrder: 0002,0000,2001,0003,2002,2003
Boot0000* LuxOS	HD(1,GPT,aaaa-1111,0x800,0x200000)/\EFI\systemd\systemd-bootx64.efi
Boot0002* Linpus lite	HD(1,GPT,aaaa-1111,0x800,0x200000)/\EFI\Boot\grubx64.efi RC
Boot0003* LuxOS	HD(1,GPT,aaaa-1111,0x800,0x200000)/\EFI\LuxOS\shimx64.efi
Boot0004* Windows Boot Manager	HD(1,GPT,cccc-3333,0x800,0x32000)/\EFI\Microsoft\Boot\bootmgfw.efi
Boot0006* Windows Boot Manager	HD(2,GPT,dddd-4444,0x800,0x32000)/\EFI\Microsoft\Boot\bootmgfw.efi
Boot2001* EFI USB Device	RC
Boot2002* EFI DVD/CDROM	RC
Boot2003* EFI Network	RC'

# zbytek "jako root": EUID nejde zmenit, kontrolu obejde kopie skriptu
sed 's/\[\[ \$EUID == 0 \]\] || die/true || die/' "$BIN" >"$T/sb-root"; chmod +x "$T/sb-root"

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
setup; echo 'MZ SDBOOT #### LoaderInfo: systemd-boot 262 SIGNED-BY-LUXOS (cizi koren v podpisu)' >"$T/lib/systemd-bootx64.efi"
out=$("$BIN" sync 2>&1)
expect "sbverify OK, ale certifikat LuxOS v podpisu neni: bere se jako nepodepsany" \
    bash -c "[[ '$out' == *'not signed'* && ! -e '$T/esp/EFI/LuxOS' ]]"
setup; rm -f "$T/esp/loader/entries/luxos.conf"
out=$("$BIN" sync 2>&1)
expect "jiny zavadec nez systemd-boot LuxOS: nic" bash -c "[[ '$out' == *'does not start with systemd-boot'* && ! -e '$T/esp/EFI/LuxOS' ]]"
setup; rm -f "$T/lib/mmx64.efi"
out=$("$BIN" sync 2>&1); rc=$?
expect "chybi soubor balicku: chyba (kod != 0)" bash -c "[[ $rc != 0 && '$out' == *missing* ]]"

echo "## Instalace na ESP"
setup
out=$("$BIN" sync 2>&1); rc=$?
expect "kod 0" test "$rc" = 0
expect "EFI/LuxOS/shimx64.efi = shim" cmp -s "$T/lib/shimx64.efi" "$T/esp/EFI/LuxOS/shimx64.efi"
expect "EFI/LuxOS/mmx64.efi = MokManager" cmp -s "$T/lib/mmx64.efi" "$T/esp/EFI/LuxOS/mmx64.efi"
expect "EFI/LuxOS/grubx64.efi = podepsany systemd-boot" cmp -s "$T/lib/systemd-bootx64.efi" "$T/esp/EFI/LuxOS/grubx64.efi"
expect "certifikat pro Enroll key from disk" cmp -s "$T/share/luxos-secureboot.cer" "$T/esp/EFI/LuxOS/luxos-secureboot.cer"
expect "EFI/LuxOS/BOOTX64.CSV pro fallback" cmp -s "$T/lib/BOOTX64.CSV" "$T/esp/EFI/LuxOS/BOOTX64.CSV"
expect "zalozni BOOTX64.EFI (byl systemd-boot) = shim" cmp -s "$T/lib/shimx64.efi" "$T/esp/EFI/BOOT/BOOTX64.EFI"
expect "zalozni fbx64.efi a mmx64.efi" bash -c "cmp -s '$T/lib/fbx64.efi' '$T/esp/EFI/BOOT/fbx64.efi' && cmp -s '$T/lib/mmx64.efi' '$T/esp/EFI/BOOT/mmx64.efi'"
expect "v EFI/BOOT zadny grubx64.efi (Acer pro nej zaklada polozku Linpus lite)" test ! -e "$T/esp/EFI/BOOT/grubx64.efi"
expect "prima cesta EFI/systemd zustala (zaloha bez Secure Boot)" grep -q OLD "$T/esp/EFI/systemd/systemd-bootx64.efi"
expect "zadne docasne soubory .luxos-new" bash -c "! find '$T/esp' -name '*.luxos-new' | grep -q ."
out2=$("$BIN" sync 2>&1)
expect "druhe spusteni: nic nezapise (zadna zprava o zmene)" bash -c "[[ '$out2' != *updated* && '$out2' != *Fallback* ]]"
echo 'MZ SDBOOT #### LoaderInfo: systemd-boot 263 SIGNED-BY-LUXOS LUXOS-CERT-DER' >"$T/lib/systemd-bootx64.efi"
"$BIN" sync --quiet >/dev/null 2>&1
expect "novy systemd-boot v baliku: EFI/LuxOS aktualizovany, EFI/BOOT dal bez grubx64.efi" \
    bash -c "grep -q 263 '$T/esp/EFI/LuxOS/grubx64.efi' && [[ ! -e '$T/esp/EFI/BOOT/grubx64.efi' ]]"

setup; old_layout
out=$("$BIN" sync 2>&1)
expect "prevod z 1.0.0-1: kopie systemd-boot EFI/BOOT/grubx64.efi smazana, fbx64.efi pridany" \
    bash -c "[[ ! -e '$T/esp/EFI/BOOT/grubx64.efi' ]] && cmp -s '$T/lib/fbx64.efi' '$T/esp/EFI/BOOT/fbx64.efi'"
expect "... BOOTX64.EFI dal shim" cmp -s "$T/lib/shimx64.efi" "$T/esp/EFI/BOOT/BOOTX64.EFI"

setup; old_layout; echo 'GRUB of another distribution' >"$T/esp/EFI/BOOT/grubx64.efi"
"$BIN" sync >/dev/null 2>&1
expect "cizi EFI/BOOT/grubx64.efi (ne systemd-boot) se nemaze" grep -q 'another distribution' "$T/esp/EFI/BOOT/grubx64.efi"

setup nofallback
"$BIN" sync >/dev/null 2>&1
expect "balik bez fbx64.efi: zalozni grubx64.efi jako driv (shim ho potrebuje)" \
    bash -c "cmp -s '$T/lib/systemd-bootx64.efi' '$T/esp/EFI/BOOT/grubx64.efi' && [[ ! -e '$T/esp/EFI/BOOT/fbx64.efi' ]]"

setup
mv "$T/esp/EFI/BOOT" "$T/esp/EFI/Boot"; mv "$T/esp/EFI/Boot/BOOTX64.EFI" "$T/esp/EFI/Boot/bootx64.efi"
cp "$T/lib/systemd-bootx64.efi" "$T/esp/EFI/Boot/GRUBX64.EFI"
"$BIN" sync >/dev/null 2>&1
expect "FAT bez ohledu na velikost pismen: EFI/Boot/bootx64.efi nahrazen, GRUBX64.EFI smazany, zadny druhy adresar" \
    bash -c "cmp -s '$T/lib/shimx64.efi' '$T/esp/EFI/Boot/bootx64.efi' && [[ ! -e '$T/esp/EFI/BOOT' && ! -e '$T/esp/EFI/Boot/GRUBX64.EFI' ]]"

setup; echo 'Windows Boot Manager bootmgfw' >"$T/esp/EFI/BOOT/BOOTX64.EFI"
"$BIN" sync >/dev/null 2>&1
expect "cizi BOOTX64.EFI (Windows/jiny shim) se neprepisuje" grep -q 'Windows Boot Manager' "$T/esp/EFI/BOOT/BOOTX64.EFI"
expect "... a do EFI/BOOT se nic nepridava" bash -c "[[ ! -e '$T/esp/EFI/BOOT/grubx64.efi' && ! -e '$T/esp/EFI/BOOT/mmx64.efi' && ! -e '$T/esp/EFI/BOOT/fbx64.efi' ]]"
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
nv_load <<'EOF'
BootCurrent: 0003
BootOrder: 0003,0000,0001
Boot0000* Windows Boot Manager	HD(1,GPT,AAAA-1111,0x800,0x32000)/File(\EFI\Microsoft\Boot\bootmgfw.efi)
Boot0001* UEFI USB	PciRoot(0x0)/Pci(0x14,0x0)
Boot0003* LuxOS	HD(1,GPT,aaaa-1111,0x800,0x32000)/File(\EFI\systemd\systemd-bootx64.efi)
EOF
"$BIN" sync >/dev/null 2>&1
expect "chybi polozka shim: efibootmgr --create LuxOS -> \\EFI\\LuxOS\\shimx64.efi na disku a oddilu ESP" \
    grep -qF 'efibootmgr -q --create --disk /dev/nvme0n1 --part 1 --label LuxOS --loader \EFI\LuxOS\shimx64.efi --unicode' "$T/efibootmgr.log"
expect "... nova polozka prvni, Windows a USB ve stejnem poradi za ni" test "$(nv_order)" = "0002,0003,0000,0001"
expect "... start nesel pres shim: BootNext na novou polozku" test "$(nv_next)" = 0002
expect "stara prima polozka se pred prvnim startem pres shim nemaze" bash -c "! grep -q -- '-B' '$T/efibootmgr.log'"

setup; : >"$T/nv/fail-create"
nv_load <<<"$(grep -v '^Boot0003' <<<"$ACER")"
out=$("$BIN" sync 2>&1); rc=$?
expect "polozku nejde zalozit: kod 0, varovani, poradi beze zmeny" bash -c "[[ $rc == 0 && '$out' == *'could not add'* ]] && ! grep -q -- ' -o ' '$T/efibootmgr.log'"

setup
nv_load <<'EOF'
BootCurrent: 0004
BootOrder: 0004,0003,0000,0005,0006
Boot0000* Windows Boot Manager	HD(1,GPT,aaaa-1111,0x800,0x32000)/File(\EFI\Microsoft\Boot\bootmgfw.efi)
Boot0003* LuxOS	HD(1,GPT,aaaa-1111,0x800,0x32000)/File(\EFI\systemd\systemd-bootx64.efi)
Boot0004* LuxOS	HD(1,GPT,AAAA-1111,0x800,0x32000)/File(\EFI\LuxOS\shimx64.efi)
Boot0005* Linux Boot Manager	HD(1,GPT,aaaa-1111,0x800,0x32000)/File(\EFI\systemd\systemd-bootx64.efi)
Boot0006* LuxOS	HD(1,GPT,bbbb-2222,0x800,0x32000)/File(\EFI\systemd\systemd-bootx64.efi)
EOF
efivar_utf16 "LoaderImageIdentifier-$LOADER" '\EFI\systemd\systemd-bootx64.efi'
echo 0003 >"$T/nv/current"
"$BIN" sync >/dev/null 2>&1
expect "start primo (ne pres shim): nic se nemaze ani nepridava" bash -c "! grep -qE -- '-B|--create' '$T/efibootmgr.log'"
expect "... ale dalsi start pres shim (BootNext)" test "$(nv_next)" = 0004
: >"$T/efibootmgr.log"; rm -f "$T/nv/next"; echo 0004 >"$T/nv/current"
efivar_utf16 "LoaderImageIdentifier-$LOADER" '\EFI\LuxOS\grubx64.efi'; efivar "SbatLevelRT-$SHIM_GUID" 73
"$BIN" sync >/dev/null 2>&1
expect "po startu pres shim: smazana stara prima polozka LuxOS (Boot0003)" grep -qF 'efibootmgr -q -B -b 0003' "$T/efibootmgr.log"
expect "... polozka shim, Windows, cizi systemd-boot (Linux Boot Manager) a LuxOS na jinem disku zustavaji" \
    bash -c "! grep -qE -- '-B -b (0004|0000|0005|0006)' '$T/efibootmgr.log'"
expect "... zadna nova polozka, poradi uz v poradku (zadny zapis), zadny BootNext" \
    bash -c "! grep -qE -- '--create| -o | -n ' '$T/efibootmgr.log'"
setup
nv_load <<<"$(sed 's/^BootCurrent: 0000/BootCurrent: 0007/' <<<"$ACER")"
echo '0007|LuxOS|HD(1,GPT,aaaa-1111,0x800,0x200000)/\EFI\BOOT\BOOTX64.EFI' >>"$T/nv/entries"
efivar_utf16 "LoaderImageIdentifier-$LOADER" '/EFI/BOOT/grubx64.efi'; efivar "SbatLevelRT-$SHIM_GUID" 73
old_layout; "$BIN" sync >/dev/null 2>&1
expect "start zaloznim shim (EFI/BOOT, lomitka /): taky uklid stare prime polozky" grep -qF -- '-B -b 0000' "$T/efibootmgr.log"

echo "## Acer (Insyde): Linpus lite, start mimo shim, MokManager se neukazal"
setup; old_layout; nv_load <<<"$ACER"
efivar_utf16 "LoaderImageIdentifier-$LOADER" '\EFI\systemd\systemd-bootx64.efi'
echo "$T/share/luxos-secureboot.cer" >"$T/mok.new"   # zapis klice uz pripraveny (stary enroll)
out=$("$BIN" status 2>&1)
expect "status (jako u majitele): boot_current=direct, boot_first=other, hint fix-boot" \
    bash -c "[[ '$out' == *boot_current=direct* && '$out' == *boot_first=other* && '$out' == *'hint=The next start will not show the enrollment screen'*'fix-boot'* ]]"
"$BIN" sync >/dev/null 2>&1   # sluzba pri startu / hook po aktualizaci
expect "sync: EFI/BOOT/grubx64.efi pryc" test ! -e "$T/esp/EFI/BOOT/grubx64.efi"
expect "sync: polozka Linpus lite (do prazdna na nasem ESP) smazana" bash -c "! grep -q '^0002|' '$T/nv/entries'"
expect "sync: shim prvni, ostatni ve stejnem poradi (0003,0000,2001,2002,2003)" test "$(nv_order)" = "0003,0000,2001,2002,2003"
expect "sync: Windows (0004, 0006) nedotcene" bash -c "grep -q '^0004|Windows' '$T/nv/entries' && grep -q '^0006|Windows' '$T/nv/entries'"
expect "sync: BootNext = shim (ceka zapis klice, start nesel pres shim)" test "$(nv_next)" = 0003
expect "sync: stara prima polozka 0000 zatim zustava (shim jeste nenastartoval)" bash -c "grep -q '^0000|' '$T/nv/entries'"
rm -f "$T/mok.new"
out=$("$T/sb-root" enroll 2>&1); rc=$?
expect "enroll: kod 0, postup + 'dalsi start pres shim Boot0003'" \
    bash -c "[[ $rc == 0 && '$out' == *'Enroll MOK'* && '$out' == *'next start goes through shim (UEFI boot entry Boot0003'* ]]"
expect "enroll: BootNext = 0003" test "$(nv_next)" = 0003
fw_boot acer
expect "firmware (Acer) nastartoval shim (zadny novy Linpus lite, BootNext)" test "$(cat "$T/nv/current")" = 0003
expect "... a ukazal by se MokManager" test "$FW_MOKMANAGER" = 1
mok_confirm; fw_boot acer
expect "po Reboot v MokManageru: zase shim (prvni v poradi)" test "$(cat "$T/nv/current")" = 0003
: >"$T/efibootmgr.log"; "$BIN" sync >/dev/null 2>&1
expect "po startu pres shim: stara prima polozka 0000 smazana" bash -c "! grep -q '^0000|' '$T/nv/entries'"
expect "... poradi 0003,2001,2002,2003, zadny BootNext" bash -c "[[ \$(cat '$T/nv/order') == 0003,2001,2002,2003 && ! -s '$T/nv/next' ]]"
echo 'VMLINUZ SIGNED-BY-LUXOS LUXOS-CERT-DER' >"$T/boot/vmlinuz-linux-luxos"
efivar "SecureBoot-$GLOBAL" 00; efivar "SetupMode-$GLOBAL" 00
out=$("$BIN" check 2>&1); rc=$?
expect "check: Secure Boot ready (klic, shim, prvni polozka, podepsane jadro), kod 0" \
    bash -c "[[ $rc == 0 && '$out' == *'Secure Boot ready'* ]]"

setup; old_layout; nv_load <<<"$ACER"
efivar_utf16 "LoaderImageIdentifier-$LOADER" '\EFI\systemd\systemd-bootx64.efi'
"$T/sb-root" enroll >/dev/null 2>&1
expect "enroll rovnou na stavu z Aceru (bez predchoziho sync): Linpus pryc, shim prvni, BootNext" \
    bash -c "! grep -q '^0002|' '$T/nv/entries' && [[ \$(cat '$T/nv/order') == 0003,* && \$(cat '$T/nv/next') == 0003 ]]"
fw_boot acer
expect "... dalsi start: shim a MokManager" bash -c "[[ \$(cat '$T/nv/current') == 0003 && $FW_MOKMANAGER == 1 ]]"

echo "## Opravena chyba: prime spusteni EFI/BOOT/grubx64.efi (Linpus lite) nebylo start pres shim"
setup; old_layout; nv_load <<<"$(sed 's/^BootCurrent: 0000/BootCurrent: 0002/' <<<"$ACER")"
efivar_utf16 "LoaderImageIdentifier-$LOADER" '\EFI\Boot\grubx64.efi'   # bez SbatLevelRT: shim nebezel
out=$("$BIN" status 2>&1)
expect "status: boot_path=direct (ne shim)" bash -c "[[ '$out' == *boot_path=direct* ]]"
"$BIN" sync --no-nvram >/dev/null 2>&1; "$BIN" sync >/dev/null 2>&1
expect "sync: stara prima polozka 0000 se nemaze (shim nikdy nenastartoval)" grep -q '^0000|' "$T/nv/entries"

echo "## Firmware, ktery zapis BootOrder ignoruje (BootNext dodrzi)"
setup; old_layout; nv_load <<<"$ACER"; : >"$T/nv/ignore-order"
efivar_utf16 "LoaderImageIdentifier-$LOADER" '\EFI\systemd\systemd-bootx64.efi'
out=$("$BIN" sync 2>&1)
expect "varovani + BootNext na shim" bash -c "[[ '$out' == *'did not accept the new boot order'* && \$(cat '$T/nv/next') == 0003 ]]"
expect "zapamatovano (firmware-quirk)" test -f "$T/state/firmware-quirk"
fw_boot
expect "start: shim (BootNext)" test "$(cat "$T/nv/current")" = 0003
"$BIN" sync >/dev/null 2>&1
expect "start pres shim, ale poradi porad spatne: BootNext znovu" test "$(nv_next)" = 0003
rm -f "$T/nv/next"; : >"$T/efibootmgr.log"
"$BIN" sync --shutdown >/dev/null 2>&1
expect "vypnuti: BootNext na shim (dalsi start zase pres shim)" bash -c "[[ \$(cat '$T/nv/next') == 0003 ]] && ! grep -qE -- ' -o |-B|--create' '$T/efibootmgr.log'"
fw_boot
expect "dalsi start: shim" test "$(cat "$T/nv/current")" = 0003

echo "## HP/Lenovo: firmware dava Windows zase dopredu"
setup
nv_load <<'EOF'
BootCurrent: 0001
BootOrder: 0001,0000
Boot0000* Windows Boot Manager	HD(1,GPT,aaaa-1111,0x800,0x32000)/\EFI\Microsoft\Boot\bootmgfw.efi
Boot0001* LuxOS	HD(1,GPT,aaaa-1111,0x800,0x200000)/\EFI\LuxOS\shimx64.efi
EOF
efivar_utf16 "LoaderImageIdentifier-$LOADER" '\EFI\LuxOS\grubx64.efi'; efivar "SbatLevelRT-$SHIM_GUID" 73
"$BIN" sync >/dev/null 2>&1
expect "vse v poradku: zadny BootNext, poradi beze zmeny" bash -c "[[ ! -s '$T/nv/next' && \$(cat '$T/nv/order') == 0001,0000 ]]"
: >"$T/efibootmgr.log"; "$BIN" sync --shutdown >/dev/null 2>&1
expect "vypnuti na beznem firmwaru: nic se nezapisuje" bash -c "! grep -qE -- ' -o | -n |-B|--create' '$T/efibootmgr.log'"
fw_boot windows-first
expect "firmware dal Windows dopredu: nastartovaly Windows" test "$(cat "$T/nv/current")" = 0000
echo 0001 >"$T/nv/current"   # uzivatel vybral LuxOS v nabidce firmwaru
"$BIN" sync >/dev/null 2>&1
expect "LuxOS: poradi zase shim prvni + zapamatovano, ze firmware poradi meni" \
    bash -c "[[ \$(cat '$T/nv/order') == 0001,0000 && -f '$T/state/firmware-quirk' ]]"
rm -f "$T/nv/next"; "$BIN" sync --shutdown >/dev/null 2>&1
fw_boot windows-first
expect "pak kazde vypnuti BootNext: dalsi start LuxOS i kdyz firmware Windows zase dal dopredu" test "$(cat "$T/nv/current")" = 0001

echo "## Cizi polozky grubx64.efi a jine disky"
setup; old_layout; echo 'GRUB of another distribution' >"$T/esp/EFI/BOOT/grubx64.efi"; nv_load <<<"$ACER"
"$BIN" sync >/dev/null 2>&1
expect "EFI/BOOT/grubx64.efi jineho systemu: jeho polozka (Linpus lite) zustava, shim ale prvni" \
    bash -c "grep -q '^0002|' '$T/nv/entries' && [[ \$(cat '$T/nv/order') == 0003,0002,* ]]"
setup; old_layout
nv_load <<<"$(sed 's/^\(Boot0002\* Linpus lite\tHD(1,GPT,\)aaaa-1111/\1eeee-5555/' <<<"$ACER")"
"$BIN" sync >/dev/null 2>&1
expect "Linpus lite na jinem disku (jiny PARTUUID) se nemaze" grep -q '^0002|' "$T/nv/entries"
setup; old_layout; nv_load <<<"$ACER"; : >"$T/in-chroot"
"$T/sb-root" enroll >/dev/null 2>&1
expect "enroll v chrootu (instalator): zadny zapis polozek UEFI (dela je instalator z live systemu)" \
    bash -c "! grep -qE -- ' -o | -n |-B|--create' '$T/efibootmgr.log'"

echo "## Zapis klice (enroll), stav"
setup
if [[ $EUID == 0 ]]; then
    ok "enroll (bezi jako root - kontrola roota se preskakuje)"
else
    out=$("$BIN" enroll 2>&1); rc=$?
    expect "enroll bez roota: chyba se zpravou" bash -c "[[ $rc != 0 && '$out' == *'run as root'* ]]"
    out=$("$BIN" fix-boot 2>&1); rc=$?
    expect "fix-boot bez roota: chyba se zpravou" bash -c "[[ $rc != 0 && '$out' == *'run as root'* ]]"
fi
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
expect "enroll bez polozky shim: zalozena a nastaveny BootNext" bash -c "[[ \$(cat '$T/nv/next') == 0000 ]] && grep -q 'shimx64' '$T/nv/entries'"
out=$("$T/sb-root" status 2>&1)
expect "status: zapis ceka + heslo znovu" bash -c "[[ '$out' == *'luxos_key=pending'* && '$out' == *'enroll_password=$pin'* ]]"
expect "status: dalsi start pres shim (boot_next=shim), zadna rada fix-boot" bash -c "[[ '$out' == *'boot_next=shim'* && '$out' != *fix-boot* ]]"
"$BIN" sync >/dev/null 2>&1
expect "sync behem cekajici zadosti: heslo zustava" test -f "$T/state/enroll-pin"
expect "stav pro uzivatele (\$RUNDIR/status) bez hesla" bash -c "[[ -f '$T/run/status' ]] && ! grep -q '$pin' '$T/run/status' && grep -q '^loader=installed' '$T/run/status'"
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
efivar_utf16 "LoaderImageIdentifier-$LOADER" '\EFI\LuxOS\grubx64.efi'; efivar "SbatLevelRT-$SHIM_GUID" 73
echo 'VMLINUZ SIGNED-BY-LUXOS LUXOS-CERT-DER' >"$T/boot/vmlinuz-linux-luxos"
out=$("$BIN" status 2>&1)
expect "status: secure_boot=enabled, boot_path=shim, kernel=signed, loader=installed, klic enrolled" bash -c "[[ '$out' == *secure_boot=enabled* && '$out' == *boot_path=shim* && '$out' == *kernel=signed* && '$out' == *loader=installed* && '$out' == *luxos_key=enrolled* ]]"
expect "status: secure_boot_ready=on" bash -c "[[ '$out' == *secure_boot_ready=on* ]]"
efivar "SecureBoot-$GLOBAL" 00
expect "status: secure_boot=disabled" bash -c "'$BIN' status | grep -qx secure_boot=disabled"
efivar "SetupMode-$GLOBAL" 01
expect "status: setup mode" bash -c "'$BIN' status | grep -qx secure_boot=setup"
out=$(LUXOS_SB_EFIVARS=$T/novars "$BIN" status)
expect "status bez UEFI: firmware=bios" bash -c "[[ '$out' == *firmware=bios* ]]"

echo "## Stav bez roota (ESP a /boot cte jen root)"
setup; old_layout
nv_load <<'EOF'
BootCurrent: 0001
BootOrder: 0001,0000
Boot0000* Windows Boot Manager	HD(1,GPT,aaaa-1111,0x800,0x32000)/\EFI\Microsoft\Boot\bootmgfw.efi
Boot0001* LuxOS	HD(1,GPT,aaaa-1111,0x800,0x200000)/\EFI\LuxOS\shimx64.efi
EOF
efivar "SecureBoot-$GLOBAL" 00; efivar "SetupMode-$GLOBAL" 00
efivar_utf16 "LoaderImageIdentifier-$LOADER" '\EFI\LuxOS\grubx64.efi'; efivar "SbatLevelRT-$SHIM_GUID" 73
echo 'VMLINUZ SIGNED-BY-LUXOS LUXOS-CERT-DER' >"$T/boot/vmlinuz-linux-luxos"
echo "$T/share/luxos-secureboot.cer" >"$T/mok.enrolled"
if [[ $EUID == 0 ]]; then
    ok "bez roota (bezi jako root - preskoceno)"
else
    chmod 000 "$T/esp" "$T/boot"
    out=$("$BIN" status 2>&1)
    expect "ESP necitelny, bez stavu ze sluzby: loader=unknown, kernel=unknown (ne 'missing'/'unsigned'), rada sudo" \
        bash -c "[[ '$out' == *loader=unknown* && '$out' == *kernel=unknown* && '$out' != *loader=missing* && '$out' == *'need root'* ]]"
    expect "... polozky UEFI i bez roota: boot_current=shim, boot_first=shim" \
        bash -c "[[ '$out' == *boot_current=shim* && '$out' == *boot_first=shim* ]]"
    chmod 755 "$T/esp" "$T/boot"; "$BIN" sync >/dev/null 2>&1; chmod 000 "$T/esp" "$T/boot"
    out=$("$BIN" status 2>&1)
    expect "se stavem ze sluzby (/run): loader=installed, kernel=signed, secure_boot_ready=yes" \
        bash -c "[[ '$out' == *loader=installed* && '$out' == *kernel=signed* && '$out' == *secure_boot_ready=yes* ]]"
    "$BIN" notify; "$BIN" notify
    expect "notify (relace uzivatele): upozorneni 'Secure Boot ready' prave jednou" \
        bash -c "[[ \$(grep -c 'Secure Boot ready' '$T/notify.log') == 1 ]]"
    chmod 755 "$T/esp" "$T/boot"
fi

echo "## check: pred zapnutim Secure Boot"
setup; old_layout; nv_load <<<"$ACER"
efivar "SecureBoot-$GLOBAL" 00; efivar "SetupMode-$GLOBAL" 00
efivar_utf16 "LoaderImageIdentifier-$LOADER" '\EFI\systemd\systemd-bootx64.efi'
out=$("$BIN" check 2>&1); rc=$?
expect "nic nepripraveno: kod 1, duvody (poradi, shim, jadro)" \
    bash -c "[[ $rc == 1 && '$out' == *'fix-boot'* && '$out' == *'did not go through shim'* && '$out' == *'not signed'* ]]"
out=$("$BIN" status 2>&1)
expect "start bez shim (zadna MokListRT): luxos_key=unknown, ne 'missing' (mokutil zapsany klic nevidi)" \
    bash -c "[[ '$out' == *luxos_key=unknown* ]]"
efivar "MokListRT-$SHIM_GUID" 00
out=$("$BIN" check 2>&1)
expect "shim bezel, klic chybi: 'not enrolled ... enroll'" bash -c "[[ '$out' == *'not enrolled'*'enroll'* ]]"
rm -f "$T/vars/MokListRT-$SHIM_GUID"
"$BIN" notify
expect "notify, kdyz neni pripraveno: nic" test ! -s "$T/notify.log"
echo "$T/share/luxos-secureboot.cer" >"$T/mok.new"
out=$("$BIN" check 2>&1)
expect "zapis ceka: 'restart and confirm'" bash -c "[[ '$out' == *'waits for confirmation'* ]]"
efivar "SecureBoot-$GLOBAL" 01
out=$("$BIN" check 2>&1); rc=$?
expect "Secure Boot uz zapnuty: kod 0" bash -c "[[ $rc == 0 && '$out' == *'Secure Boot is on'* ]]"

echo "## fix-boot"
setup; old_layout; nv_load <<<"$ACER"
efivar_utf16 "LoaderImageIdentifier-$LOADER" '\EFI\LuxOS\grubx64.efi'; efivar "SbatLevelRT-$SHIM_GUID" 73
echo 0003 >"$T/nv/current"
out=$("$T/sb-root" fix-boot 2>&1); rc=$?
expect "fix-boot: kod 0, shim prvni, BootNext i bez cekajiciho zapisu" \
    bash -c "[[ $rc == 0 && '$out' == *'first entry'* && '$out' == *'next start goes through shim'* && \$(cat '$T/nv/next') == 0003 && \$(cat '$T/nv/order') == 0003,* ]]"
setup; old_layout; nv_load <<<"$ACER"; : >"$T/nv/ignore-order"
out=$("$T/sb-root" fix-boot 2>&1)
expect "fix-boot na firmwaru bez zapisu poradi: vysvetleni (BootNext pri kazdem vypnuti)" \
    bash -c "[[ '$out' == *'keeps its own boot order'* && \$(cat '$T/nv/next') == 0003 ]]"

echo "## Plny ESP (incident 2026-11-10: No space left on device -> prazdny shim, BootNext do prazdna)"
# Puvodni stav jako u majitele: jen stara prima polozka systemd-boot, prvni instalace luxos-secureboot
DIRECT='BootCurrent: 0000
BootOrder: 0000,0004
Boot0000* LuxOS	HD(1,GPT,aaaa-1111,0x800,0x200000)/\EFI\systemd\systemd-bootx64.efi
Boot0004* Windows Boot Manager	HD(1,GPT,cccc-3333,0x800,0x32000)/\EFI\Microsoft\Boot\bootmgfw.efi'
setup; nv_load <<<"$DIRECT"
efivar_utf16 "LoaderImageIdentifier-$LOADER" '\EFI\systemd\systemd-bootx64.efi'
: >"$T/cp-enospc"   # cp nezapise nic a skonci ENOSPC (df ale misto "ukazuje" - FAT se casto splete)
out=$("$BIN" sync 2>&1); rc=$?
expect "ENOSPC pri zapisu: kod != 0" test "$rc" != 0
expect "... jasna chyba (No space left on device, predchozi soubor zustal)" \
    bash -c "[[ '$out' == *'No space left on device'* && '$out' == *'previous file was kept'* && '$out' == *'could not be updated'* ]]"
expect "... zadna zprava 'Secure Boot loader updated' ani 'Fallback loader'" bash -c "[[ '$out' != *updated\ in* && '$out' != *'Fallback loader'* ]]"
expect "... na ESP zadny prazdny soubor" bash -c "! find '$T/esp' -type f -size 0 | grep -q ."
expect "... zadne docasne *.luxos-new" bash -c "! find '$T/esp' -name '*.luxos-new' | grep -q ."
expect "... EFI/LuxOS/shimx64.efi nevznikl" test ! -e "$T/esp/EFI/LuxOS/shimx64.efi"
expect "... zalozni BOOTX64.EFI dal puvodni systemd-boot" grep -q 'MZ OLD' "$T/esp/EFI/BOOT/BOOTX64.EFI"
expect "... zadna polozka UEFI na shim, BootOrder ani BootNext beze zmeny" \
    bash -c "! grep -qE -- '--create| -o | -n ' '$T/efibootmgr.log' && [[ \$(cat '$T/nv/order') == 0000,0004 && ! -s '$T/nv/next' ]]"
expect "... stav pro uzivatele zapsany (loader=missing)" grep -qx 'loader=missing' "$T/run/status"
rm -f "$T/cp-enospc"
out=$("$BIN" sync 2>&1); rc=$?
expect "po uvolneni mista: dalsi sync vse doplni (kod 0, shim, BootNext)" \
    bash -c "[[ $rc == 0 ]] && cmp -s '$T/lib/shimx64.efi' '$T/esp/EFI/LuxOS/shimx64.efi' && [[ \$(cat '$T/nv/next') == 0001 ]]"

setup; old_layout; nv_load <<<"$ACER"
echo "MZ SHIM-FEDORA-NEW $(head -c 4000 /dev/zero | tr '\0' n)" >"$T/lib/shimx64.efi"
echo 100 >"$T/cp-enospc"   # neuplny zapis (100 B) noveho shim
out=$("$BIN" sync 2>&1); rc=$?
expect "neuplny zapis nove verze: kod != 0, stary shim v EFI/LuxOS i EFI/BOOT beze zmeny" \
    bash -c "[[ $rc != 0 ]] && grep -q 'MZ SHIM-FEDORA ' '$T/esp/EFI/LuxOS/shimx64.efi' && grep -q 'MZ SHIM-FEDORA ' '$T/esp/EFI/BOOT/BOOTX64.EFI'"
expect "... zadny neuplny ani docasny soubor" bash -c "! find '$T/esp' -name '*.luxos-new' | grep -q . && ! find '$T/esp' -type f -size 0 | grep -q ."
expect "... platny stary shim: polozky UEFI se dal spravuji (shim prvni)" test "$(nv_order | cut -d, -f1)" = 0003

setup; nv_load <<<"$DIRECT"; echo 500000 >"$T/esp-avail"
out=$("$BIN" sync 2>&1); rc=$?
expect "malo mista uz pred zapisem (df): kod != 0, 'Not enough space ... Nothing was changed'" \
    bash -c "[[ $rc != 0 && '$out' == *'Not enough space on the EFI partition'*'Nothing was changed'* ]]"
expect "... nic se nezapsalo (zadny EFI/LuxOS), zadna polozka UEFI" \
    bash -c "[[ ! -e '$T/esp/EFI/LuxOS' ]] && ! grep -qE -- '--create| -o | -n ' '$T/efibootmgr.log'"

setup; nv_load <<<"$DIRECT"; : >"$T/lib/shimx64.efi"
out=$("$BIN" sync 2>&1); rc=$?
expect "prazdny soubor v balicku: kod != 0, na ESP nic" \
    bash -c "[[ $rc != 0 && '$out' == *'missing or empty'* && ! -e '$T/esp/EFI/LuxOS/shimx64.efi' ]]"

echo "## Zbytky po plnem ESP (0 B soubory z 1.0.0-1): rozpoznani a oprava"
# Stav u majitele: EFI/LuxOS/{shimx64,grubx64}.efi a EFI/BOOT/{BOOTX64,grubx64,mmx64}.efi maji 0 B,
# polozka shim prvni a BootNext na ni - firmware ji preskocil a nastartoval starou primou polozku
incident_layout() {
    mkdir -p "$T/esp/EFI/LuxOS"
    : >"$T/esp/EFI/LuxOS/shimx64.efi"; : >"$T/esp/EFI/LuxOS/grubx64.efi"
    cp "$T/lib/mmx64.efi" "$T/share/luxos-secureboot.cer" "$T/esp/EFI/LuxOS/"
    : >"$T/esp/EFI/BOOT/BOOTX64.EFI"; : >"$T/esp/EFI/BOOT/grubx64.efi"; : >"$T/esp/EFI/BOOT/mmx64.efi"
    : >"$T/esp/EFI/LuxOS/grubx64.efi.luxos-new"
    nv_load <<'EOF'
BootCurrent: 0000
BootNext: 0003
BootOrder: 0003,0000,0004
Boot0000* LuxOS	HD(1,GPT,aaaa-1111,0x800,0x200000)/\EFI\systemd\systemd-bootx64.efi
Boot0003* LuxOS	HD(1,GPT,aaaa-1111,0x800,0x200000)/\EFI\LuxOS\shimx64.efi
Boot0004* Windows Boot Manager	HD(1,GPT,cccc-3333,0x800,0x32000)/\EFI\Microsoft\Boot\bootmgfw.efi
EOF
    efivar_utf16 "LoaderImageIdentifier-$LOADER" '\EFI\systemd\systemd-bootx64.efi'
}
setup; incident_layout
out=$("$BIN" status 2>&1)
expect "status: loader=broken + seznam poskozenych souboru + rada sync" \
    bash -c "[[ '$out' == *loader=broken* && '$out' == *loader_damaged=*EFI/LuxOS/shimx64.efi* && '$out' == *EFI/BOOT/BOOTX64.EFI* && '$out' == *EFI/BOOT/grubx64.efi* && '$out' == *'hint=Boot loader files on the EFI partition are damaged'*'luxos-secureboot sync'* ]]"
expect "... EFI/LuxOS/mmx64.efi (v poradku) neni v seznamu" bash -c "[[ '$out' != *EFI/LuxOS/mmx64.efi* ]]"
out=$("$BIN" check 2>&1); rc=$?
expect "check: kod 1, duvod 'damaged ... sync'" bash -c "[[ $rc == 1 && '$out' == *'boot loader files on the EFI partition are damaged'*'sync'* ]]"
echo 100000 >"$T/esp-avail"   # ESP porad plny
out=$("$BIN" sync 2>&1); rc=$?
expect "ESP porad plny: kod != 0" test "$rc" != 0
expect "... BootNext na prazdny shim zrusen" test -z "$(nv_next)"
expect "... polozka shim na konec poradi, stara prima polozka (funkcni) prvni" test "$(nv_order)" = "0000,0004,0003"
expect "... zadna nova polozka, zadny BootNext" bash -c "! grep -qE -- '--create| -n ' '$T/efibootmgr.log'"
rm -f "$T/nv/next"; mkdir -p "$T/state"; echo quirk >"$T/state/firmware-quirk"
"$BIN" sync --quiet --shutdown >/dev/null 2>&1
expect "vypnuti s poskozenym shim (firmware-quirk): zadny BootNext" test -z "$(nv_next)"
out=$("$T/sb-root" fix-boot 2>&1); rc=$?
expect "fix-boot s poskozenym shim a plnym ESP: kod != 0, zadny BootNext" bash -c "[[ $rc != 0 && -z \$(cat '$T/nv/next' 2>/dev/null) ]]"
rm -f "$T/esp-avail" "$T/state/firmware-quirk"; : >"$T/efibootmgr.log"
out=$("$BIN" sync 2>&1); rc=$?
expect "misto uvolnene: sync opravi (kod 0)" test "$rc" = 0
expect "... EFI/LuxOS/shimx64.efi a grubx64.efi = balicek" \
    bash -c "cmp -s '$T/lib/shimx64.efi' '$T/esp/EFI/LuxOS/shimx64.efi' && cmp -s '$T/lib/systemd-bootx64.efi' '$T/esp/EFI/LuxOS/grubx64.efi'"
expect "... prazdny EFI/BOOT/BOOTX64.EFI = shim (nas zbytek, ne cizi zavadec), mmx64/fbx64 doplnene" \
    bash -c "cmp -s '$T/lib/shimx64.efi' '$T/esp/EFI/BOOT/BOOTX64.EFI' && cmp -s '$T/lib/mmx64.efi' '$T/esp/EFI/BOOT/mmx64.efi' && cmp -s '$T/lib/fbx64.efi' '$T/esp/EFI/BOOT/fbx64.efi'"
expect "... prazdny EFI/BOOT/grubx64.efi smazany, *.luxos-new smazany" \
    bash -c "[[ ! -e '$T/esp/EFI/BOOT/grubx64.efi' ]] && ! find '$T/esp' -name '*.luxos-new' | grep -q ."
expect "... shim zase prvni a BootNext na nej (tento start nesel pres shim)" \
    bash -c "[[ \$(cat '$T/nv/order') == 0003,* && \$(cat '$T/nv/next') == 0003 ]]"
out=$("$BIN" status 2>&1)
expect "... status: loader=installed, nic poskozeneho" bash -c "[[ '$out' == *loader=installed* && '$out' != *loader_damaged* && '$out' != *damaged* ]]"

setup; old_layout; head -c 50 "$T/lib/shimx64.efi" >"$T/esp/EFI/BOOT/BOOTX64.EFI"
out=$("$BIN" status 2>&1)
expect "neuplna kopie shim (50 B) v EFI/BOOT: hlasena jako poskozena" bash -c "[[ '$out' == *loader_damaged=EFI/BOOT/BOOTX64.EFI* ]]"
"$BIN" sync >/dev/null 2>&1
expect "... a nahrazena celym shim" cmp -s "$T/lib/shimx64.efi" "$T/esp/EFI/BOOT/BOOTX64.EFI"
setup; old_layout; echo 'MZ Windows Boot Manager bootmgfw' >"$T/esp/EFI/BOOT/BOOTX64.EFI"
out=$("$BIN" status 2>&1)
expect "cizi BOOTX64.EFI (Windows): neni 'poskozeny' a zustava" \
    bash -c "[[ '$out' != *loader_damaged* ]] && '$BIN' sync >/dev/null 2>&1; grep -q 'Windows Boot Manager' '$T/esp/EFI/BOOT/BOOTX64.EFI'"
setup; mkdir -p "$T/esp/EFI/LuxOS"; echo 'not a PE file' >"$T/esp/EFI/LuxOS/grubx64.efi"
out=$("$BIN" status 2>&1)
expect "EFI/LuxOS/grubx64.efi bez hlavicky MZ: poskozeny" bash -c "[[ '$out' == *loader_damaged=EFI/LuxOS/grubx64.efi* ]]"

echo
echo "luxos-secureboot: $NPASS ok, $NFAIL failed"
exit "$NFAIL"
