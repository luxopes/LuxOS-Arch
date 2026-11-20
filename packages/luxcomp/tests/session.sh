#!/bin/bash
# Bezi v kontejneru: luxcomp-demo (headless pixman 1920x1080, nebo BACKENDS=x11 ve vnorenem Xvfb),
# prikazy pres fifo (funkce cmd), pak scenar $1 a cekani na konec kompozitoru
set -u
export B=${B:-/w/build} OUT=${OUT:-/w/shots}; mkdir -p "$OUT"
export XDG_RUNTIME_DIR=$(mktemp -d) WLR_BACKENDS=${BACKENDS:-headless} WLR_LIBINPUT_NO_DEVICES=1 \
  WLR_HEADLESS_OUTPUTS=1 LUXCOMP_OUTPUT_MODE=1920x1080 LD_LIBRARY_PATH=$B
chmod 700 "$XDG_RUNTIME_DIR"
fifo=$XDG_RUNTIME_DIR/cmd; mkfifo "$fifo"
"$B/luxcomp-demo" <"$fifo" >"$OUT/demo.log" 2>&1 &
pid=$!
exec 3>"$fifo"
for i in $(seq 50); do [ -S "$XDG_RUNTIME_DIR/wayland-0" ] && break; sleep 0.1; done
export WAYLAND_DISPLAY=wayland-0
cmd() { echo "$1" >&3; sleep ${2:-0.5}; }
source "$1"
wait $pid
