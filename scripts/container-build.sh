#!/bin/bash
# LuxOS - sestaveni baliku a ISO (bezi uvnitr Arch kontejneru, viz build.sh)
# Pouziti: container-build.sh [all|packages|apps|drivers|iso|one BALIK]
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
#  gdk-pixbuf2 = nahrada baliku z Archu bez glycinu, obrazky se dekoduji v procesu, luxos-pixbuf-svg = zavadec SVG,
#  vte3 = VTE z Archu s obrazky SIXEL pro luxos-terminal,
#  adcli + realmd = overene kopie z AUR pro luxos-domain - pripojeni k domene Active Directory)
PACKAGES=(lux-engine gdk-pixbuf2 luxos-pixbuf-svg libfprint xfce4-genmon-plugin rofi vte3 xfce4-notifyd xfce4-screensaver xfce4-whiskermenu-plugin luxos-keyring luxos-i18n blesh lsh luxos-themes luxos-branding luxos-shell luxos-terminal luxos-tweaks luxos-drivers lux luxos-account luxos-sandbox luxos-safe luxos-store luxos-greeter luxdrop luxos-care luxos-guard luxos-backup luxos-printing adcli realmd luxos-domain luxos-weather luxos-maps luxos-desktop luxos-installer
          # Legacy ovladace NVIDIA z AUR (Maxwell/Pascal/Volta 580xx, Kepler 470xx) - jen online, ne v ISO
          nvidia-580xx-utils lib32-nvidia-580xx-utils nvidia-470xx-utils lib32-nvidia-470xx-utils)
# Baliky, ktere se nekopiruji do mistniho repozitare v ISO (velke, potrebuje je jen malo pocitacu;
# instalator je stahuje z online [luxos], viz install_online_drivers v luxos-install)
# Hlavicky jadra (linux-luxos-headers, ~90 MB) v ISO byt MUSI: luxos-hwdetect je pridava do prvni
# instalace pro ovladace DKMS (nvidia-open-dkms, broadcom-wl-dkms) a [luxos] je v live systemu jen
# mistni repozitar - bez nich instalace skoncila "target not found: linux-luxos-headers" (0.9.7-0.9.11).
ISO_ONLINE_ONLY=('*nvidia-[0-9]*xx*')
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

