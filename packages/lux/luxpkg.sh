# lux - vlastni format balicku LuxOS (.lux), nacita /usr/bin/lux
#
# Balicek .lux = tar.zst:
#   lux.json      metadata (format, name, version, release, arch, summary, description, license,
#                 url, depends.system[] (pacman), depends.lux[], bin{prikaz: cesta v app/})
#   app/          aplikace -> /opt/lux/<name>/
#   share/        applications/*.desktop, icons/hicolor/... -> /usr/local/share/
#   scripts/      post_install, pre_remove (bash, spousti se jako root)
# Repozitar: $LUX_INDEX_URL/index.json (+ .sig), balicky vedle; vse podepsane klicem LuxOS.
# Specifikace: /usr/share/doc/lux/lux-package-format.md

LUX_ROOT=/opt/lux
LUX_DB=/var/lib/lux/installed
LUX_SHARE=/usr/local/share
LUX_INDEX_URL=${LUX_INDEX_URL:-https://lsl.lux-ai.cz/luxos/lux}
LUX_KEYRING=${LUX_KEYRING:-/usr/share/pacman/keyrings/luxos.gpg}
LUX_FORMAT=1

lp_valid_name() { [[ $1 =~ ^[a-z0-9][a-z0-9._+-]*$ ]]; }

# Overeni podpisu klicem LuxOS (gpgv s docasnou klicenkou)
lp_verify() {  # lp_verify SOUBOR PODPIS
    [[ -r $LUX_KEYRING && -r $2 ]] || return 1
    local tmp rc
    tmp=$(mktemp -d)
    gpg --dearmor <"$LUX_KEYRING" >"$tmp/luxos.gpg" 2>/dev/null &&
        gpgv --keyring "$tmp/luxos.gpg" "$2" "$1" >/dev/null 2>&1
    rc=$?
    rm -rf "$tmp"
    return $rc
}

lp_meta() { tar --zstd -xOf "$1" lux.json 2>/dev/null; }  # lp_meta SOUBOR.lux -> JSON

lp_installed() { [[ -f $LUX_DB/$1.json ]]; }
lp_installed_version() { jq -r '"\(.version)-\(.release // 1)"' "$LUX_DB/$1.json" 2>/dev/null; }

# Index repozitare (overeny), ulozeny v mezipameti
lp_index() {
    local dir file
    if ((EUID == 0)); then dir=/var/cache/lux; else dir=$LUX_CACHE; fi
    mkdir -p "$dir"
    file=$dir/index.json
    if [[ ! -s $file || -n $(find "$file" -mmin +30 2>/dev/null) || ${LUX_REFRESH:-0} == 1 ]]; then
        if curl -fsSL --max-time 15 -o "$file.new" "$LUX_INDEX_URL/index.json" &&
           curl -fsSL --max-time 15 -o "$file.new.sig" "$LUX_INDEX_URL/index.json.sig" &&
           lp_verify "$file.new" "$file.new.sig"; then
            mv "$file.new" "$file"
        else
            rm -f "$file.new" "$file.new.sig"
            [[ -s $file ]] || { echo '{"format":1,"packages":[]}'; return; }
        fi
        rm -f "$file.new.sig"
    fi
    cat "$file"
}

lp_index_entry() { lp_index | jq -c --arg n "$1" '.packages[] | select(.name == $n)' | head -1; }

# ---- pack -----------------------------------------------------------------------
lp_pack() {  # lp_pack ADRESAR [VYSTUP] - sestavi .lux z adresare s lux.json
    local dir=${1%/} out=${2:-.} name version release arch file
    [[ -f $dir/lux.json ]] || die "$(T "%s has no lux.json" "$dir")"
    jq -e . "$dir/lux.json" >/dev/null || die "$(T "lux.json is not valid JSON")"
    name=$(jq -r '.name // empty' "$dir/lux.json")
    version=$(jq -r '.version // empty' "$dir/lux.json")
    release=$(jq -r '.release // 1' "$dir/lux.json")
    arch=$(jq -r '.arch // "any"' "$dir/lux.json")
    lp_valid_name "$name" || die "$(T "Invalid package name: %s" "$name")"
    [[ $version =~ ^[0-9A-Za-z._+]+$ ]] || die "$(T "Invalid version: %s" "$version")"
    [[ -d $dir/app ]] || die "$(T "%s has no app/ directory" "$dir")"
    local bad
    bad=$(jq -r '.bin // {} | to_entries[] | .value' "$dir/lux.json" | while read -r rel; do
        [[ -f $dir/app/$rel ]] || echo "$rel"; done)
    [[ -z $bad ]] || die "$(T "Missing files listed in bin: %s" "$bad")"
    mkdir -p "$out"
    file=$out/$name-$version-$release-$arch.lux
    local parts=(lux.json app)
    [[ -d $dir/share ]] && parts+=(share)
    [[ -d $dir/scripts ]] && parts+=(scripts)
    tar -C "$dir" --owner=0 --group=0 --numeric-owner --sort=name --mtime=@0 --zstd -cf "$file" "${parts[@]}"
    ok "$(T "Built %s" "$file")"
    echo "$file"
}

# ---- instalace (jako root) ------------------------------------------------------
lp_install_file() {  # lp_install_file SOUBOR.lux [overeno=1]
    local file=$1 verified=${2:-0} meta name version tmp dest
    meta=$(lp_meta "$file") || die "$(T "%s is not a lux package" "$file")"
    [[ $(jq -r '.format // 0' <<<"$meta") -le $LUX_FORMAT ]] || die "$(T "This package needs a newer lux")"
    name=$(jq -r .name <<<"$meta")
    version=$(jq -r '"\(.version)-\(.release // 1)"' <<<"$meta")
    lp_valid_name "$name" || die "$(T "Invalid package name: %s" "$name")"
    if ((!verified)); then
        if [[ -r $file.sig ]] && lp_verify "$file" "$file.sig"; then
            ok "$(T "Signature OK (LuxOS)")"
        else
            warn "$(T "%s is not signed by LuxOS." "$file")"
            ask "$(T "Install it anyway?")" n || exit 1
        fi
    fi

    # zavislosti: systemove balicky (pacman), pak dalsi balicky lux
    local -a sys=() dep
    mapfile -t sys < <(jq -r '.depends.system // [] | .[]' <<<"$meta")
    if ((${#sys[@]})); then
        say "$(T "Installing dependencies: %s" "${sys[*]}")"
        pacman -S --needed --noconfirm -- "${sys[@]}" || die "$(T "Dependencies could not be installed")"
    fi
    while read -r dep; do
        [[ -n $dep ]] && ! lp_installed "$dep" && lp_install_name "$dep"
    done < <(jq -r '.depends.lux // [] | .[]' <<<"$meta")

    say "$(T "Installing %s %s" "${B}$name${R}" "$version")"
    lp_installed "$name" && lp_run_script "$name" pre_remove
    mkdir -p "$LUX_ROOT"
    tmp=$(mktemp -d "$LUX_ROOT/.new-XXXXXX")
    tar --zstd -xf "$file" -C "$tmp" --no-same-owner || { rm -rf "$tmp"; die "$(T "Could not unpack %s" "$file")"; }
    dest=$LUX_ROOT/$name
    lp_unlink "$name"
    rm -rf "$dest"
    mv "$tmp" "$dest"
    chmod 755 "$dest"

    # integrace: prikazy, .desktop, ikony; seznam souboru do databaze
    local -a files=()
    local cmd rel f target
    while IFS=$'\t' read -r cmd rel; do
        [[ -n $cmd ]] || continue
        lp_valid_name "$cmd" || continue
        mkdir -p /usr/local/bin
        ln -sfn "$dest/app/$rel" "/usr/local/bin/$cmd"
        chmod 755 "$dest/app/$rel"
        files+=("/usr/local/bin/$cmd")
    done < <(jq -r '.bin // {} | to_entries[] | "\(.key)\t\(.value)"' "$dest/lux.json")
    if [[ -d $dest/share ]]; then
        while IFS= read -r -d '' f; do
            rel=${f#"$dest/share/"}
            target=$LUX_SHARE/$rel
            mkdir -p "$(dirname "$target")"
            cp -f "$f" "$target"
            files+=("$target")
        done < <(find "$dest/share" -type f -print0)
    fi
    mkdir -p "$LUX_DB"
    jq --argjson files "$(printf '%s\n' "${files[@]}" | jq -R . | jq -s .)" \
       --arg date "$(date -Iseconds)" '. + {installed_files: $files, installed: $date}' \
       "$dest/lux.json" >"$LUX_DB/$name.json"
    lp_run_script "$name" post_install
    lp_refresh_caches
    ok "$(T "%s is installed" "$name")"
}

lp_run_script() {  # lp_run_script NAME post_install|pre_remove
    local s=$LUX_ROOT/$1/scripts/$2
    [[ -f $s ]] && LUX_PACKAGE=$1 LUX_PREFIX=$LUX_ROOT/$1 bash "$s"
    return 0
}

lp_unlink() {  # odstrani integrovane soubory podle databaze
    local f
    [[ -f $LUX_DB/$1.json ]] || return 0
    while IFS= read -r f; do
        [[ $f == /usr/local/* ]] && rm -f -- "$f"
    done < <(jq -r '.installed_files // [] | .[]' "$LUX_DB/$1.json")
}

lp_refresh_caches() {
    command -v update-desktop-database &>/dev/null && update-desktop-database -q "$LUX_SHARE/applications" 2>/dev/null
    [[ -d $LUX_SHARE/icons/hicolor ]] && gtk-update-icon-cache -qtf "$LUX_SHARE/icons/hicolor" 2>/dev/null
    return 0
}

lp_remove() {  # lp_remove NAME (jako root)
    lp_installed "$1" || die "$(T "Package '%s' not found" "$1")"
    say "$(T "Removing %s" "${B}$1${R}")"
    lp_run_script "$1" pre_remove
    lp_unlink "$1"
    rm -rf -- "${LUX_ROOT:?}/$1" "$LUX_DB/$1.json"
    lp_refresh_caches
    ok "$(T "%s was removed" "$1")"
}

# Stazeni z repozitare, overeni podpisu a kontrolniho souctu, instalace (jako root)
lp_install_name() {
    local entry file url sha tmp
    entry=$(lp_index_entry "$1")
    [[ -n $entry ]] || die "$(T "Package '%s' not found" "$1")"
    file=$(jq -r .file <<<"$entry")
    sha=$(jq -r .sha256 <<<"$entry")
    [[ $file =~ ^[A-Za-z0-9._+-]+\.lux$ ]] || die "$(T "Invalid package name: %s" "$file")"
    tmp=$(mktemp -d)
    url=$LUX_INDEX_URL/$file
    say "$(T "Downloading %s" "$file")"
    curl -fL --progress-bar -o "$tmp/$file" "$url" && curl -fsSL -o "$tmp/$file.sig" "$url.sig" ||
        { rm -rf "$tmp"; die "$(T "Download failed: %s" "$url")"; }
    [[ $(sha256sum "$tmp/$file" | cut -d' ' -f1) == "$sha" ]] || { rm -rf "$tmp"; die "$(T "Checksum mismatch: %s" "$file")"; }
    lp_verify "$tmp/$file" "$tmp/$file.sig" || { rm -rf "$tmp"; die "$(T "Bad signature: %s" "$file")"; }
    lp_install_file "$tmp/$file" 1
    rm -rf "$tmp"
}

# Aktualizace nainstalovanych balicku lux podle indexu
lp_updates() {  # vypise "name stara nova"
    local f name cur new
    [[ -d $LUX_DB ]] || return 0
    for f in "$LUX_DB"/*.json; do
        [[ -e $f ]] || continue
        name=$(jq -r .name "$f")
        cur=$(lp_installed_version "$name")
        new=$(lp_index_entry "$name" | jq -r '"\(.version)-\(.release // 1)"' 2>/dev/null)
        [[ -n $new && $new != null-* ]] && (( $(vercmp "$new" "$cur") > 0 )) && echo "$name $cur $new"
    done
}

lp_list() {  # nainstalovane balicky lux "nazev verze"
    local f
    for f in "$LUX_DB"/*.json; do
        [[ -e $f ]] && jq -r '"\(.name) \(.version)-\(.release // 1)"' "$f"
    done
    return 0
}
