#!/bin/bash
# Porovnani vystupu lux_alpm.py a lux-alpm (LSL): stdout, stderr a navratovy kod, en/cs a obycejny,
# barevny a strojovy vystup. Jen cteci prikazy, nic se neinstaluje.
#   lslc --target linux-x86_64-gnu --system-bindings packages/lux/lsl \
#        --system-bindings packages/luxos-desktop/files/lsl packages/lux/lsl/lux-alpm.lsl /tmp/lux-alpm
#   packages/lux/lsl/parity.sh /tmp/lux-alpm
set -u
PY=${LUX_ALPM_PY:-/usr/lib/lux/lux_alpm.py}; LSL=$1; fails=0; n=0
t=$(mktemp -d); trap 'rm -rf "$t"' EXIT
cases=(
 "search vim" "search ^vim" "search *qt6*" "search vim\$" "search firefox browser" "search --installed glib" "search neexistujicixyz"
 "info glibc" "info firefox" "info --sync glibc" "info vim" "info base-devel" "info neexistuje"
 "list" "list --explicit" "list --foreign" "list --orphans" "list --upgradable" "list --sync" "list lib" "list --sync qt6"
 "files glibc" "files neexistuje" "owns /usr/bin/bash" "owns bash" "owns /etc/" "owns /neni/takovy" "owns /usr/lib/libc.so.6 /usr/bin/ls"
 "resolve glibc base-devel sh neexistuje extra/vim"
)
for lng in en_US.UTF-8 cs_CZ.UTF-8; do for mode in "" "--color always" "--machine"; do for c in "${cases[@]}"; do
  n=$((n+1))
  a=$(LANG=$lng $PY $mode $c 2>"$t/pe"; echo "rc=$?"); ae=$(cat "$t/pe")
  b=$(LANG=$lng $LSL $mode $c 2>"$t/le"; echo "rc=$?"); be=$(cat "$t/le")
  if [[ "$a" != "$b" || "$ae" != "$be" ]]; then
    fails=$((fails+1)); echo "=== ROZDIL: LANG=$lng $mode $c"
    diff <(echo "$a"; echo "--stderr--"; echo "$ae") <(echo "$b"; echo "--stderr--"; echo "$be") | head -8
  fi
done; done; done
echo "shoda $((n-fails))/$n"
[[ $fails == 0 ]]
