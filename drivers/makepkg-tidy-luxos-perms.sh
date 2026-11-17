#!/usr/bin/bash
# LuxOS - krok "tidy" makepkg jen pro ovladace [luxos-drivers] (scripts/container-build.sh: MAKEPKG_LIBRARY je kopie
# /usr/share/makepkg s timto souborem v tidy/). Bezi ve fakeroot v $pkgdir kazdeho baliku PO package() - plati
# tedy i pro prava, ktera nastavi skripty vyrobce (make install, RPM ...), nejen PKGBUILD.
#   - setuid/setgid u souboru: odebrat (filtry a backendy CUPS bezi pod uzivatelem cups, root netreba)
#   - soubor/adresar zapisovatelny pro vsechny: zapis pro ostatni pryc; skupina cups (209, pevne GID z balicku
#     cups) smi zapisovat - filtry nekterych ovladacu (Brother brcupsconfig) si tam zapisuji nastaveni ulohy
# Vyjimky: LUXDRV_PERMS_ALLOW_TSV (radky "pkgname<TAB>cesta<TAB>mod" z drivers/perms-allow.json).
# Hotovy balik pak jeste zkontroluje drivers/luxdrv.py perms - co neprojde, se nezverejni.

[[ -n "$LIBMAKEPKG_TIDY_LUXOS_PERMS_SH" ]] && return
LIBMAKEPKG_TIDY_LUXOS_PERMS_SH=1

tidy_modify+=('tidy_luxos_perms')

tidy_luxos_perms() {
	local f rel mode allow=${LUXDRV_PERMS_ALLOW_TSV:-}
	while IFS= read -r -d '' f; do
		rel=${f#./}
		mode=$(stat -c %a -- "$f") || continue
		if [[ -n $allow && -r $allow ]] && grep -qxF "${pkgname}	${rel}	${mode}" "$allow"; then
			continue
		fi
		if [[ -f $f ]] && (( 8#$mode & 8#6000 )); then
			chmod ug-s -- "$f"
			warning "LuxOS: removed setuid/setgid from /%s (%s)" "$rel" "$mode"
		fi
		if (( 8#$mode & 8#0002 )); then
			chgrp 209 -- "$f"
			chmod o-w,g+w -- "$f"
			warning "LuxOS: /%s (%s) is no longer world-writable (group cups may write)" "$rel" "$mode"
		fi
	done < <(find . -mindepth 1 \( -type f -o -type d \) -perm /6002 -print0)
}
