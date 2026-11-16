#!/bin/bash
# sudo bez anglicke "lecture" pri prvnim pouziti (regrese audit 1.0.2: tlacitko Aktualizovat v uvitacim
# okne ukazalo "We trust you have received the usual lecture from the local System Administrator...").
#   bash packages/luxos-tweaks/tests/test-sudoers.sh
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
F=$HERE/../files/security/sudoers-luxos-lecture
FAIL=0
ok() { if "${@:2}"; then echo "ok    $1"; else echo "FAIL  $1"; FAIL=$((FAIL + 1)); fi; }
ok "Defaults lecture=never" grep -qx 'Defaults lecture=never' "$F"
ok "jen komentare a Defaults (zadna prava navic)" bash -c "! grep -vE '^(#.*|Defaults lecture=never|)$' '$F'"
if command -v visudo >/dev/null; then ok "visudo: platna syntaxe" visudo -cqf "$F"; fi
ok "PKGBUILD: 0440 v /etc/sudoers.d, adresar 0750" bash -c \
    "grep -q 'install -m440 \"\$f/security/sudoers-luxos-lecture\" \"\$pkgdir/etc/sudoers.d/05-luxos-lecture\"' '$HERE/../PKGBUILD' &&
     grep -q 'install -dm750 \"\$pkgdir/etc/sudoers.d\"' '$HERE/../PKGBUILD'"
echo
echo "Vysledek: $FAIL FAIL"
exit $((FAIL > 0))
