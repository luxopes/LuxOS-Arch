#!/bin/bash
# LuxOS - sestaveni baliku a ISO (bezi uvnitr Arch kontejneru, viz build.sh)
# Pouziti: container-build.sh [all|packages|apps|iso]
set -euo pipefail

ROOT=/luxos
OUT=$ROOT/out
REPO=$OUT/repo
SOURCES=$OUT/sources
BUILD=/tmp/luxos-build
WORK=/tmp/luxos-work
PROFILE=/tmp/luxos-profile
target=${1:-all}

# Repozitar [luxos]: system LuxOS, poradi = zavislosti vlastnich baliku prvni
PACKAGES=(luxos-keyring luxos-i18n blesh lsh luxos-themes luxos-branding luxos-shell luxos-tweaks luxos-drivers lux luxos-store luxos-desktop luxos-installer)
# Repozitar [luxos-apps]: aplikace ke stazeni (kazdy adresar v packages/apps)
mapfile -t APPS < <(find "$ROOT/packages/apps" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' 2>/dev/null | sort)
ARCH=x86_64

msg() { printf '\n\e[1;38;2;167;123;255m==> %s\e[0m\n' "$*"; }

# Podpisovy klic (build.sh pripoji ~/.local/share/luxos/signing do /signing)
GPGKEY=
setup_signing() {
    [[ -d /signing ]] || { msg "No signing key - packages will be unsigned"; return; }
    export GNUPGHOME=/tmp/luxos-gnupg
    rm -rf "$GNUPGHOME"
    cp -a /signing "$GNUPGHOME"
    chmod 700 "$GNUPGHOME"
    GPGKEY=$(gpg --list-secret-keys --with-colons | awk -F: '/^fpr/{print $10; exit}')
    [[ -n $GPGKEY ]] || { echo "No secret key in /signing" >&2; exit 1; }
    msg "Signing with key $GPGKEY"
}

build_one() {  # build_one ADRESAR_BALIKU CIL_PKGDEST
    local src=$1 dest=$2 p=${1##*/}
    msg "Building package $p"
    rm -rf "${BUILD:?}/$p"
    cp -r "$src" "$BUILD/$p"
    chown -R builder: "$BUILD/$p"
    # makepkg bezi s --nodeps (zavislosti na vlastnich balicich), makedepends instalujeme zvlast
    (set +u; makedepends=(); source "$BUILD/$p/PKGBUILD"; ((${#makedepends[@]})) && pacman -S --needed --noconfirm "${makedepends[@]}" >/dev/null || true)
    (cd "$BUILD/$p" && sudo -u builder env SRCDEST="$SOURCES" PKGDEST="$dest" \
        makepkg --force --nodeps --noconfirm --cleanbuild)
}

make_repo() {  # make_repo NAZEV ADRESAR_S_BALIKY
    local name=$1 pkgs=$2 dir=$REPO/$1/$ARCH f
    rm -rf "$dir"
    mkdir -p "$dir"
    shopt -s nullglob
    local files=("$pkgs"/*.pkg.tar.zst)
    shopt -u nullglob
    if ((${#files[@]})); then
        install -m644 "${files[@]}" "$dir/"
        if [[ -n $GPGKEY ]]; then
            for f in "$dir"/*.pkg.tar.zst; do
                gpg --batch --yes --detach-sign --no-armor -u "$GPGKEY" "$f"
            done
            repo-add -q -n -s -k "$GPGKEY" "$dir/$name.db.tar.gz" "$dir"/*.pkg.tar.zst
        else
            repo-add -q -n "$dir/$name.db.tar.gz" "$dir"/*.pkg.tar.zst
        fi
    else
        # Prazdny repozitar (zatim bez aplikaci) - pacman ho musi umet synchronizovat
        for f in db files; do
            bsdtar -czf "$dir/$name.$f.tar.gz" -T /dev/null
            ln -sf "$name.$f.tar.gz" "$dir/$name.$f"
            [[ -n $GPGKEY ]] && gpg --batch --yes --detach-sign --no-armor -u "$GPGKEY" "$dir/$name.$f.tar.gz" \
                && ln -sf "$name.$f.tar.gz.sig" "$dir/$name.$f.sig"
        done
    fi
    msg "Repository [$name]: ${#files[@]} packages in out/repo/$name/$ARCH"
}

build_packages() {
    msg "Updating build container"
    pacman -Syu --noconfirm --needed >/dev/null

    setup_signing
    rm -rf "$BUILD"
    mkdir -p "$SOURCES" "$BUILD/pkgs/luxos" "$BUILD/pkgs/luxos-apps"
    chown -R builder: "$SOURCES" "$BUILD"
    rm -rf "$REPO"
    mkdir -p "$REPO"

    local p
    for p in "${APPS[@]}"; do
        build_one "$ROOT/packages/apps/$p" "$BUILD/pkgs/luxos-apps"
    done
    for p in "${PACKAGES[@]}"; do
        build_one "$ROOT/packages/$p" "$BUILD/pkgs/luxos"
    done
    chown -R root: "$SOURCES"

    make_repo luxos "$BUILD/pkgs/luxos"
    make_repo luxos-apps "$BUILD/pkgs/luxos-apps"
}

# Jen repozitar [luxos-apps] (packages/apps/*): [luxos] v out/repo zustava, jak je
build_apps() {
    msg "Updating build container"
    pacman -Syu --noconfirm --needed >/dev/null

    setup_signing
    rm -rf "$BUILD"
    mkdir -p "$SOURCES" "$BUILD/pkgs/luxos-apps" "$REPO"
    chown -R builder: "$SOURCES" "$BUILD"

    local p
    for p in "${APPS[@]}"; do
        build_one "$ROOT/packages/apps/$p" "$BUILD/pkgs/luxos-apps"
    done
    chown -R root: "$SOURCES"

    make_repo luxos-apps "$BUILD/pkgs/luxos-apps"
}

build_iso() {
    [[ -f $REPO/luxos/$ARCH/luxos.db.tar.gz ]] || { echo "Build packages first" >&2; exit 1; }
    msg "Preparing archiso profile"
    cleanup_work
    rm -rf "$PROFILE"
    cp -a "$ROOT/archiso" "$PROFILE"
    sed -i "s|@LUXOS_REPO@|$REPO|" "$PROFILE/pacman.conf"
    # Starsi sestaveni vlastnich baliku (stejna verze, jiny obsah) z cache pacmanu pryc
    local f
    for f in "$REPO"/*/"$ARCH"/*.pkg.tar.zst; do
        rm -f "/var/cache/pacman/pkg/${f##*/}" "/var/cache/pacman/pkg/${f##*/}.sig"
    done
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
    apps)     build_apps ;;
    iso)      build_iso ;;
    all)      build_packages; build_iso ;;
    *) echo "Usage: $0 [all|packages|apps|iso]" >&2; exit 2 ;;
esac
