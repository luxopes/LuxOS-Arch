#!/bin/bash
# LuxOS - klic Secure Boot a podpis souboru EFI (jadro, systemd-boot) - jen u spravce, nikdy na GitHubu
#
#   scripts/sb-sign.sh init                 vytvori klic Secure Boot LuxOS (jednou; existujici nikdy neprepise)
#                                           a verejny certifikat da do packages/luxos-secureboot/files
#   scripts/sb-sign.sh package BALIK...     podepise jadro / systemd-boot uvnitr baliku (.pkg.tar.zst, na miste;
#                                           podpis GPG BALIK.sig se smaze - podepsat znovu, repo-add)
#   scripts/sb-sign.sh efi SOUBOR...        podepise soubory EFI na miste (uz podepsane klicem LuxOS preskoci)
#   scripts/sb-sign.sh verify SOUBOR|BALIK...  overi podpis certifikatem LuxOS (navratovy kod 1 = nepodepsane)
#   scripts/sb-sign.sh test-key ADRESAR     jednorazovy TESTOVACI klic (iso-test, testy ve VM) - nikdy pro vydani
#
# Klic (adresar 0700, luxos-secureboot.key 0600, .crt PEM, .cer DER): LUXOS_SB_DIR, jinak Trezor
# /safe/$USER/luxos-signing-sb (doporuceno, jako klic repozitare), jinak ~/.local/share/luxos/signing-sb.
# Soukromy klic nikdy necommitovat ani nenahravat na GitHub: CI stavi nepodepsane baliky, podepisuje
# az spravce (build.sh packages / tento skript) pred podpisem GPG a zverejnenim.
#
# Co se podepisuje (SB_PATTERNS): jadro usr/lib/modules/*/vmlinuz (linux-luxos) a systemd-boot v balicku
# luxos-secureboot. shim a MokManager (Fedora, podepsane Microsoftem) se NIKDY nepodepisuji.
# Bez sbsign na hostiteli (balik sbsigntools) bezi skript v kontejneru luxos-builder (podman/docker) -
# soubory pak musi byt uvnitr repozitare.
set -euo pipefail
ROOT=$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)
SB_PATTERNS=('usr/lib/modules/*/vmlinuz' 'usr/lib/luxos/secureboot/systemd-boot*.efi')
PUBLIC=$ROOT/packages/luxos-secureboot/files/luxos-secureboot.pem
CN="LuxOS Secure Boot Signing Key"

die() { echo "sb-sign: $*" >&2; exit 1; }

key_dir() {
    if [[ -n ${LUXOS_SB_DIR:-} ]]; then echo "$LUXOS_SB_DIR"
    elif [[ $(findmnt -no FSTYPE --mountpoint "/safe/$USER" 2>/dev/null | tail -n1) == fuse.gocryptfs ]]; then
        echo "/safe/$USER/luxos-signing-sb"
    elif [[ -f /safe/.vaults/$USER/gocryptfs.conf && ! -d $HOME/.local/share/luxos/signing-sb ]]; then
        die "unlock the Safe first (luxos-safe unlock): the Secure Boot key belongs to /safe/$USER/luxos-signing-sb"
    else echo "$HOME/.local/share/luxos/signing-sb"
    fi
}

# genkey ADRESAR CN DNI - RSA 3072, SHA-256, jen podpis kodu. Bez OID "jen moduly jadra"
# (1.3.6.1.4.1.2312.16.1.2): s nim by shim klicem MOK neoveril zavadec ani jadro.
genkey() {
    local dir=$1 cn=$2 days=$3
    (umask 077; mkdir -p "$dir")
    chmod 700 "$dir"
    [[ -e $dir/luxos-secureboot.key ]] && die "$dir/luxos-secureboot.key already exists - never overwritten"
    (umask 077
     openssl req -new -x509 -newkey rsa:3072 -sha256 -nodes -days "$days" -subj "/CN=$cn/O=LuxOS/" \
        -addext "basicConstraints=critical,CA:FALSE" \
        -addext "keyUsage=critical,digitalSignature" \
        -addext "extendedKeyUsage=codeSigning" \
        -addext "subjectKeyIdentifier=hash" \
        -keyout "$dir/luxos-secureboot.key" -out "$dir/luxos-secureboot.crt" 2>/dev/null)
    chmod 600 "$dir/luxos-secureboot.key"
    openssl x509 -in "$dir/luxos-secureboot.crt" -outform DER -out "$dir/luxos-secureboot.cer"
    chmod 644 "$dir/luxos-secureboot.crt" "$dir/luxos-secureboot.cer"
}

