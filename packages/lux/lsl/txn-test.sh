#!/bin/bash
# Transakce lux_alpm.py a lux-alpm (LSL) vedle sebe ve falesnych korenech: kazdy scenar v cerstvem
# koreni pro kazdou verzi, porovna vystup, mistni databazi a strom souboru. Nic se nedotkne systemu:
# RootDir/DBPath/CacheDir jsou v docasne slozce, "root" je jen v user namespace (unshare -r),
# ochrana /usr (LuxOS Care) je vypnuta testovacim LUXOS_CARE_ROOT, countme a migrace take.
#
#   packages/lux/lsl/txn-test.sh /cesta/lux-alpm [LIBALPM_DIR]
#
# LIBALPM_DIR: libalpm s lux-engine zaplatou 0004 (bez ni lux-alpm scriptlety a hooky nespusti -
# log callback v detskem procesu). Stahuje z internetu (iana-etc, tzdata, zlib + zavislosti, ~15 MB).
# Rozdily v poradi paralelne stahovanych souboru a v casech nejsou chyba.
set -u
LSL=$1; LIBALPM=${2:-}
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
mkdir -p "$T/care" "$T/gnupg"; chmod 700 "$T/gnupg"
cp /etc/lux/keyring/{pubring.gpg,trustdb.gpg,gpg.conf} "$T/gnupg/" 2>/dev/null

mkroot() {
    local R=$1
    rm -rf "$R"; mkdir -p "$R"/var/lib/lux/{sync,local} "$R"/var/cache/lux/pkg "$R"/etc "$R"/var/log "$R"/tmp
    cp -a /var/lib/lux/sync/*.db /var/lib/lux/sync/*.sig "$R"/var/lib/lux/sync/ 2>/dev/null
    cp -a /var/lib/lux/local/ALPM_DB_VERSION "$R"/var/lib/lux/local/ 2>/dev/null
    cat > "$R/engine.conf" <<C
[options]
RootDir = $R/
DBPath = $R/var/lib/lux/
CacheDir = $R/var/cache/lux/pkg/
LogFile = $R/var/log/lux.log
GPGDir = $T/gnupg/
HookDir = $R/etc/lux/hooks/
Architecture = auto
SigLevel = Required DatabaseOptional
LocalFileSigLevel = Optional
CheckSpace
ParallelDownloads = 5
HoldPkg = glibc filesystem

[luxos]
Server = https://luxos.lux-ai.cz/staging/\$repo/\$arch
[luxos-apps]
Server = https://luxos.lux-ai.cz/staging/\$repo/\$arch
[core]
Server = https://frankfurt.mirror.pkgbuild.com/\$repo/os/\$arch
[extra]
Server = https://frankfurt.mirror.pkgbuild.com/\$repo/os/\$arch
C
}

run() {  # run py|lsl ROOT args...
    local w=$1 R=$2; shift 2
    local B=/usr/lib/lux/lux_alpm.py; [[ $w == lsl ]] && B=$LSL
    env ${LIBALPM:+LD_LIBRARY_PATH=$LIBALPM} LUX_ENGINE_CONF="$R/engine.conf" LUXOS_CARE_ROOT="$T/care" \
        LUX_NO_COUNTME=1 LUX_MIGRATE=/nonexistent LUX_RETRY_DELAY=0 TMPDIR="$T" unshare -r "$B" "$@"
}

norm() {  # cesty, casy a rychlosti pryc
    sed -E "s#$2#ROOT#g; s/[0-9]+([.,][0-9]+)? (s|kB|MB|B)\\b/N \\2/g; s/ [0-9]+[.,][0-9]+\$/ T/" "$1"
}

tree() { (cd "$1" && find . -path ./var/cache -prune -o -path ./var/log -prune -o -print | sort); }

fails=0; n=0
scenario() {  # scenario JMENO "PRIPRAVA" args...
    local name=$1 pre=$2; shift 2
    n=$((n+1))
    for w in py lsl; do
        mkroot "$T/$w"
        [[ -n $pre ]] && run $w "$T/$w" -y $pre >/dev/null 2>&1
        run $w "$T/$w" "$@" > "$T/$w.out" 2>&1 < /dev/null; echo "rc=$?" >> "$T/$w.out"
    done
    local bad=""
    diff <(norm "$T/py.out" "$T/py") <(norm "$T/lsl.out" "$T/lsl") > "$T/diff" || bad="vystup"
    [[ $(ls "$T/py/var/lib/lux/local") == $(ls "$T/lsl/var/lib/lux/local") ]] || bad="$bad databaze"
    [[ $(tree "$T/py") == $(tree "$T/lsl") ]] || bad="$bad soubory"
    if [[ -n $bad ]]; then
        fails=$((fails+1)); echo "=== ROZDIL ($bad): $name"; head -12 "$T/diff"
    else
        echo "ok   $name"
    fi
}

scenario "install --machine" "" --machine -y install iana-etc
scenario "install" "" -y install tzdata
scenario "install cs" "" --lang cs_CZ.UTF-8 -y install tzdata
scenario "install se zavislostmi a scriptlety" "" -v -y install --asdeps zlib
scenario "install --needed" "install iana-etc" --machine -y install --needed iana-etc
scenario "install --download-only" "" --machine -y install --download-only tzdata
scenario "neexistujici balik" "" -y install neexistujici-balik
scenario "bez -y mimo terminal" "" --machine install tzdata
scenario "reinstall" "install iana-etc" --machine -y reinstall iana-etc
scenario "remove" "install iana-etc tzdata" --machine -y remove tzdata
scenario "remove HoldPkg" "install zlib" --machine -y remove zlib
scenario "remove neinstalovany" "" -y remove neexistujici-balik
scenario "autoremove" "install --asdeps iana-etc" -y autoremove
scenario "upgrade nic" "" --machine -y upgrade
scenario "sync" "" --machine sync
echo "shoda $((n-fails))/$n"
[[ $fails == 0 ]]
