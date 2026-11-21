#!/bin/bash
# LuxOS Desktop pro jine distribuce (Fedora, Arch; dalsi Debian/Ubuntu) - sestaveni
#
#   desktop-standalone/build.sh [stage|rpm|pacman]
#
# Jediny zdroj kodu: desktop se sestavi z PKGBUILDu LuxOS v packages/ (luxos-i18n, luxos-themes,
# luxos-desktop a rofi), ne z kopie. Funkce prepare/build/package ze PKGBUILDu spusti maly
# "mini-makepkg" nize; pak se odeberou systemove casti LuxOS (prune.list), upravi se cesty knihoven
# (Fedora: lib64) a pridaji se soubory relace "LuxOS Desktop". Vysledek:
#   stage   jen strom souboru ve work/stage (vychozi)
#   rpm     balicek RPM lux-desktop (Fedora) ve work/out
#   pacman  balicek lux-desktop pro pacman (Arch a odvozene) ve work/out
#
# Nic neinstaluje a nespousti jako root. Zavislosti pro sestaveni: deps/<distribuce>-build.txt.
# Promenne: LUXD_WORK (pracovni adresar, vychozi desktop-standalone/work), LUXD_JOBS.
set -euo pipefail

HERE=$(dirname "$(readlink -f "$0")")
ROOT=$(readlink -f "$HERE/..")
PK=$ROOT/packages
WORK=${LUXD_WORK:-$HERE/work}
STAGE=$WORK/stage
CACHE=$WORK/cache
SHIM=$WORK/shim
OUT=$WORK/out
mode=${1:-stage}

LSL_VER=0.10.15
LSL_SHA=db0709defae0309bd893bebe7a84e7d4aeaa483cbdeaca8f099626819aa44317
# soukrome programy jen pro relaci LuxOS Desktop (upravena rofi pro Launchpad); system se nemeni
PRIV=/usr/lib/lux-desktop

say() { printf '\033[1m==> %s\033[0m\n' "$*" >&2; }
die() { printf 'lux-desktop build: %s\n' "$*" >&2; exit 1; }

[[ $EUID -ne 0 ]] || die "do not run the build as root (install.sh asks for sudo only to install)"
case $mode in stage|rpm|pacman) ;; *) die "unknown mode '$mode' (stage, rpm, pacman)" ;; esac

# Adresar knihoven GTK/Xfce na tomto systemu: /usr/lib (Arch, Debian multiarch reseno jinde) nebo /usr/lib64
LIBDIR=$(pkg-config --variable=libdir gtk+-3.0 2>/dev/null || echo /usr/lib)
[[ -d $LIBDIR ]] || die "gtk3 development files missing (pkg-config gtk+-3.0)"

rm -rf "$STAGE" "$WORK/build"
mkdir -p "$STAGE" "$CACHE" "$SHIM" "$OUT" "$WORK/build"

# ---- shimy: prikazy, ktere PKGBUILDy LuxOS predpokladaji z Archu -------------------------------
# python (Fedora ma jen python3), arch-meson (vychozi volby mesonu Archu, prefix nastavitelny)
command -v python >/dev/null || ln -sf "$(command -v python3)" "$SHIM/python"
cat >"$SHIM/arch-meson" <<'EOF'
#!/bin/bash
exec meson setup --prefix="${LUXD_MESON_PREFIX:-/usr}" --libexecdir=lib --sbindir=bin --buildtype=plain \
    --auto-features=enabled --wrap-mode=nodownload -Db_pie=true ${LUXD_MESON_OPTS:-} "$@"
EOF
chmod +x "$SHIM/arch-meson"

# prekladac LSL (MIT, https://lsl.lux-ai.cz) - programy desktopu jsou z vetsiny v LSL
lsl_tar=$CACHE/lsl-$LSL_VER.tar.gz
if [[ ! -f $lsl_tar ]]; then
    say "Downloading LSL $LSL_VER"
    curl -fL --retry 3 -o "$lsl_tar.part" "https://lsl.lux-ai.cz/downloads/lsl-$LSL_VER-linux-x86_64.tar.gz"
    mv "$lsl_tar.part" "$lsl_tar"
