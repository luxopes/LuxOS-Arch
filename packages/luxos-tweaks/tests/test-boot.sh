#!/bin/bash
# LuxOS - testy hlaseni neuspesneho startu (luxos-boot-failure, luxos-boot-watch, zz-luxos-boot.conf)
# bez initramfs a bez roota: prikazy (lsblk, mount, journalctl, systemctl, ...) nahrazuji skripty v PATH.
#   bash packages/luxos-tweaks/tests/test-boot.sh
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
B=$HERE/../files/boot
I18N=$HERE/../../luxos-i18n/files
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
FAIL=0
ok() { if "$@"; then echo "ok    $DESC"; else echo "FAIL  $DESC"; FAIL=$((FAIL + 1)); fi; }

# ---- nahradni prikazy ----
mkdir -p "$T/bin"
mk() { printf '#!/bin/bash\n%s\n' "$2" >"$T/bin/$1"; chmod +x "$T/bin/$1"; }
mk journalctl 'echo "JOURNAL LINE 1"; echo "JOURNAL LINE 2"'
mk systemctl 'echo "systemctl $*" >>"$MOCKLOG"; [[ $1 == --failed ]] && echo "sysroot.mount loaded failed failed /sysroot"; true'
mk findmnt '[[ -n ${MOCK_ESP_MNT-} ]] && echo "$MOCK_ESP_MNT"; true'
mk mount 'echo "mount $*" >>"$MOCKLOG"; true'
mk umount 'echo "umount $*" >>"$MOCKLOG"; true'
mk modprobe 'true'
mk sync 'true'
mk plymouth 'echo "plymouth $*" >>"$MOCKLOG"'
mk lsblk 'printf "/dev/vda1 C12A7328-F81F-11D2-BA4B-00A0C93EC93B\n/dev/vda2 0fc63daf-8483-4772-8e79-3d69d8477de4\n"'
export PATH="$T/bin:$PATH" MOCKLOG=$T/log

# ---- koren s locale a preklady ----
newroot() {  # newroot JAZYK [FONT]
    R=$T/root-$1; rm -rf "$R"; mkdir -p "$R/etc" "$R/usr/lib/luxos" "$R/run"
    echo "LANG=$1" >"$R/etc/locale.conf"
    echo "KEYMAP=cz-us-qwertz" >"$R/etc/vconsole.conf"
    [[ -n ${2-} ]] && echo "FONT=$2" >>"$R/etc/vconsole.conf"
    ln -s "$I18N/i18n.sh" "$R/usr/lib/luxos/i18n.sh"
}
msgs() { LUXOS_BOOT_ROOT=$R LUXOS_I18N_DIR=$I18N bash "$B/luxos-boot-failure" --messages; }

echo "## texty"
newroot cs_CZ.UTF-8
eval "$(msgs)"
DESC="cs: zprava pro uvodni obrazovku s diakritikou"; ok test "$MSG_WRONG" = "Špatné heslo, zkuste to znovu."
DESC="cs: konzole bez pisma -> ASCII"; ok test "$TTY_WRONG" = "Spatne heslo, zkuste to znovu."
DESC="cs: %s zustava v textu o ulozeni"; ok grep -q '%s' <<<"$TTY_SAVED"
newroot cs_CZ.UTF-8 eurlatgr
eval "$(msgs)"
DESC="cs + FONT ve vconsole.conf: konzole s diakritikou"; ok test "$TTY_WRONG" = "Špatné heslo, zkuste to znovu."
newroot uk_UA.UTF-8
eval "$(msgs)"
DESC="uk: uvodni obrazovka ukrajinsky"; ok test "$MSG_WRONG" = "Неправильний пароль, спробуйте ще раз."
DESC="uk: konzole bez cyrilice -> anglicky"; ok test "$TTY_WRONG" = "Wrong password, try again."
newroot en_US.UTF-8
eval "$(msgs)"
DESC="en: anglicky"; ok test "$MSG_TITLE" = "LuxOS could not start." -a "$TTY_TITLE" = "LuxOS could not start."

