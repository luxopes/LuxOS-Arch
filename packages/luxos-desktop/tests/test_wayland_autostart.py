#!/usr/bin/env python3
"""XDG autostart relace na Waylandu (luxos-wayland-session, funkce autostart) nad soubory balicku.

    python3 -m unittest -v packages/luxos-desktop/tests/test_wayland_autostart.py

Lista na Waylandu ma vlastni polozku site, Dock a Bluetooth: nm-applet, blueman a Plank se v relaci LuxOS
spoustet nesmi (druha ikona site v liste), v relaci X11 (XFCE) ano. /etc/xdg/luxos ma prednost pred /etc/xdg,
takze polozka LuxOS zakryje puvodni nm-applet.desktop z network-manager-applet (ten LuxOS nevylucuje).
Misto systemd-run zapise falesny program jmena jednotek; nic se nespousti.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
FILES = HERE.parent / "files"
SESSION = FILES / "bin/luxos-wayland-session"
UPSTREAM_NM = "[Desktop Entry]\nName=Network\nExec=nm-applet\nNotShowIn=KDE;GNOME;\n"


class Autostart(unittest.TestCase):
    def started(self, desktop):
        """Jednotky app-luxos-autostart-*, ktere by relace spustila pro XDG_CURRENT_DESKTOP=desktop."""
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            luxos = t / "etc/xdg/luxos"
            luxos.mkdir(parents=True)
            subprocess.run(["cp", "-r", str(FILES / "xdg/autostart"), str(luxos)], check=True)
            (t / "etc/xdg/autostart").mkdir(parents=True)
            (t / "etc/xdg/autostart/nm-applet.desktop").write_text(UPSTREAM_NM)
            (t / "etc/xdg/autostart/other-app.desktop").write_text("[Desktop Entry]\nExec=other-app %U\n")
            (t / "bin").mkdir()
            log = t / "units"
            (t / "bin/systemd-run").write_text(f'#!/bin/sh\nfor a; do case $a in --unit=*) echo "${{a#--unit=}}" >>{log};; esac; done\n')
            (t / "bin/systemd-run").chmod(0o755)
            script = SESSION.read_text()
            func = script[script.index("autostart() {"):script.index("\n}\n", script.index("autostart() {")) + 3]
            env = {"PATH": f"{t}/bin:/usr/bin", "HOME": str(t / "home"), "XDG_CONFIG_HOME": str(t / "home/.config"),
                   "XDG_CONFIG_DIRS": f"{luxos}:{t}/etc/xdg"}
            # OnlyShowIn/NotShowIn se v relaci porovnava s LuxOS; pro X11 stejna pravidla proti XFCE
            func = func.replace("LuxOS", desktop)
            subprocess.run(["bash", "-c", func + "\nautostart"], env=env, check=True, timeout=30)
            return sorted(log.read_text().split()) if log.exists() else []

    def test_wayland_session_skips_x11_tray_applets(self):
        units = self.started("LuxOS")
        self.assertEqual(units, ["app-luxos-autostart-other-app"], units)

    def test_x11_session_keeps_nm_applet(self):
        units = self.started("XFCE")
        for want in ("app-luxos-autostart-nm-applet", "app-luxos-autostart-plank"):
            self.assertIn(want, units)


if __name__ == "__main__":
    unittest.main()
