#!/bin/bash
# LuxOS - konfigurace nainstalovaneho systemu (bezi uvnitr arch-chroot)
set -Eeuo pipefail
. /root/luxos-setup.env

echo "--> Locale ($LOCALE)"
sed -i -E "s/^#\s*(${LOCALE//./\\.}\s)/\1/; s/^#\s*(en_US\.UTF-8\s)/\1/" /etc/locale.gen
locale-gen
echo "LANG=$LOCALE" > /etc/locale.conf

echo "--> Keyboard ($XKB_LAYOUT ${XKB_VARIANT})"
echo "KEYMAP=$CONSOLE_KEYMAP" > /etc/vconsole.conf
layouts=$XKB_LAYOUT variants=$XKB_VARIANT options=""
if [[ $XKB_LAYOUT != us ]]; then
    # Druhe rozlozeni US pro psani kodu/hesel, prepinani Alt+Shift
    layouts="$XKB_LAYOUT,us" variants="$XKB_VARIANT," options="grp:alt_shift_toggle"
fi
mkdir -p /etc/X11/xorg.conf.d
cat > /etc/X11/xorg.conf.d/00-keyboard.conf <<KB
Section "InputClass"
    Identifier "system-keyboard"
    MatchIsKeyboard "on"
    Option "XkbLayout" "$layouts"
    Option "XkbVariant" "$variants"
    Option "XkbOptions" "$options"
EndSection
KB

echo "--> Time zone ($TIMEZONE)"
ln -sf "/usr/share/zoneinfo/$TIMEZONE" /etc/localtime
hwclock --systohc || true

echo "--> Hostname ($HOSTNAME_SEL)"
echo "$HOSTNAME_SEL" > /etc/hostname
cat > /etc/hosts <<H
127.0.0.1   localhost
::1         localhost
127.0.1.1   $HOSTNAME_SEL.localdomain $HOSTNAME_SEL
H

echo "--> User ($USERNAME)"
groups=wheel
for g in video audio input lp storage scanner network rfkill sys; do
    getent group "$g" >/dev/null && groups+=",$g"
done
id "$USERNAME" &>/dev/null || useradd -m -G "$groups" -s /usr/bin/lsh -c "$FULLNAME" "$USERNAME"
passwd -l root >/dev/null
install -Dm440 /dev/stdin /etc/sudoers.d/10-luxos <<S
%wheel ALL=(ALL:ALL) ALL
Defaults pwfeedback
Defaults timestamp_timeout=15
S
if ((AUTOLOGIN)); then
    groupadd -rf autologin
    gpasswd -a "$USERNAME" autologin >/dev/null
    install -Dm644 /dev/stdin /etc/lightdm/lightdm.conf.d/60-autologin.conf <<A
[Seat:*]
autologin-user=$USERNAME
autologin-session=luxos
A
fi

echo "--> Initramfs"
modules=""
# Rane nacteni NVIDIA jen bez integrovane grafiky (u hybridni jen zpomaluje start)
pac=/usr/lib/lux/alpm/pacman   # skutecny pacman (luxos-pacman); /usr/bin/pacman je kompatibilni vrstva
[[ -x $pac ]] || pac=pacman
if ((${NVIDIA_EARLY:-1})) && "$pac" -Qq nvidia-open-dkms &>/dev/null; then
    modules="nvidia nvidia_modeset nvidia_uvm nvidia_drm"
