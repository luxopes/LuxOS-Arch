#!/bin/bash
# LuxOS - testy hooku initramfs "luxos-slim" a drop-inu zz-luxos-slim.conf (bez roota, bez mkinitcpio):
# funkce mkinitcpio (msg2, error) a prikazy (modprobe, stat, luxos-care) nahrazuji skripty v PATH.
#   bash packages/luxos-tweaks/tests/test-slim.sh
# Skutecne sestaveni (mensi obraz, start ve VM) overuje docs/proposals/esp-space.md, Testy.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
B=$HERE/../files/boot
T=$(mktemp -d "${TMPDIR:-/tmp}/luxos-slim-test.XXXXXX")
trap 'rm -rf "$T"' EXIT
FAIL=0
ok() { if "$@"; then echo "ok    $DESC"; else echo "FAIL  $DESC"; FAIL=$((FAIL + 1)); fi; }

mkdir -p "$T/bin"
mk() { printf '#!/bin/bash\n%s\n' "$2" >"$T/bin/$1"; chmod +x "$T/bin/$1"; }
# modprobe -c: blacklist z modprobe.d (nvidia-utils zakazuje nouveau; pcspkr nikdo nepouziva)
mk modprobe 'cat "$T/modprobe.conf"'
# stat -f: volne misto z $T/avail (bajty); jinak skutecny stat
mk stat 'if [[ " $* " == *" -f "* ]]; then echo "$(cat "$T/avail")*1"; else exec /usr/bin/stat "$@"; fi'
# luxos-care esp-clean: "uvolni" misto ($T/after-clean), zaznam volani
mk luxos-care 'echo "luxos-care $*" >>"$T/care.log"; [[ -f $T/after-clean ]] && cp "$T/after-clean" "$T/avail"; true'
export PATH="$T/bin:$PATH" T LUXOS_SLIM_CARE=$T/bin/luxos-care

# Spusti build() hooku jako mkinitcpio: stejny proces, globalni _autodetect_cache a _optgenimg
run_hook() {  # run_hook "MODULY_AUTODETEKCE" -> vypis + "CACHE: ..." (serazene)
    bash -c '
        msg2() { local f=$1; shift; printf "  -> $f\n" "$@"; }
        error() { local f=$1; shift; printf "==> ERROR: $f\n" "$@"; }
        declare -A _autodetect_cache=()
        for m in $1; do _autodetect_cache[$m]=1; done
        _optgenimg=${IMG-}
        . "$2"
        build
        echo "CACHE: $(printf "%s\n" "${!_autodetect_cache[@]}" | sort | tr "\n" " ")"
    ' _ "$1" "$B/luxos-slim.hook"
}

echo "## Zakazane moduly"
printf 'alias pci:v000010DEd* nouveau\nblacklist nouveau\nblacklist nova_core\nblacklist pcspkr\noptions nvidia NVreg_DynamicPowerManagement=0x02\n' >"$T/modprobe.conf"
printf 'nvidia 1 0 - Live 0x0\namdgpu 1 0 - Live 0x0\n' >"$T/modules"
echo "BOOT_IMAGE=/vmlinuz root=UUID=x quiet" >"$T/cmdline"
export LUXOS_SLIM_MODULES=$T/modules LUXOS_SLIM_CMDLINE=$T/cmdline
out=$(run_hook "amdgpu nouveau nvidia xhci_pci nvme")
DESC="nouveau (blacklist, nenacteny) z autodetekce pryc - kms ho ani jeho firmware neprida"; ok bash -c "[[ '$out' == *'CACHE: amdgpu nvidia nvme xhci_pci '* ]]"
DESC="... zprava v mkinitcpio"; ok bash -c "[[ '$out' == *'Blacklisted modules left out (not loaded): nouveau'* ]]"
DESC="blacklist modulu mimo autodetekci (pcspkr, nova_core): nic se nepridava ani nehlasi"; ok bash -c "[[ '$out' != *pcspkr* && '$out' != *nova_core* ]]"
printf 'nouveau 1 0 - Live 0x0\n' >"$T/modules"
out=$(run_hook "amdgpu nouveau")
DESC="zakazany, ale nacteny (rucne povoleny): zustava"; ok bash -c "[[ '$out' == *'CACHE: amdgpu nouveau '* && '$out' != *'left out'* ]]"
: >"$T/modules"
out=$(run_hook "")
DESC="bez autodetect (zalozni/genericky obraz): nic, zadna zprava"; ok bash -c "[[ '$out' == 'CACHE:  ' ]]"
echo "BOOT_IMAGE=/vmlinuz module_blacklist=amdgpu,i915 modprobe.blacklist=btusb quiet" >"$T/cmdline"
: >"$T/modprobe.conf"
out=$(run_hook "amdgpu btusb nvme")
DESC="module_blacklist= a modprobe.blacklist= z prikazove radky jadra"; ok bash -c "[[ '$out' == *'CACHE: nvme '* ]]"
echo "BOOT_IMAGE=/vmlinuz quiet" >"$T/cmdline"
printf 'blacklist snd-hda-intel\n' >"$T/modprobe.conf"
out=$(run_hook "snd_hda_intel nvme")
DESC="nazev s pomlckou v blacklistu = modul s podtrzitkem"; ok bash -c "[[ '$out' == *'CACHE: nvme '* ]]"

