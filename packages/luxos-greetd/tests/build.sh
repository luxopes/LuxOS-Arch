#!/bin/bash
# Stavba luxos-greeter (LSL) pro testy na hostiteli, vystup out/greeter-build/luxos-greeter. Vazby greeteru
# a moduly luxos-desktop jako systemove bindingy (lslc >= 0.11; LSLC prepise prekladac). Balik: PKGBUILD.
set -euo pipefail
root=$(cd "$(dirname "$0")/../../.." && pwd)
b=${LUXOS_GREETER_BUILD:-$root/out/greeter-build}
mkdir -p "$b"
"${LSLC:-lslc}" --target linux-x86_64-gnu --system-bindings "$root/packages/luxos-greetd/files/lsl" \
    --system-bindings "$root/packages/luxos-desktop/files/lsl" "$root/packages/luxos-greetd/files/lsl/luxos-greeter.lsl" \
    "$b/luxos-greeter"
echo "$b/luxos-greeter"
