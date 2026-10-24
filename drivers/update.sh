#!/bin/bash
# LuxOS - udrzba [luxos-drivers]: znovu overit vse, co se v AUR zmenilo, ukazat rozdily, sestavit.
#   drivers/update.sh [--discover]     (--discover = i nove baliky vyrobcu z AUR)
# Zverejneni je zamerne rucni krok: scripts/publish-repo.sh (po kontrole out/drivers/diffs/).
# Volitelne LUXOS_DRIVERS_REVIEW=prikaz (napr. kontrola LuxAI): JSON na stdin, nenulovy kod = odmitnuto.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."

[[ ${1:-} == --discover ]] && python3 drivers/luxdrv.py discover
rm -rf out/drivers/diffs
python3 drivers/luxdrv.py verify
python3 drivers/luxdrv.py report
if compgen -G "out/drivers/diffs/*.diff" >/dev/null; then
    echo "==> Changes since the last verified versions (passed the rules - read them anyway):"
    for f in out/drivers/diffs/*.diff; do
        printf '\n----- %s\n' "$(basename "$f" .diff)"
        cat "$f"
    done | ${PAGER:-less -R}
fi
read -rp "Build [luxos-drivers] now? [y/N] " a
[[ $a == [yY]* ]] || exit 0
./build.sh drivers
echo "==> Built: out/drivers-repo/luxos-drivers (failed: out/drivers-repo/failed.txt)"
echo "    Publish with: scripts/publish-repo.sh"
