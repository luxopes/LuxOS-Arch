#!/bin/bash
# LuxOS - sestaveni baliku a ISO (bezi uvnitr Arch kontejneru, viz build.sh)
# Pouziti: container-build.sh [all|packages|apps|iso|one BALIK]
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
# (lux-engine = jadro lux: libalpm a nastroje z pacmanu Arch Linuxu, bez prikazu pacman; potrebuji ho lux, pyalpm i base;
#  gdk-pixbuf2 = nahrada baliku z Archu bez glycinu, obrazky se dekoduji v procesu, luxos-pixbuf-svg = zavadec SVG)
PACKAGES=(lux-engine gdk-pixbuf2 luxos-pixbuf-svg libfprint xfce4-genmon-plugin luxos-keyring luxos-i18n blesh lsh luxos-themes luxos-branding luxos-shell luxos-tweaks luxos-drivers lux luxos-account luxos-sandbox luxos-safe luxos-store luxos-greeter luxdrop luxos-care luxos-guard luxos-printing luxos-desktop luxos-installer
          # Legacy ovladace NVIDIA z AUR (Maxwell/Pascal/Volta 580xx, Kepler 470xx) - jen online, ne v ISO
          nvidia-580xx-utils lib32-nvidia-580xx-utils nvidia-470xx-utils lib32-nvidia-470xx-utils)
