python3 /src/tests/bar.py >/dev/null 2>&1 &
sleep 2
foot -W 72x18 >/dev/null 2>&1 &
sleep 1.5
weston-terminal >/dev/null 2>&1 &
sleep 2
cmd list
grim "$OUT/nested-wayland.png"
xwd -root -display :7 -silent > "$OUT/nested-xvfb.xwd" && magick "xwd:$OUT/nested-xvfb.xwd" "$OUT/nested-xvfb.png" && rm "$OUT/nested-xvfb.xwd"
cmd quit 1
