pss() { awk '/^Pss:/{print $2}' /proc/$pid/smaps_rollup; }
echo "pss_kib_start $(pss)" >"$OUT/pss.txt"
foot -W 72x18 -T "Terminal (foot)" >/dev/null 2>&1 &
sleep 1.5
weston-terminal >/dev/null 2>&1 &
sleep 2
cmd list
sleep 5
echo "pss_kib_2windows_idle $(pss)" >>"$OUT/pss.txt"
grep -E '^(Rss|Pss|Pss_Anon|Pss_File|Pss_Shmem|Private_Dirty)' /proc/$pid/smaps_rollup >>"$OUT/pss.txt"
grim "$OUT/01-two-windows.png"
python3 /src/tests/bar.py >/dev/null 2>&1 &
sleep 2
foot -W 72x18 -T "Second foot" >/dev/null 2>&1 &
sleep 1.5
foot -W 60x14 -T "Third foot" >/dev/null 2>&1 &
sleep 1.5
cmd list
grim "$OUT/02-bar-placement-cascade.png"
echo "pss_kib_4windows_bar $(pss)" >>"$OUT/pss.txt"
cmd fullscreen 1.5
cmd list
grim "$OUT/03-fullscreen-above-bar.png"
cmd fullscreen 1.5
cmd slide-left 0.1
grim "$OUT/04-slide-midway.png"
sleep 1
grim "$OUT/05-workspace2.png"
cmd slide 1.2
cmd list
grim "$OUT/06-after-reversed-slide.png"
cmd quit 1
