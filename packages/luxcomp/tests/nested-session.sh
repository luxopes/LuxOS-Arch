#!/bin/bash
# Bezi v kontejneru: soukromy Xvfb a v nem luxcomp-demo s backendem x11
Xvfb :7 -screen 0 1920x1080x24 -nolisten tcp >/dev/null 2>&1 &
xpid=$!
sleep 1
DISPLAY=:7 BACKENDS=x11 OUT=${OUT:-/w/shots-nested} /src/tests/session.sh "$1"
kill $xpid