need_key() {
    KDIR=$(key_dir)
    [[ -f $KDIR/luxos-secureboot.key && -f $KDIR/luxos-secureboot.crt ]] ||
        die "no Secure Boot key in $KDIR - create it once with: scripts/sb-sign.sh init"
    [[ $(stat -c %a "$KDIR/luxos-secureboot.key") == 600 ]] || die "$KDIR/luxos-secureboot.key must be mode 0600"
}

# Bez sbsign: stejny prikaz v kontejneru luxos-builder (sbsigntools), klic jen pro cteni z kopie v RAM
in_container() {
    local engine copy rc
    engine=$(command -v podman || command -v docker || true)
    [[ -n $engine ]] || die "sbsign not found: install sbsigntools (or podman for the build container)"
    local a
    for a in "${@:2}"; do
        [[ $(readlink -m "$a") == "$ROOT"/* ]] || die "without sbsign on the host, files must be inside $ROOT: $a"
    done
    "$engine" image exists luxos-builder 2>/dev/null ||
        "$engine" build -q -t luxos-builder -f "$ROOT/scripts/Containerfile" "$ROOT/scripts" >/dev/null
    local -a mounts=(-v "$ROOT:/luxos:z")
    if [[ $1 == efi || $1 == package ]]; then
        need_key
        # Trezor (FUSE bez allow_other) kontejner nevidi: kopie jen na dobu behu v $XDG_RUNTIME_DIR (tmpfs)
        copy=$(mktemp -d "${XDG_RUNTIME_DIR:-/dev/shm}/luxos-sb.XXXXXX")
        cp -a "$KDIR/." "$copy/"
        mounts+=(-v "$copy:/sb:ro,z" -e LUXOS_SB_DIR=/sb)
    fi
    local -a args=("$1")
    for a in "${@:2}"; do args+=("/luxos/$(realpath -m --relative-to="$ROOT" "$a")"); done
    rc=0
    [[ -n ${LUXOS_SB_CERT:-} ]] && mounts+=(-e "LUXOS_SB_CERT=/luxos/$(realpath -m --relative-to="$ROOT" "$LUXOS_SB_CERT")")
    "$engine" run --rm "${mounts[@]}" luxos-builder \
        bash -c 'command -v sbsign >/dev/null || pacman -Syu --noconfirm --needed sbsigntools >/dev/null; exec "$@"' \
        _ /luxos/scripts/sb-sign.sh "${args[@]}" || rc=$?
    [[ -n ${copy:-} ]] && rm -rf "$copy"
    return "$rc"
}

# signed_by_us SOUBOR CERT -> 0 = podpis certifikatem CERT je platny a CERT je primo v podpisu
# (sbverify --cert hlasi "OK" i u nekterych cizich retezcu s korenem v podpisu, napr. shim od Microsoftu)
signed_by_us() {
    sbverify --cert "$2" "$1" >/dev/null 2>&1 || return 1
    local der
    der=$(openssl x509 -in "$2" -outform DER | od -An -v -tx1 | tr -d ' \n')
    [[ $(od -An -v -tx1 "$1" | tr -d ' \n' | grep -cF "$der") != 0 ]]
}

sign_efi() {  # sign_efi SOUBOR... (klic v KDIR)
    local f
    for f in "$@"; do
        [[ -f $f ]] || die "no such file: $f"
        if signed_by_us "$f" "$KDIR/luxos-secureboot.crt"; then echo "already signed: $f"; continue; fi
        # jiny podpis (napr. testovaci klic) pryc, at je v souboru jen podpis LuxOS
        if sbverify --list "$f" 2>/dev/null | grep -q '^signature [0-9]'; then
            sbattach --remove "$f" >/dev/null
        fi
        sbsign --key "$KDIR/luxos-secureboot.key" --cert "$KDIR/luxos-secureboot.crt" --output "$f.signed" "$f" >/dev/null
        signed_by_us "$f.signed" "$KDIR/luxos-secureboot.crt" || { rm -f "$f.signed"; die "signature check failed: $f"; }
        mv -f "$f.signed" "$f"
        echo "signed: $f"
    done
}

verify_one() {  # verify_one SOUBOR|BALIK CERT
    local f=$1 cert=$2 tmp m rc=0 n=0
    if [[ $f == *.pkg.tar.zst ]]; then
        tmp=$(mktemp -d)
        while read -r m; do
            for p in "${SB_PATTERNS[@]}"; do
                # shellcheck disable=SC2053  # vzor (glob) zamerne
                [[ $m == $p ]] || continue
                n=$((n + 1))
                tar --zstd -xf "$f" -C "$tmp" "$m"
                if signed_by_us "$tmp/$m" "$cert"; then echo "OK      ${f##*/}: $m"
                else echo "UNSIGNED ${f##*/}: $m"; rc=1; fi
            done
        done < <(tar --zstd -tf "$f")
        rm -rf "$tmp"
        ((n)) || echo "-       ${f##*/}: no EFI files to sign"
    elif signed_by_us "$f" "$cert"; then echo "OK      $f"
    else echo "UNSIGNED $f"; rc=1; fi
    return "$rc"
}

cmd=${1:-}
shift || true
case $cmd in
    init)
        KDIR=$(key_dir)
        if [[ -f $KDIR/luxos-secureboot.key ]]; then
            echo "Secure Boot key already exists in $KDIR (not changed)."
        else
            genkey "$KDIR" "$CN" 10950    # 30 let - firmware ani shim platnost nekontroluji
            echo "Created the LuxOS Secure Boot key in $KDIR (private key 0600)."
            echo "Back it up like the repository key (the Safe); if it is lost, every computer must enroll a new key."
        fi
        install -Dm644 "$KDIR/luxos-secureboot.crt" "$PUBLIC"
        echo "Public certificate: $PUBLIC - commit it (public, safe to publish):"
        openssl x509 -in "$PUBLIC" -noout -subject -fingerprint -sha256 -enddate
        ;;
    test-key)
        dir=${1:?directory}
        genkey "$dir" "LuxOS Secure Boot TEST key - not for production" 60
        echo "Throwaway TEST key in $dir (60 days) - never use it for a release."
        ;;
    efi|package)
        (($#)) || die "no files given"
        if ! command -v sbsign >/dev/null; then in_container "$cmd" "$@"; exit; fi
        need_key
        if [[ $cmd == efi ]]; then
            sign_efi "$@"
        else
            for pkg in "$@"; do
                [[ $pkg == *.pkg.tar.zst && -f $pkg ]] || die "not a package: $pkg"
                python3 "$ROOT/scripts/sb_repack.py" "$pkg" "$(printf '%q _sign-one' "$ROOT/scripts/sb-sign.sh")" "${SB_PATTERNS[@]}" \
                    | sed 's/^/  /'
            done
        fi
        ;;
    _sign-one)   # interni: sb_repack.py vola skript na jeden vybaleny soubor
        need_key
        sign_efi "$1" >/dev/null
        ;;
    verify)
        (($#)) || die "no files given"
        if ! command -v sbverify >/dev/null; then in_container verify "$@"; exit; fi
        cert=${LUXOS_SB_CERT:-$PUBLIC}
        [[ -f $cert ]] || die "no certificate $cert (scripts/sb-sign.sh init, or LUXOS_SB_CERT=...)"
        rc=0
        for f in "$@"; do verify_one "$f" "$cert" || rc=1; done
        exit "$rc"
        ;;
    *)
        sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
        exit 2
        ;;
esac
