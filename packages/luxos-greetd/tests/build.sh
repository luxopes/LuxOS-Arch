#!/bin/bash
# Stavba luxos-greeter (LSL) pro testy na hostiteli: moduly greeteru a sdilene moduly z luxos-desktop do jednoho
# adresare (LSL hleda moduly vedle zdroje), vystup out/greeter-build/luxos-greeter. Balik se stavi pres PKGBUILD.
set -euo pipefail
root=$(cd "$(dirname "$0")/../../.." && pwd)
b=${LUXOS_GREETER_BUILD:-$root/out/greeter-build}
mkdir -p "$b/src"
cp "$root"/packages/luxos-greetd/files/lsl/*.lsl "$b/src/"
for m in luxos_glib luxos_gio luxos_gtk luxos_sys luxos_text luxos_i18n luxos_material luxos_lock_draw luxos_lock_sys luxos_tokens; do
    cp "$root/packages/luxos-desktop/files/lsl/$m.lsl" "$b/src/"
done
lslc --target linux-x86_64-gnu "$b/src/luxos-greeter.lsl" "$b/luxos-greeter"
echo "$b/luxos-greeter"
