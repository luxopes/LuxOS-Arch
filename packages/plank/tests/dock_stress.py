#!/usr/bin/env python3
"""LuxOS - zatezovy test Docku (Plank): rychle odkryti / najeti mysi / odchod.

Spousti se UVNITR izolovane relace (session.sh). Plank bezi s nastavenim LuxOS
(window-dodge, zoom 150 %, hide-delay 300, unhide-delay 0), prekryva ho okno pres celou
obrazovku, takze je Dock skryty a odkryva se najetim mysi na spodni okraj.

Zamrznuti se pozna podle framebufferu Xvfb (XWD):
  - po najeti na ikonu a posunu o nekolik ikon se musi obraz Docku zmenit (zvetseni jde za mysi),
  - po odchodu mysi se Dock musi do 2 s schovat (spodni pruh = barva prekryvneho okna),
  - Plank musi odpovidat na D-Bus (hlavni smycka bezi).
Kazde selhani se zapise (cas, cyklus, druh) a test pak pocka, jestli se Dock sam vzpamatuje.

Pouziti: dock_stress.py PRACOVNI_ADRESAR [--cycles N] [--plank /usr/bin/plank] [--seed S]
         [--churn] (otevirani/zavirani oken a pridavani/odebirani ikon behem testu)
"""
import argparse
import json
import os
import random
import signal
import struct
import subprocess
import sys
import time

COVER = (0x33, 0x66, 0x99)          # barva prekryvneho okna
W, H = 1280, 800
APPS = ["firefox", "chromium", "luxai", "luxos-launchpad", "luxos-calculator",
        "luxos-maps", "luxos-mail", "luxos-monitor", "luxos-camera", "luxos-about",
        "luxos-backup", "luxos-emoji"]


def sh(*cmd, check=False, **kw):
    return subprocess.run(cmd, check=check, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, **kw)


