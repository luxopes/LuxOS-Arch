#!/usr/bin/env python3
"""LuxOS - zvetsovani ikon v Docku (Plank) musi fungovat VZDY, kdyz je mys nad ikonami.

Spousti se UVNITR izolovane relace (session.sh: Xvfb, soukromy HOME/XDG_*/D-Bus, xfwm4
s kompozici). Plank bezi s nastavenim LuxOS (window-dodge, zoom 150 %, tema WhiteSur-Light).
Zvetseni se meri z framebufferu Xvfb: vyska Docku (nejvyssi radek s pixely Docku nad spodnim
okrajem) s mysi nad ikonou musi byt aspon o ZOOM_MIN px vetsi nez bez mysi.

Situace (kazda: prijezd mysi + kontrola, ze zvetseni jde za mysi):
  zespodu, z boku po spodnim okraji, skokem na ikonu, skokem na spodni okraj, rychly navrat
  behem zmenseni, po vypnuti/zapnuti kompozice, po prepnuti plochy (i s posunem ploch), behem
  a po okne pres celou obrazovku, skryty Dock (okno pres Dock) zespodu i z boku, po menu
  ikony (Escape i klik mimo), po uchopu mysi jinou aplikaci, po zmene velikosti zvetseni,
  prijezd do mezery nad ikonami. Kontrola testu: se zoom-enabled=false se zvetseni najit nesmi.

Pouziti: dock_zoom.py PRACOVNI_ADRESAR PLANK [--only NAZEV[,NAZEV]] [--shots ADRESAR]
Navratovy kod: 0 = vsude zvetseni, 1 = nekde chybelo.
"""
# LuxOS: testy GUI nikdy na skutecne obrazovce a v relaci uzivatele (scripts/luxos_testguard.py)
import os as _tg_os, sys as _tg_sys  # noqa: E401
_tg_d = _tg_os.path.dirname(_tg_os.path.abspath(__file__))
while _tg_d != "/" and not _tg_os.path.exists(_tg_os.path.join(_tg_d, "scripts", "luxos_testguard.py")):
    _tg_d = _tg_os.path.dirname(_tg_d)
if _tg_d != "/":
    _tg_sys.path.insert(0, _tg_os.path.join(_tg_d, "scripts"))
    import luxos_testguard  # noqa: E402,F401
else:
    _tg_os.environ.pop("DISPLAY", None)
import argparse
import json
import os
import signal
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dock_stress import Fb, H, W, gset, mouse, sh  # noqa: E402

APPS = ["firefox", "chromium", "luxai", "luxos-launchpad", "luxos-calculator", "luxos-maps",
        "luxos-mail", "luxos-monitor"]
ZOOM_MIN = 6            # tema WhiteSur: 48 px -> 72 px pri 150 % vycniva asi 11 px nad pozadi Docku
SETTLE = 0.6            # zvetseni trva 200 ms, odkryti Docku do ~300 ms

WIN_PY = r'''
import gi, sys
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib
w = Gtk.Window(title=sys.argv[1])
w.set_wmclass(sys.argv[1], sys.argv[1])
css = Gtk.CssProvider(); css.load_from_data(b"window { background: #336699; }")
Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), css, 600)
x, y, ww, hh = map(int, sys.argv[2:6])
w.move(x, y); w.set_default_size(ww, hh); w.set_decorated(False)
if len(sys.argv) > 6 and sys.argv[6] == "fullscreen":
    w.fullscreen()
w.connect("destroy", Gtk.main_quit); w.show_all(); Gtk.main()
'''


def px(buf, i):
    return buf[i], buf[i + 1], buf[i + 2]


def differs(a, b, tol=10):
    return abs(a[0] - b[0]) > tol or abs(a[1] - b[1]) > tol or abs(a[2] - b[2]) > tol


class Probe:
    def __init__(self, fb):
        self.fb = fb

    def height(self, span=170):
        """Vyska Docku nad spodnim okrajem (0 = Dock neni videt)."""
        y0 = H - span
        x0, x1 = int(W * 0.15), int(W * 0.85)
        buf = self.fb.rows(y0, H, x0, x1)
        bg = px(self.fb.rows(H - 2, H - 1, 2, 3), 0)
        width = x1 - x0
        for row in range(span):
            n = 0
            base = row * width * 4
            for c in range(0, width, 2):
                if differs(px(buf, base + c * 4), bg):
                    n += 1
                    if n >= 4:
                        return span - row
        return 0

    def wait_height(self, pred, timeout=1.5):
        t0 = time.monotonic()
        h = self.height()
        while time.monotonic() - t0 < timeout:
            h = self.height()
            if pred(h):
                return h
            time.sleep(0.05)
        return h


