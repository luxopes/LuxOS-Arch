#!/bin/bash
# LuxOS Mail - automaticky zaznam ukazkoveho videa pro overeni aplikace OAuth u Googlu.
#
#   docs/google-verification/record-demo.sh [--email ADRESA] [--name JMENO] [--debug] [--out ADRESAR]
#
# Vse bezi na virtualni obrazovce xvfb 1920x1080 (nikdy na skutecne obrazovce) v docasnem HOME,
# s vlastnim D-Bus, klicenkou a falesnymi servery (Gmail IMAP, token, accounts.google.com za mistni proxy).
# Nic se neposila na Google ani jinam do internetu. Posta se prelozi ze zdroju (lslc).
# Vysledek v ~/LuxOS-Arch/out/google-verification: parts/part-{a,g,b}.mp4 a luxos-mail-demo-preview.mp4.
# Klip se skutecnym souhlasem Google do videa vlozi record-consent.sh (spousti vlastnik na sve plose).
set -euo pipefail
here=$(dirname "$(readlink -f "$0")")
for t in xvfb-run xdotool xfwm4 xfce4-panel plank firefox certutil ffmpeg ffprobe rsvg-convert lslc dbus-daemon gnome-keyring-daemon python3; do
    command -v "$t" >/dev/null || { echo "Missing $t" >&2; exit 1; }
done
export LUXOS_DEMO_XVFB=1
exec env -u DISPLAY -u WAYLAND_DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u XDG_RUNTIME_DIR -u XAUTHORITY \
    nice -n 10 xvfb-run -a -s "-screen 0 1920x1080x24 -nolisten tcp" python3 "$here/record_demo.py" "$@"