# Baliky, ktere se nekopiruji do mistniho repozitare v ISO (velke, potrebuje je jen malo pocitacu;
# instalator je stahuje z online [luxos], viz install_online_drivers v luxos-install)
# (hlavicky jadra jen pro moduly DKMS, napr. NVIDIA - instaluji se spolu s ovladacem)
ISO_ONLINE_ONLY=('*nvidia-[0-9]*xx*' 'linux-luxos-headers-[0-9]*')
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
    # mezipameti Pythonu z testu (py_compile, import skriptu) do balicku nepatri - a "install -t dir/*" na nich selze
    find "$BUILD/$p" -name __pycache__ -type d -prune -exec rm -rf {} +
    chown -R builder: "$BUILD/$p"
    # makepkg bezi s --nodeps (zavislosti na vlastnich balicich), makedepends a checkdepends instalujeme zvlast.
    # Zavislost z vlastniho repozitare (napr. lsl z [luxos-apps] pro luxos-desktop) neni v repozitarich
    # Archu: nainstaluje se balik sestaveny drive v tomto behu (aplikace se stavi pred [luxos]).
    (set +u; depends=(); makedepends=(); checkdepends=(); source "$BUILD/$p/PKGBUILD"
     sync=(); local_pkgs=()
     # depends z repozitaru Archu taky: baliky prevzate z Archu (libfprint, gdk-pixbuf2) proti nim linkuji
     for d in "${depends[@]}"; do
         pacman -Si "${d%%[<>=]*}" &>/dev/null && sync+=("$d")
     done
     for d in "${makedepends[@]}" "${checkdepends[@]}"; do
         n=${d%%[<>=]*}
         if pacman -Si "$n" &>/dev/null; then sync+=("$d"); continue; fi
         f=("$BUILD"/pkgs/*/"$n"-[0-9]*.pkg.tar.zst)
         if [[ -e ${f[0]} ]]; then local_pkgs+=("${f[0]}"); else echo "WARNING: build dependency $d of $p not found" >&2; fi
     done
     ((${#sync[@]})) && { pacman -S --needed --noconfirm "${sync[@]}" >/dev/null || true; }
     ((${#local_pkgs[@]})) && { pacman -U --needed --noconfirm "${local_pkgs[@]}" >/dev/null || true; }
     true)   # bez zavislosti by posledni (( )) vratilo 1 a set -e ukoncil sestaveni
    # Podepsane zdroje (source=...?signed, validpgpkeys): verejne klice z keys/pgp jako v Arch devtools
    if compgen -G "$BUILD/$p/keys/pgp/*.asc" >/dev/null; then
        sudo -u builder env -u GNUPGHOME gpg --batch --quiet --import "$BUILD/$p"/keys/pgp/*.asc
    fi
    (cd "$BUILD/$p" && sudo -u builder env -u GNUPGHOME SRCDEST="$SOURCES" PKGDEST="$dest" \
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
    # Ikony aplikaci pro Obchod LuxOS (aplikace jeste neni nainstalovana): icons/<balik>.png|svg
    local pkgname icon
    mkdir -p "$dir/icons"
    for f in "${files[@]}"; do
        pkgname=$(tar --zstd -xOf "$f" .PKGINFO | awk -F' = ' '$1 == "pkgname" {print $2}' | head -1)
        icon=$(tar --zstd -tf "$f" | grep -E "^usr/share/icons/hicolor/(scalable|512x512|256x256|128x128)/apps/$pkgname\.(svg|png)$" |
               sort | head -1 || true)
        [[ -n $icon ]] && tar --zstd -xOf "$f" "$icon" >"$dir/icons/$pkgname.${icon##*.}"
    done
    msg "Repository [$name]: ${#files[@]} packages in out/repo/$name/$ARCH"
}

# Balicky ve vlastnim formatu LuxOS (.lux): kazdy adresar v lux-packages s lux.json.
# Vystup out/repo/lux: balicky, podpisy, ikony a podepsany index.json pro lux a Obchod.
make_lux_repo() {
    local dir=$REPO/lux d f name icon
    rm -rf "$dir"
    mkdir -p "$dir"
    for d in "$ROOT"/lux-packages/*/; do
        [[ -f $d/lux.json ]] || continue
        msg "Packing ${d%/}"
        bash "$ROOT/packages/lux/lux" pack "${d%/}" "$dir" >/dev/null || exit 1
        # ikona pro Obchod: SVG, jinak nejvetsi PNG ze share/icons
        name=$(jq -r .name "$d/lux.json")
        icon=$(find "$d/share/icons" -name '*.svg' 2>/dev/null | head -1)
        [[ -z $icon ]] && icon=$(find "$d/share/icons" -name '*.png' 2>/dev/null | sort -V | tail -1)
        [[ -n $icon ]] && cp "$icon" "$dir/$name.icon.${icon##*.}"
    done
    python3 - "$dir" <<'PY'
import hashlib, json, os, subprocess, sys
d = sys.argv[1]
pkgs = []
for f in sorted(os.listdir(d)):
    if not f.endswith(".lux"):
        continue
    meta = json.loads(subprocess.run(["tar", "--zstd", "-xOf", os.path.join(d, f), "lux.json"],
                                     capture_output=True, check=True).stdout)
    data = open(os.path.join(d, f), "rb").read()
    entry = {k: meta.get(k) for k in ("name", "title", "version", "release", "arch", "summary", "description", "depends",
                                      "license", "url", "categories") if meta.get(k) is not None}
    entry.update(file=f, size=len(data), sha256=hashlib.sha256(data).hexdigest())
    for ext in ("svg", "png"):
        if os.path.exists(os.path.join(d, f"{meta['name']}.icon.{ext}")):
            entry["icon"] = f"{meta['name']}.icon.{ext}"
    pkgs.append(entry)
json.dump({"format": 1, "packages": pkgs}, open(os.path.join(d, "index.json"), "w"), indent=1, ensure_ascii=False)
PY
    if [[ -n $GPGKEY ]]; then
        for f in "$dir"/*.lux "$dir/index.json"; do
            [[ -e $f ]] && gpg --batch --yes --detach-sign --no-armor -u "$GPGKEY" "$f"
        done
    fi
    msg "Repository [lux]: $(find "$dir" -name '*.lux' | wc -l) packages in out/repo/lux"
}

# lux-engine musi drzet krok s pacmanem Arch Linuxu: pyalpm a dalsi baliky z Archu se sestavuji
# proti jeho libalpm.so. Kontejner je po -Syu aktualni Arch, takze jeho [core]/pacman je Arch.
check_pacman_version() {
    local arch ours
    arch=$(LC_ALL=C pacman -Si core/pacman 2>/dev/null | awk -F': ' '/^Version/ {print $2; exit}')
    ours=$(set +u; source "$ROOT/packages/lux-engine/PKGBUILD"; echo "$pkgver-$pkgrel")
    [[ -n $arch ]] || { msg "WARNING: cannot read the Arch Linux pacman version"; return 0; }
    if (($(vercmp "$arch" "$ours") > 0)); then
        msg "WARNING: Arch Linux has pacman $arch, lux-engine is $ours"
        printf '    Update packages/lux-engine/PKGBUILD from the Arch tag (see its header) before publishing.\n' >&2
    fi
}

build_packages() {
    msg "Updating build container"
    pacman -Syu --noconfirm --needed >/dev/null
    check_pacman_version

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
    # Jadro LuxOS se stavi na GitHub Actions (luxopes/luxos-kernel); build.sh ho stahne a overi
    # (scripts/fetch-kernel.sh: SHA256SUMS + attestace puvodu) do out/kernel, tady se jen podepise.
    compgen -G "$OUT/kernel/linux-luxos-[0-9]*.pkg.tar.zst" >/dev/null ||
        { echo "Missing out/kernel/linux-luxos-*.pkg.tar.zst (scripts/fetch-kernel.sh)" >&2; exit 1; }
    install -m644 "$OUT"/kernel/linux-luxos-*.pkg.tar.zst "$BUILD/pkgs/luxos/"

    make_repo luxos "$BUILD/pkgs/luxos"
    make_repo luxos-apps "$BUILD/pkgs/luxos-apps"
    make_lux_repo
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
    # pacman.conf profilu = konfigurace mkarchiso na tomto hostiteli (ne live system)
    sed -i "s|@LUXOS_REPO@|$REPO|" "$PROFILE/pacman.conf"
    # ISO pojmenovane podle verze LuxOS (packages/luxos-branding/files/version): luxos-0.9.0-x86_64.iso
    local VERSION
    VERSION=$(. "$ROOT/packages/luxos-branding/files/version" && echo "$VERSION")
    sed -i "s|^iso_version=.*|iso_version=\"$VERSION\"|" "$PROFILE/profiledef.sh"
    # Starsi sestaveni vlastnich baliku (stejna verze, jiny obsah) z cache pacmanu pryc
    local f
    for f in "$REPO"/*/"$ARCH"/*.pkg.tar.zst; do
        rm -f "/var/cache/pacman/pkg/${f##*/}" "/var/cache/pacman/pkg/${f##*/}.sig"
    done
    # Lokalni repozitar i v live systemu (instalator z nej instaluje baliky LuxOS)
    mkdir -p "$PROFILE/airootfs/opt/luxos-repo"
    cp -a "$REPO"/. "$PROFILE/airootfs/opt/luxos-repo/"
    iso_drop_online_only "$PROFILE/airootfs/opt/luxos-repo/luxos/$ARCH"
    rsvg-convert "$ROOT/packages/luxos-branding/files/syslinux/splash.svg" -o "$PROFILE/syslinux/splash.png"

    msg "Building ISO (mkarchiso)"
    mkarchiso -v -w "$WORK" -o "$OUT" "$PROFILE"
    cleanup_work
    ls -lh "$OUT"/*.iso
}

# Z kopie repozitaru [luxos] v ISO odebere baliky jen pro online instalaci (ISO_ONLINE_ONLY).
# Live system ma pro [luxos] SigLevel Optional: neplatny podpis databaze se smaze.
iso_drop_online_only() {  # iso_drop_online_only ADRESAR_REPOZITARE
    local dir=$1 f n pat
    local -a names=() files=()
    shopt -s nullglob
    for pat in "${ISO_ONLINE_ONLY[@]}"; do files+=("$dir"/$pat.pkg.tar.zst); done
    for f in "${files[@]}"; do
        n=$(tar --zstd -xOf "$f" .PKGINFO | awk -F' = ' '$1 == "pkgname" {print $2; exit}')
        [[ -n $n ]] && names+=("$n")
        rm -f "$f" "$f.sig" "$dir/icons/$n".*
    done
    shopt -u nullglob
    ((${#names[@]})) || return 0
    repo-remove -q "$dir/luxos.db.tar.gz" "${names[@]}"
    rm -f "$dir"/luxos.db.sig "$dir"/luxos.db.tar.gz.sig "$dir"/luxos.files.sig "$dir"/luxos.files.tar.gz.sig
    msg "ISO: left out of the local [luxos] repository (installed online): ${names[*]}"
}

# Jeden balik z packages/ (nebo packages/apps/) do out/single bez prestavby repozitare - na zkousku
build_single() {
    local p=${1:?package name} src
    src=$ROOT/packages/$p
    [[ -f $src/PKGBUILD ]] || src=$ROOT/packages/apps/$p
    [[ -f $src/PKGBUILD ]] || { echo "No package $p" >&2; exit 2; }
    msg "Updating build container"
    pacman -Syu --noconfirm --needed >/dev/null
    rm -rf "$BUILD"
    mkdir -p "$SOURCES" "$BUILD/pkgs/single" "$OUT/single"
    chown -R builder: "$SOURCES" "$BUILD"
    build_one "$src" "$BUILD/pkgs/single"
    chown -R root: "$SOURCES"
    install -m644 "$BUILD"/pkgs/single/*.pkg.tar.zst "$OUT/single/"
    ls -lh "$OUT"/single/
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
    one)      build_single "${2:-}" ;;
    *) echo "Usage: $0 [all|packages|apps|iso|one PACKAGE]" >&2; exit 2 ;;
esac
