#!/bin/bash
# LuxOS - sestaveni baliku a ISO (bezi uvnitr Arch kontejneru, viz build.sh)
# Pouziti: container-build.sh [all|packages|iso]
set -euo pipefail

ROOT=/luxos
OUT=$ROOT/out
REPO=$OUT/repo
SOURCES=$OUT/sources
BUILD=/tmp/luxos-build
WORK=/tmp/luxos-work
PROFILE=/tmp/luxos-profile
target=${1:-all}

# Poradi: zavislosti vlastnich baliku prvni
PACKAGES=(blesh lsl lsh luxos-themes luxos-branding luxos-shell luxos-tweaks luxos-drivers lux luxos-desktop luxos-installer)

msg() { printf '\n\e[1;38;2;167;123;255m==> %s\e[0m\n' "$*"; }

build_packages() {
    msg "Updating build container"
    pacman -Syu --noconfirm --needed >/dev/null

    mkdir -p "$REPO" "$SOURCES" "$BUILD/pkgs"
    chown -R builder: "$SOURCES" "$BUILD"
    rm -f "$REPO"/*.pkg.tar.zst "$REPO"/luxos.*

    local p
    for p in "${PACKAGES[@]}"; do
        msg "Building package $p"
        rm -rf "${BUILD:?}/$p"
        cp -r "$ROOT/packages/$p" "$BUILD/$p"
        chown -R builder: "$BUILD/$p"
        # makepkg bezi s --nodeps (zavislosti na vlastnich balicich), makedepends instalujeme zvlast
        (set +u; makedepends=(); source "$BUILD/$p/PKGBUILD"; ((${#makedepends[@]})) && pacman -S --needed --noconfirm "${makedepends[@]}" >/dev/null || true)
        (cd "$BUILD/$p" && sudo -u builder env SRCDEST="$SOURCES" PKGDEST="$BUILD/pkgs" \
            makepkg --force --nodeps --noconfirm --cleanbuild)
    done
    chown -R root: "$SOURCES"

    install -m644 "$BUILD"/pkgs/*.pkg.tar.zst "$REPO/"
    repo-add -q -n "$REPO/luxos.db.tar.gz" "$REPO"/*.pkg.tar.zst
    msg "Repository: $(ls "$REPO"/*.pkg.tar.zst | wc -l) packages in out/repo"
}

build_iso() {
    [[ -f $REPO/luxos.db.tar.gz ]] || { echo "Build packages first" >&2; exit 1; }
    msg "Preparing archiso profile"
    cleanup_work
    rm -rf "$PROFILE"
    cp -a "$ROOT/archiso" "$PROFILE"
    sed -i "s|@LUXOS_REPO@|$REPO|" "$PROFILE/pacman.conf"
    # Lokalni repozitar i v live systemu (instalator z nej instaluje baliky LuxOS)
    mkdir -p "$PROFILE/airootfs/opt/luxos-repo"
    cp -a "$REPO"/. "$PROFILE/airootfs/opt/luxos-repo/"
    rsvg-convert "$ROOT/packages/luxos-branding/files/syslinux/splash.svg" -o "$PROFILE/syslinux/splash.png"

    msg "Building ISO (mkarchiso)"
    mkarchiso -v -w "$WORK" -o "$OUT" "$PROFILE"
    cleanup_work
    ls -lh "$OUT"/*.iso
}

# Pripadne zbyle pripojeni (dev, proc...) odpojit pred mazanim pracovniho adresare
cleanup_work() {
    findmnt -rno TARGET | grep "^$WORK/" | sort -r | xargs -r umount -l || true
    rm -rf --one-file-system "$WORK"
}

case $target in
    packages) build_packages ;;
    iso)      build_iso ;;
    all)      build_packages; build_iso ;;
    *) echo "Usage: $0 [all|packages|iso]" >&2; exit 2 ;;
esac