echo "## zaznam na EFI oddilu"
newroot cs_CZ.UTF-8
ESP=$T/esp; mkdir -p "$ESP/EFI/LuxOS"
for i in 1 2 3 4 5 6; do echo old >"$ESP/EFI/LuxOS/boot-failure-2026010${i}-000000.log"; done
: >"$MOCKLOG"
out=$(MOCK_ESP_MNT=$ESP LUXOS_BOOT_ROOT=$R LUXOS_I18N_DIR=$I18N LUXOS_BOOT_NOW=20261024-120000 bash "$B/luxos-boot-failure")
f=$ESP/EFI/LuxOS/boot-failure-20261024-120000.log
DESC="zaznam ulozen"; ok test -s "$f"
DESC="zaznam obsahuje zurnal a selhane jednotky"; ok bash -c "grep -q 'JOURNAL LINE 2' '$f' && grep -q 'sysroot.mount' '$f'"
DESC="nejvys 5 zaznamu (nejstarsi smazane)"; ok test "$(ls "$ESP/EFI/LuxOS" | wc -l)" -eq 5 -a ! -e "$ESP/EFI/LuxOS/boot-failure-20260101-000000.log"
DESC="pripojeny ESP se nepripojuje ani neodpojuje"; ok bash -c "! grep -qE '^(mount|umount) ' '$MOCKLOG'"
DESC="hlaseni: nadpis cesky (ASCII)"; ok grep -q "LuxOS se nepodarilo spustit." <<<"$out"
DESC="hlaseni: cesta k zaznamu"; ok grep -qF '\EFI\LuxOS\boot-failure-20261024-120000.log' <<<"$out"
DESC="hlaseni: selhana jednotka"; ok grep -q "sysroot.mount" <<<"$out"
DESC="hlaseni: co delat"; ok grep -q "Ctrl+Alt+Delete" <<<"$out"

: >"$MOCKLOG"
out=$(LUXOS_BOOT_ROOT=$R LUXOS_I18N_DIR=$I18N LUXOS_BOOT_NOW=20261024-130000 bash "$B/luxos-boot-failure")
DESC="nepripojeny ESP (podle typu GPT z lsblk): pripoji se /dev/vda1 a zase odpoji"; ok bash -c "grep -q 'mount -t vfat -o rw,noatime /dev/vda1 $R/run/luxos-esp' '$MOCKLOG' && grep -q 'umount $R/run/luxos-esp' '$MOCKLOG'"
DESC="zaznam v pripojenem miste"; ok test -s "$R/run/luxos-esp/EFI/LuxOS/boot-failure-20261024-130000.log"

mk lsblk 'true'
mk blkid 'true'
out=$(LUXOS_BOOT_ROOT=$R LUXOS_I18N_DIR=$I18N bash "$B/luxos-boot-failure")
DESC="bez EFI oddilu: hlaseni, ze zaznam nejde ulozit"; ok grep -q "Zaznam startu se nepodarilo ulozit." <<<"$out"
echo "Systemovy disk se neobjevil vcas." >"$R/run/luxos-boot-reason"
out=$(LUXOS_BOOT_ROOT=$R LUXOS_I18N_DIR=$I18N bash "$B/luxos-boot-failure")
DESC="duvod z luxos-boot-watch v hlaseni"; ok grep -q "Systemovy disk se neobjevil vcas." <<<"$out"

echo "## hlidani hesla a disku (initramfs)"
W() { LUXOS_BOOT_SOURCE_ONLY=1 . "$B/luxos-boot-watch"; }
(
    W
    DESC="spatne heslo (systemd 262)"; ok is_wrong_password "Failed to activate with specified passphrase. (Passphrase incorrect?)"
    DESC="spatne heslo (starsi znení)"; ok is_wrong_password "Failed to activate, key file or passphrase incorrect? No key available with this passphrase."
    DESC="jina zprava neni spatne heslo"; ok bash -c "! (LUXOS_BOOT_SOURCE_ONLY=1 . '$B/luxos-boot-watch'; is_wrong_password 'Set cipher aes, mode xts-plain64')"
)
newroot cs_CZ.UTF-8
LUXOS_BOOT_ROOT=$R LUXOS_I18N_DIR=$I18N bash "$B/luxos-boot-failure" --messages >"$R/etc/luxos-boot.msg"
mkdir -p "$R/sysroot" "$R/run/systemd/ask-password"
mk mountpoint 'false'
: >"$MOCKLOG"
LUXOS_BOOT_ROOT=$R LUXOS_BOOT_SYSROOT=$R/sysroot LUXOS_ROOT_WAIT=2 LUXOS_BOOT_TICK=1 LUXOS_BOOT_CONSOLE=$T/console \
    bash -c 'LUXOS_BOOT_SOURCE_ONLY=1 . "$1"; watch_root' _ "$B/luxos-boot-watch"
