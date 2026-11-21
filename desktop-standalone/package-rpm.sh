#!/bin/bash
# LuxOS Desktop: balicek RPM z hotoveho stromu (build.sh rpm). $1 strom, $2 verze, $3 commit, $4 vystup
set -euo pipefail
HERE=$(dirname "$(readlink -f "$0")")
stage=$(readlink -f "$1") ver=$2 commit=$3 out=$4
top=$(dirname "$stage")/rpmbuild
rm -rf "$top" && mkdir -p "$top"/{SPECS,BUILD,RPMS,SOURCES,SRPMS}
requires=$(grep -v '^#' "$HERE/deps/fedora-runtime.txt" | tr -s ' \n' ' ')

# Seznam souboru: vlastni adresare LuxOS cele, jinde jen jednotlive soubory (adresare systemu vlastni jine balicky)
own='^/(usr/lib/luxos|usr/share/luxos|etc/xdg/luxos|usr/lib/lux-desktop|usr/share/backgrounds/luxos|usr/share/themes/WhiteSur[^/]*|usr/share/icons/WhiteSur[^/]*|usr/share/plank/themes/WhiteSur[^/]*|usr/share/licenses/lux-desktop|usr/share/doc/lux-desktop|usr/share/licenses/luxos-[^/]*|usr/share/sounds/luxos)(/|$)'
(cd "$stage" && find . -mindepth 1 \( -type f -o -type l \) -printf '/%P\n' | sort) | awk -v own="$own" '
    { if ($0 ~ own) { match($0, own); d = substr($0, 1, RLENGTH); sub(/\/$/, "", d); if (!(d in seen)) { seen[d] = 1; print "%dir_or_tree " d } }
      else print }' | sed -e 's/^%dir_or_tree //' | sort -u | sed -e 's/^/"/' -e 's/$/"/' >"$top/files.list"

cat >"$top/SPECS/lux-desktop.spec" <<SPEC
%global debug_package %{nil}
%global __os_install_post %{nil}
%global __brp_check_rpaths %{nil}
%define _build_id_links none
%global __requires_exclude_from ^/usr/lib/lux-desktop/rofi/.*\$
Name:           lux-desktop
Version:        $ver
Release:        1%{?dist}
Summary:        The LuxOS desktop on top of Xfce
License:        GPL-3.0-or-later AND MIT AND LGPL-2.1-or-later
URL:            https://github.com/luxopes/lux-desktop
BuildArch:      x86_64
Requires:       $requires

%description
LuxOS Desktop: the desktop of LuxOS (menu bar, Dock, Launchpad, Control Center, widgets,
hot corners, Emoji, screenshots, settings), written mostly in LSL, as an extra
"LuxOS Desktop" session for this distribution. Built from LuxOS-Arch commit $commit.

%install
cp -a "$stage/." %{buildroot}/

%post
gtk-update-icon-cache -q -f /usr/share/icons/hicolor >/dev/null 2>&1 || :
for t in /usr/share/icons/WhiteSur*; do gtk-update-icon-cache -q -f "\$t" >/dev/null 2>&1 || :; done
udevadm control --reload >/dev/null 2>&1 || :

%postun
gtk-update-icon-cache -q -f /usr/share/icons/hicolor >/dev/null 2>&1 || :

%files -f $top/files.list
SPEC
rpmbuild -bb --quiet --define "_topdir $top" "$top/SPECS/lux-desktop.spec"
find "$top/RPMS" -name '*.rpm' -exec cp {} "$out/" \;
ls -1 "$out"/*.rpm
