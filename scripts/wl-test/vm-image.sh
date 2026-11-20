#!/bin/bash
# Minimalni obraz Arch Linuxu s labwc pro VM matici (vm-matrix.sh).
#   vm-image.sh [BALIK.pkg.tar.zst..]   navic mistni baliky, napr. wlroots0.20 a luxcomp z build.sh one
# Stavi se v kontejneru (pacstrap jako u build.sh), vysledek: $WLT_OUT/vm/{root.img,vmlinuz,initramfs.img}
# Root bez hesla s automatickym prihlasenim na tty1 - jen pro jednorazove testovaci VM s -snapshot.
set -euo pipefail
here=$(dirname "$(readlink -f "$0")")
repo=$(readlink -f "$here/../..")
out=${WLT_OUT:-$repo/out/wl-test}
vm=$out/vm
image=${WLT_BUILDER_IMAGE:-localhost/luxos-builder}
engine=$(command -v podman || command -v docker) || { echo "podman or docker is required" >&2; exit 1; }

make -s -C "$here" OUT="$out"
"$engine" image exists "$image" 2>/dev/null || "$engine" build -t "$image" -f "$repo/scripts/Containerfile" "$repo/scripts"
mkdir -p "$vm"
rm -rf "$vm/pkgs" && mkdir -p "$vm/pkgs"
(($#)) && cp "$@" "$vm/pkgs/"

"$engine" run --rm --privileged -v "$vm:/vm:z" -v "$out/bin:/wltbin:ro,z" -v "$here/vm-guest:/guest:ro,z" \
    -v "$here/labwc:/labwc:ro,z" "$image" bash -euo pipefail -c '
    r=/rootfs
    mkdir -p $r
    pacman -Sy --noconfirm >/dev/null
    pacstrap -c $r base linux labwc wlroots0.20 wlr-randr grim mesa >/dev/null
    # mistni baliky nahradi ty z Archu, zavislosti se doinstaluji (font pro titulky oken luxcomp)
    if compgen -G "/vm/pkgs/*.pkg.tar.zst" >/dev/null; then
        pacstrap -c -U $r /vm/pkgs/*.pkg.tar.zst >/dev/null
        pacstrap -c $r ttf-dejavu >/dev/null
    fi
    install -Dm755 /wltbin/wlt-client $r/usr/local/bin/wlt-client
    install -Dm755 /guest/wlt-guest $r/usr/local/bin/wlt-guest
    install -Dm644 /guest/autologin.conf $r/etc/systemd/system/getty@tty1.service.d/autologin.conf
    install -Dm644 /guest/bash_profile $r/root/.bash_profile
    mkdir -p $r/root/.config && cp -r /labwc $r/root/.config/labwc
    install -Dm644 /guest/autostart $r/root/.config/labwc/autostart
    echo "/dev/vda / ext4 rw,noatime 0 1" >$r/etc/fstab
    echo wlt-vm >$r/etc/hostname
    passwd -R $r -d root >/dev/null
    # bez cekani na sit a bez zbytecnych sluzeb - rychly start
    systemctl --root=$r mask systemd-networkd-wait-online.service systemd-timesyncd.service >/dev/null 2>&1 || true
    kver=$(ls $r/usr/lib/modules)
    # bez autodetect: kontejner nema hardware VM, initramfs musi mit virtio a ext4
    arch-chroot $r mkinitcpio -k "$kver" -S autodetect -g /boot/initramfs-wlt.img >/dev/null 2>&1
    cp $r/boot/vmlinuz-linux /vm/vmlinuz
    cp $r/boot/initramfs-wlt.img /vm/initramfs.img
    pacman -Q --root $r --dbpath $r/var/lib/pacman >/vm/packages.txt
    rm -f /vm/root.img
    mkfs.ext4 -q -L wltroot -d $r /vm/root.img 4G
'

# QEMU hostitele bez modulu virtio-vga (balicky qemu-hw-display-virtio-* v Archu jsou volitelne):
# moduly stejne verze se stahnou do $WLT_OUT/qemu-mod a vm-matrix.sh je nacte pres QEMU_MODULE_DIR
if ! qemu-system-x86_64 -device help 2>/dev/null | grep -q '"virtio-vga"'; then
    ver=$(basename "$(ls -d /var/lib/{lux,pacman}/local/qemu-base-* 2>/dev/null | head -1)")
    ver=${ver#qemu-base-}
    [[ -n $ver ]] || { echo "Cannot find the host QEMU package version" >&2; exit 1; }
    mod=$out/qemu-mod
    rm -rf "$mod" && mkdir -p "$mod/pkg"
    for p in qemu-hw-display-virtio-gpu qemu-hw-display-virtio-gpu-pci qemu-hw-display-virtio-vga; do
        f=$p-$ver-x86_64.pkg.tar.zst
        curl -fsSL -o "$mod/pkg/$f" "https://archive.archlinux.org/packages/q/$p/$f"
        curl -fsSL -o "$mod/pkg/$f.sig" "https://archive.archlinux.org/packages/q/$p/$f.sig"
    done
    "$engine" run --rm -v "$mod/pkg:/p:ro,z" "$image" bash -euo pipefail -c '
        pacman-key --init >/dev/null 2>&1; pacman-key --populate archlinux >/dev/null 2>&1
        for f in /p/*.zst; do pacman-key --verify "$f.sig" "$f" >/dev/null 2>&1 || { echo "bad signature: $f" >&2; exit 1; }; done'
    for f in "$mod"/pkg/*.zst; do tar --zstd -xf "$f" -C "$mod" usr/lib/qemu; done
    mv "$mod/usr/lib/qemu" "$mod/lib" && rm -rf "$mod/usr"
fi
echo "$vm"
