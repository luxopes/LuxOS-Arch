#!/bin/bash
# Zkusebni VM s nahledem desktopu LuxOS 1.1.0 na Waylandu: LuxOS z publikovanych repozitaru [luxos] a [luxos-apps]
# (aplikace, vzhled, pisma, ikony a nastaveni jako po instalaci) plus mistni baliky Waylandu z vetve wayland-1.1.
#
#   scripts/wl-preview/build-image.sh BALIK.pkg.tar.zst..     napr. out/single/{wlroots0.20,luxcomp,luxwm,luxos-desktop,luxos-greetd}-*
#
# Stavi se v kontejneru luxos-builder (pacstrap, mkfs.ext4 -d, nic jako root na hostiteli). Vystup do
# $LUXOS_PREVIEW_DIR (vychozi out/vm-wayland-preview): base.qcow2, vmlinuz, initramfs.img, packages.txt a
# start.sh s README.txt. Po startu prihlasovaci obrazovka greetd (luxos-greetd), uzivatel luxos / luxos.
set -euo pipefail
here=$(dirname "$(readlink -f "$0")")
repo=$(readlink -f "$here/../..")
dir=${LUXOS_PREVIEW_DIR:-$repo/out/vm-wayland-preview}
image=${LUXOS_BUILDER_IMAGE:-localhost/luxos-builder}
repo_url=${LUXOS_REPO_URL:-https://luxos.lux-ai.cz/repo}
engine=$(command -v podman || command -v docker) || { echo "podman or docker is required" >&2; exit 1; }
(($#)) || { echo "usage: $0 PACKAGE.pkg.tar.zst..." >&2; exit 2; }

"$engine" image exists "$image" 2>/dev/null || "$engine" build -t "$image" -f "$repo/scripts/Containerfile" "$repo/scripts"
work=$dir/build
rm -rf "$work" && mkdir -p "$work/pkgs" "$dir/pkgcache"
cp "$@" "$work/pkgs/"
cp "$repo/packages/luxos-keyring/files/luxos.gpg" "$work/"

"$engine" run --rm --privileged -e "REPO_URL=$repo_url" \
    -v "$work:/w:z" -v "$dir/pkgcache:/var/cache/pacman/pkg:z" \
    "$image" bash -euo pipefail -c '
    r=/w/rootfs
    mkdir -p $r
    pacman-key --init >/dev/null 2>&1
    pacman-key --populate archlinux >/dev/null 2>&1
    pacman-key --add /w/luxos.gpg >/dev/null
    pacman-key --lsign-key "$(gpg --show-keys --with-colons /w/luxos.gpg | awk -F: "/^fpr/{print \$10; exit}")" >/dev/null 2>&1
    # mistni baliky Waylandu jako repozitar [wlpreview] pred [luxos]: maji prednost pred publikovanymi a vse
    # se nainstaluje jednou transakci (lux-engine v cili po instalaci presouva databazi, druhy pacstrap by ji nevidel)
    repo-add -q /w/pkgs/wlpreview.db.tar.gz /w/pkgs/*.pkg.tar.zst
    awk -v url="$REPO_URL" "/^\[core\]/ && !done { printf \"[wlpreview]\nSigLevel = Optional TrustAll\nServer = file:///w/pkgs\n\n[luxos]\nSigLevel = Required\nServer = %s/\$repo/\$arch\n\n[luxos-apps]\nSigLevel = Required\nServer = %s/\$repo/\$arch\n\n\", url, url; done=1 } { print }" \
        /etc/pacman.conf | sed "/^NoExtract/d" >/w/pacman.conf   # kontejner Archu vynechava preklady, locales i man
    pacman -Sy --config /w/pacman.conf --noconfirm >/dev/null
    kernel=linux-luxos
    pacman -Sp --config /w/pacman.conf linux-luxos >/dev/null 2>&1 || kernel=linux
    local_pkgs=$(pacman -Sl --config /w/pacman.conf wlpreview | awk "{print \$2}")
    # zaklad instalace LuxOS (luxos-installer/files/packages) bez firmwaru, posty a soukromych aplikaci;
    # aplikace na zkouseni (gtk3-demo, xeyes pres XWayland), busybox pro maly koren sandboxu bez pacstrapu
    # (smoke.sh), guest agent pro testy
    pacstrap -C /w/pacman.conf -c $r base lux-engine $kernel sudo nano networkmanager pipewire-jack noto-fonts \
        luxos-desktop plymouth greetd $local_pkgs gtk3-demos xorg-xeyes xorg-xwayland libnotify firefox busybox \
        qemu-guest-agent >/w/pacstrap.log 2>&1 || { tail -30 /w/pacstrap.log; exit 1; }


    echo "/dev/vda / ext4 rw,noatime 0 1" >$r/etc/fstab
    echo luxos-preview >$r/etc/hostname
    printf "127.0.0.1 localhost\n::1 localhost\n127.0.1.1 luxos-preview\n" >$r/etc/hosts
    sed -i -E "s/^#\s*(cs_CZ\.UTF-8\s)/\1/; s/^#\s*(en_US\.UTF-8\s)/\1/" $r/etc/locale.gen
    arch-chroot $r locale-gen >/dev/null
    echo LANG=cs_CZ.UTF-8 >$r/etc/locale.conf
    printf "KEYMAP=cz-qwertz\nXKBLAYOUT=cz,us\nXKBOPTIONS=grp:alt_shift_toggle\n" >$r/etc/vconsole.conf
    ln -sf /usr/share/zoneinfo/Europe/Prague $r/etc/localtime

    groups=wheel
    for g in video audio input lp storage network rfkill sys; do
        grep -q "^$g:" $r/etc/group && groups+=",$g"
    done
    arch-chroot $r useradd -m -G "$groups" -s /usr/bin/lsh -c "LuxOS" luxos
    echo luxos:luxos | arch-chroot $r chpasswd
    passwd -R $r -l root >/dev/null
    printf "%%wheel ALL=(ALL:ALL) ALL\nDefaults pwfeedback\n" | install -Dm440 /dev/stdin $r/etc/sudoers.d/10-luxos
    [[ -x $r/usr/lib/luxos/apply-branding ]] && arch-chroot $r /usr/lib/luxos/apply-branding >/dev/null 2>&1 || true

    # sluzby jako instalator, ale prihlaseni pres greetd (luxos-greetd) misto lightdm a bez casovacu site
    while read -r s; do
        case $s in ""|"#"*|lightdm.service|reflector.timer) continue ;; esac
        systemctl --root=$r enable "$s" >/dev/null 2>&1 || true
    done <$r/usr/lib/luxos/services
    systemctl --root=$r enable -f luxos-greetd.service >/dev/null
    systemctl --root=$r enable qemu-guest-agent.service >/dev/null 2>&1 || true
    systemctl --root=$r set-default graphical.target >/dev/null
    systemctl --root=$r mask systemd-networkd-wait-online.service NetworkManager-wait-online.service >/dev/null 2>&1 || true

    kver=$(ls $r/usr/lib/modules | head -1)
    # initramfs se splashem jako instalace (setup-chroot.sh), ale bez autodetect (kontejner nema hardware VM,
    # initramfs musi mit virtio a ext4) a misto kms jen grafika QEMU (-vga std = bochs, virtio-vga): Plymouth
    # kresli od zacatku startu (VM startuje pres -kernel bez EFI framebufferu)
    printf "MODULES=(bochs virtio_gpu)\nHOOKS=(base systemd plymouth modconf keyboard sd-vconsole block filesystems fsck)\nCOMPRESSION=zstd\n" \
        >$r/etc/mkinitcpio.conf.d/luxos.conf
    arch-chroot $r mkinitcpio -k "$kver" -g /boot/initramfs-preview.img >/w/mkinitcpio.log 2>&1
    grep -q "Theme=luxos" $r/etc/plymouth/plymouthd.conf || { echo "no LuxOS splash theme" >&2; exit 1; }
    cp $r/boot/vmlinuz-$kernel /w/vmlinuz
    cp $r/boot/initramfs-preview.img /w/initramfs.img
    pacman -Q --root $r --dbpath $r/var/lib/pacman >/w/packages.txt 2>/dev/null \
        || ls $r/var/lib/lux/local >/w/packages.txt
    du -sh --exclude=proc $r | cut -f1 >/w/size.txt
    rm -f /w/root.img
    mkfs.ext4 -q -L luxos -d $r /w/root.img 24G
    rm -rf --one-file-system $r
'
qemu-img convert -c -O qcow2 "$work/root.img" "$dir/base.qcow2.new"
mv "$work/vmlinuz" "$work/initramfs.img" "$work/packages.txt" "$dir/"
mv "$dir/base.qcow2.new" "$dir/base.qcow2"
rm -f "$dir/disk.qcow2"
install -m755 "$here/start.sh" "$dir/start.sh"
install -m644 "$here/README.txt" "$dir/README.txt"
echo "rootfs $(cat "$work/size.txt"), image $(du -h "$dir/base.qcow2" | cut -f1)"
rm -rf "$work"
echo "$dir"