echo "## Plny EFI oddil: stary initramfs se neprepise useknutym"
: >"$T/modprobe.conf"
mkdir -p "$T/esp"; head -c 4000000 /dev/zero >"$T/esp/initramfs-linux-luxos.img"
# potreba = 1,25 x 4 000 000 + 16 MiB = 21 777 216
echo 30000000 >"$T/avail"
out=$(IMG=$T/esp/initramfs-linux-luxos.img run_hook "nvme"); rc=$?
DESC="misto je: build pokracuje (kod 0), luxos-care se nevola"; ok bash -c "[[ $rc == 0 && '$out' == *CACHE:* && ! -s '$T/care.log' ]]"
echo 10000000 >"$T/avail"; echo 40000000 >"$T/after-clean"
out=$(IMG=$T/esp/initramfs-linux-luxos.img run_hook "nvme"); rc=$?
DESC="malo mista: luxos-care esp-clean --need ... --path ESP, pak build pokracuje"
ok bash -c "[[ $rc == 0 && '$out' == *CACHE:* ]] && grep -qx 'luxos-care esp-clean --need 21777216 --path $T/esp' '$T/care.log'"
echo 10000000 >"$T/avail"; rm -f "$T/after-clean"; : >"$T/care.log"
out=$(IMG=$T/esp/initramfs-linux-luxos.img run_hook "nvme"); rc=$?
DESC="ani po uklidu misto neni: chyba a konec (kod != 0) drive, nez se obraz zmeni"
ok bash -c "[[ $rc != 0 && '$out' == *'Not enough space'*'was kept'* && '$out' != *CACHE:* ]]"
DESC="... stary obraz beze zmeny"; ok test "$(stat -c %s "$T/esp/initramfs-linux-luxos.img")" = 4000000
out=$(IMG=$T/esp/new.img run_hook "nvme"); rc=$?
DESC="novy obraz (stary neexistuje): zadna kontrola"; ok bash -c "[[ $rc == 0 && '$out' == *CACHE:* ]]"

echo "## Drop-in zz-luxos-slim.conf"
hooks() { bash -c 'HOOKS=('"$1"'); . "$1"; echo "${HOOKS[*]}"' _ "$B/zz-luxos-slim.conf"; }
DESC="hned za autodetect"; ok test "$(hooks 'base systemd plymouth autodetect microcode modconf kms')" = "base systemd plymouth autodetect luxos-slim microcode modconf kms"
DESC="bez autodetect: na konec"; ok test "$(hooks 'base systemd kms block')" = "base systemd kms block luxos-slim"
DESC="live ISO (bez systemd): beze zmeny"; ok test "$(hooks 'base udev autodetect archiso')" = "base udev autodetect archiso"
DESC="uz je tam: beze zmeny (zadny druhy)"; ok test "$(hooks 'base systemd autodetect luxos-slim kms')" = "base systemd autodetect luxos-slim kms"
DESC="pomocne promenne nezustanou"; ok test "$(bash -c 'HOOKS=(base systemd autodetect); . "$1"; echo "${_luxos_h-}${_luxos_x-}"' _ "$B/zz-luxos-slim.conf")" = ""

echo
if ((FAIL)); then echo "luxos-slim: $FAIL failed"; else echo "luxos-slim: all ok"; fi
exit "$FAIL"
