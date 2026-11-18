#!/usr/bin/env python3
"""LuxOS - greeter: datum nad hodinami v jazyce greeteru a citelny zastupny text hesla (rezim --demo).

    xvfb-run -a dbus-run-session python3 packages/luxos-greeter/tests/gui-date-placeholder.py [--shots DIR]

Overuje: bez date-format se datum sklada podle jazyka greeteru (luxos_i18n.format_date), i kdyz je v
systemu jen C/en_US locale (driv "Wednesday 18. November" mezi ceskymi texty); vyslovny date-format
z konfigurace ma prednost; bez novejsiho luxos-i18n ceska zaloha bez anglickych slov; zastupny text
hesla na oranzove tapete ma dost kontrastu (svetly text na ztmavenem poli).
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
import sys
import tempfile
import time
from importlib.machinery import SourceFileLoader
if "xvfb-run" not in os.environ.get("XAUTHORITY", "") and os.environ.get("LUXOS_TEST_X") != "1":
    sys.exit("Run under xvfb-run (or LUXOS_TEST_X=1 in a VM) - never on a real display.")

ap = argparse.ArgumentParser()
ap.add_argument("--shots")
args = ap.parse_args()

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
I18N = os.path.join(REPO, "packages", "luxos-i18n", "files")
TMP = tempfile.mkdtemp(prefix="luxos-greeter-date-", dir=os.environ.get("LUXOS_TEST_TMP"))
CONF = os.path.join(TMP, "luxos-greeter.conf")
# jazyk greeteru cestina, ceska locale v systemu ale byt nemusi (strftime by dal anglictinu)
for k in ("LC_ALL", "LC_TIME", "LC_MESSAGES"):
    os.environ.pop(k, None)
os.environ.update({"LANG": "cs_CZ.UTF-8", "LUXOS_GREETER_CONF": CONF, "XDG_CACHE_HOME": TMP,
                   "LUXOS_I18N_DIR": I18N})
sys.path.insert(0, I18N)
sys.dont_write_bytecode = True
with open(CONF, "w") as f:
    f.write("[greeter]\n")
g = SourceFileLoader("luxos_greeter", os.path.join(HERE, "..", "files", "luxos-greeter")).load_module()
from gi.repository import Gdk, Gtk  # noqa: E402

# greeter si pridava /usr/lib/luxos/python dopredu: testovat formatovani z repozitare
sys.path.insert(0, I18N)
sys.modules.pop("luxos_i18n", None)
import luxos_i18n  # noqa: E402
g.i18n_format_date = luxos_i18n.format_date

FAILS = []


def check(desc, cond, extra=""):
    print(("ok    " if cond else "FAIL  ") + desc + (f"\n      {extra}" if extra and not cond else ""))
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


wed = time.strptime("2026-11-18 10:00", "%Y-%m-%d %H:%M")
check("config without date-format -> empty (language-based date)", g.load_config()["date"] == "")
check("cs date", g.localized_date(wed) == "středa 18. listopadu", g.localized_date(wed))
for lang, want in (("de", "Mittwoch, 18. November"), ("en", "Wednesday, November 18"),
                   ("pl", "środa, 18 listopada"), ("fr", "mercredi 18 novembre")):
    g.LANG = lang
    check(f"{lang} date", g.localized_date(wed) == want, g.localized_date(wed))
g.LANG = "cs"
check("explicit date-format wins", g.localized_date(wed, "%Y-%m-%d") == "2026-11-18")
keep = g.i18n_format_date
g.i18n_format_date = None
check("old luxos-i18n: Czech fallback", g.localized_date(wed) == "středa 18. listopadu", g.localized_date(wed))
g.LANG = "de"
check("old luxos-i18n, other language: no English words", "Wednesday" not in g.localized_date(wed),
      g.localized_date(wed))
g.i18n_format_date = keep
g.LANG = "cs"

# zastupny text hesla na oranzovych/svetlych tapetach
WALLS = os.path.join(REPO, "packages", "luxos-branding", "files", "wallpapers")
g.DEMO_FPRINT = None
for wall in ("luxos-aurora-orange.jpg", "luxos-citrus.jpg", "luxos-sunrise.jpg", "luxos-flow-light.jpg"):
    os.environ["LUXOS_GREETER_DEMO_BACKGROUND"] = os.path.join(WALLS, wall)
    win = g.Greeter(argparse.Namespace(demo=True, users=1, sessions=1, lock=True))
    pump(0.5)
    win.set_active(True)
    pump(1.5)
    alloc = win.pw.get_allocation()
    ox, oy = win.pw.translate_coordinates(win, 0, 0)
    gw = win.get_window()
    pb = Gdk.pixbuf_get_from_window(gw, ox, oy, alloc.width, alloc.height)
    check(f"{wall}: password field shown", pb is not None and alloc.width > 50 and win.pw.get_mapped(), alloc.width)
    if pb is not None:
        data, rs, nc = pb.get_pixels(), pb.get_rowstride(), pb.get_n_channels()

        def lum(x, y):
            i = y * rs + x * nc
            f = (lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
            r, gg, b = (f(data[i + k] / 255) for k in range(3))
            return 0.2126 * r + 0.7152 * gg + 0.0722 * b
        vals = sorted(lum(x, y) for y in range(alloc.height // 4, alloc.height * 3 // 4)
                      for x in range(alloc.height // 2, alloc.width * 2 // 3))
        bg, fg = vals[len(vals) // 2], vals[-max(1, len(vals) // 200)]
        ratio = (fg + 0.05) / (bg + 0.05)
        check(f"{wall}: placeholder contrast >= 3:1 ({ratio:.2f}:1)", ratio >= 3.0)
    if args.shots:
        os.makedirs(args.shots, exist_ok=True)
        full = Gdk.pixbuf_get_from_window(gw, 0, 0, gw.get_width(), gw.get_height())
        full.savev(os.path.join(args.shots, "greeter-cs-" + wall.replace(".jpg", ".png")), "png", [], [])
    win.destroy()
    pump(0.05)

print(f"\n{len(FAILS)} failure(s)" if FAILS else "\nall ok")
sys.exit(1 if FAILS else 0)
