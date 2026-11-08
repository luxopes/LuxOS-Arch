#!/usr/bin/env python3
"""LuxOS - jak dlouho stoji hlavni smycka Docku (Plank) pri odkryti a zvetsovani ikon.

Spousti se UVNITR izolovane relace (session.sh). Nastaveni jako v LuxOS (tema WhiteSur-Light,
ikony WhiteSur-light, zoom 150 %, window-dodge). Behem testu se Plank kazdych 5 ms pinga pres
D-Bus (net.launchpad.plank.Items.GetCount se vyridi v hlavni smycce Planku); nejdelsi odezva =
nejdelsi zastaveni hlavni smycky.

Prubeh: 1) prvni odkryti + pomaly pruchod mysi po Docku (studene vyrovnavaci pameti ikon),
2) totez znovu (teple), 3) zmena tematu ikon (jako po aktualizaci systemu: Plank zahodi
vsechny vykreslene ikony) a znovu pruchod.

Pouziti: dock_latency.py PRACOVNI_ADRESAR [--plank /usr/bin/plank] [--rounds 3]
Vystup: JSON s max/p99 odezvou pro kazdou fazi (ms) do PRACOVNI_ADRESAR/latency.json
"""
import argparse
import json
import os
import subprocess
import sys
import threading
import time

from gi.repository import Gio, GLib

W, H = 1280, 800
APPS = ["luxos-launchpad", "luxai", "luxos-store", "thunar", "firefox", "luxos-terminal",
        "luxos-text", "xfce-settings-manager", "luxos-maps", "luxos-mail", "luxos-calculator"]
COVER_PY = r'''
import gi, sys
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk
w = Gtk.Window(title="cover"); w.move(0, 0); w.set_default_size(1280, 800); w.set_decorated(False)
w.connect("destroy", Gtk.main_quit); w.show_all(); Gtk.main()
'''


class Pinger(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.samples = []      # (cas, odezva s)
        self.run_flag = True

    def run(self):
        while self.run_flag:
            t0 = time.monotonic()
            try:
                self.bus.call_sync("net.launchpad.plank", "/net/launchpad/plank/dock1",
                                   "net.launchpad.plank.Items", "GetCount", None, None,
                                   Gio.DBusCallFlags.NONE, 30000, None)
            except GLib.Error:
                pass
            dt = time.monotonic() - t0
            self.samples.append((t0, dt))
            time.sleep(0.005)

    def window(self, t_from, t_to):
        v = sorted(dt for t, dt in self.samples if t_from <= t <= t_to)
        if not v:
            return {"n": 0}
        return {"n": len(v), "max_ms": round(v[-1] * 1000, 1),
                "p99_ms": round(v[int(len(v) * 0.99) - 1] * 1000, 1),
                "median_ms": round(v[len(v) // 2] * 1000, 1)}


def mouse(x, y):
    subprocess.run(["xdotool", "mousemove", str(int(x)), str(int(y))])


def gset(key, val):
    subprocess.run(["gsettings", "set", "net.launchpad.plank.dock.settings:/net/launchpad/plank/docks/dock1/",
                    key, val])


def sweep(x0, x1, steps=120, dt=0.012):
    mouse(x0, H - 1)
    time.sleep(0.05)
    for i in range(steps + 1):
        mouse(x0 + (x1 - x0) * i / steps, H - 2)
        time.sleep(dt)
    for i in range(steps + 1):
        mouse(x1 - (x1 - x0) * i / steps, H - 2)
        time.sleep(dt)
    mouse(W // 2, 200)
    time.sleep(1.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("work")
    ap.add_argument("--plank", default="/usr/bin/plank")
    a = ap.parse_args()
    home = os.environ["HOME"]
    os.makedirs(os.path.join(home, ".config/gtk-3.0"), exist_ok=True)
    with open(os.path.join(home, ".config/gtk-3.0/settings.ini"), "w") as fh:
        fh.write("[Settings]\ngtk-icon-theme-name=WhiteSur-light\ngtk-theme-name=WhiteSur-Light\n")
    launch = os.path.join(home, ".config/plank/dock1/launchers")
    os.makedirs(launch, exist_ok=True)
    apps = [p for p in APPS if os.path.exists(f"/usr/share/applications/{p}.desktop")]
    for p in apps:
        with open(os.path.join(launch, f"{p}.dockitem"), "w") as fh:
            fh.write(f"[PlankDockItemPreferences]\nLauncher=file:///usr/share/applications/{p}.desktop\n")
    gset("dock-items", "[" + ",".join(f"'{p}.dockitem'" for p in apps) + "]")
    for k, v in [("theme", "'WhiteSur-Light'"), ("icon-size", "48"), ("zoom-enabled", "true"),
                 ("zoom-percent", "150"), ("hide-mode", "'window-dodge'"), ("unhide-delay", "0"),
                 ("hide-delay", "300"), ("tooltips-enabled", "true")]:
        gset(k, v)
    cover = subprocess.Popen([sys.executable, "-c", COVER_PY])
    time.sleep(1.0)
    log = open(os.path.join(a.work, "plank-latency.log"), "w")
    plank = subprocess.Popen([a.plank], stdout=log, stderr=subprocess.STDOUT)
    time.sleep(4.0)
    p = Pinger()
    p.start()
    time.sleep(1.0)
    n = len(apps)
    x0, x1 = W / 2 - n * 26, W / 2 + n * 26
    res = {"plank": a.plank, "items": n}
    t = time.monotonic()
    res["idle"] = p.window(t - 1.0, t)
    t0 = time.monotonic(); sweep(x0, x1); res["cold"] = p.window(t0, time.monotonic())
    t0 = time.monotonic(); sweep(x0, x1); res["warm"] = p.window(t0, time.monotonic())
    # zmena tematu ikon (napr. po aktualizaci): GtkIconTheme si zmeny adresaru vsimne -> Plank zahodi ikony
    icons = os.path.join(home, ".local/share/icons")
    os.makedirs(icons, exist_ok=True)
    time.sleep(6.0)
    os.utime(icons)
    mouse(x0, H - 1)       # GtkIconTheme kontroluje zmeny pri pouziti
    time.sleep(0.4)
    mouse(W // 2, 200)
    time.sleep(1.5)
    t0 = time.monotonic(); sweep(x0, x1); res["after_icon_theme_change"] = p.window(t0, time.monotonic())
    p.run_flag = False
    p.join(2)
    res["plank_alive"] = plank.poll() is None
    plank.terminate()
    cover.terminate()
    with open(os.path.join(a.work, "latency.json"), "w") as fh:
        json.dump(res, fh, indent=1)
    print(json.dumps(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
