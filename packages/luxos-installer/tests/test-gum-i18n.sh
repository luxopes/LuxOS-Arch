#!/bin/bash
# Textovy instalator: kazde "gum confirm" ma prelozena tlacitka (bez --affirmative/--negative ukaze gum
# anglicke "Yes"/"No" i v ceskem pruvodci - regrese audit 1.0.2: otazka na casove pasmo).
#   bash packages/luxos-installer/tests/test-gum-i18n.sh
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
fail=0
for f in "$HERE"/../files/luxos-install "$HERE"/../files/luxos-oem "$HERE"/../files/*.sh; do
    [[ -f $f ]] || continue
    while IFS=: read -r n line; do
        if [[ $line != *--affirmative* || $line != *--negative* ]]; then
            echo "FAIL  ${f##*/}:$n: gum confirm bez prelozenych tlacitek"
            fail=1
        fi
    done < <(grep -n 'gum confirm' "$f" | grep -v '^[0-9]*:[[:space:]]*#')
done
((fail)) || echo "ok    vsechna gum confirm maji --affirmative a --negative"
exit $fail
