# Vstup pres Xvfb (xdotool): klik do zahlavi = zamereni + presun, zavreni semaforem, Alt+Tab, Ctrl+Right
X() { DISPLAY=:7 xdotool "$@"; sleep 0.4; }
foot -W 60x14 >/dev/null 2>&1 &
sleep 1.5
foot -W 60x14 >/dev/null 2>&1 &
sleep 1.5
cmd list
# zahlavi prvniho foot (neaktivni): podle listu; demo umistuje prvni doprostred
read -r _ id app _ geo _ <<<"$(grep '^view' "$OUT/demo.log" | tail -1)"
echo "first: $id $geo" >>"$OUT/input.txt"
g=${geo##*x}; w=${geo%%x*}; rest=${geo#*+}; x=${rest%%+*}; y=${rest##*+}
X mousemove $((x + 150)) $((y - 14)) mousedown 1
X mousemove $((x + 450)) $((y + 186))
X mouseup 1
cmd list
grim "$OUT/input-after-drag.png"
X key alt+Tab
cmd list
# psani jde do zameraneho okna (klavesnice pres seat)
X type "echo luxcomp-keyboard-ok"
X key Return
grim "$OUT/input-typed.png"
X key ctrl+Right
sleep 0.6
grim "$OUT/input-after-ctrl-right.png"
X key ctrl+Left
sleep 0.6
cmd list
# zavrit nejvyssi okno cervenym tlacitkem
read -r _ id _ _ geo _ <<<"$(grep '^view' "$OUT/demo.log" | tail -2 | head -1)"
rest=${geo#*+}; x=${rest%%+*}; y=${rest##*+}
X mousemove $((x + 14)) $((y - 14)) click 1
sleep 0.5
cmd list
cmd quit 1
