#!/bin/bash
# LuxOS - doplni site/iso.json (posledni ISO na webu) z hotoveho ISO
#
#   scripts/update-iso-json.sh out/iso/luxos-1.0.1-x86_64.iso            datum = dnes (UTC)
#   scripts/update-iso-json.sh --date 2026-11-08 cesta/luxos-1.0.1-x86_64.iso
#
# Zapise version, file, size (bajty), date a sha256. Verze se bere z nazvu souboru
# (luxos-X.Y.Z-x86_64.iso) a musi se shodovat s packages/luxos-branding/files/version; TEST ISO
# (luxos-X.Y.Z-TEST-...) se odmitne. Kdyz vedle ISO lezi SHA256SUMS, musi v nem byt stejny soucet.
# Soubor se zapise atomicky; nic se nenahrava (web zverejni scripts/publish-site.sh).
# LUXOS_ISO_JSON = jiny cilovy soubor (testy).
set -euo pipefail
ROOT=$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)
OUT_JSON=${LUXOS_ISO_JSON:-$ROOT/site/iso.json}
VERSION_FILE=${LUXOS_VERSION_FILE:-$ROOT/packages/luxos-branding/files/version}

die() { echo "update-iso-json: $*" >&2; exit 1; }

date=$(date -u +%F)
if [[ ${1:-} == --date ]]; then
    [[ $# -ge 2 ]] || die "--date needs a value (YYYY-MM-DD)"
    date=$2
    shift 2
fi
[[ $# -eq 1 ]] || die "usage: $0 [--date YYYY-MM-DD] luxos-X.Y.Z-x86_64.iso"
iso=$1
[[ $date =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] && date -u -d "$date" +%F >/dev/null 2>&1 \
    || die "bad date '$date' (YYYY-MM-DD)"
[[ -f $iso ]] || die "no such file: $iso"

file=${iso##*/}
[[ $file =~ ^luxos-([0-9]+\.[0-9]+\.[0-9]+)-x86_64\.iso$ ]] \
    || die "'$file' is not a release ISO name (luxos-X.Y.Z-x86_64.iso; TEST builds are not published)"
version=${BASH_REMATCH[1]}
branding=$(. "$VERSION_FILE" && echo "$VERSION")
[[ $version == "$branding" ]] \
    || die "ISO version $version differs from $VERSION_FILE (VERSION=$branding)"

size=$(stat -c %s -- "$iso")
(( size > 100 * 1024 * 1024 )) || die "$file has only $size bytes - not a complete ISO"
echo "==> sha256 $file ($size bytes)"
sha=$(sha256sum -- "$iso" | cut -d' ' -f1)

sums=$(dirname -- "$iso")/SHA256SUMS
if [[ -f $sums ]]; then
    listed=$(awk -v f="$file" '{n=$2; sub(/^\*/, "", n)} n == f {print $1}' "$sums")
    [[ -n $listed ]] || die "$file is not listed in $sums"
    [[ $listed == "$sha" ]] || die "checksum of $file differs from $sums ($listed)"
    echo "    matches $sums"
fi
[[ -f $iso.sig ]] || echo "    note: $file.sig not found yet (sign before publishing: see docs/release-*.md)" >&2

tmp=$(mktemp "$OUT_JSON.XXXXXX")
trap 'rm -f "$tmp"' EXIT
python3 - "$tmp" "$version" "$file" "$size" "$date" "$sha" <<'PY'
import json, sys
out, version, name, size, date, sha = sys.argv[1:]
with open(out, "w", encoding="utf-8") as f:
    json.dump({"version": version, "file": name, "size": int(size), "date": date, "sha256": sha}, f, indent=2)
    f.write("\n")
PY
chmod 644 "$tmp"
mv -f "$tmp" "$OUT_JSON"
trap - EXIT
echo "==> $OUT_JSON:"
cat "$OUT_JSON"