class Fb:
    """Cteni framebufferu Xvfb (-fbdir, XWD, 32 bpp)."""

    def __init__(self, path):
        self.f = open(path, "rb")
        hdr = self.f.read(100)
        f = struct.unpack(">25I", hdr)
        self.header_size, self.width, self.height = f[0], f[4], f[5]
        self.bpl, ncolors = f[12], f[19]
        self.off = self.header_size + ncolors * 12

    def rows(self, y0, y1, x0=0, x1=None):
        x1 = W if x1 is None else x1
        out = bytearray()
        for y in range(y0, y1):
            self.f.seek(self.off + y * self.bpl + x0 * 4)
            out += self.f.read((x1 - x0) * 4)
        return bytes(out)

    def strip(self, h=40):
        return self.rows(H - h, H)

    @staticmethod
    def non_cover(buf):
        """Pocet pixelu, ktere nejsou barvou prekryvneho okna (BGRX)."""
        n = 0
        b, g, r = COVER[2], COVER[1], COVER[0]
        for i in range(0, len(buf), 4):
            if not (abs(buf[i] - b) < 4 and abs(buf[i + 1] - g) < 4 and abs(buf[i + 2] - r) < 4):
                n += 1
        return n

    def dock_columns(self, h=20):
        """Rozsah x, kde jsou ve spodnim pruhu pixely Docku."""
        buf = self.rows(H - h, H)
        cols = set()
        b, g, r = COVER[2], COVER[1], COVER[0]
        for i in range(0, len(buf), 4):
            if not (abs(buf[i] - b) < 4 and abs(buf[i + 1] - g) < 4 and abs(buf[i + 2] - r) < 4):
                cols.add((i // 4) % W)
        return (min(cols), max(cols)) if cols else None

    def zoom_center(self, h=110):
        """Stred x nejvyssi casti Docku (spicka zvetsene ikony) - posouva se se zvetsenim.

        Vraci None, kdyz v dolnich h radcich zadny Dock neni. Zvyrazneni ikony pod mysi
        (zesvetleni) bez zvetseni tuto hodnotu nezmeni - pozna se tak zamrzle zvetseni."""
        y0 = H - h
        buf = self.rows(y0, H)
        b, g, r = COVER[2], COVER[1], COVER[0]
        rows = {}
        for i in range(0, len(buf), 4):
            if not (abs(buf[i] - b) < 4 and abs(buf[i + 1] - g) < 4 and abs(buf[i + 2] - r) < 4):
                rows.setdefault((i // 4) // W, []).append((i // 4) % W)
        if not rows:
            return None
        top = min(rows)
        xs = [x for y in range(top, top + 6) for x in rows.get(y, [])]
        return sum(xs) / len(xs)


def mouse(x, y):
    sh("xdotool", "mousemove", str(int(x)), str(int(y)))


def plank_alive(timeout=2.0):
    """D-Bus ping Planku - odpovi jen pri bezici hlavni smycce."""
    try:
        r = subprocess.run(["gdbus", "call", "--session", "--dest", "net.launchpad.plank",
                            "--object-path", "/net/launchpad/plank/dock1",
                            "--method", "net.launchpad.plank.Items.GetCount"],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
        return r.returncode == 0
    except subprocess.TimeoutExpired:
        return False


def gset(key, val):
    sh("gsettings", "set", "net.launchpad.plank.dock.settings:/net/launchpad/plank/docks/dock1/", key, val)


COVER_PY = r'''
import gi, sys
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk
w = Gtk.Window(title=sys.argv[1])
w.set_wmclass(sys.argv[1], sys.argv[1])
css = Gtk.CssProvider(); css.load_from_data(b"window { background: #336699; }")
Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), css, 600)
x, y, ww, hh = map(int, sys.argv[2:6])
w.move(x, y); w.set_default_size(ww, hh); w.set_decorated(False)
w.connect("destroy", Gtk.main_quit); w.show_all(); Gtk.main()
'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("work")
    ap.add_argument("--cycles", type=int, default=1000)
    ap.add_argument("--plank", default="/usr/bin/plank")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--churn", action="store_true")
    ap.add_argument("--tooltips", action="store_true")
    a = ap.parse_args()
    rnd = random.Random(a.seed)
    work = os.path.abspath(a.work)
    home = os.environ["HOME"]

    # Ikony Docku: .dockitem soubory na existujici .desktop
    launch = os.path.join(home, ".config/plank/dock1/launchers")
    spare = os.path.join(home, "spare-launchers")
    os.makedirs(launch, exist_ok=True)
    os.makedirs(spare, exist_ok=True)
    apps = [p for p in APPS if os.path.exists(f"/usr/share/applications/{p}.desktop")]
    for i, p in enumerate(apps):
        d = launch if i < 8 else spare
        with open(os.path.join(d, f"{p}.dockitem"), "w") as fh:
            fh.write(f"[PlankDockItemPreferences]\nLauncher=file:///usr/share/applications/{p}.desktop\n")
    items = "[" + ",".join(f"'{p}.dockitem'" for p in apps[:8]) + "]"
    for k, v in [("dock-items", items), ("theme", "'Default'"), ("position", "'bottom'"),
                 ("icon-size", "48"), ("zoom-enabled", "true"), ("zoom-percent", "150"),
                 ("hide-mode", "'window-dodge'"), ("unhide-delay", "0"), ("hide-delay", "300"),
                 ("pressure-reveal", "false"), ("show-dock-item", "false"),
                 ("tooltips-enabled", "true" if a.tooltips else "false")]:
        gset(k, v)

    cover = subprocess.Popen([sys.executable, "-c", COVER_PY, "cover", "0", "0", str(W), str(H)])
    time.sleep(1.0)
    log = open(os.path.join(work, "plank.log"), "w")
    plank = subprocess.Popen([a.plank], stdout=log, stderr=subprocess.STDOUT)
    time.sleep(3.0)
    fb = Fb(os.path.join(work, "fb", "Xvfb_screen0"))

    def hidden_ok(timeout=2.0):
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            if Fb.non_cover(fb.strip(6)) == 0:
                return True
            time.sleep(0.05)
        return False

    # Kalibrace: odkryt Dock a najit sloupce ikon
    mouse(W // 2, H - 1)
    time.sleep(1.2)
    cols = fb.dock_columns()
    mouse(W // 2, 100)
    if not cols:
        print("CHYBA: Dock se po najeti na okraj neukazal", file=sys.stderr)
        plank.kill()
        cover.kill()
        return 2
    x0, x1 = cols
    print(f"dock x {x0}..{x1}", flush=True)
    if not hidden_ok(3.0):
        print("CHYBA: Dock se po odchodu neschoval", file=sys.stderr)

    failures = []
    extra = []          # okna otevrena pri --churn
    stats = {"cycles": 0, "zoom_checks": 0, "hide_checks": 0, "ping_checks": 0}
    t_start = time.monotonic()

    def fail(kind, cyc, info=""):
        rec = {"t": round(time.monotonic() - t_start, 2), "cycle": cyc, "kind": kind, "info": info}
        # samoobnova: znovu zkusit za 0.5/1/2 s
        recovered = None
        for wait in (0.5, 1.0, 2.0):
            time.sleep(wait)
            if kind == "hide" and Fb.non_cover(fb.strip(6)) == 0:
                recovered = wait
                break
            if kind == "zoom":
                xa, xb = x0 + (x1 - x0) * 0.2, x0 + (x1 - x0) * 0.8
                mouse(xa, H - 2)
                time.sleep(0.3)
                ca = fb.zoom_center()
                mouse(xb, H - 2)
                time.sleep(0.3)
                cb = fb.zoom_center()
                if ca is not None and cb is not None and cb - ca >= (xb - xa) * 0.5:
                    recovered = wait
                    break
            if kind == "ping" and plank_alive():
                recovered = wait
                break
        rec["recovered_after_s"] = recovered
        failures.append(rec)
        print("FAIL", json.dumps(rec), flush=True)
        try:
            sh("gdb", "-p", str(plank.pid), "-batch", "-ex", "thread apply all bt 8",
               timeout=30) if os.environ.get("DOCK_STRESS_GDB") else None
        except Exception:
            pass

    for cyc in range(a.cycles):
        if plank.poll() is not None:
            failures.append({"cycle": cyc, "kind": "exit", "info": f"rc {plank.returncode}"})
            print("FAIL plank skoncil", plank.returncode, flush=True)
            break
        stats["cycles"] += 1
        # 1) odkryt: mys na spodni okraj (nahodne x v Docku), nahodne cekani i behem animace
        mouse(rnd.uniform(x0, x1), H - 1)
        time.sleep(rnd.choice([0, 0.005, 0.02, 0.05, 0.1, 0.2]))
        # 2) pohyb po ikonach s nahodnym tempem (behem odkryvaci animace)
        for _ in range(rnd.randint(1, 12)):
            mouse(rnd.uniform(x0 - 30, x1 + 30), H - rnd.randint(1, 60))
            time.sleep(rnd.choice([0, 0.001, 0.005, 0.01, 0.03, 0.08]))
        # obcas odchod a hned navrat (hide-delay 300 ms)
        if rnd.random() < 0.3:
            mouse(rnd.uniform(0, W), rnd.uniform(100, H - 150))
            time.sleep(rnd.choice([0, 0.05, 0.2, 0.29, 0.31, 0.35, 0.5]))
            mouse(rnd.uniform(x0, x1), H - 1)
            time.sleep(rnd.choice([0, 0.01, 0.05]))
        if a.churn and rnd.random() < 0.15:
            if extra and rnd.random() < 0.5:
                p = extra.pop(rnd.randrange(len(extra)))
                p.terminate()
            else:
                # dalsi okno = prepocet window-dodge (otevreni/zavreni okna); konci nad spodnimi
                # 180 radky, aby jeho stin nezasahoval do mereni zvetseni (zoom_center)
                yy = rnd.choice([0, 200, H - 380])
                extra.append(subprocess.Popen([sys.executable, "-c", COVER_PY, rnd.choice(apps),
                                               str(rnd.randint(0, 600)), str(yy), "500", "200"]))
        if a.churn and rnd.random() < 0.08:
            names = os.listdir(launch)
            spares = os.listdir(spare)
            if spares and (len(names) <= 6 or rnd.random() < 0.5):
                n = rnd.choice(spares)
                os.rename(os.path.join(spare, n), os.path.join(launch, n))
            elif len(names) > 6:
                n = rnd.choice(names)
                os.rename(os.path.join(launch, n), os.path.join(spare, n))
        # 3) kontroly (kazdy 5. cyklus, aby test nebyl zbytecne pomaly)
        if cyc % 5 == 0:
            # zvetseni musi sledovat mys
            cols2 = None
            mouse((x0 + x1) / 2, H - 2)
            time.sleep(0.45)
            cols2 = fb.dock_columns() or (x0, x1)
            xa = cols2[0] + (cols2[1] - cols2[0]) * 0.2
            xb = cols2[0] + (cols2[1] - cols2[0]) * 0.8
            mouse(xa, H - 3)
            time.sleep(0.35)
            ca = fb.zoom_center()
            mouse(xb, H - 3)
            time.sleep(0.35)
            cb = fb.zoom_center()
            stats["zoom_checks"] += 1
            if ca is None or cb is None or cb - ca < (xb - xa) * 0.5:
                fail("zoom", cyc, f"zvetseni nesleduje mys ({ca} -> {cb}, mys {xa:.0f} -> {xb:.0f})")
        if cyc % 5 == 2:
            mouse(rnd.uniform(0, W), rnd.uniform(100, H - 200))
            stats["hide_checks"] += 1
            if not hidden_ok(2.0):
                # okno z --churn nemusi Dock prekryvat -> pak se Dock schovat nema
                if not a.churn:
                    fail("hide", cyc, "Dock se po odchodu mysi neschoval")
        if cyc % 25 == 0:
            stats["ping_checks"] += 1
            if not plank_alive():
                fail("ping", cyc, "Plank neodpovida na D-Bus")
        if cyc % 100 == 0:
            print(f"cycle {cyc} failures {len(failures)} t {time.monotonic() - t_start:.0f}s", flush=True)

    for p in extra:
        p.terminate()
    alive = plank.poll() is None
    plank.send_signal(signal.SIGTERM)
    try:
        plank.wait(5)
    except subprocess.TimeoutExpired:
        plank.kill()
    cover.terminate()
    res = {"stats": stats, "failures": failures, "plank_alive_at_end": alive,
           "seconds": round(time.monotonic() - t_start, 1), "plank": a.plank, "seed": a.seed,
           "churn": a.churn}
    with open(os.path.join(work, "result.json"), "w") as fh:
        json.dump(res, fh, indent=1)
    print(json.dumps({k: res[k] for k in ("stats", "seconds", "plank_alive_at_end")}),
          "failures:", len(failures), flush=True)
    return 1 if failures or not alive else 0


if __name__ == "__main__":
    sys.exit(main())
