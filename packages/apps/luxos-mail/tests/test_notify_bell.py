"""Posta + skutecny xfce4-notifyd (z packages/xfce4-notifyd) + zvonek v horni liste:

- upozorneni na novou postu zustane (i po 30 s), je v historii oznameni (log.sqlite, aplikace luxos-mail),
- dalsi posta ho nahradi souhrnem - v historii zustane jeden zaznam,
- po precteni zprav (v Poste i jinde pres IMAP \\Seen) se popup zavre a zaznam je precteny,
- zvonek v liste ma pri neprectenych oznamenich cervenou tecku (svetla i tmava lista), pri Nerusit
  preskrtnuty zvonek s teckou; oznameni pri Nerusit se po precteni v historii take oznaci jako prectene.

    LUXOS_MAIL_BIN=.../luxos-mail LUXOS_NOTIFYD=.../usr/lib/xfce4/notifyd/xfce4-notifyd \\
    LUXOS_NOTIFY_PLUGIN=.../usr/lib/xfce4/panel/plugins/libnotification-plugin.so [LUXOS_BELL_SHOTS=adresar] \\
    env -u DISPLAY xvfb-run -a -s "-screen 0 1280x800x24" python3 -m unittest test_notify_bell -v

Vse na soukrome sbernici D-Bus s docasnym HOME a XDG_RUNTIME_DIR (700), nastaveni xfconf ze systemovych
vychozich hodnot LuxOS (luxos-desktop/files/xdg). Upraveny plugin zvonku se podstrci jen liste spustene
v soukromem jmennem prostoru pripojeni (unshare, bez sudo) - system ani skutecna relace se nemeni.
Bez LUXOS_NOTIFYD / xvfb-run se preskoci.
"""
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mailtest as mt  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
XDG = os.path.normpath(os.path.join(HERE, "..", "..", "..", "luxos-desktop", "files", "xdg"))
NOTIFYD = os.environ.get("LUXOS_NOTIFYD", "")
PLUGIN = os.environ.get("LUXOS_NOTIFY_PLUGIN", "")
SHOTS = os.environ.get("LUXOS_BELL_SHOTS", "")
SYSTEM_PLUGIN = "/usr/lib/xfce4/panel/plugins/libnotification-plugin.so"
UNDER_XVFB = bool(os.environ.get("DISPLAY")) and "xvfb-run" in os.environ.get("XAUTHORITY", "")
TOOLS = all(shutil.which(t) for t in ("xdotool", "xfconf-query", "xfce4-panel", "unshare"))

SHOT = r'''
import sys, gi
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk
x, y, w, h = map(int, sys.argv[2:6])
pb = Gdk.pixbuf_get_from_window(Gdk.get_default_root_window(), x, y, w, h)
pb.savev(sys.argv[1], "png", [], [])
'''


def red_pixels(path):
    """Mnozina souradnic vyrazne cervenych pixelu (tecka zvonku) v PNG."""
    import gi
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf
    pb = GdkPixbuf.Pixbuf.new_from_file(path)
    data = pb.get_pixels()
    n = pb.get_n_channels()
    stride = pb.get_rowstride()
    out = set()
    for y in range(pb.get_height()):
        row = y * stride
        for x in range(pb.get_width()):
            r, g, b = data[row + x * n], data[row + x * n + 1], data[row + x * n + 2]
            if r > 150 and g < 120 and b < 120:
                out.add((x, y))
    return out


def largest_blob(pixels):
    """Nejvetsi souvisla skupina pixelu (tecka; cervene okraje pismen hodin pri vyhlazovani jsou drobne)."""
    left = set(pixels)
    best = set()
    while left:
        todo = [left.pop()]
        blob = set(todo)
        while todo:
            x, y = todo.pop()
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    q = (x + dx, y + dy)
                    if q in left:
                        left.remove(q)
                        blob.add(q)
                        todo.append(q)
        if len(blob) > len(best):
            best = blob
    return best


