#!/bin/bash
# gamescope pro test_luxwm_gaming.py (vnoreny gamescope v luxwm): balicky Archu stazene pacmanem v kontejneru
# (overene podpisy), rozbalene do out/gamescope/root bez instalace na hostitele. Knihovny, ktere hostitel
# nema (libseat, libeis), jsou ve stejnem stromu; Xwayland bere test ze sysroot harnessu.
set -euo pipefail
root=$(cd "$(dirname "$0")/../../.." && pwd)
out=$root/out/gamescope
mkdir -p "$out/pkgs" "$out/root"
env -u DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u XAUTHORITY timeout 900 podman run --rm -v "$out/pkgs:/pkgs:z" \
  docker.io/archlinux/archlinux:latest bash -c 'pacman -Sy --noconfirm >/dev/null && pacman -Sw --noconfirm --cachedir /pkgs gamescope seatd libei >/dev/null'
for p in gamescope seatd libei; do
  f=$(ls "$out"/pkgs/$p-[0-9]*.pkg.tar.zst | tail -1)
  sha256sum "$f"
  tar -C "$out/root" -xf "$f" usr
done
echo "$out/root"