def glide(points, step=12, delay=0.008):
    """Plynuly pohyb mysi pres body (jako skutecna mys - hodne udalosti pohybu)."""
    for (xa, ya), (xb, yb) in zip(points, points[1:]):
        n = max(1, int(max(abs(xb - xa), abs(yb - ya)) / step))
        for i in range(1, n + 1):
            mouse(xa + (xb - xa) * i / n, ya + (yb - ya) * i / n)
            time.sleep(delay)


def xfwm(prop, typ, val):
    sh("xfconf-query", "-c", "xfwm4", "-p", prop, "-n", "-t", typ, "-s", val)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("work")
    ap.add_argument("plank")
    ap.add_argument("--only", default="")
    ap.add_argument("--shots", default="")
    ap.add_argument("--theme", default="WhiteSur-Light")
    a = ap.parse_args()
    work = os.path.abspath(a.work)
    cfg = os.environ["XDG_CONFIG_HOME"]
    assert cfg.startswith(work), "XDG_CONFIG_HOME musi byt v pracovnim adresari"
    launch = os.path.join(cfg, "plank/dock1/launchers")
    os.makedirs(launch, exist_ok=True)
    apps = [p for p in APPS if os.path.exists(f"/usr/share/applications/{p}.desktop")]
    for p in apps:
        with open(os.path.join(launch, f"{p}.dockitem"), "w") as fh:
            fh.write(f"[PlankDockItemPreferences]\nLauncher=file:///usr/share/applications/{p}.desktop\n")
    gset("dock-items", "[" + ",".join(f"'{p}.dockitem'" for p in apps) + "]")
    theme = a.theme if os.path.isdir(f"/usr/share/plank/themes/{a.theme}") else "Default"
    for k, v in [("theme", f"'{theme}'"), ("position", "'bottom'"), ("alignment", "'center'"),
                 ("icon-size", "48"), ("zoom-enabled", "true"), ("zoom-percent", "150"),
                 ("hide-mode", "'window-dodge'"), ("unhide-delay", "0"), ("hide-delay", "300"),
                 ("pressure-reveal", "false"), ("show-dock-item", "false"),
                 ("tooltips-enabled", "false")]:
        gset(k, v)
    xfwm("/general/workspace_count", "int", "3")

    # okno nad Dockem (nezasahuje do nej -> Dock je pri window-dodge videt)
    wins = [subprocess.Popen([sys.executable, "-c", WIN_PY, "top", "0", "0", str(W), str(H - 300)])]
    time.sleep(1.0)
    log_path = os.path.join(work, "plank-zoom.log")
    plank = subprocess.Popen([a.plank], stdout=open(log_path, "w"), stderr=subprocess.STDOUT)
    time.sleep(3.5)
    fb = Fb(os.path.join(work, "fb", "Xvfb_screen0"))
    pr = Probe(fb)
    cx = W // 2

    away = (cx, 200)
    mouse(*away)
    time.sleep(0.8)
    base = pr.height()
    print(f"vyska Docku bez mysi: {base}", flush=True)
    if base < 20:
        print("FAIL Dock neni videt", flush=True)
        plank.kill()
        return 1

    results = []
    shot_n = [0]

    def shot(name):
        if not a.shots:
            return
        os.makedirs(a.shots, exist_ok=True)
        shot_n[0] += 1
        out = os.path.join(a.shots, f"{shot_n[0]:02d}-{name}.png")
        sh("python3", "-c", SHOT_PY, os.path.join(work, "fb", "Xvfb_screen0"), out)

    def check(name, hidden_base=False):
        """Mys je nad Dockem: zvetseni musi byt videt a jit za mysi."""
        h = pr.wait_height(lambda v: v >= base + ZOOM_MIN)
        ok = h >= base + ZOOM_MIN
        # zvetseni jde za mysi: posun o par ikon, porad zvetseno
        glide([(cx, H - 6), (cx - 110, H - 6)])
        h2 = pr.wait_height(lambda v: v >= base + ZOOM_MIN, 0.8)
        ok2 = h2 >= base + ZOOM_MIN
        shot(name)
        res = {"name": name, "ok": ok and ok2, "height": h, "height_moved": h2, "base": base}
        results.append(res)
        print(("OK   " if res["ok"] else "FAIL ") + json.dumps(res), flush=True)
        # odjet a pockat na zmenseni
        mouse(*away)
        pr.wait_height(lambda v: v <= base + 2 or (hidden_base and v == 0), 1.5)
        time.sleep(0.3)
        return res["ok"]

    only = set(filter(None, a.only.split(",")))

    def want(n):
        return not only or n in only

    # --- prijezd mysi ---
    if want("from-below"):
        glide([away, (cx, H - 200), (cx, H - 6)])
        check("from-below")
    if want("from-side"):
        mouse(3, H - 4)
        time.sleep(0.3)
        glide([(3, H - 4), (cx, H - 4)])
        check("from-side")
    if want("warp-icon"):
        mouse(cx, H - 30)
        check("warp-icon")
    if want("warp-edge"):
        mouse(cx, H - 1)
        check("warp-edge")
    if want("gap-above"):
        # najezd shora do pasu tesne nad nezvetsenymi ikonami a pomalu dolu
        glide([away, (cx, H - base - 10)], step=20)
        time.sleep(0.3)
        glide([(cx, H - base - 10), (cx, H - 8)], step=2, delay=0.03)
        check("gap-above")
    if want("reenter-zoomout"):
        for wait in (0.0, 0.05, 0.1, 0.15, 0.25):
            mouse(cx, H - 8)
            time.sleep(0.5)
            mouse(cx, H - 250)
            time.sleep(wait)
            glide([(cx, H - 250), (cx + 40, H - 8)], step=30, delay=0.004)
            if not check(f"reenter-zoomout-{wait}"):
                break
    if want("reenter-edge-zoomout"):
        # odjezd jen tesne nad zvetsene ikony (do vstupni oblasti zvetseneho Docku) a zpet
        for wait in (0.02, 0.08, 0.15):
            glide([away, (cx, H - 8)])
            time.sleep(0.5)
            glide([(cx, H - 8), (cx, H - base - 30)], step=8, delay=0.004)
            time.sleep(wait)
            glide([(cx, H - base - 30), (cx - 30, H - base + 6), (cx - 40, H - 8)], step=4, delay=0.01)
            if not check(f"reenter-edge-zoomout-{wait}"):
                break

    # --- kompozice ---
    if want("compositing-toggle"):
        xfwm("/general/use_compositing", "bool", "false")
        time.sleep(1.5)
        xfwm("/general/use_compositing", "bool", "true")
        time.sleep(2.0)
        glide([away, (cx, H - 6)])
        check("compositing-toggle")
    if want("compositing-hover-toggle"):
        # kompozice se zapne, zatimco mys uz je nad Dockem
        xfwm("/general/use_compositing", "bool", "false")
        time.sleep(1.5)
        glide([away, (cx, H - 6)])
        time.sleep(0.5)
        xfwm("/general/use_compositing", "bool", "true")
        time.sleep(2.0)
        glide([(cx, H - 6), (cx + 50, H - 6)])
        check("compositing-hover-toggle")

    # --- plochy ---
    if want("workspace-switch"):
        sh("wmctrl", "-s", "1")
        time.sleep(1.0)
        glide([away, (cx, H - 6)])
        check("workspace-other")
        sh("wmctrl", "-s", "0")
        time.sleep(1.0)
        glide([away, (cx, H - 6)])
        check("workspace-back")
    if want("workspace-switch-hovered"):
        # prepnuti plochy klavesou, zatimco je mys nad Dockem
        glide([away, (cx, H - 6)])
        time.sleep(0.5)
        sh("wmctrl", "-s", "1")
        time.sleep(0.6)
        sh("wmctrl", "-s", "0")
        time.sleep(0.6)
        glide([(cx, H - 6), (cx + 60, H - 6)])
        check("workspace-switch-hovered")

    # --- okno pres celou obrazovku ---
    if want("fullscreen"):
        fs = subprocess.Popen([sys.executable, "-c", WIN_PY, "fs", "0", "0", "800", "600", "fullscreen"])
        time.sleep(1.5)
        fs.terminate()
        fs.wait()
        time.sleep(1.0)
        glide([away, (cx, H - 6)])
        check("fullscreen-after")

    # --- skryty Dock (okno pres Dock) ---
    if want("hidden"):
        cover = subprocess.Popen([sys.executable, "-c", WIN_PY, "cover", "0", "0", str(W), str(H)])
        time.sleep(1.5)
        hb = pr.height()
        print(f"vyska skryteho Docku: {hb}", flush=True)
        mouse(cx, H - 1)
        check("hidden-edge", hidden_base=True)
        mouse(3, H - 1)
        time.sleep(0.3)
        glide([(3, H - 1), (cx, H - 1)])
        check("hidden-side", hidden_base=True)
        glide([away, (cx, H - 1)], step=25)
        check("hidden-from-above", hidden_base=True)
        for wait in (0.05, 0.15, 0.3, 0.45):
            mouse(cx, H - 1)
            time.sleep(0.6)
            mouse(cx, 300)
            time.sleep(wait)
            mouse(cx, H - 1)
            if not check(f"hidden-reenter-{wait}", hidden_base=True):
                break
        cover.terminate()
        cover.wait()
        time.sleep(1.0)

    # --- menu ikony ---
    if want("menu"):
        glide([away, (cx, H - 8)])
        time.sleep(0.5)
        sh("xdotool", "click", "3")
        time.sleep(0.8)
        sh("xdotool", "key", "Escape")
        time.sleep(0.6)
        glide([(cx, H - 8), (cx + 50, H - 8)])
        check("menu-escape")
        glide([away, (cx, H - 8)])
        time.sleep(0.5)
        sh("xdotool", "click", "3")
        time.sleep(0.8)
        mouse(100, 100)
        sh("xdotool", "click", "1")
        time.sleep(0.6)
        glide([(100, 100), (cx, H - 8)])
        check("menu-click-outside")

    # --- uchop mysi jinou aplikaci (Alt+Tab, snimek obrazovky, menu jine aplikace) ---
    if want("grab"):
        for move in (False, True):
            glide([away, (cx, H - 8)])
            time.sleep(0.5)
            g = subprocess.Popen([sys.executable, "-c", GRAB_PY, "1.0"])
            time.sleep(0.4)
            if move:
                glide([(cx, H - 8), (cx + 80, H - 8)])
            g.wait()
            time.sleep(0.3)
            glide([(cx + (80 if move else 0), H - 8), (cx + 20, H - 8)])
            check("grab-moved" if move else "grab")

    # --- zmena nastaveni ---
    if want("zoom-percent"):
        glide([away, (cx, H - 8)])
        time.sleep(0.4)
        gset("zoom-percent", "170")
        time.sleep(0.8)
        glide([(cx, H - 8), (cx + 30, H - 8)])
        check("zoom-percent-hovered")
        gset("zoom-percent", "150")
        time.sleep(0.8)
        glide([away, (cx, H - 8)])
        check("zoom-percent-after")

    # --- kontrola testu: s vypnutym zvetsovanim (tak ho vypinal Sporic baterie do LuxOS 1.0.x)
    # musi mereni zvetseni NEnajit, jinak by test nic nedokazoval ---
    control_ok = True
    if want("control"):
        gset("zoom-enabled", "false")
        time.sleep(0.8)
        glide([away, (cx, H - 8)])
        h = pr.wait_height(lambda v: v >= base + ZOOM_MIN, 1.0)
        control_ok = h < base + ZOOM_MIN and h >= base - 2
        print(("OK   " if control_ok else "FAIL ") + json.dumps(
            {"name": "control-zoom-disabled", "height": h, "base": base}), flush=True)
        mouse(*away)
        gset("zoom-enabled", "true")
        time.sleep(0.8)

    plank_alive = plank.poll() is None
    plank.send_signal(signal.SIGTERM)
    try:
        plank.wait(5)
    except subprocess.TimeoutExpired:
        plank.kill()
    for w in wins:
        w.terminate()
    bad = [r["name"] for r in results if not r["ok"]]
    with open(os.path.join(work, "zoom-result.json"), "w") as fh:
        json.dump({"base": base, "results": results, "plank_alive": plank_alive}, fh, indent=1)
    print(f"{{\"zoom_checks\": {len(results)}, \"failed\": {json.dumps(bad)}, \"plank_alive\": "
          f"{json.dumps(plank_alive)}, \"control_ok\": {json.dumps(control_ok)}}}", flush=True)
    if not plank_alive:
        print("FAIL Plank behem testu skoncil (viz plank-zoom.log)", flush=True)
    return 1 if bad or not plank_alive or not control_ok or not (results or only == {"control"}) else 0


