#!/bin/bash
# LuxOS - slozeni stabilniho vydani repozitaru z testovaciho (staging) bez baliku, ktere jeste
# nejsou hotove
#
#   scripts/compose-stable-repo.sh [ZDROJ] [CIL]     vychozi out/repo -> out/repo-stable
#   LUXOS_REPO_SRC=out/repo-stable LUXOS_REPO_CHANNEL=stable scripts/publish-repo.sh
#
# Z kopie ZDROJE (reflink, zdroj se nemeni):
#   - LUXOS_STABLE_EXCLUDE (vychozi "luxos-mail luxos-app-studio luxos-icon-studio luxos-sdk"): baliky se z databaze odeberou a jejich soubory
#     (vsechny verze, ikona pro Obchod) smazou - ve stabilnim kanalu nebudou;
#   - LUXOS_STABLE_KEEP (vychozi "lux-code lux-code-next"): zustane verze, ktera je ted ve stabilnim
#     kanalu (LUXOS_STABLE_URL, vychozi https://luxos.lux-ai.cz/repo); stahne se i s podpisem,
#     overi klicem LuxOS (packages/luxos-keyring) a nahradi novejsi verzi ze staging. Balik, ktery ve
#     stabilnim kanalu neni, se odebere stejne jako u EXCLUDE.
# Databaze se znovu podepisou klicem LuxOS (stejne poradi jako build.sh: LUXOS_SIGNING_DIR, Trezor
# /safe/$USER/luxos-signing, ~/.local/share/luxos/signing; kopie klice jen v RAM, $XDG_RUNTIME_DIR).
# Na konci se vypise obsah databazi a overi podpisy. Nic se nenahrava.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."

