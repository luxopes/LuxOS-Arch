"""Profilova fotka: okno s aktualni fotkou a orez noveho obrazku do kruhu.

AccountsService je napodobena (LUXOS_ACCOUNTS_FAKE jako tests/gui-profile-picture.py), ~/.face je
v docasnem HOME a jmeno uctu je ukazkove (luxos_avatar.real_name se v obalu nahradi - jinak by
se ukazalo skutecne jmeno uzivatele z /etc/passwd). Fotka = tapeta LuxOS z luxos-branding."""
import os

WRAPPER = r'''
import runpy, sys
import luxos_avatar
luxos_avatar.real_name = lambda: "Alex Morgan"
sys.argv = [sys.argv[1]] + sys.argv[2:]
runpy.run_path(sys.argv[0], run_name="__main__")
'''


def prepare_face(s, src, out):
    """Ctvercovy vyrez obrazku do ~/.face (jako ulozeni z aplikace)."""
    from gi.repository import GdkPixbuf
    pb = GdkPixbuf.Pixbuf.new_from_file(src)
    side = min(pb.get_width(), pb.get_height())
    x = (pb.get_width() - side) // 2
    sq = pb.new_subpixbuf(x, (pb.get_height() - side) // 2, side, side).scale_simple(
        512, 512, GdkPixbuf.InterpType.HYPER)
    sq.savev(out, "png", [], [])


def shots(s):
    wrapper = os.path.join(s.tmp, "run-profile-picture.py")
    with open(wrapper, "w", encoding="utf-8") as f:
        f.write(WRAPPER)
    app = s.src("luxos-desktop/files/bin/luxos-profile-picture")
    env = {"LUXOS_ACCOUNTS_FAKE": os.path.join(s.tmp, "accounts-icon"), "LUXOS_CAMERA_TEST": "1"}
    s.python_env()
    prepare_face(s, s.src("luxos-branding/files/wallpapers/luxos-sunrise.jpg"), os.path.join(s.home, ".face"))
    import sys
    p = s.launch([sys.executable, wrapper, app], env=env)
    win = s.window(pid=p.pid, size=None)
    s.capture("1", win)
    s.stop()
    # orez noveho obrazku (luxos-profile-picture SOUBOR)
    p = s.launch([sys.executable, wrapper, app, s.src("luxos-branding/files/wallpapers/luxos-lagoon.jpg")], env=env)
    win = s.window(pid=p.pid, size=None)
    for _ in range(3):                  # trochu priblizit (kolecko mysi v orezu)
        s.click(231, 260, win, button=4, delay=0.2)
    s.capture("2", win)
