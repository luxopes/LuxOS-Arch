"""Profilova fotka: okno s aktualni fotkou a orez noveho obrazku do kruhu.

AccountsService je napodobena (LUXOS_ACCOUNTS_FAKE jako tests/test_luxos_profile_picture.py), ~/.face je
v docasnem HOME a jmeno uctu je ukazkove (LUXOS_AVATAR_NAME - jinak by se ukazalo skutecne jmeno uzivatele
z /etc/passwd). Fotka = tapeta LuxOS z luxos-branding."""
import os


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
    app = s.lslc("luxos-desktop/files/lsl/luxos-profile-picture.lsl")
    env = {"LUXOS_ACCOUNTS_FAKE": os.path.join(s.tmp, "accounts-icon"), "LUXOS_CAMERA_TEST": "1",
           "LUXOS_AVATAR_NAME": "Alex Morgan"}
    prepare_face(s, s.src("luxos-branding/files/wallpapers/luxos-sunrise.jpg"), os.path.join(s.home, ".face"))
    p = s.launch([app], env=env)
    win = s.window(pid=p.pid, size=None)
    s.capture("1", win)
    s.stop()
    # orez noveho obrazku (luxos-profile-picture SOUBOR)
    p = s.launch([app, s.src("luxos-branding/files/wallpapers/luxos-lagoon.jpg")], env=env)
    win = s.window(pid=p.pid, size=None)
    for _ in range(3):                  # trochu priblizit (kolecko mysi v orezu)
        s.click(231, 260, win, button=4, delay=0.2)
    s.capture("2", win)
