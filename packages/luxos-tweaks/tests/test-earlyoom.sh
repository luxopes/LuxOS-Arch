#!/bin/bash
# LuxOS - test seznamu earlyoom (--avoid/--prefer v files/earlyoom.conf): ktere procesy jsou chranene
# a ktere se ukonci prednostne. Jmena jsou /proc/PID/comm (nejvys 15 znaku) - vcetne procesu, ktere
# earlyoom ukoncil pri skutecnem nedostatku pameti 2. 11. 2026. Bez roota, nic nespousti.
#   bash packages/luxos-tweaks/tests/test-earlyoom.sh
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
CONF=$HERE/../files/earlyoom.conf
FAIL=0
ok() { if "$@"; then echo "ok    $DESC"; else echo "FAIL  $DESC"; FAIL=$((FAIL + 1)); fi; }

# regularni vyraz z ExecStart ("$$" v systemd = "$")
regex() { sed -n "s/.*--$1 \"\\([^\"]*\\)\".*/\\1/p" "$CONF" | sed 's/\$\$/$/'; }
AVOID=$(regex avoid)
PREFER=$(regex prefer)
DESC="--avoid a --prefer jsou v konfiguraci"; ok test -n "$AVOID" -a -n "$PREFER"
# earlyoom pouziva POSIX ERE (regcomp REG_EXTENDED) stejne jako grep -E
matches() { printf '%s\n' "$2" | grep -Eq -- "$1"; }

echo "## chranene (male sluzby sezeni - ukonceni neuvolni pamet, ale rozbije sezeni)"
for name in Xorg xfce4-panel wrapper-2.0 xfwm4 pipewire pipewire-pulse wireplumber dbus-broker \
            xfce4-notifyd xfconfd xfce4-power-man xfce4-screensav light-locker gnome-keyring-d \
            dconf-service xdg-desktop-por xdg-document-po xdg-permission- flatpak-portal \
            flatpak-session gvfsd gvfsd-metadata gvfsd-trash gvfs-udisks2-vo gvfs-mtp-volume bamfdaemon \
            luxos-hub luxos-menubar; do
    DESC="avoid: $name"; ok matches "$AVOID" "$name"
done

echo "## nechranene (velke aplikace, hry, nase okna - i luxos-bluetooth s unikem pameti)"
for name in godot Hanakage.x86_64 cs2 python3 luxos-bluetooth firefox Thunar luxai steam \
            xfce4-notifyd-c gvfs; do
    DESC="not avoid: $name"; ok bash -c '! printf "%s\n" "$2" | grep -Eq -- "$1"' _ "$AVOID" "$name"
done

echo "## prednostne"
for name in steamwebhelper "Web Content" "Isolated Web Co" WebExtensions chromium electron WebKitWebProces; do
    DESC="prefer: $name"; ok matches "$PREFER" "$name"
done
for name in xfce4-notifyd godot Xorg steam; do
    DESC="not prefer: $name"; ok bash -c '! printf "%s\n" "$2" | grep -Eq -- "$1"' _ "$PREFER" "$name"
done

echo "## zadny proces neni zaroven chraneny i prednostni"
for name in steamwebhelper "Web Content" xfce4-notifyd gvfsd; do
    DESC="ne obe: $name"
    ok bash -c '! { printf "%s\n" "$3" | grep -Eq -- "$1" && printf "%s\n" "$3" | grep -Eq -- "$2"; }' _ "$AVOID" "$PREFER" "$name"
done

if command -v systemd-analyze >/dev/null; then
    echo "## drop-in je platny pro systemd"
    T=$(mktemp -d)
    trap 'rm -rf "$T"' EXIT
    printf '[Service]\nExecStart=/usr/bin/earlyoom\n' >"$T/earlyoom.service"
    mkdir -p "$T/earlyoom.service.d"
    cp "$CONF" "$T/earlyoom.service.d/10-luxos.conf"
    out=$(cd "$T" && SYSTEMD_UNIT_PATH="$T:" systemd-analyze verify earlyoom.service 2>&1 | grep -v "earlyoom.service: Command /usr/bin/earlyoom is not executable")
    DESC="systemd-analyze verify bez chyb"; ok test -z "$out"
fi

echo
[ $FAIL -eq 0 ] && echo "VSE OK" || echo "SELHALO: $FAIL"
exit $FAIL