rc=$?
DESC="koren se neobjevil: nouzovy rezim"; ok bash -c "[[ $rc == 1 ]] && grep -q 'systemctl --no-block start emergency.target' '$MOCKLOG'"
DESC="koren se neobjevil: duvod pro hlaseni (ASCII)"; ok grep -q "Systemovy disk se neobjevil vcas." "$R/run/luxos-boot-reason"
DESC="koren se neobjevil: zprava na uvodni obrazovce cesky bez diakritiky"; ok grep -q "plymouth display-message --text=Systemovy disk se neobjevil vcas." "$MOCKLOG"
: >"$MOCKLOG"; : >"$R/run/systemd/ask-password/ask.1234"
timeout 4 env LUXOS_BOOT_ROOT=$R LUXOS_BOOT_SYSROOT=$R/sysroot LUXOS_ROOT_WAIT=2 LUXOS_BOOT_TICK=1 LUXOS_BOOT_CONSOLE=$T/console \
    bash -c 'LUXOS_BOOT_SOURCE_ONLY=1 . "$1"; watch_root' _ "$B/luxos-boot-watch"
rc=$?
DESC="behem psani hesla se cas nepocita (zadny nouzovy rezim)"; ok bash -c "[[ $rc == 124 ]] && ! grep -q emergency '$MOCKLOG'"
rm -f "$R/run/systemd/ask-password/ask.1234"
mk mountpoint 'true'
LUXOS_BOOT_ROOT=$R LUXOS_BOOT_SYSROOT=$R/sysroot LUXOS_ROOT_WAIT=2 LUXOS_BOOT_TICK=1 \
    bash -c 'LUXOS_BOOT_SOURCE_ONLY=1 . "$1"; watch_root' _ "$B/luxos-boot-watch"
DESC="koren pripojeny: konec bez nouzoveho rezimu"; ok test $? -eq 0
: >"$MOCKLOG"
LUXOS_BOOT_ROOT=$R LUXOS_BOOT_CONSOLE=$T/console \
    bash -c 'LUXOS_BOOT_SOURCE_ONLY=1 . "$1"; say "$MSG_WRONG" "$TTY_WRONG"' _ "$B/luxos-boot-watch"
DESC="spatne heslo: uvodni obrazovka i konzole bez diakritiky (label-freetype)"; ok bash -c "grep -q 'display-message --text=Spatne heslo' '$MOCKLOG' && grep -q 'Spatne heslo, zkuste to znovu.' '$T/console'"

# Hlidani zurnalu: dve spatna hesla -> dve zpravy; opakovane spusteni journalctl je neohlasi znovu
mk journalctl 'printf "%s\n" "Set cipher aes" "Failed to activate with specified passphrase. (Passphrase incorrect?)" "Set cipher aes" "Failed to activate with specified passphrase. (Passphrase incorrect?)"'
: >"$MOCKLOG"
LUXOS_BOOT_ROOT=$R LUXOS_BOOT_CONSOLE=$T/console LUXOS_BOOT_JOURNAL_READY=1 LUXOS_BOOT_ONCE=1 \
    bash -c 'LUXOS_BOOT_SOURCE_ONLY=1 . "$1"; watch_passwords; LUXOS_BOOT_COUNT=$LUXOS_BOOT_ROOT/run/luxos-boot-wrong; n=0
             while IFS= read -r line; do is_wrong_password "$line" || continue; n=$((n+1)); ((n > $(wc -l <"$LUXOS_BOOT_COUNT"))) && say x x; done < <(journalctl)' _ "$B/luxos-boot-watch"
DESC="zurnal: kazde spatne heslo jedna zprava, opakovane cteni bez duplicit"; ok test "$(grep -c display-message "$MOCKLOG")" -eq 2
mk journalctl 'echo "JOURNAL LINE 1"; echo "JOURNAL LINE 2"'

echo "## mkinitcpio drop-in"
hooks() { bash -c 'HOOKS=('"$1"'); . "$1"; echo "${HOOKS[*]}"' _ "$B/zz-luxos-boot.conf"; }
DESC="systemd initramfs: hook pridan"; ok test "$(hooks "base systemd plymouth block sd-encrypt lvm2 filesystems fsck")" = "base systemd plymouth block sd-encrypt lvm2 filesystems fsck luxos-boot"
DESC="uz pridany: neopakuje se"; ok test "$(hooks "base systemd luxos-boot")" = "base systemd luxos-boot"
DESC="live ISO (udev, bez systemd): beze zmeny"; ok test "$(hooks "base udev archiso block")" = "base udev archiso block"

echo
echo "Vysledek: $FAIL FAIL"
exit $((FAIL > 0))