fi
echo "$LSL_SHA  $lsl_tar" | sha256sum -c --quiet - || die "LSL download has a wrong checksum"
rm -rf "$WORK/lsl" && mkdir -p "$WORK/lsl" && tar -xzf "$lsl_tar" -C "$WORK/lsl"
PATH="$SHIM:$WORK/lsl/lsl-$LSL_VER/bin:$PATH"
export PATH CARCH=x86_64 CPPFLAGS="${CPPFLAGS:-}" CFLAGS="${CFLAGS:--O2 -pipe -fno-plt}" LDFLAGS="${LDFLAGS:--Wl,-O1,--as-needed}"
export MAKEFLAGS="-j${LUXD_JOBS:-$(nproc)}" SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH:-$(git -C "$ROOT" log -1 --format=%ct 2>/dev/null || date +%s)}

# ---- mini-makepkg ------------------------------------------------------------------------------
# Stazeni zdroju podle source=() / sha256sums=() (git+URL#tag|commit=, https, mistni soubory),
# rozbaleni archivu (mimo noextract) a spusteni prepare/build/package v podshellu.
fetch_sources() {   # $1 = srcdir; promenne z PKGBUILDu
    local i entry name url frag ref kind sum
    for i in "${!source[@]}"; do
        entry=${source[$i]}
        name=${entry%%::*}; url=${entry#*::}
        [[ $entry == *::* ]] || name=""
        sum=${sha256sums[$i]:-SKIP}
        case $url in
            git+*)
                url=${url#git+}; frag=""
                [[ $url == *#* ]] && { frag=${url#*#}; url=${url%%#*}; }
                [[ -n $name ]] || { name=${url##*/}; name=${name%.git}; }
                local mirror=$CACHE/git/$name.git
                if [[ -d $mirror ]]; then git -C "$mirror" fetch -q --tags origin '+refs/heads/*:refs/heads/*' || true
                else mkdir -p "$CACHE/git"; git clone -q --mirror "$url" "$mirror"; fi
                git clone -q "$mirror" "$1/$name"
                if [[ -n $frag ]]; then
                    kind=${frag%%=*}; ref=${frag#*=}
                    case $kind in tag|commit|branch) git -C "$1/$name" checkout -q "$ref" ;; esac
                fi
                ;;
            http://*|https://*)
                [[ -n $name ]] || name=${url##*/}
                if [[ ! -f $CACHE/$name ]]; then
                    curl -fL --retry 3 -o "$CACHE/$name.part" "$url" && mv "$CACHE/$name.part" "$CACHE/$name"
                fi
                if [[ $sum != SKIP ]]; then
                    echo "$sum  $CACHE/$name" | sha256sum -c --quiet - || die "$name: wrong checksum"
                fi
                ln -sf "$CACHE/$name" "$1/$name"
                if [[ " ${noextract[*]:-} " != *" $name "* ]]; then
                    case $name in *.tar|*.tar.*|*.tgz|*.zip) bsdtar -xf "$1/$name" -C "$1" ;; esac
                fi
                ;;
            *) ln -sf "$startdir/$url" "$1/${url##*/}" ;;
        esac
    done
}

# run_pkgbuild <balik v packages/> <cilovy pkgdir>
run_pkgbuild() {
    local name=$1 dest=$2
    say "Building $name (packages/$name/PKGBUILD)"
    (
        set -euo pipefail
        startdir=$PK/$name
        srcdir=$WORK/build/$name
        pkgdir=$dest
        mkdir -p "$srcdir" "$pkgdir"
        source=(); sha256sums=(); noextract=()
        # shellcheck disable=SC1091
        source "$startdir/PKGBUILD"
        pkgname=${pkgname:-$name}
        fetch_sources "$srcdir"
        cd "$srcdir"
        if declare -F prepare >/dev/null; then (cd "$srcdir" && prepare); fi
        if declare -F build >/dev/null; then (cd "$srcdir" && build); fi
        (cd "$srcdir" && package)
    )
}

# ---- 1. preklady, motivy, desktop ----------------------------------------------------------------
run_pkgbuild luxos-i18n "$STAGE"

# Branding: jen logo, ikony aplikaci LuxOS a tapety (bez Plymouth, os-release a zavadece)
say "Branding (logo, icons, wallpapers)"
(
    f=$PK/luxos-branding/files r=$WORK/build/branding
    mkdir -p "$r"
    install -Dm644 "$f/logo/luxos-logo.svg" "$STAGE/usr/share/icons/hicolor/scalable/apps/luxos-logo.svg"
    install -Dm644 "$f/logo/luxos-logo-symbolic.svg" "$STAGE/usr/share/icons/hicolor/symbolic/apps/luxos-logo-symbolic.svg"
    install -Dm644 -t "$STAGE/usr/share/icons/hicolor/symbolic/apps" "$f"/symbolic/*.svg
    for s in 16 24 32 48 64 128 256 512; do
        rsvg-convert -w $s -h $s "$f/logo/luxos-logo.svg" -o "$r/logo-$s.png"
        install -Dm644 "$r/logo-$s.png" "$STAGE/usr/share/icons/hicolor/${s}x$s/apps/luxos-logo.png"
    done
    rsvg-convert -w 256 -h 256 "$f/logo/luxos-logo-white.svg" -o "$r/logo-white.png"
    install -Dm644 "$r/logo-256.png" "$STAGE/usr/share/pixmaps/luxos-logo.png"
    install -Dm644 -t "$STAGE/usr/share/luxos/logo" "$f"/logo/*.svg "$f/logo/luxos-logo.png" "$r/logo-white.png"
    for i in "$f"/icons/*.png; do
        install -Dm644 "$i" "$STAGE/usr/share/icons/hicolor/512x512/apps/${i##*/}"
        for s in 48 64 128 256; do
            magick "$i" -filter Lanczos -resize ${s}x$s "$r/icon-$s-${i##*/}"
            install -Dm644 "$r/icon-$s-${i##*/}" "$STAGE/usr/share/icons/hicolor/${s}x$s/apps/${i##*/}"
        done
    done
    install -Dm644 -t "$STAGE/usr/share/backgrounds/luxos" "$f"/wallpapers/*.jpg
    ln -sf luxos-flow-dark.jpg "$STAGE/usr/share/backgrounds/luxos/luxos-dark.jpg"
    ln -sf luxos-flow-light.jpg "$STAGE/usr/share/backgrounds/luxos/luxos-light.jpg"
    install -Dm644 "$f/version" "$STAGE/usr/lib/luxos/version"
)

run_pkgbuild luxos-themes "$STAGE"
run_pkgbuild luxos-desktop "$STAGE"
# Textovy editor a Terminal LuxOS (vychozi aplikace desktopu, male programy v C)
run_pkgbuild luxos-text "$STAGE"
run_pkgbuild luxos-terminal "$STAGE"
# vychozi terminal jen v relaci LuxOS Desktop (/etc/xdg/luxos je v XDG_CONFIG_DIRS jen tam)
mv "$STAGE/etc/xdg/xdg-terminals.list" "$STAGE/etc/xdg/luxos/xdg-terminals.list"

# ---- 2. upravena rofi (Launchpad: -hover-no-scroll, -custom-exit, -custom-resort) jen pro relaci ----
LUXD_MESON_PREFIX=$PRIV/rofi LUXD_MESON_OPTS="-Dwayland=disabled -Dcheck=disabled -Dimdkit=false" \
    run_pkgbuild rofi "$WORK/rofi-stage"
mkdir -p "$STAGE$PRIV/bin"
cp -a "$WORK/rofi-stage$PRIV/rofi" "$STAGE$PRIV/"
rm -rf "$STAGE$PRIV/rofi/include" "$STAGE$PRIV/rofi/lib/pkgconfig" "$STAGE$PRIV/rofi/share/man"
ln -sf ../rofi/bin/rofi "$STAGE$PRIV/bin/rofi"
install -Dm644 "$WORK/rofi-stage/usr/share/licenses/rofi/COPYING" "$STAGE/usr/share/licenses/lux-desktop/rofi.COPYING"
# systemova konfigurace rofi LuxOS jen pro tuto rofi (/etc/rofi.rasi by zmenila rofi celeho systemu)
mkdir -p "$STAGE$PRIV/rofi/etc"
mv "$STAGE/etc/rofi.rasi" "$STAGE$PRIV/rofi/etc/rofi.rasi"

# ---- 3. odebrat systemove casti LuxOS ------------------------------------------------------------
say "Removing LuxOS system parts (prune.list)"
(
    cd "$STAGE"
    shopt -s nullglob globstar
    while read -r pat; do
        [[ -z $pat || $pat == \#* ]] && continue
        # shellcheck disable=SC2086
        for p in $pat; do rm -rf -- "$p"; done
    done <"$HERE/prune.list"
)

# Aplikace LuxOS jen v relacich Xfce (LuxOS Desktop), ne v nabidce GNOME/KDE stejneho uzivatele
for d in "$STAGE"/usr/share/applications/*.desktop; do
    grep -qE '^(OnlyShowIn|NotShowIn)=' "$d" || sed -i '/^\[Desktop Entry\]/a OnlyShowIn=XFCE;' "$d"
done

# ---- 4. cesty knihoven (Fedora: /usr/lib64) ---------------------------------------------------
if [[ $LIBDIR != /usr/lib ]]; then
    say "Moving GTK modules and panel plugins to $LIBDIR"
    mkdir -p "$STAGE$LIBDIR/gtk-3.0/modules"
    mv "$STAGE"/usr/lib/gtk-3.0/modules/*.so "$STAGE$LIBDIR/gtk-3.0/modules/"
    rmdir -p "$STAGE/usr/lib/gtk-3.0/modules" 2>/dev/null || true
fi
# lehka horni lista: xfce4-panel hleda moduly v <prefix>/<lib nebo lib64>/xfce4/panel/plugins
[[ ${LIBDIR##*/} == lib ]] || ln -sfn lib "$STAGE/usr/lib/luxos/panel/${LIBDIR##*/}"
# odkazy na pluginy Xfce v lehke horni liste: na skutecne umisteni v tomto systemu
xfce_plugins=$(pkg-config --variable=libdir libxfce4panel-2.0 2>/dev/null || echo "$LIBDIR")/xfce4/panel/plugins
for l in "$STAGE"/usr/lib/luxos/panel/lib/xfce4/panel/plugins/lib{genmon,systray}.so; do
    [[ -L $l ]] && ln -sfn "$xfce_plugins/${l##*/}" "$l"
done
# setric obrazovky: xfce4-screensaver spousti jen programy ze sve slozky (Fedora: libexec)
ss_dir=$(pkg-config --variable=privlibexecdir libxfce4-screensaver 2>/dev/null || true)
if [[ -z $ss_dir ]]; then
    for c in /usr/libexec/xfce4-screensaver /usr/lib/xfce4-screensaver /usr/lib64/xfce4-screensaver; do
        [[ -d $c ]] && { ss_dir=$c; break; }
    done
fi
if [[ -n $ss_dir && $ss_dir != /usr/lib/xfce4-screensaver && -e $STAGE/usr/lib/xfce4-screensaver/luxos ]]; then
    install -Dm755 "$STAGE/usr/lib/xfce4-screensaver/luxos" "$STAGE$ss_dir/luxos"
    rm -rf "$STAGE/usr/lib/xfce4-screensaver"
fi

# ---- 5. relace "LuxOS Desktop" ------------------------------------------------------------------
say "Session files"
install -Dm755 "$HERE/session/lux-desktop-session" "$STAGE$PRIV/lux-desktop-session"
install -Dm644 "$HERE/session/lux-desktop.desktop" "$STAGE/usr/share/xsessions/lux-desktop.desktop"
# Dock: vychozi polozky LuxOS (v LuxOS z /etc/skel) bez LuxAI a Obchodu LuxOS; relace je zkopiruje
# uzivateli pri prvnim prihlaseni
grep -vE "'(luxai|luxos-store)\.dockitem', " "$PK/luxos-desktop/files/dconf/10-luxos" \
    | install -Dm644 /dev/stdin "$STAGE$PRIV/dconf-defaults"
install -dm755 "$STAGE$PRIV/plank-launchers"
for d in "$PK"/luxos-desktop/files/skel/.config/plank/dock1/launchers/*.dockitem; do
    case ${d##*/} in luxai.dockitem|luxos-store.dockitem) continue ;; esac
    # LuxOS: kratke nazvy aplikaci v /var/lib/luxos/apps (jen v LuxOS) - jinde .desktop distribuce
    sed 's#/var/lib/luxos/apps/applications/#/usr/share/applications/#' "$d" \
        | install -Dm644 /dev/stdin "$STAGE$PRIV/plank-launchers/${d##*/}"
done
install -Dm644 "$ROOT/LICENSE" "$STAGE/usr/share/licenses/lux-desktop/LICENSE"
install -Dm644 "$HERE/README.md" "$STAGE/usr/share/doc/lux-desktop/README.md"
version=$(. "$PK/luxos-branding/files/version"; echo "$VERSION")
commit=$(git -C "$ROOT" rev-parse --short=10 HEAD 2>/dev/null || echo unknown)
printf 'VERSION=%s\nCOMMIT=%s\n' "$version" "$commit" >"$STAGE$PRIV/version"

say "Stage ready: $STAGE ($(du -sh "$STAGE" | cut -f1))"

# ---- 6. nativni balicek ------------------------------------------------------------------------
pkgver=${version}.$(date -u -d "@$SOURCE_DATE_EPOCH" +%Y%m%d)
case $mode in
    rpm)    "$HERE/package-rpm.sh" "$STAGE" "$pkgver" "$commit" "$OUT" ;;
    pacman) "$HERE/package-pacman.sh" "$STAGE" "$pkgver" "$commit" "$OUT" ;;
esac