GRAB_PY = r'''
import gi, sys
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib
w = Gtk.Window(type=Gtk.WindowType.POPUP)
w.move(0, 0); w.resize(1, 1); w.show_all()
def grab():
    seat = Gdk.Display.get_default().get_default_seat()
    print("grab", seat.grab(w.get_window(), Gdk.SeatCapabilities.ALL, True, None, None, None, None),
          flush=True)
    GLib.timeout_add(int(float(sys.argv[1]) * 1000), lambda: (seat.ungrab(), Gtk.main_quit()))
GLib.timeout_add(50, grab)
Gtk.main()
'''

SHOT_PY = r'''
import struct, sys, zlib
src, out = sys.argv[1:3]
f = open(src, "rb"); hdr = struct.unpack(">25I", f.read(100))
hs, w, h, bpl, nc = hdr[0], hdr[4], hdr[5], hdr[12], hdr[19]
y0 = h - 200
f.seek(hs + nc * 12 + y0 * bpl)
raw = b""
for y in range(y0, h):
    row = f.read(bpl)
    raw += b"\0" + b"".join(bytes((row[i + 2], row[i + 1], row[i])) for i in range(0, w * 4, 4))
def chunk(t, d):
    c = struct.pack(">I", len(d)) + t + d
    return c + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h - y0, 8, 2, 0, 0, 0))
png += chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")
open(out, "wb").write(png)
'''

if __name__ == "__main__":
    sys.exit(main())
