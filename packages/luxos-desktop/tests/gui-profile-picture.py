#!/usr/bin/env python3
"""LuxOS - okno Profilova fotka: orez obrazku, fotka z testovaci kamery, ulozeni a odebrani.

    env -u DISPLAY xvfb-run -a python3 packages/luxos-desktop/tests/gui-profile-picture.py [--shots DIR]

AccountsService je napodobena (LUXOS_ACCOUNTS_FAKE), kamera je videotestsrc (LUXOS_CAMERA_TEST=1),
domov v docasne slozce - nic se nemeni na skutecnem systemu.
"""
import os
import sys
import tempfile
import time
from importlib.machinery import SourceFileLoader

if "xvfb-run" not in os.environ.get("XAUTHORITY", "") and os.environ.get("LUXOS_TEST_X") != "1":
    sys.exit("Run under xvfb-run (or LUXOS_TEST_X=1 in a VM) - never on a real display.")

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = os.path.join(HERE, "..", "files")
I18N = os.path.join(HERE, "..", "..", "luxos-i18n", "files")
SHOTS = sys.argv[sys.argv.index("--shots") + 1] if "--shots" in sys.argv else ""
HOME = tempfile.mkdtemp(prefix="luxos-avatar-")
FAKE = os.path.join(HOME, "accounts-icon")
os.environ.update({"HOME": HOME, "XDG_CONFIG_HOME": os.path.join(HOME, ".config"), "LUXOS_I18N_DIR": I18N,
                   "LANG": "en_US.UTF-8", "LUXOS_ACCOUNTS_FAKE": FAKE, "LUXOS_CAMERA_TEST": "1"})
sys.argv = sys.argv[:1]
sys.path.insert(0, I18N)
sys.path.insert(0, os.path.join(FILES, "python"))
import luxos_i18n  # noqa: E402

app = SourceFileLoader("luxos_profile_picture", os.path.join(FILES, "bin", "luxos-profile-picture")).load_module()
from gi.repository import GdkPixbuf, Gdk, Gst, Gtk  # noqa: E402

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


def wait(cond, timeout=8.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        pump()
        if cond():
            return True
        time.sleep(0.02)
    return cond()


def shot(win, name):
    if not SHOTS:
        return
    pump(0.3)
    gw = win.get_window()
    pb = Gdk.pixbuf_get_from_window(gw, 0, 0, gw.get_width(), gw.get_height())
    if pb:
        os.makedirs(SHOTS, exist_ok=True)
        pb.savev(os.path.join(SHOTS, name + ".png"), "png", [], [])


def set_lang(code):
    luxos_i18n._TR.clear()
    if code != "en":
        with open(os.path.join(I18N, code + ".tsv"), encoding="utf-8") as f:
            for line in f:
                if line.startswith("#") or "\t" not in line:
                    continue
                k, v = line.rstrip("\n").split("\t", 1)
                luxos_i18n._TR[k] = v


def test_photo():
    """Obrazek 600x400: vlevo cerveny, vpravo modry pruh."""
    pb = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 600, 400)
    pb.fill(0x2060e0ff)
    left = pb.new_subpixbuf(0, 0, 300, 400)
    left.fill(0xe03030ff)
    path = os.path.join(HOME, "photo.jpg")
    pb.savev(path, "jpeg", [], [])
    return path


def pixel(pb, x, y):
    n = pb.get_n_channels()
    data = pb.get_pixels()
    i = y * pb.get_rowstride() + x * n
    return tuple(data[i:i + 3])


def run(lang):
    set_lang(lang)
    sfx = "-" + lang
    for p in (FAKE, os.path.join(HOME, ".face")):
        if os.path.exists(p):
            os.unlink(p)
    Gst.init(None)
    win = app.PictureWindow()
    win.show_all()
    win.load_current()
    pump(0.3)
    check("bez fotky: tlacitko Odebrat skryte", not win.remove_btn.get_visible())
    check("horni lista s tlacitkem zavrit", win.get_titlebar().get_visible() and win.get_titlebar().get_show_close_button())
    shot(win, "profile-empty" + sfx)

    # orez obrazku: posun doleva az na doraz -> pod kruhem cervena polovina
    check("obrazek se otevre v orezu", win.open_file(test_photo()) and win.stack.get_visible_child_name() == "crop")
    win.crop.ox = 10000
    win.crop.clamp()
    check("posun omezen (kruh zustane zakryty)", 0 < win.crop.ox < 1000 and win.crop.oy == 0, win.crop.ox)
    win.set_zoom(1.5)
    pump(0.2)
    shot(win, "profile-crop" + sfx)
    win.save(None)
    face = os.path.join(HOME, ".face")
    check("ulozeno do ~/.face", os.path.isfile(face))
    check("AccountsService dostala ~/.face", open(FAKE).read() == face if os.path.exists(FAKE) else False)
    pb = GdkPixbuf.Pixbuf.new_from_file(face)
    check("fotka je ctverec 384 px", pb.get_width() == pb.get_height() == 384)
    r, g, b = pixel(pb, 192, 192)
    check("vyrez z leve (cervene) casti", r > 180 and b < 90, (r, g, b))
    check("Odebrat je videt", win.remove_btn.get_visible())
    check("zpet na hlavni strane", win.stack.get_visible_child_name() == "main")
    shot(win, "profile-saved" + sfx)

    # kamera (videotestsrc) -> fotka -> orez
    win.open_camera()
    check("kamera: nahled bezi", wait(lambda: win.cam_stack.get_visible_child_name() == "preview"))
    pump(0.3)
    shot(win, "profile-camera" + sfx)
    win.take_photo(None)
    check("kamera: fotka jde do orezu", wait(lambda: win.stack.get_visible_child_name() == "crop"))
    check("kamera: zastavena", win.pipeline is None)
    win.back()

    # bez kamery
    win.cam.TEST = "none"
    win.open_camera()
    check("bez kamery: hlaska", win.cam_stack.get_visible_child_name() == "state" and not win.shutter.get_sensitive())
    shot(win, "profile-nocamera" + sfx)
    win.cam.TEST = "1"
    win.back()

    win.remove_picture(None)
    check("odebrano: ~/.face smazan", not os.path.exists(face))
    check("odebrano: AccountsService bez fotky", open(FAKE).read() == "")
    check("odebrano: Odebrat skryte", not win.remove_btn.get_visible())

    check("neobrazek: chyba", not win.open_file(os.path.join(HERE, "..", "PKGBUILD")))
    win.destroy()
    pump(0.1)


for code in ("en", "cs"):
    run(code)
print("FAIL: %d" % len(FAILS) if FAILS else "all ok")
sys.exit(1 if FAILS else 0)
