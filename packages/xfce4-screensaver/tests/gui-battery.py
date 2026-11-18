#!/usr/bin/env python3
"""LuxOS - ikona baterie na zamykaci obrazovce (xfce4-screensaver-dialog) v Xvfb.

    gcc -shared -fPIC -o fake-pam.so packages/xfce4-screensaver/tests/fake-pam.c
    python3 packages/xfce4-screensaver/tests/gui-battery.py \\
        --dialog BUILD/src/xfce4-screensaver-dialog --fake-pam fake-pam.so [--shots DIR]

Prostredi jako tests/gui-caps-lock.py (vlastni Xvfb, D-Bus, HOME, napodobeny libpam). Baterie je
napodobeny adresar /sys/class/power_supply (LUXOS_LOCK_DEMO_POWER_SUPPLY): BAT0 + AC.

Overuje pri meritku 1x a 2x, na tmave, svetle a bile tapete a pri nabiti 10/50/95/100 % (100 % jako
"Full" a 80 % jako "Not charging" s pripojenou nabijeckou): ikona baterie je videt a blesk se v ni
skutecne nakresli - snimek s nabijeckou se proti snimku bez ni (stejne nabiti) lisi v dost pixelech,
jen v ikone baterie a o dost jasu. Presny kontrast blesku proti okoli pro vsechna nabiti, tapety
a velikosti overuje tests/test-lock-battery.c.
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
import os
import shutil
import sys
import time
from importlib.machinery import SourceFileLoader

import cairo

HERE = os.path.dirname(os.path.abspath(__file__))
caps = SourceFileLoader("gui_caps_lock", os.path.join(HERE, "gui-caps-lock.py")).load_module()
REPO = caps.REPO
FAILS = caps.FAILS
check = caps.check


def shot(env, path):
    """Snimek obrazovky Xvfb ve skutecnych pixelech (bez GDK_SCALE)."""
    e = dict(env.env)
    e.pop("GDK_SCALE", None)
    code = ("import sys,gi; gi.require_version('Gdk','3.0'); from gi.repository import Gdk;"
            "w=Gdk.get_default_root_window(); "
            "Gdk.pixbuf_get_from_window(w,0,0,w.get_width(),w.get_height()).savev(sys.argv[1],'png',[],[])")
    r = caps.subprocess.run([sys.executable, "-c", code, path], env=e, capture_output=True, text=True)
    ok = r.returncode == 0 and os.path.exists(path)
    check(ok, f"screenshot {os.path.basename(path)} {r.stderr[-300:]}")
    return ok


def power_supply(base, level, status, online):
    d = os.path.join(base, f"ps-{level}-{status.replace(' ', '_')}-{online}")
    shutil.rmtree(d, ignore_errors=True)
    for name, files in (("AC", {"type": "Mains", "online": "1" if online else "0"}),
                        ("BAT0", {"type": "Battery", "capacity": str(level), "status": status})):
        os.makedirs(os.path.join(d, name))
        for k, v in files.items():
            with open(os.path.join(d, name, k), "w") as f:
                f.write(v + "\n")
    return d


def white_wallpaper(path):
    s = cairo.ImageSurface(cairo.FORMAT_RGB24, 640, 400)
    cr = cairo.Context(s)
    g = cairo.LinearGradient(0, 0, 640, 400)
    g.add_color_stop_rgb(0, 1, 1, 1)
    g.add_color_stop_rgb(1, 0.93, 0.94, 0.96)
    cr.set_source(g)
    cr.paint()
    s.write_to_png(path)


def lum(data, stride, x, y):
    i = y * stride + x * 4
    b, g, r = data[i], data[i + 1], data[i + 2]
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0


def load(path):
    s = cairo.ImageSurface.create_from_png(path)
    return s, s.get_data(), s.get_stride()


def compare(path_on, path_off, scale, what):
    """Blesk: pixely, ktere se se zapnutou nabijeckou lisi, v pravem hornim rohu (stavovy radek)."""
    on, d1, st = load(path_on)
    _off, d2, _st = load(path_off)
    w, h = on.get_width(), on.get_height()
    x0, y0, x1, y1 = w - int(320 * scale), 0, w, int(80 * scale)
    diff = []
    for y in range(y0, y1):
        for x in range(x0, x1):
            a, b = lum(d1, st, x, y), lum(d2, st, x, y)
            if abs(a - b) > 0.25:
                diff.append((x, y, a, b))
    check(len(diff) >= 10 * scale * scale, f"{what}: bolt drawn ({len(diff)} changed pixels)")
    if not diff:
        return
    xs = [p[0] for p in diff]
    ys = [p[1] for p in diff]
    bx0, bx1, by0, by1 = min(xs), max(xs), min(ys), max(ys)
    check(bx1 - bx0 <= 40 * scale and by1 - by0 <= 20 * scale,
          f"{what}: change limited to the battery icon ({bx1 - bx0 + 1}x{by1 - by0 + 1} px)")
    big = max(abs(p[2] - p[3]) for p in diff)
    check(big >= 0.5, f"{what}: bolt changes the icon clearly (max brightness change {big:.2f})")


def crop(src, dst, scale):
    s = cairo.ImageSurface.create_from_png(src)
    w = s.get_width()
    cw, ch = int(260 * scale), int(56 * scale)
    out = cairo.ImageSurface(cairo.FORMAT_RGB24, cw * 3, ch * 3)
    cr = cairo.Context(out)
    cr.scale(3, 3)
    cr.set_source_surface(s, -(w - cw), 0)
    cr.get_source().set_filter(cairo.FILTER_NEAREST)
    cr.paint()
    out.write_to_png(dst)


def run(args, base, scale):
    w, h = 1280, 800
    env = caps.Env(base, "us", screen=f"{w * scale}x{h * scale}x24",
                   extra_env={"GDK_SCALE": str(scale)} if scale != 1 else None)
    shots = args.shots or os.path.join(env.dir, "shots")
    os.makedirs(shots, exist_ok=True)
    white = os.path.join(env.dir, "white.png")
    white_wallpaper(white)
    walls = (("dark", "/usr/share/backgrounds/luxos/luxos-dark.jpg"),
             ("light", "/usr/share/backgrounds/luxos/luxos-light.jpg"), ("white", white))
    cases = ((10, "Charging", True), (50, "Charging", True), (95, "Charging", True), (100, "Full", True),
             (80, "Not charging", True))
    try:
        for wname, wpath in walls:
            if not os.path.exists(wpath):
                print(f"skip {wname}: {wpath} missing")
                continue
            env.wallpaper(wpath)
            for level, status, online in cases:
                tag = f"{wname}-{level}-{status.replace(' ', '-').lower()}-{scale}x"
                paths = {}
                for plugged in (True, False):
                    ps = power_supply(env.dir, level, status if plugged else "Discharging", plugged)
                    d = caps.Dialog(env, args.dialog, args.fake_pam, extra_env={"LUXOS_LOCK_DEMO_POWER_SUPPLY": ps},
                                    size=(w, h))
                    check(d.wid is not None, f"{tag}: dialog shown (plugged={plugged})")
                    time.sleep(1.0)
                    p = os.path.join(shots if plugged else env.dir, f"lock-{tag}{'' if plugged else '-unplugged'}.png")
                    shot(env, p)
                    paths[plugged] = p
                    d.close()
                if all(os.path.exists(p) for p in paths.values()):
                    compare(paths[True], paths[False], scale, tag)
                    crop(paths[True], os.path.join(shots, f"lock-{tag}-icon.png"), scale)
        # baterie s prazdnym souborem capacity se neukaze (driv ikona s 0 %) - stejne jako bez baterie
        empty = os.path.join(env.dir, "ps-empty")
        os.makedirs(empty, exist_ok=True)
        got = {}
        for name, ps in (("none", empty), ("nocap", power_supply(env.dir, "", "Charging", True))):
            d = caps.Dialog(env, args.dialog, args.fake_pam, extra_env={"LUXOS_LOCK_DEMO_POWER_SUPPLY": ps},
                            size=(w, h))
            time.sleep(1.0)
            got[name] = os.path.join(env.dir, f"lock-battery-{name}-{scale}x.png")
            shot(env, got[name])
            d.close()
        if all(os.path.exists(p) for p in got.values()):
            a, da, st = load(got["none"])
            _b, db, _st = load(got["nocap"])
            wd = a.get_width()
            changed = sum(1 for y in range(0, int(80 * scale)) for x in range(wd - int(320 * scale), wd)
                          if abs(lum(da, st, x, y) - lum(db, st, x, y)) > 0.1)
            check(changed == 0, f"battery without readable capacity is not shown ({changed} px differ from no battery)")
    finally:
        env.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dialog", required=True)
    ap.add_argument("--fake-pam", required=True)
    ap.add_argument("--shots")
    ap.add_argument("--scale", type=int, choices=(1, 2), action="append")
    args = ap.parse_args()
    args.fake_pam = os.path.abspath(args.fake_pam)
    base = os.environ.get("LUXOS_TEST_TMP") or os.path.join(REPO, "out")
    os.makedirs(base, exist_ok=True)
    if os.path.realpath(base).startswith("/tmp"):
        sys.exit("refusing: temporary files must not be in /tmp")
    if args.shots:
        os.makedirs(args.shots, exist_ok=True)
    for scale in args.scale or (1, 2):
        run(args, base, scale)
    print(f"\n{len(FAILS)} failure(s)" if FAILS else "\nall passed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
