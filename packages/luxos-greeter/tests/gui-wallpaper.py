#!/usr/bin/env python3
"""LuxOS - tapeta prihlasovaci a zamykaci obrazovky (rezim --demo), bez LightDM.

    env -u DISPLAY xvfb-run -a python3 packages/luxos-greeter/tests/gui-wallpaper.py

Overuje: tapeta zamceneho / posledniho uzivatele z AccountsService (BackgroundFile, sem ji
zapisuje luxos-appearance greeter-sync), stejna tapeta i po prepnuti na jineho uzivatele,
necitelna nebo chybejici tapeta -> vychozi (svetla, jako vychozi rezim plochy), vyslovne
user-background=false a vlastni background= v konfiguraci.
"""
import argparse
import os
import sys
import tempfile
import time
from importlib.machinery import SourceFileLoader
# Jen virtualni X z xvfb-run (nebo vyslovne LUXOS_TEST_X=1 ve VM) - nikdy skutecna obrazovka
if "xvfb-run" not in os.environ.get("XAUTHORITY", "") and os.environ.get("LUXOS_TEST_X") != "1":
    sys.exit("Run under xvfb-run (or LUXOS_TEST_X=1 in a VM) - never on a real display.")

HERE = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp(prefix="luxos-greeter-wall-")
CONF = os.path.join(TMP, "luxos-greeter.conf")
os.environ.update({"LANG": "en_US.UTF-8", "LUXOS_GREETER_CONF": CONF, "XDG_CACHE_HOME": TMP})
sys.dont_write_bytecode = True
g = SourceFileLoader("luxos_greeter", os.path.join(HERE, "..", "files", "luxos-greeter")).load_module()
from gi.repository import Gtk  # noqa: E402

WALLS = os.path.normpath(os.path.join(HERE, "..", "..", "luxos-branding", "files", "wallpapers"))
LIGHT = os.path.join(WALLS, "luxos-flow-light.jpg")
DARK = os.path.join(WALLS, "luxos-flow-dark.jpg")
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


def conf(text):
    with open(CONF, "w") as f:
        f.write("[greeter]\n" + text)


def greeter(backgrounds, users=2, lock=True):
    os.environ["LUXOS_GREETER_DEMO_BACKGROUND"] = ":".join(backgrounds)
    g.DEMO_FPRINT = None
    win = g.Greeter(argparse.Namespace(demo=True, users=users, sessions=1, lock=lock))
    pump(0.2)
    return win


def done(win):
    win.destroy()
    pump(0.05)


def mean(win):
    """Prumerny jas vykreslene tapety (svetla > 120, tmava < 90)."""
    surf = win.bg_surf.map_to_image(None)
    data, stride = bytes(surf.get_data()), surf.get_stride()
    vals = [data[y * stride + x * 4 + 1] for y in range(0, surf.get_height(), 17) for x in range(0, surf.get_width(), 23)]
    win.bg_surf.unmap_image(surf)
    return sum(vals) / len(vals)


check("default background is the light one (default desktop mode)", g.DEFAULT_BG.endswith("/luxos-light.jpg"), g.DEFAULT_BG)
conf("")
check("config without background -> DEFAULT_BG", g.load_config()["background"] == g.DEFAULT_BG)
with open(os.path.join(HERE, "..", "files", "luxos-greeter.conf")) as f:
    shipped = f.read()
check("shipped config: light fallback, user wallpaper on",
      "background=/usr/share/backgrounds/luxos/luxos-light.jpg\n" in shipped and "user-background=true\n" in shipped)

# 1. zamceny uzivatel (anna) ma svetlou tapetu plochy -> svetla i na zamykaci obrazovce
w = greeter([LIGHT, DARK])
check("lock: locked user's desktop wallpaper", w.background_path() == LIGHT, w.background_path())
check("lock: rendered wallpaper is light", mean(w) > 120, mean(w))
# 2. prepnuti na jineho uzivatele: tapeta se nemeni (zadne skakani)
other = w.users[1]
w.on_user_clicked(None, other)
pump(0.2)
check("switch user: same wallpaper", w.user is other and w.background_path() == LIGHT, w.background_path())
done(w)

# 3. tmavy rezim uzivatele -> tmava tapeta
w = greeter([DARK, LIGHT])
check("lock: dark desktop -> dark wallpaper", w.background_path() == DARK and mean(w) < 90, (w.background_path(), mean(w)))
done(w)

# 4. bez tapety / necitelna tapeta -> vychozi z konfigurace
conf(f"background={DARK}\n")
w = greeter(["", LIGHT])
check("no user wallpaper -> configured background", w.background_path() == DARK, w.background_path())
done(w)
private = os.path.join(TMP, "private")
os.makedirs(private)
pic = os.path.join(private, "photo.jpg")
with open(pic, "w") as f:
    f.write("x")
os.chmod(pic, 0)
w = greeter([pic])
check("unreadable user wallpaper -> configured background", w.background_path() == DARK, w.background_path())
done(w)
w = greeter(["/nonexistent/x.jpg"])
check("missing user wallpaper -> configured background", w.background_path() == DARK, w.background_path())
done(w)

# 5. spravce vypnul tapety uzivatelu
conf(f"background={DARK}\nuser-background=false\n")
w = greeter([LIGHT])
check("user-background=false keeps configured background", w.background_path() == DARK, w.background_path())
done(w)

# 6. prihlasovaci obrazovka (bez zamceni): tapeta uzivatele vybraneho pri startu
conf("")
w = greeter([DARK, LIGHT], lock=False)
want = {"anna": DARK, "petr": LIGHT}[w.user.name]
check("login: selected user's wallpaper", w.background_path() == want, (w.user.name, w.background_path()))
done(w)

print(f"\n{len(FAILS)} failure(s)" if FAILS else "\nall ok")
sys.exit(1 if FAILS else 0)