# Repozitar [luxos-drivers]: overene ovladace tiskaren a skeneru z AUR (drivers/luxdrv.py verify).
# Stavi se jen zapichnuty commit z drivers/state/manifest.json (z mistniho zrcadla out/drivers/aur.git),
# zdroje jsou uz stazene a overene (out/drivers/src) a makepkg bezi BEZ SITE. Hotove baliky zustavaji v out/drivers-repo (build_packages
# maze out/repo), znovu se stavi jen balik, jehoz overeny commit se zmenil.
drv_pkgfiles() {  # drv_pkgfiles ADRESAR NAZEV -> soubory presne tohoto baliku (ne "nazev-dalsi")
    local f rest
    for f in "$1/$2"-*.pkg.tar.zst; do
        [[ -e $f ]] || continue
        rest=${f##*/}; rest=${rest#"$2"-}
        [[ $rest =~ ^[^-]+-[^-]+-[^-]+\.pkg\.tar\.zst$ ]] && echo "$f"
    done
    return 0
}

build_drivers() {
    local DREPO=$OUT/drivers-repo manifest=$ROOT/drivers/state/manifest.json
    [[ -f $manifest ]] || { echo "No drivers/state/manifest.json (drivers/luxdrv.py verify)" >&2; exit 1; }
    # 32bitove knihovny (lib32-*) potrebuji nektere starsi ovladace - jen v kontejneru
    grep -q '^\[multilib\]' /etc/pacman.conf || printf '\n[multilib]\nInclude = /etc/pacman.d/mirrorlist\n' >>/etc/pacman.conf
    msg "Updating build container"
    pacman -Syu --noconfirm --needed >/dev/null
    setup_signing
    mkdir -p "$DREPO/pkgs" "$DREPO/built" "$OUT/drivers/src" "$BUILD"
    # zdroje jen ke cteni (makepkg je nestahuje - bez site); vlastnika v out/ nemenit
    chown -R builder: "$BUILD"
    # Stary C kod vyrobcu: GCC 14+ dela z techto varovani chyby (implicitni deklarace, int, ukazatele),
    # C23 (vychozi od GCC 15) zase meni bool/prototypy - pro ovladace standard C17 jako driv.
    # Jen pro sestaveni ovladacu (~builder/.makepkg.conf), baliky [luxos] se stavi beze zmeny.
    # Nektere Makefile vyrobcu CFLAGS ignoruji - proto i v CC (-fpermissive = tyto chyby jen jako varovani);
    # PKGBUILD s vlastnim CC (gcc -m32) dostane aspon CFLAGS.
    cat >/home/builder/.makepkg.conf <<'EOF'
CFLAGS+=" -std=gnu17 -Wno-error=implicit-function-declaration -Wno-error=implicit-int -Wno-error=incompatible-pointer-types -Wno-error=int-conversion"
export CC="gcc -std=gnu17 -fpermissive"
EOF
    local base commit dir n=0 failed=() rest progress f line
    rm -f "$BUILD"/drvmiss-*
    mapfile -t rest < <(jq -r 'to_entries[] | "\(.key) \(.value.commit)"' "$manifest" | sort)
    # jen vybrane (./build.sh drivers BALIK...) i s overenymi baliky, na kterych zavisi; jinak vsechny overene
    if (($#)); then
        local want sel=()
        want=" $(python3 "$ROOT/drivers/luxdrv.py" closure "$@" | tr '\n' ' ') "
        for line in "${rest[@]}"; do [[ $want == *" ${line%% *} "* ]] && sel+=("$line"); done
        rest=("${sel[@]}")
    fi
    # zapichnute commity z AUR a zdroje, ktere tu jeste nejsou (napr. GitHub Actions); kazdy zdroj
    # musi mit sha256 z manifestu - co nesedi, se zahodi a balik pak skonci s "verified source missing"
    msg "Fetching verified AUR commits and sources"
    python3 "$ROOT/drivers/luxdrv.py" fetch "${rest[@]%% *}" || msg "Fetch failed - building what is here"
    # zavislosti: kdo co poskytuje mezi uz sestavenymi ovladaci (nazev i provides)
    drv_provider() {  # drv_provider NAZEV -> soubor baliku
        local f
        f=$(drv_pkgfiles "$DREPO/pkgs" "$1" | head -1)
        [[ -n $f ]] && { echo "$f"; return; }
        for f in "$DREPO"/pkgs/*.pkg.tar.zst; do
            [[ -e $f ]] || continue
            tar --zstd -xOf "$f" .PKGINFO | awk -F' = ' -v n="$1" '$1 == "provides" { sub(/[<>=].*/, "", $2)
                if ($2 == n) found = 1 } END { exit !found }' && { echo "$f"; return; }
        done
        return 0
    }
    # ovladace, ktere uz nejsou overene (odebrane z manifestu), z repozitare pryc
    for f in "$DREPO"/built/*; do
        base=${f##*/}
        [[ -e $f && $base != luxos-drivers-index ]] || continue
        jq -e --arg b "$base" 'has($b)' "$manifest" >/dev/null && continue
        msg "Removing driver $base (no longer verified)"
        tail -n +2 "$f" | while read -r nm; do drv_pkgfiles "$DREPO/pkgs" "$nm" | xargs -r rm -f; done
        rm -f "$f"
    done
    while ((${#rest[@]})); do
        progress=0
        local next=()
        for line in "${rest[@]}"; do
            read -r base commit <<<"$line"
            # balik se stejnym jmenem jako v Archu by ho v systemu nahradil - takovy se nestavi (a pryc)
            local clash=
            while read -r nm; do
                pacman -Si "$nm" &>/dev/null && { clash=$nm; break; }
            done < <(jq -r --arg b "$base" '.[$b].pkgnames[]' "$manifest")
            if [[ -n $clash ]]; then
                if [[ -f $DREPO/built/$base ]]; then
                    tail -n +2 "$DREPO/built/$base" | while read -r nm; do drv_pkgfiles "$DREPO/pkgs" "$nm" | xargs -r rm -f; done
                    rm -f "$DREPO/built/$base"
                fi
                failed+=("$base (package $clash already exists in Arch Linux)"); continue
            fi
            [[ $(head -1 "$DREPO/built/$base" 2>/dev/null) == "$commit" ]] && continue
            dir=$BUILD/drv/$base
            rm -rf "$dir"
            # soubory presne overeneho commitu z mistniho zrcadla AUR (drivers/luxdrv.py verify)
            mkdir -p "$dir"
            git -c safe.directory='*' --git-dir="$OUT/drivers/aur.git" archive "$commit" | tar -x -C "$dir" ||
                { failed+=("$base (commit $commit not in out/drivers/aur.git)"); continue; }
            # zaplaty LuxOS (drivers/patches/BALIK) - presne ty, ktere prosly overenim (sha256 v manifestu)
            local pf ph patchok=1
            while IFS=$'\t' read -r pf ph; do
                [[ -n $pf ]] || continue
                if [[ $(sha256sum <"$ROOT/drivers/patches/$base/$pf" 2>/dev/null | cut -d' ' -f1) != "$ph" ]] ||
                        ! patch -p1 -N -s --no-backup-if-mismatch -r - -d "$dir" -i "$ROOT/drivers/patches/$base/$pf" >/dev/null; then
                    patchok=0; break
                fi
            done < <(jq -r --arg b "$base" '.[$b].patches // {} | to_entries[] | "\(.key)\t\(.value)"' "$manifest")
            ((patchok)) || { failed+=("$base (LuxOS patch $pf differs from the verified one or does not apply)"); continue; }
            chown -R builder: "$dir"
            # zavislosti: z Archu (i virtualni - provides), nebo jiny overeny ovladac (musi byt sestaveny driv)
            local missing=0 nm why=
            # (PKGBUILD cte uzivatel builder bez site, ne root)
            # shellcheck disable=SC2016  # promenne rozvine az bash uzivatele builder
            (cd "$dir" && unshare -n sudo -u builder bash -c 'set +u; depends=(); makedepends=(); CARCH=x86_64
                depends_x86_64=(); makedepends_x86_64=()
                source ./PKGBUILD >/dev/null 2>&1
                for d in "${depends[@]}" "${makedepends[@]}" "${depends_x86_64[@]}" "${makedepends_x86_64[@]}"; do
                    echo "${d%%[<>=]*}"; done') >"$dir/.deps"
            while read -r nm; do
                [[ -n $nm ]] || continue
                pacman -T "$nm" &>/dev/null && continue
                pacman -S --needed --noconfirm "$nm" &>/dev/null && continue
                f=$(drv_provider "$nm")
                if [[ -n $f ]]; then pacman -U --needed --noconfirm --ask 4 "$f" &>/dev/null || { missing=1; why+=" $nm(install)"; }
                else missing=1; why+=" $nm"; fi
            done <"$dir/.deps"
            if ((missing)); then next+=("$line"); echo "$why" >"$BUILD/drvmiss-$base"; continue; fi

            msg "Building driver $base ($commit)"
            # SRCDEST (makepkg ho chce zapisovatelny): odkazy na overene zdroje out/drivers/src/SHA256/NAZEV
            rm -rf "$BUILD/drvsrc"; mkdir -p "$BUILD/drvsrc" "$BUILD/drvout"
            local srcok=1 sf sh
            # (tabulator: nazvy zdroju muzou obsahovat mezery, napr. "Kyocera ECOSYS P5021cdw.PPD")
            while IFS=$'\t' read -r sf sh; do
                [[ -f $dir/$sf ]] && continue      # soubor primo v AUR (zaplata) - je v overenem commitu
                [[ -f $OUT/drivers/src/$sh/$sf ]] || { srcok=0; break; }
                cp "$OUT/drivers/src/$sh/$sf" "$BUILD/drvsrc/$sf"   # kopie: prepare() smi menit prava zdroju
            done < <(jq -r --arg b "$base" '.[$b].sources | to_entries[] | "\(.key)\t\(.value)"' "$manifest")
            ((srcok)) || { failed+=("$base (verified source $sf missing - run drivers/luxdrv.py verify)"); continue; }
            chown -R builder: "$BUILD/drvsrc" "$BUILD/drvout"
            if (cd "$dir" && unshare -n sudo -u builder env -u GNUPGHOME HOME=/home/builder SRCDEST="$BUILD/drvsrc" \
                    PKGDEST="$BUILD/drvout" makepkg --force --nodeps --noconfirm --cleanbuild >"$dir/.log" 2>&1); then
                # stare verze baliku z tohoto pkgbase pryc, nove dovnitr (znacka: commit + nazvy baliku)
                echo "$commit" >"$DREPO/built/$base.new"
                rm -f "$BUILD"/drvout/*-debug-*.pkg.tar.zst
                for f in "$BUILD"/drvout/*.pkg.tar.zst; do
                    nm=$(tar --zstd -xOf "$f" .PKGINFO | awk -F' = ' '$1=="pkgname"{print $2; exit}')
                    drv_pkgfiles "$DREPO/pkgs" "$nm" | xargs -r rm -f
                    echo "$nm" >>"$DREPO/built/$base.new"
                done
                mv "$BUILD"/drvout/*.pkg.tar.zst "$DREPO/pkgs/"
                mv "$DREPO/built/$base.new" "$DREPO/built/$base"
                n=$((n + 1)); progress=1
            else
                mkdir -p "$DREPO/logs"; cp "$dir/.log" "$DREPO/logs/$base.log"
                { echo "--- zdroje (SRCDEST, src):"; ls -la "$BUILD/drvsrc" "$dir/src" 2>&1 | head -40; } >>"$DREPO/logs/$base.log"
                failed+=("$base (makepkg: $(grep -m1 -E 'error:|ERROR' "$dir/.log" || tail -1 "$dir/.log"))")
            fi
            rm -rf "$dir" "$BUILD/drvout"
        done
        rest=("${next[@]}")
        ((progress)) || { for line in "${rest[@]}"; do
            failed+=("${line%% *} (missing dependency:$(cat "$BUILD/drvmiss-${line%% *}" 2>/dev/null))"); done; break; }
    done
    # luxos-drivers-index: ktere zarizeni potrebuje ktery balik (luxos-printing, luxos-hwdetect)
    local idx=$BUILD/luxos-drivers-index sum
    rm -rf "$idx"; mkdir -p "$idx"
    python3 "$ROOT/drivers/luxdrv.py" index "$DREPO/pkgs" "$idx"
    sum=$(cat "$idx"/drivers-index.json "$idx"/drivers-usb.tsv | sha256sum | cut -d' ' -f1)
    if [[ $(cat "$DREPO/built/luxos-drivers-index" 2>/dev/null) != "$sum" ]] ||
            ! compgen -G "$DREPO/pkgs/luxos-drivers-index-[0-9]*.pkg.tar.zst" >/dev/null; then
        cat >"$idx/PKGBUILD" <<EOF
pkgname=luxos-drivers-index
pkgver=$(date -u +%Y%m%d.%H%M)
pkgrel=1
pkgdesc='LuxOS - which printer or scanner needs which verified driver from [luxos-drivers]'
arch=(any)
license=(MIT)
source=(drivers-index.json drivers-usb.tsv)
sha256sums=(SKIP SKIP)
package() {
    install -Dm644 -t "\$pkgdir/usr/share/luxos" drivers-index.json drivers-usb.tsv
}
EOF
        chown -R builder: "$idx"
        rm -f "$DREPO"/pkgs/luxos-drivers-index-[0-9]*.pkg.tar.zst
        (cd "$idx" && sudo -u builder env -u GNUPGHOME PKGDEST="$idx/out" makepkg --force --nodeps --noconfirm >/dev/null)
        mv "$idx"/out/*.pkg.tar.zst "$DREPO/pkgs/"
        echo "$sum" >"$DREPO/built/luxos-drivers-index"
    fi
    rm -f "$DREPO"/pkgs/*.sig
    REPO=$DREPO make_repo luxos-drivers "$DREPO/pkgs"
    rm -f /home/builder/.makepkg.conf
    printf '%s\n' "${failed[@]}" >"$DREPO/failed.txt"
    msg "Drivers: $n built, ${#failed[@]} failed (out/drivers-repo/failed.txt)"
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
# Zverejnene repozitare LuxOS jako zdroj zavislosti (rofi, lsl, lux-engine...) pro sestaveni
# jednoho baliku bez stavby celeho [luxos] (GitHub Actions: target one). Podpisy povinne,
# klic LuxOS z packages/luxos-keyring. LUXOS_PUBLISHED_REPO=0 vypne.
use_published_repos() {
    [[ ${LUXOS_PUBLISHED_REPO:-1} == 1 ]] || return 0
    grep -q '^\[luxos\]' /etc/pacman.conf && return 0
    local key=$ROOT/packages/luxos-keyring/files/luxos.gpg fpr
    pacman-key --init >/dev/null 2>&1 || true
    pacman-key --add "$key" >/dev/null
    fpr=$(gpg --show-keys --with-colons "$key" | awk -F: '/^fpr/{print $10; exit}')
    pacman-key --lsign-key "$fpr" >/dev/null
    # [luxos] pred [core]/[extra] jako v LuxOS (vlastni rofi, gdk-pixbuf2...)
    local conf
    conf=$(mktemp)
    awk -v url="${LUXOS_REPO_URL:-https://luxos.lux-ai.cz/repo}" '
        /^\[core\]/ && !done { printf "[luxos]\nSigLevel = Required\nServer = %s/$repo/$arch\n\n[luxos-apps]\nSigLevel = Required\nServer = %s/$repo/$arch\n\n", url, url; done=1 }
        { print }' /etc/pacman.conf >"$conf"
    cat "$conf" >/etc/pacman.conf
    rm -f "$conf"
    # pacman kontejneru nikdy nenahradit balikem lux-engine (replaces=pacman)
    sed -i 's/^#\?IgnorePkg *=.*/IgnorePkg = pacman lux-engine/' /etc/pacman.conf
    pacman -Sy --noconfirm >/dev/null
    msg "Dependencies also from the published LuxOS repositories"
}

build_single() {
    local p=${1:?package name} src
    src=$ROOT/packages/$p
    [[ -f $src/PKGBUILD ]] || src=$ROOT/packages/apps/$p
    [[ -f $src/PKGBUILD ]] || { echo "No package $p" >&2; exit 2; }
    msg "Updating build container"
    pacman -Syu --noconfirm --needed >/dev/null
    # az po aktualizaci kontejneru: lux-engine z [luxos] nahrazuje pacman (ten kontejner potrebuje)
    use_published_repos
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
    drivers)  shift; build_drivers "$@" ;;
    one)      build_single "${2:-}" ;;
    *) echo "Usage: $0 [all|packages|apps|drivers [PKGBASE...]|iso|one PACKAGE]" >&2; exit 2 ;;
esac
