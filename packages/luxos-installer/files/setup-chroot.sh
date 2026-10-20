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
id "$USERNAME" &>/dev/null || useradd -m -G "$groups" -s /bin/bash -c "$FULLNAME" "$USERNAME"
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
autologin-session=xfce
A
fi

echo "--> Initramfs"
modules=""
if pacman -Qq nvidia-open-dkms &>/dev/null; then
    modules="nvidia nvidia_modeset nvidia_uvm nvidia_drm"
fi
encrypt_hook=""
((ENCRYPT)) && encrypt_hook="sd-encrypt"
cat > /etc/mkinitcpio.conf.d/luxos.conf <<M
# LuxOS - systemd initramfs s Plymouth (boot splash)
MODULES=($modules)
HOOKS=(base systemd plymouth autodetect microcode modconf kms keyboard sd-vconsole block $encrypt_hook filesystems fsck)
COMPRESSION="zstd"
M
/usr/lib/luxos/apply-branding
mkinitcpio -P

echo "--> Boot loader ($BOOTMODE)"
kernel=linux-zen
if [[ $BOOTMODE == uefi ]]; then
    bootctl install --esp-path=/boot
    mkdir -p /boot/loader/entries
    cat > /boot/loader/loader.conf <<L
default luxos.conf
timeout 0
console-mode max
editor no
L
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
