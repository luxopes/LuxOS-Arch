# Material (blur.c) headless pod pixman: plocha "test-popup@popup:16" 400x500 nad oknem s pruhy;
# snimky s rozmazanim, pri pohybu okna (wiggle, cas snimku v demo.log s LUXCOMP_STATS), jednolita barva,
# plocha bez materialu a automaticky prechod na jednolitou barvu (LUXCOMP_BLUR_SLOW_MS v druhem behu).
# Vyhodnoceni: blur_check.py
python3 /src/tests/material.py stripes 1600 900 >>"$OUT/clients.log" 2>&1 &
sleep 2
python3 /src/tests/material.py layer "test-popup@popup:16" 400 500 >>"$OUT/clients.log" 2>&1 &
popup=$!
sleep 2
grim "$OUT/blur-on.png"
cmd "wiggle 1200" 11
grim "$OUT/blur-after-move.png"
if [ -n "${LUXCOMP_BLUR_SLOW_MS-}" ]; then cmd quit 1; return; fi
cmd "blur 0" 1
grim "$OUT/blur-solid.png"
cmd "blur 1" 1
kill $popup
python3 /src/tests/material.py layer "test-popup" 400 500 >>"$OUT/clients.log" 2>&1 &
sleep 2
grim "$OUT/blur-absent.png"
cmd quit 1
