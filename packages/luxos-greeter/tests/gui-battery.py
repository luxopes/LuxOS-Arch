#!/usr/bin/env python3
"""LuxOS - ikona baterie prihlasovaci a zamykaci obrazovky luxos-greeter (rezim --demo), bez LightDM.

    env -u DISPLAY xvfb-run -a -s "-screen 0 1920x1080x24" python3 packages/luxos-greeter/tests/gui-battery.py [--shots DIR]
    env -u DISPLAY GDK_SCALE=2 xvfb-run -a -s "-screen 0 2560x1600x24" \
        python3 packages/luxos-greeter/tests/gui-battery.py --window-only [--shots DIR]      (meritko 2x)

Overuje:
  - blesk pri nabijeni je videt pri kazdem nabiti 0-100 %, na tmave az bile tapete, pri meritku 1x
    i 2x: jas pixelu uvnitr blesku se lisi od lemu kolem nej a od plochy baterie dal od nej (nad
    vyplni i nad prazdnou casti zvlast), obrys baterie se lisi od tapety (stejne jako
    packages/xfce4-screensaver/tests/test-lock-battery.c pro zamek)
  - stav baterie z napodobeneho /sys/class/power_supply (LUXOS_GREETER_DEMO_POWER_SUPPLY): nabijeni,
    "Full" a "Not charging" s nabijeckou = blesk, vybijeni = bez blesku, baterie bez kapacity se
    preskoci (driv "-1 %"), kapacita mimo 0-100 se orizne
  - ve skutecnem okne (GDK_SCALE 1 a 2) se blesk nakresli: snimek s nabijeckou se od snimku bez ni
    lisi jen v ikone baterie a o dost jasu; snimky na tmave a svetle tapete (--shots)
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
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
from importlib.machinery import SourceFileLoader

# Jen virtualni X z xvfb-run (nebo vyslovne LUXOS_TEST_X=1 ve VM) - nikdy skutecna obrazovka
if "xvfb-run" not in os.environ.get("XAUTHORITY", "") and os.environ.get("LUXOS_TEST_X") != "1":
    sys.exit("Run under xvfb-run (or LUXOS_TEST_X=1 in a VM) - never on a real display.")

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
BASE = os.environ.get("LUXOS_TEST_TMP") or os.path.join(REPO, "out")
os.makedirs(BASE, exist_ok=True)
if os.path.realpath(BASE).startswith("/tmp"):
    sys.exit("refusing: temporary files must not be in /tmp")
TMP = tempfile.mkdtemp(prefix="luxos-greeter-battery-", dir=BASE)
CONF = os.path.join(TMP, "luxos-greeter.conf")
with open(CONF, "w") as _f:
    _f.write("[greeter]\n")
os.environ.update({"LANG": "en_US.UTF-8", "LUXOS_GREETER_CONF": CONF, "XDG_CACHE_HOME": TMP})
sys.dont_write_bytecode = True
g = SourceFileLoader("luxos_greeter", os.path.join(HERE, "..", "files", "luxos-greeter")).load_module()
import cairo  # noqa: E402
from gi.repository import Gdk, Gtk  # noqa: E402

WALLS = os.path.normpath(os.path.join(HERE, "..", "..", "luxos-branding", "files", "wallpapers"))
LIGHT = os.path.join(WALLS, "luxos-flow-light.jpg")
DARK = os.path.join(WALLS, "luxos-flow-dark.jpg")
FAILS = []
MARGIN_RING, MARGIN_AREA = 0.35, 0.25


def check(desc, cond, extra=""):
    print(("ok    " if cond else "FAIL  ") + desc + (f"\n      {extra}" if extra and not cond else ""), flush=True)
    if not cond:
        FAILS.append(desc)


def pump(sec=0.0):
    end = time.monotonic() + sec
    while True:
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        if time.monotonic() >= end:
            break
        time.sleep(0.01)


# ---- kresba ikony do obrazku ---------------------------------------------------------------
def lum_buf(surf):
    data, st = bytes(surf.get_data()), surf.get_stride()
    return lambda x, y: (0.2126 * data[y * st + x * 4 + 2] + 0.7152 * data[y * st + x * 4 + 1]
                         + 0.0722 * data[y * st + x * 4]) / 255.0


def mask(w, ht, scale, geom, stroke):
    s = cairo.ImageSurface(cairo.FORMAT_A8, w, ht)
    cr = cairo.Context(s)
    cr.scale(scale, scale)
    g.battery_bolt_path(cr, geom)
    if stroke:
        cr.set_line_width(stroke)
        cr.set_line_join(cairo.LINE_JOIN_ROUND)
        cr.stroke_preserve()
    cr.fill()
    s.flush()
    data, st = bytes(s.get_data()), s.get_stride()
    return lambda x, y: data[y * st + x]


def check_icon(h, scale, bg, level):
    """Vrati (pocet porovnani, chyby) - stejna mereni jako tests/test-lock-battery.c zamku."""
    x = y = 4
    w, ht = math.ceil((h * 2.05 + 8) * scale), math.ceil((h + 8) * scale)
    geom = g.battery_geom(x, y, h, level)
    img = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, ht)
    cr = cairo.Context(img)
    cr.set_source_rgb(bg, bg, bg)
    cr.paint()
    cr.scale(scale, scale)
    g.icon_battery(cr, x, y, h, level, True)
    img.flush()
    L = lum_buf(img)
    mb, mr, mf = mask(w, ht, scale, geom, 0), mask(w, ht, scale, geom, 2 * geom["ring"]), \
        mask(w, ht, scale, geom, 2 * (geom["ring"] + 2.0))
    ex, band = (geom["fx"] + geom["fw"]) * scale, (geom["ring"] + 2.5) * scale

    def inside(px, py):
        lx, ly = (px + 0.5) / scale, (py + 0.5) / scale
        return (geom["ix"] + 0.5 < lx < geom["ix"] + geom["iw"] - 0.5
                and geom["iy"] + 0.5 < ly < geom["iy"] + geom["ih"] - 0.5)

    acc = {k: [[0.0, 0], [0.0, 0]] for k in ("bolt", "ring", "area")}
    outline = 0.0
    errors, compared = [], 0
    for py in range(ht):
        for px in range(w):
            ins, l, dx = inside(px, py), L(px, py), px + 0.5
            if not ins:
                outline = max(outline, abs(l - bg))
                continue
            if abs(dx - ex) < band:
                continue
            side = 0 if dx < ex else 1
            b, r, f = mb(px, py), mr(px, py), mf(px, py)
            key = "bolt" if b >= 192 else "ring" if (b <= 40 and r >= 160) else "area" if (r <= 5 and f >= 250) else None
            if key:
                acc[key][side][0] += l
                acc[key][side][1] += 1
    # mistni kontrast vcetne mista, kde okraj vyplne protina blesk
    rad = geom["ring"] * scale + 1.5
    rr = math.ceil(rad)
    checked = passed = 0
    for py in range(ht):
        for px in range(w):
            dx = px + 0.5
            if mb(px, py) < 192 or abs(dx - ex) < 1.0 or not inside(px, py):
                continue
            vals = [L(qx, qy) for qy in range(max(0, py - rr), min(ht, py + rr + 1))
                    for qx in range(max(0, px - rr), min(w, px + rr + 1))
                    if (qx - px) ** 2 + (qy - py) ** 2 <= rad * rad and mb(qx, qy) <= 40 and mr(qx, qy) >= 160
                    and abs(qx + 0.5 - ex) >= 1.0 and ((qx + 0.5 < ex) == (dx < ex)) and inside(qx, qy)]
            if not vals:
                continue
            checked += 1
            passed += abs(L(px, py) - sum(vals) / len(vals)) >= MARGIN_RING
    if checked >= 3:
        compared += 1
        if passed < checked * 0.9:
            errors.append(f"only {passed} of {checked} bolt pixels stand out")
    for side in (0, 1):
        (bs, bn), (rs, rn), (as_, an) = acc["bolt"][side], acc["ring"][side], acc["area"][side]
        if bn < 3 or rn < 3:
            continue
        compared += 1
        if abs(bs / bn - rs / rn) < MARGIN_RING or (an >= 3 and abs(bs / bn - as_ / an) < MARGIN_AREA):
            errors.append(f"{'over empty part' if side else 'over fill'}: bolt {bs / bn:.2f} ring {rs / rn:.2f} "
                          f"area {as_ / an if an else 0:.2f}")
    if outline < 0.25:
        errors.append(f"outline blends into the wallpaper ({outline:.2f})")
    return compared, errors, geom


def test_render():
    expected = bad = 0
    first = []
    for status in (16, 12):
        for scale in (1, 2):
            h = status * g.BATTERY_H
            for bg in (0.04, 0.25, 0.5, 0.75, 0.97):
                for level in range(0, 101, 5):
                    n, errors, geom = check_icon(h, scale, bg, level)
                    if h * scale >= 10.5 and abs(geom["fx"] + geom["fw"] - geom["cx"]) > \
                            0.58 * geom["k"] + geom["ring"] + 1.0 / scale:
                        expected += 1
                        if n < 1:
                            errors.append("nothing compared")
                    if errors:
                        bad += 1
                        first.append(f"h={h:.1f} x{scale} bg={bg} {level}%: {'; '.join(errors)}")
    check(f"bolt stands out at every charge level, wallpaper and scale ({expected} cases)",
          bad == 0 and expected >= 150, "\n      ".join(first[:8]))


def test_state():
    d = os.path.join(TMP, "ps")

    def make(bat=None, ac=None, extra=None):
        shutil.rmtree(d, ignore_errors=True)
        for name, files in (("AC", ac), ("BAT0", bat)) + tuple((extra or {}).items()):
            if files is None:
                continue
            os.makedirs(os.path.join(d, name))
            for k, v in files.items():
                with open(os.path.join(d, name, k), "w") as f:
                    f.write(v + "\n")

    make({"type": "Battery", "capacity": "42", "status": "Charging"}, {"type": "Mains", "online": "1"})
    check("charging -> bolt", g.battery_state(d) == (42, True), g.battery_state(d))
    make({"type": "Battery", "capacity": "100", "status": "Full"}, {"type": "Mains", "online": "1"})
    check("full on charger -> bolt", g.battery_state(d) == (100, True), g.battery_state(d))
    make({"type": "Battery", "capacity": "80", "status": "Not charging"}, {"type": "Mains", "online": "1"})
    check("plugged but not charging -> bolt", g.battery_state(d) == (80, True), g.battery_state(d))
    make({"type": "Battery", "capacity": "80", "status": "Discharging"}, {"type": "Mains", "online": "0"})
    check("discharging -> no bolt", g.battery_state(d) == (80, False), g.battery_state(d))
    make({"type": "Battery", "capacity": "80", "status": "Unknown"}, {"type": "Mains", "online": "0"})
    check("unknown status, charger offline -> no bolt", g.battery_state(d) == (80, False), g.battery_state(d))
    make({"type": "Battery", "status": "Charging"}, {"type": "Mains", "online": "1"},
         {"BAT1": {"type": "Battery", "capacity": "63", "status": "Charging"}})
    check("battery without capacity skipped (was -1 %)", g.battery_state(d) == (63, True), g.battery_state(d))
    make({"type": "Battery", "capacity": "abc", "status": "Charging"})
    check("unreadable capacity -> no battery", g.battery_state(d) is None, g.battery_state(d))
    make({"type": "Battery", "capacity": "104", "status": "Full"}, {"type": "Mains", "online": "1"})
    check("capacity over 100 clamped", g.battery_state(d) == (100, True), g.battery_state(d))
    make({"type": "Battery", "capacity": "50", "status": "Discharging", "scope": "Device"})
    check("device battery (mouse) ignored", g.battery_state(d) is None, g.battery_state(d))
    check("missing directory -> no battery", g.battery_state(os.path.join(TMP, "nope")) is None)


# ---- skutecne okno ----------------------------------------------------------------------------
def window_shot(win):
    gw = win.get_window()
    pb = Gdk.pixbuf_get_from_window(gw, 0, 0, gw.get_width(), gw.get_height())
    return pb


def power_dir(level, status, online):
    d = os.path.join(TMP, f"ps-{level}-{status.replace(' ', '_')}-{int(online)}")
    shutil.rmtree(d, ignore_errors=True)
    for name, files in (("AC", {"type": "Mains", "online": "1" if online else "0"}),
                        ("BAT0", {"type": "Battery", "capacity": str(level), "status": status})):
        os.makedirs(os.path.join(d, name))
        for k, v in files.items():
            with open(os.path.join(d, name, k), "w") as f:
                f.write(v + "\n")
    return d


def icon_rect(win):
    """Ikona baterie v pixelech okna (alokace widgetu * meritko)."""
    a = win.bat_icon.get_allocation()
    x, y = win.bat_icon.translate_coordinates(win, 0, 0)
    s = win.get_scale_factor()
    return int(x * s), int(y * s), int(a.width * s), int(a.height * s)


def test_window(shots):
    scale = int(os.environ.get("GDK_SCALE", "1"))
    for wname, wall in (("dark", DARK), ("light", LIGHT)):
        for level, status in ((10, "Charging"), (50, "Charging"), (95, "Charging"), (100, "Full"),
                              (80, "Not charging")):
            pbs = {}
            for plugged in (True, False):
                os.environ["LUXOS_GREETER_DEMO_POWER_SUPPLY"] = power_dir(level, status if plugged else "Discharging",
                                                                         plugged)
                os.environ["LUXOS_GREETER_DEMO_BACKGROUND"] = wall
                g.DEMO_FPRINT = None
                win = g.Greeter(argparse.Namespace(demo=True, users=1, sessions=1, lock=True))
                pump(0.6)
                win.update_status()
                pump(0.4)
                rect = icon_rect(win)
                pbs[plugged] = window_shot(win)
                tag = f"greeter-{wname}-{level}-{status.replace(' ', '-').lower()}-{scale}x"
                if plugged and shots:
                    pbs[plugged].savev(os.path.join(shots, tag + ".png"), "png", [], [])
                    x, y, w, h = rect
                    pad = 120 * scale
                    x0 = max(0, x - pad * 2)
                    sub = pbs[plugged].new_subpixbuf(x0, max(0, y - 10 * scale),
                                                     min(pbs[plugged].get_width() - x0, w + pad * 3),
                                                     h + 20 * scale)
                    sub.scale_simple(sub.get_width() * 3, sub.get_height() * 3, 0).savev(
                        os.path.join(shots, tag + "-icon.png"), "png", [], [])
                win.destroy()
                pump(0.1)
            a, b = pbs[True], pbs[False]
            x, y, w, h = rect
            da, db = a.get_pixels(), b.get_pixels()
            st, nc = a.get_rowstride(), a.get_n_channels()
            changed, outside, big = 0, 0, 0.0
            # stavovy radek vpravo nahore (hodiny uprostred se mezi snimky muzou zmenit)
            for yy in range(0, min(a.get_height(), y + h + 20 * scale)):
                for xx in range(max(0, x - 300 * scale), a.get_width()):
                    i = yy * st + xx * nc
                    la = (0.2126 * da[i] + 0.7152 * da[i + 1] + 0.0722 * da[i + 2]) / 255
                    lb = (0.2126 * db[i] + 0.7152 * db[i + 1] + 0.0722 * db[i + 2]) / 255
                    if abs(la - lb) > 0.25:
                        if x <= xx < x + w and y <= yy < y + h:
                            changed += 1
                            big = max(big, abs(la - lb))
                        else:
                            outside += 1
            tag = f"{wname} {level}% {status} x{scale}"
            check(f"window {tag}: bolt drawn in the battery icon only ({changed} px, {outside} elsewhere)",
                  changed >= 10 * scale * scale and outside == 0)
            check(f"window {tag}: bolt changes the icon clearly (max brightness change {big:.2f})", big >= 0.5)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots")
    ap.add_argument("--window-only", action="store_true")
    args = ap.parse_args()
    if args.shots:
        os.makedirs(args.shots, exist_ok=True)
    try:
        if not args.window_only:
            test_render()
            test_state()
        test_window(args.shots)
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    print(f"\n{len(FAILS)} failure(s)" if FAILS else "\nall passed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