fi
# Sifrovany / (sd-encrypt: rd.luks.* + /etc/crypttab.initramfs) a / na LVM (lvm2); poradi: block sd-encrypt lvm2
storage_hooks=""
((ENCRYPT || ${ENCRYPT_HOOK:-0})) && storage_hooks="sd-encrypt"
((${LVM_HOOK:-0})) && storage_hooks+=" lvm2"
cat > /etc/mkinitcpio.conf.d/luxos.conf <<M
# LuxOS - systemd initramfs s Plymouth (boot splash)
MODULES=($modules)
HOOKS=(base systemd plymouth autodetect microcode modconf kms keyboard sd-vconsole block ${storage_hooks# } filesystems fsck)
COMPRESSION="zstd"
M
/usr/lib/luxos/apply-branding
# ESP v /efi (vedle jinych systemu nebo rucne): jadro zustava v /boot a kopiruje se na ESP
[[ -n ${ESP_MOUNT-} ]] || { [[ ${DISK_MODE:-erase} == freespace ]] && ESP_MOUNT=/efi || ESP_MOUNT=/boot; }
if [[ $ESP_MOUNT == /efi && ${BOOTLOADER:-auto} != none ]]; then
    # Sdileny ESP: fallback initramfs by z /boot (btrfs) stejne nesel spustit - jen zdrzuje
    sed -i "s/^PRESETS=.*/PRESETS=('default')/" /etc/mkinitcpio.d/linux-zen.preset
    rm -f /boot/initramfs-linux-zen-fallback.img
fi
mkinitcpio -P

echo "--> Boot loader ($BOOTMODE, ${BOOTLOADER:-auto})"
kernel=linux-zen
if [[ ${BOOTLOADER:-auto} == none ]]; then
    echo "   (skip - jadro zustava v /boot)"
elif [[ $BOOTMODE == uefi && $ESP_MOUNT == /efi ]]; then
    # ESP sdileny s jinymi systemy (/efi): cizi soubory, polozky ani loader.conf se neprepisuji.
    # Jadro a initramfs se kopiruji do vlastniho adresare EFI/LuxOS/<id> (zadna kolize nazvu).
    esp=/efi
    dir=EFI/LuxOS/$ESP_ID
    install -Dm644 /dev/stdin /etc/luxos/esp.conf <<C
# LuxOS - kopie jadra na sdileny ESP (luxos-esp-sync)
ESP_DIR=$esp/$dir
KERNEL=$kernel
C
    install -Dm755 /dev/stdin /usr/local/sbin/luxos-esp-sync <<'S'
#!/bin/bash
# LuxOS - zkopiruje jadro a initramfs z /boot na sdileny ESP (jen pri zmene)
set -eu
. /etc/luxos/esp.conf
mountpoint -q "${ESP_DIR%%/EFI/*}" || { echo "luxos-esp-sync: ESP is not mounted" >&2; exit 0; }
mkdir -p "$ESP_DIR"
for f in "vmlinuz-$KERNEL" "initramfs-$KERNEL.img"; do
    [[ -e /boot/$f ]] || continue
    cmp -s "/boot/$f" "$ESP_DIR/$f" && continue
    cp "/boot/$f" "$ESP_DIR/$f.new"
    mv -f "$ESP_DIR/$f.new" "$ESP_DIR/$f"
done
S
    # Po kazde transakci pacmanu (po mkinitcpio) a po rucnim mkinitcpio
    install -Dm644 /dev/stdin /etc/pacman.d/hooks/99-luxos-esp-sync.hook <<'H'
[Trigger]
Type = Package
Operation = Install
Operation = Upgrade
Target = *

[Action]
Description = Copying the LuxOS kernel to the EFI system partition...
When = PostTransaction
Exec = /usr/local/sbin/luxos-esp-sync
H
    mkdir -p /etc/initcpio/post
    ln -sf /usr/local/sbin/luxos-esp-sync /etc/initcpio/post/luxos-esp-sync
    /usr/local/sbin/luxos-esp-sync
    [[ -e $esp/$dir/vmlinuz-$kernel && -e $esp/$dir/initramfs-$kernel.img ]] || { echo "Kernel copy to ESP failed" >&2; exit 1; }

    # systemd-boot jen pokud na ESP jeste neni (jiny systemd-boot se neprepisuje)
    mkdir -p "$esp/EFI/systemd" "$esp/loader/entries"
    sdboot=/usr/lib/systemd/boot/efi/systemd-bootx64.efi
    [[ -e $esp/EFI/systemd/systemd-bootx64.efi ]] || install -m644 "$sdboot" "$esp/EFI/systemd/systemd-bootx64.efi"
    # Zalozni zavadec jen kdyz zadny neni (napr. Windows ho nema)
    if ! compgen -G "$esp/[Ee][Ff][Ii]/[Bb][Oo][Oo][Tt]/[Bb][Oo][Oo][Tt][Xx]64.[Ee][Ff][Ii]" >/dev/null; then
        install -Dm644 "$sdboot" "$esp/EFI/BOOT/BOOTX64.EFI"
    fi
    if [[ ! -e $esp/loader/loader.conf ]]; then
        # Jine systemy na disku: menu s odpoctem 3 s (Windows systemd-boot najde sam)
        cat > "$esp/loader/loader.conf" <<L
default luxos-$ESP_ID.conf
timeout 3
console-mode max
editor no
L
    fi
    cat > "$esp/loader/entries/luxos-$ESP_ID.conf" <<E
title   LuxOS
linux   /$dir/vmlinuz-$kernel
initrd  /$dir/initramfs-$kernel.img
options $CMDLINE
E
    systemctl enable systemd-boot-update.service
elif [[ $BOOTMODE == uefi ]]; then
    if ((${ESP_KEEP:-0})); then
        # Zachovany ESP v /boot (rucni rozdeleni): cizi zavadece a loader.conf se neprepisuji
        sdboot=/usr/lib/systemd/boot/efi/systemd-bootx64.efi
        install -Dm644 "$sdboot" /boot/EFI/systemd/systemd-bootx64.efi
        if ! compgen -G "/boot/[Ee][Ff][Ii]/[Bb][Oo][Oo][Tt]/[Bb][Oo][Oo][Tt][Xx]64.[Ee][Ff][Ii]" >/dev/null; then
            install -Dm644 "$sdboot" /boot/EFI/BOOT/BOOTX64.EFI
        fi
        mkdir -p /boot/loader/entries
        [[ -e /boot/loader/loader.conf ]] || cat > /boot/loader/loader.conf <<L
default luxos.conf
timeout 3
console-mode max
editor no
L
    else
        bootctl install --esp-path=/boot
        mkdir -p /boot/loader/entries
        cat > /boot/loader/loader.conf <<L
default luxos.conf
timeout 0
console-mode max
editor no
L
    fi
    cat > /boot/loader/entries/luxos.conf <<E
title   LuxOS
linux   /vmlinuz-$kernel
initrd  /initramfs-$kernel.img
options $CMDLINE
E
    if [[ -e /boot/initramfs-$kernel-fallback.img ]]; then
        cat > /boot/loader/entries/luxos-fallback.conf <<E
title   LuxOS (safe mode)
linux   /vmlinuz-$kernel
initrd  /initramfs-$kernel-fallback.img
options ${CMDLINE/quiet splash/}
E
    fi
    systemctl enable systemd-boot-update.service
else
    sed -i \
        -e 's/^GRUB_DISTRIBUTOR=.*/GRUB_DISTRIBUTOR="LuxOS"/' \
        -e 's/^GRUB_TIMEOUT=.*/GRUB_TIMEOUT=1/' \
        -e 's/^GRUB_TIMEOUT_STYLE=.*/GRUB_TIMEOUT_STYLE=hidden/' \
        -e "s|^GRUB_CMDLINE_LINUX_DEFAULT=.*|GRUB_CMDLINE_LINUX_DEFAULT=\"${CMDLINE//|/\\|}\"|" \
        /etc/default/grub
    grub-install --target=i386-pc "$DISK"
    grub-mkconfig -o /boot/grub/grub.cfg
fi

echo "--> Services"
mapfile -t svcs < <(grep -vE '^\s*(#|$)' /usr/lib/luxos/services)
for s in "${svcs[@]}" $HW_SERVICES; do
    if systemctl cat "$s" &>/dev/null; then systemctl enable "$s"; else echo "   (skip $s)"; fi
done
systemctl set-default graphical.target

echo "--> Done"