def box_of(pixels, pad=2):
    xs = [p[0] for p in pixels]
    ys = [p[1] for p in pixels]
    return (min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad)


def inside(pixels, box):
    return {p for p in pixels if box[0] <= p[0] <= box[2] and box[1] <= p[1] <= box[3]}


@unittest.skipUnless(NOTIFYD and os.path.exists(NOTIFYD) and UNDER_XVFB and TOOLS,
                     "needs LUXOS_NOTIFYD (xfce4-notifyd from packages/xfce4-notifyd), xvfb-run, xdotool, xfce4-panel")
class NotifyBell(unittest.TestCase):
    dark = False
    scale = 1

    def setUp(self):
        # xfconfd spousti sbernice relace -> systemove vychozi hodnoty LuxOS musi mit uz dbus-daemon
        old = os.environ.get("XDG_CONFIG_DIRS")
        os.environ["XDG_CONFIG_DIRS"] = XDG + ":/etc/xdg"
        try:
            self.s = mt.Session(notifications=False)
        finally:
            if old is None:
                os.environ.pop("XDG_CONFIG_DIRS", None)
            else:
                os.environ["XDG_CONFIG_DIRS"] = old
        self.server = mt.FakeServer(self.s.root, self.s.certs, seed=mt.FIXTURES)
        gtk, icons = ("WhiteSur-Dark", "WhiteSur-dark") if self.dark else ("WhiteSur-Light", "WhiteSur-light")
        d = os.path.join(self.s.env["XDG_CONFIG_HOME"], "gtk-3.0")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "settings.ini"), "w") as f:
            f.write("[Settings]\ngtk-theme-name=%s\ngtk-icon-theme-name=%s\ngtk-font-name=Inter 10\n" % (gtk, icons))
        self.xenv = dict(self.s.env, DISPLAY=os.environ["DISPLAY"], XAUTHORITY=os.environ.get("XAUTHORITY", ""))
        if self.scale > 1:
            self.xenv["GDK_SCALE"] = str(self.scale)
        self.xfconf("xfce4-notifyd", "/theme", "string", gtk)
        if self.dark:
            self.xfconf("xfce4-panel", "/panels/dark-mode", "bool", "true")
            subprocess.run(["xfconf-query", "-c", "xfce4-panel", "-p", "/panels/panel-1/background-rgba", "-n",
                            "-t", "double", "-s", "0.09", "-t", "double", "-s", "0.09", "-t", "double", "-s", "0.12",
                            "-t", "double", "-s", "0.62"], env=self.xenv, check=True, timeout=10)
        self.procs = []
        if shutil.which("xfwm4"):
            # spravce oken: pracovni plocha bez horni listy (_NET_WORKAREA) -> oznameni pod listou jako v LuxOS
            self.spawn(["xfwm4", "--compositor=off", "--sm-client-disable"])
            time.sleep(0.5)
        self.notifyd = self.spawn([NOTIFYD])
        self.wait_name("org.freedesktop.Notifications")
        self.panel = None
        if PLUGIN:
            # jen v soukromem jmennem prostoru pripojeni: lista nacte upraveny plugin misto systemoveho
            self.panel = self.spawn(["unshare", "--map-user=%d" % os.getuid(), "--map-group=%d" % os.getgid(), "--keep-caps", "-m",
                                     "sh", "-c", 'mount --bind "$1" "$2" && exec xfce4-panel --disable-wm-check', "sh",
                                     PLUGIN, SYSTEM_PLUGIN])
        else:
            self.panel = self.spawn(["xfce4-panel", "--disable-wm-check"])
        self.c = self.s.start_service()

    def tearDown(self):
        try:
            self.c.call("quit")
        except OSError:
            pass
        for p in reversed(self.procs):
            try:
                os.killpg(p.pid, 15)
            except OSError:
                pass
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                os.killpg(p.pid, 9)
        self.server.stop()
        self.s.close()

    # ---- pomocne -----------------------------------------------------------------------------------------------

    def spawn(self, argv):
        p = subprocess.Popen(argv, env=self.xenv, stdout=subprocess.DEVNULL, stderr=open(os.path.join(self.s.root, "x.log"), "ab"),
                             start_new_session=True)
        self.procs.append(p)
        return p

    def xfconf(self, channel, prop, kind, value):
        subprocess.run(["xfconf-query", "-c", channel, "-p", prop, "-n", "-t", kind, "-s", value],
                       env=self.xenv, check=True, timeout=10)

    def wait_name(self, name):
        def owned():
            r = subprocess.run(["gdbus", "call", "--session", "-d", "org.freedesktop.DBus", "-o", "/org/freedesktop/DBus",
                                "-m", "org.freedesktop.DBus.NameHasOwner", name], env=self.xenv, capture_output=True, text=True)
            return "true" in r.stdout
        self.assertTrue(mt.wait_for(owned, 10), name)

    def popups(self):
        r = subprocess.run(["xdotool", "search", "--onlyvisible", "--classname", "xfce4-notifyd"], env=self.xenv,
                           capture_output=True, text=True, timeout=10)
        return [w for w in r.stdout.split() if w]

    def log_rows(self):
        path = os.path.join(self.s.env["XDG_CACHE_HOME"], "xfce4", "notifyd", "log.sqlite")
        if not os.path.exists(path):
            return []
        con = sqlite3.connect(path)
        try:
            return con.execute("SELECT app_id, summary, is_read FROM notifications ORDER BY timestamp").fetchall()
        except sqlite3.Error:
            return []
        finally:
            con.close()

    def mail_rows(self):
        return [r for r in self.log_rows() if r[0] == "luxos-mail"]

    def shot(self, name, x, y, w, h):
        d = SHOTS or self.s.root
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, name)
        # snimek ve skutecnych pixelech obrazovky (bez GDK_SCALE)
        env = {k: v for k, v in self.xenv.items() if k != "GDK_SCALE"}
        subprocess.run([sys.executable, "-c", SHOT, path, str(x), str(y), str(w), str(h)], env=env, check=True, timeout=20)
        return path

    def bar(self, name):
        """Horni lista: pravy konec se zvonkem a hodinami (orez 400x28 px)."""
        k = self.scale
        return self.shot(name, 1280 - 400 * k, 0, 400 * k, 28 * k)

    def theme(self):
        return ("dark" if self.dark else "light") + ("-%dx" % self.scale if self.scale > 1 else "")

    def deliver(self, name, flags=""):
        self.server.control(("deliver INBOX " + os.path.join(mt.FIXTURES, name) + " " + flags).strip())

    # ---- test --------------------------------------------------------------------------------------------------

    def test_persistent_mail_notification_and_bell(self):
        t = self.theme()
        acc = self.c.call("add_account", **mt.account_request(self.server))["account"]
        self.assertTrue(mt.wait_for(lambda: self.server.control("sessions")["sessions"] >= 1, 5))
        time.sleep(2.0)  # lista a plugin
        # cervena muze byt v liste i jinde (vlajka rozlozeni klavesnice) -> porovnani s vychozim stavem
        base = red_pixels(self.bar("bell-%s-0-none.png" % t))

        # nova posta: popup + zaznam v historii (neprecteny) + cervena tecka
        self.deliver("de-alternative.eml")
        self.assertTrue(mt.wait_for(lambda: len(self.popups()) == 1, 8), self.s.service_log())
        self.assertTrue(mt.wait_for(lambda: len(self.mail_rows()) == 1, 5), self.log_rows())
        self.assertEqual(self.mail_rows()[0][1:], ("Nová pošta od Jürgen Müller", 0))
        time.sleep(1.0)
        shot = self.bar("bell-%s-1-unread.png" % t)
        if PLUGIN:
            # tecka ~6x6 px vpravo nahore na zvonku
            k = self.scale
            dot = largest_blob(red_pixels(shot) - base)
            self.assertGreaterEqual(len(dot), 16 * k * k)
            box = box_of(dot)
            self.assertTrue(4 * k + 4 <= box[2] - box[0] <= 10 * k + 4 and 4 * k + 4 <= box[3] - box[1] <= 10 * k + 4, box)
            self.assertLess(box[3], 16 * k, box)
        self.shot("screen-%s-1-popup.png" % t, 0, 0, 1280, 400)
        if not self.dark and self.scale == 1:
            # zustava (vychozi expire-timeout LuxOS je 6 s)
            time.sleep(31)
            self.assertEqual(len(self.popups()), 1)

        # dalsi posta: stejny popup, jeden souhrnny zaznam v historii
        self.deliver("cs-iso88592-qp.eml")
        self.assertTrue(mt.wait_for(lambda: [r[1] for r in self.mail_rows()] == ["Nové zprávy: 2"], 8), self.log_rows())
        self.assertEqual(self.mail_rows()[0][2], 0)
        self.assertEqual(len(self.popups()), 1)
        self.shot("screen-%s-2-summary.png" % t, 0, 0, 1280, 400)

        # jedna prectena v Poste: nic se nemeni
        self.assertTrue(self.c.call("flags", account=acc, mailbox="INBOX", uids=[10], add=True, flags=["\\Seen"])["ok"])
        time.sleep(1.0)
        self.assertEqual(len(self.popups()), 1)
        self.assertEqual(self.mail_rows()[0][2], 0)
        # druha prectena jinde (IMAP \Seen pres IDLE): popup zmizi, zaznam precteny, tecka zmizi
        self.server.control("flags INBOX 11 \\Seen")
        self.assertTrue(mt.wait_for(lambda: len(self.popups()) == 0, 8), self.s.service_log())
        self.assertTrue(mt.wait_for(lambda: self.mail_rows() and self.mail_rows()[0][2] == 1, 5), self.log_rows())
        self.assertEqual(len(self.mail_rows()), 1)
        time.sleep(1.0)
        shot = self.bar("bell-%s-3-read.png" % t)
        if PLUGIN:
            self.assertEqual(inside(red_pixels(shot) - base, box), set())

        # Nerusit: popup se neukaze, v historii je, zvonek preskrtnuty s teckou; po precteni zaznam precteny
        self.xfconf("xfce4-notifyd", "/do-not-disturb", "bool", "true")
        time.sleep(0.5)
        self.deliver("uk-koi8u-base64.eml")
        self.assertTrue(mt.wait_for(lambda: len(self.mail_rows()) == 2, 8), self.log_rows())
        self.assertEqual(self.mail_rows()[-1][2], 0)
        self.assertEqual(self.popups(), [])
        time.sleep(1.0)
        shot = self.bar("bell-%s-4-dnd-unread.png" % t)
        if PLUGIN:
            # tecka na stejnem miste i na preskrtnutem zvonku
            self.assertGreaterEqual(len(inside(red_pixels(shot) - base, box)), 16 * self.scale * self.scale)
        self.server.control("flags INBOX 12 \\Seen")
        self.assertTrue(mt.wait_for(lambda: self.mail_rows()[-1][2] == 1, 8), (self.log_rows(), self.s.service_log()))
        time.sleep(1.0)
        shot = self.bar("bell-%s-5-dnd-read.png" % t)
        if PLUGIN:
            self.assertEqual(inside(red_pixels(shot) - base, box), set())

        # docasna oznameni (hlasitost) do historie nepatri
        subprocess.run(["notify-send", "-a", "Volume", "-e", "-h", "int:value:40", "Volume", "40 %"], env=self.xenv, timeout=10)
        time.sleep(0.5)
        self.assertNotIn("Volume", [r[1] for r in self.log_rows()])


class NotifyBellDark(NotifyBell):
    dark = True


class NotifyBellHiDPI(NotifyBell):
    """Lista pri dvojnasobnem meritku (GDK_SCALE=2): tecka ostra, 12x12 px."""
    scale = 2


if __name__ == "__main__":
    unittest.main()