SRC=${1:-out/repo}
DEST=${2:-out/repo-stable}
ARCH=x86_64
STABLE_URL=${LUXOS_STABLE_URL:-https://luxos.lux-ai.cz/repo}
read -r -a EXCLUDE <<<"${LUXOS_STABLE_EXCLUDE-luxos-mail luxos-app-studio luxos-icon-studio luxos-sdk}"
read -r -a KEEP <<<"${LUXOS_STABLE_KEEP-lux-code lux-code-next}"
PUBKEY=${LUXOS_KEYRING_FILE:-packages/luxos-keyring/files/luxos.gpg}
REPOS=(luxos luxos-apps)

die() { echo "compose-stable-repo: $*" >&2; exit 1; }
[[ $(readlink -f "$SRC") != "$(readlink -f "$DEST")" ]] || die "source and destination are the same"
for r in "${REPOS[@]}"; do
    [[ -f $SRC/$r/$ARCH/$r.db.tar.gz ]] || die "missing $SRC/$r - build or fetch the staging repo first"
done
case $DEST in out/*|/*/out/*) ;; *) die "destination must be under out/ (got $DEST)" ;; esac

# --- podpisovy klic (kopie v RAM) a overovaci klicenka ---
key=${LUXOS_SIGNING_DIR:-}
if [[ -z $key ]]; then
    for k in "/safe/$USER/luxos-signing" "$HOME/.local/share/luxos/signing"; do
        [[ -d $k ]] && { key=$k; break; }
    done
fi
[[ -n $key && -d $key ]] || die "no signing key: unlock the Safe (luxos-safe unlock) or set LUXOS_SIGNING_DIR"
work=$(mktemp -d "${XDG_RUNTIME_DIR:-/dev/shm}/luxos-compose.XXXXXX")
cleanup() {
    local h
    for h in "$work/sign" "$work/verify"; do [[ -d $h ]] && GNUPGHOME=$h gpgconf --kill gpg-agent 2>/dev/null; done
    rm -rf "$work"
}
trap cleanup EXIT
mkdir -m700 "$work/sign" "$work/verify" "$work/dl"
cp -a "$key/." "$work/sign/"
chmod 700 "$work/sign"
GPGKEY=$(GNUPGHOME=$work/sign gpg --batch --list-secret-keys --with-colons | awk -F: '/^fpr/{print $10; exit}')
[[ -n $GPGKEY ]] || die "no secret key in $key"
GNUPGHOME=$work/verify gpg --batch --quiet --import "$PUBKEY"
verify() { GNUPGHOME=$work/verify gpg --batch --status-fd 1 --verify "$1.sig" "$1" 2>/dev/null | grep -q '^\[GNUPG:\] VALIDSIG'; }
sign_env() { GNUPGHOME=$work/sign "$@"; }
get() { curl -fsSL --retry 4 --retry-delay 3 -o "$2" "$1"; }

# soubory baliku presne tohoto jmena (lux-code nesmi chytit lux-code-next): NAZEV-VERZE-REL-ARCH
pkg_files() {  # pkg_files ADRESAR NAZEV
    local f b
    for f in "$1"/*.pkg.tar.zst; do
        [[ -e $f ]] || continue
        b=${f##*/}
        [[ $b == "$2"-* && ${b#"$2"-} =~ ^[^-]+-[^-]+-[^-]+\.pkg\.tar\.zst$ ]] && echo "$f"
    done
    return 0
}
db_has() {  # db_has DB NAZEV -> verze nebo nic
    tar -xzOf "$1" --wildcards '*/desc' 2>/dev/null | awk -v n="$2" '
        /^%NAME%$/ {getline; name=$0} /^%VERSION%$/ {getline; if (name == n) print $0}'
}
drop() {  # drop REPO NAZEV - z databaze i soubory
    local dir=$DEST/$1/$ARCH f
    if [[ -n $(db_has "$dir/$1.db.tar.gz" "$2") ]]; then
        sign_env repo-remove -q -s -k "$GPGKEY" "$dir/$1.db.tar.gz" "$2"
    fi
    while read -r f; do [[ -n $f ]] && rm -f -- "$f" "$f.sig"; done < <(pkg_files "$dir" "$2")
    rm -f -- "$dir/icons/$2.png" "$dir/icons/$2.svg"
}

echo "==> Copying $SRC -> $DEST"
rm -rf -- "$DEST"
mkdir -p "$(dirname "$DEST")"
cp -a --reflink=auto -- "$SRC" "$DEST"

for r in "${REPOS[@]}"; do
    dir=$DEST/$r/$ARCH
    db=$dir/$r.db.tar.gz
    for n in "${EXCLUDE[@]}"; do
        [[ -n $(db_has "$db" "$n") || -n $(pkg_files "$dir" "$n") ]] || continue
        echo "==> [$r] removing $n (not in the stable release)"
        drop "$r" "$n"
    done
    stable_db=
    for n in "${KEEP[@]}"; do
        [[ -n $(db_has "$db" "$n") || -n $(pkg_files "$dir" "$n") ]] || continue
        if [[ -z $stable_db ]]; then
            stable_db=$work/dl/$r.db.tar.gz
            get "$STABLE_URL/$r/$ARCH/$r.db.tar.gz" "$stable_db"
            get "$STABLE_URL/$r/$ARCH/$r.db.tar.gz.sig" "$stable_db.sig"
            verify "$stable_db" || die "bad signature of the stable $r database ($STABLE_URL)"
        fi
        # repo-add pise v kazdem desc %FILENAME% pred %NAME%
        file=$(tar -xzOf "$stable_db" --wildcards '*/desc' | awk -v n="$n" '
            /^%FILENAME%$/ {getline; fn=$0}
            /^%NAME%$/ {getline; if ($0 == n) {print fn; exit}}')
        if [[ -z $file ]]; then
            echo "==> [$r] $n is not in the stable channel - removing it"
            drop "$r" "$n"
            continue
        fi
        [[ $file =~ ^[A-Za-z0-9@._+-]+\.pkg\.tar\.zst$ ]] || die "unexpected file name in the stable database: $file"
        echo "==> [$r] keeping the stable $n: $file (staging has $(db_has "$db" "$n"))"
        get "$STABLE_URL/$r/$ARCH/$file" "$work/dl/$file"
        get "$STABLE_URL/$r/$ARCH/$file.sig" "$work/dl/$file.sig"
        verify "$work/dl/$file" || die "bad signature: $file"
        drop "$r" "$n"
        install -m644 "$work/dl/$file" "$work/dl/$file.sig" "$dir/"
        sign_env repo-add -q -s -k "$GPGKEY" "$db" "$dir/$file"
        # ikona pro Obchod (jako make_repo v container-build.sh)
        icon=$(tar --zstd -tf "$dir/$file" | grep -E "^usr/share/icons/hicolor/(scalable|512x512|256x256|128x128)/apps/$n\.(svg|png)$" |
               sort | head -1 || true)
        if [[ -n $icon ]]; then mkdir -p "$dir/icons"; tar --zstd -xOf "$dir/$file" "$icon" >"$dir/icons/$n.${icon##*.}"; fi
    done
done

# zalohy databazi z repo-add/repo-remove (*.old) do vydani nepatri
find "$DEST" \( -name '*.tar.gz.old' -o -name '*.tar.gz.old.sig' \) -delete

echo "==> Checking $DEST"
bad=0
for r in "${REPOS[@]}"; do
    dir=$DEST/$r/$ARCH
    for f in "$r.db.tar.gz" "$r.files.tar.gz"; do
        verify "$dir/$f" || { echo "    BAD signature: $dir/$f" >&2; bad=1; }
    done
    for n in "${EXCLUDE[@]}"; do
        if [[ -n $(db_has "$dir/$r.db.tar.gz" "$n") || -n $(pkg_files "$dir" "$n") ]]; then
            echo "    $n is still in [$r]" >&2; bad=1
        fi
    done
    # kazdy balik z databaze musi lezet vedle s platnym podpisem
    while read -r f; do
        [[ -f $dir/$f ]] && verify "$dir/$f" || { echo "    [$r] $f missing or badly signed" >&2; bad=1; }
    done < <(tar -xzOf "$dir/$r.db.tar.gz" --wildcards '*/desc' | awk '/^%FILENAME%$/ {getline; print}')
    echo "    [$r] $(tar -xzOf "$dir/$r.db.tar.gz" --wildcards '*/desc' | awk '/^%FILENAME%$/ {getline; print}' | sort | paste -sd' ')"
done
((bad == 0)) || die "the composed repository is not consistent (see above)"
echo "==> Done: LUXOS_REPO_SRC=$DEST LUXOS_REPO_CHANNEL=stable scripts/publish-repo.sh"
