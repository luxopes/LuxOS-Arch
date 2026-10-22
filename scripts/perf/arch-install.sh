#!/bin/bash
# LuxOS - srovnavaci instalace ciste Arch Linux + Xfce + LightDM do VM (bezi UVNITR live ISO Archu
# jako root, spousti arch-compare.sh pres guest agenta). Uzivatel lux / heslo luxos jako u LuxOS.
set -euxo pipefail
timedatectl set-ntp true || true
sgdisk -Z /dev/vda
sgdisk -n1:0:+512M -t1:ef00 -n2:0:0 -t2:8300 /dev/vda
mkfs.fat -F32 /dev/vda1
mkfs.ext4 -F /dev/vda2
mount /dev/vda2 /mnt
mkdir -p /mnt/boot
mount /dev/vda1 /mnt/boot
pacstrap -K /mnt base linux linux-firmware xfce4 lightdm lightdm-gtk-greeter networkmanager qemu-guest-agent \
    sudo xorg-xprop wmctrl noto-fonts
genfstab -U /mnt >>/mnt/etc/fstab
arch-chroot /mnt bash -euxo pipefail <<'IN'
ln -sf /usr/share/zoneinfo/Europe/Prague /etc/localtime
sed -i 's/^#cs_CZ.UTF-8/cs_CZ.UTF-8/; s/^#en_US.UTF-8/en_US.UTF-8/' /etc/locale.gen
locale-gen
echo LANG=cs_CZ.UTF-8 >/etc/locale.conf
echo archxfce >/etc/hostname
useradd -m -G wheel -s /bin/bash lux
echo lux:luxos | chpasswd
echo root:luxos | chpasswd
echo '%wheel ALL=(ALL:ALL) ALL' >/etc/sudoers.d/wheel
systemctl enable lightdm NetworkManager qemu-guest-agent
bootctl install
cat >/boot/loader/loader.conf <<L
default arch.conf
timeout 0
L
cat >/boot/loader/entries/arch.conf <<L
title Arch Linux
linux /vmlinuz-linux
initrd /initramfs-linux.img
options root=/dev/vda2 rw quiet
L
IN
sync
umount -R /mnt
echo ARCH-INSTALL-DONE
