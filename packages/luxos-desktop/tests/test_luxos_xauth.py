"""LuxOS - pristup k obrazovce po zmene nazvu pocitace (files/session/luxos-xauth-wildcard).

Skutecny pripad: nazev pocitace se za behu relace zmenil (jupiter -> luxos pres hostname1), LightDM mel
v ~/.Xauthority cookie jen pro "jupiter/unix:0" a kazdy nove spusteny program koncil "Authorization
required ... Failed to open display" (Launchpad, Hodiny, snimky obrazovky).

Test spusti vlastni Xvfb s -auth (skutecny cookie, server odmita spojeni bez nej) a nazev pocitace meni
v soukromem jmennem prostoru (unshare -U -u, bez roota; skutecny nazev pocitace se nemeni). Skutecny
~/.Xauthority, obrazovka ani relace se nepouzivaji (scripts/luxos_testguard.py).

Spusteni:  env -u DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u XAUTHORITY \\
               python3 -m unittest packages/luxos-desktop/tests/test_luxos_xauth.py -v
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
import os
import re
import shutil
import stat
import subprocess
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = os.path.normpath(os.path.join(HERE, "..", "files"))
HELPER = os.path.join(FILES, "session", "luxos-xauth-wildcard")
XINIT = os.path.join(FILES, "xinit", "10-luxos-xauth.sh")
MIT = b"MIT-MAGIC-COOKIE-1".hex()
TOOLS = all(shutil.which(t) for t in ("Xvfb", "xauth", "xprop", "unshare"))
REAL_HOME = os.path.expanduser("~")


def userns_ok():
    if not shutil.which("unshare"):
        return False
    r = subprocess.run(["unshare", "-Ur", "-u", "python3", "-c",
                        "import socket; socket.sethostname('luxos-ns-test'); print(socket.gethostname())"],
                       capture_output=True, text=True)
    return r.returncode == 0 and r.stdout.strip() == "luxos-ns-test"


USERNS = TOOLS and userns_ok()


def entry(family, host, num, cookie):
    """Radek ve formatu xauth nlist (prazdna adresa = dve mezery)."""
    a = host.encode().hex()
    n = str(num).encode().hex()
    return "%s %04x %s %04x %s %04x %s %04x %s" % (family, len(a) // 2, a, len(n) // 2, n, len(MIT) // 2, MIT,
                                                   len(cookie) // 2, cookie)


def write_auth(path, lines):
    """Soubor autorizace pres xauth nmerge ze standardniho vstupu (cookie ne v argumentech)."""
    if os.path.exists(path):
        os.unlink(path)
    subprocess.run(["xauth", "-f", path, "nmerge", "-"], input="".join(l + "\n" for l in lines),
                   text=True, check=True, capture_output=True)
    os.chmod(path, 0o600)


def readb(path):
    with open(path, "rb") as f:
        return f.read()


def readt(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def nlist(path):
    return subprocess.run(["xauth", "-f", path, "nlist"], capture_output=True, text=True).stdout.splitlines()


@unittest.skipUnless(TOOLS, "chybi Xvfb, xauth, xprop nebo unshare")
class XauthWildcard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="luxos-xauth-test-")
        cls.cookie = os.urandom(16).hex()
        cls.server_auth = os.path.join(cls.tmp, "server-auth")
        write_auth(cls.server_auth, [entry("ffff", "", 0, cls.cookie)])
        cls.num = next(n for n in range(140, 240)
                       if not os.path.exists("/tmp/.X11-unix/X%d" % n) and not os.path.exists("/tmp/.X%d-lock" % n))
        cls.xvfb = subprocess.Popen(["Xvfb", ":%d" % cls.num, "-auth", cls.server_auth, "-nolisten", "tcp",
                                     "-screen", "0", "320x240x24"],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            if os.path.exists("/tmp/.X11-unix/X%d" % cls.num):
                break
            time.sleep(0.05)
        time.sleep(0.2)
        cls.display = ":%d" % cls.num

    @classmethod
    def tearDownClass(cls):
        cls.xvfb.terminate()     # jen nas vlastni proces (Popen), nikdy podle jmena
        cls.xvfb.wait(5)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.home = tempfile.mkdtemp(dir=self.tmp)
        self.run_dir = os.path.join(self.home, "run")
        os.mkdir(self.run_dir, 0o700)
        self.auth = os.path.join(self.home, ".Xauthority")
        self.assertFalse(os.path.realpath(self.auth).startswith(os.path.realpath(REAL_HOME) + "/.Xauthority"))

    def env(self, **extra):
        e = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": self.home, "DISPLAY": self.display,
             "XAUTHORITY": self.auth, "XDG_RUNTIME_DIR": self.run_dir, "LUXOS_XAUTH_FSTYPE": "ext2/ext3"}
        e.update(extra)
        return {k: v for k, v in e.items() if v is not None}

    def ns(self, host, cmd, **extra):
        """Prikaz s nazvem pocitace HOST (soukromy jmenny prostor UTS, skutecny nazev se nemeni)."""
        if USERNS:
            argv = ["unshare", "-Ur", "-u", "python3", "-c",
                    "import os, socket, sys; socket.sethostname(sys.argv[1]); os.execvp(sys.argv[2], sys.argv[2:])",
                    host] + cmd
        else:
            argv = cmd
        return subprocess.run(argv, env=self.env(**extra), capture_output=True, text=True, timeout=30)

    def connects(self, host):
        return self.ns(host, ["xprop", "-root", "-len", "0", "_NET_SUPPORTED"]).returncode == 0

    def helper(self, host, **extra):
        r = self.ns(host, ["bash", HELPER], **extra)
        self.assertNotIn(self.cookie, r.stdout + r.stderr)    # cookie se nikdy nevypisuje
        return r

    def test_sanity_server_requires_cookie(self):
        write_auth(self.auth, [entry("0100", "nobody-host", self.num, "00" * 16)])
        self.assertFalse(self.connects("jupiter"))

    @unittest.skipUnless(USERNS, "bez user namespace (unshare -U -u) nejde zmenit nazev pocitace")
    def test_rename_during_session(self):
        write_auth(self.auth, [entry("0100", "jupiter", self.num, self.cookie)])
        # puvodni chyba: po prejmenovani se novy program nepripoji
        self.assertTrue(self.connects("jupiter"))
        self.assertFalse(self.connects("luxos"))
        # prihlaseni (xinitrc.d) jeste pod starym nazvem
        r = self.helper("jupiter")
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
        for host in ("luxos", "jupiter", "pc-01.firma.local"):
            self.assertTrue(self.connects(host), host)
        lines = nlist(self.auth)
        self.assertEqual(lines, [entry("0100", "jupiter", self.num, self.cookie),    # polozka pro nazev zustava
                                 entry("ffff", "jupiter", self.num, self.cookie)])
        self.assertEqual(stat.S_IMODE(os.stat(self.auth).st_mode), 0o600)
        self.assertEqual([f for f in os.listdir(self.home) if f != "run"], [".Xauthority"])  # zadne zbytky
        self.assertEqual(os.listdir(self.run_dir), [])
        # znovu (luxos-session, dalsi prihlaseni) - bez zmeny se soubor neprepisuje
        before = os.stat(self.auth)
        r = self.helper("luxos")
        self.assertEqual(r.returncode, 0)
        after = os.stat(self.auth)
        self.assertEqual((before.st_ino, before.st_mtime_ns), (after.st_ino, after.st_mtime_ns))

    @unittest.skipUnless(USERNS, "bez user namespace (unshare -U -u) nejde zmenit nazev pocitace")
    def test_stale_entries_replaced_others_kept(self):
        ssh = entry("0100", "jupiter", 10, "ab" * 16)          # ssh -X: jiny displej zustava
        write_auth(self.auth, [entry("ffff", "oldpc", self.num, "11" * 16),       # stara polozka FamilyWild
                               entry("0100", "luxos", self.num, "22" * 16),       # stara polozka pro novy nazev
                               ssh,
                               entry("0100", "jupiter", self.num, self.cookie)])
        self.assertFalse(self.connects("luxos"))        # stara polozka pro novy nazev ma prednost
        self.assertFalse(self.connects("pc-02"))        # stara FamilyWild
        self.assertEqual(self.helper("jupiter").returncode, 0)
        for host in ("luxos", "jupiter", "pc-02"):
            self.assertTrue(self.connects(host), host)
        # stare polozky tohoto displeje pryc, ssh -X a polozka pro nazev zustavaji
        self.assertEqual(nlist(self.auth), [ssh, entry("0100", "jupiter", self.num, self.cookie),
                                            entry("ffff", "jupiter", self.num, self.cookie)])

    def test_already_renamed_session_recovers(self):
        """Relace, ktera uz nazev zmenila (napr. oprava po aktualizaci): spravny cookie je jen u stareho
        nazvu, polozka pro aktualni nazev je stara - pouzije se cookie, ktery server opravdu prijme."""
        cur = "luxos-now"
        write_auth(self.auth, [entry("0100", cur, self.num, "33" * 16),
                               entry("0100", "jupiter-old-name", self.num, self.cookie)])
        self.assertFalse(self.connects(cur))
        self.assertEqual(self.helper(cur).returncode, 0)
        self.assertTrue(self.connects(cur))
        if USERNS:
            self.assertTrue(self.connects("another-name"))

    def test_network_home_untouched(self):
        write_auth(self.auth, [entry("0100", "jupiter", self.num, self.cookie)])
        before = readb(self.auth)
        for fs in ("nfs", "cifs", "smb2", "fuse.sshfs"):
            self.assertEqual(self.helper("jupiter", LUXOS_XAUTH_FSTYPE=fs).returncode, 0)
            self.assertEqual(readb(self.auth), before, fs)

    def test_nothing_to_do(self):
        # zadny displej, vzdaleny displej, chybejici soubor, odkaz misto souboru: nic se nezmeni ani nevytvori
        self.assertEqual(self.helper("jupiter", DISPLAY=None).returncode, 0)
        self.assertEqual(self.helper("jupiter", DISPLAY="example.org:0").returncode, 0)
        self.assertEqual(self.helper("jupiter").returncode, 0)
        self.assertFalse(os.path.exists(self.auth))
        real = os.path.join(self.home, "real-auth")
        write_auth(real, [entry("0100", "jupiter", self.num, self.cookie)])
        os.symlink(real, self.auth)
        before = readb(real)
        self.assertEqual(self.helper("jupiter").returncode, 0)
        self.assertEqual(readb(real), before)
        # cookie, ktery server neprijme: nic se neprida
        os.unlink(self.auth)
        write_auth(self.auth, [entry("0100", "jupiter", self.num, "44" * 16)])
        before = readb(self.auth)
        self.assertEqual(self.helper("jupiter").returncode, 0)
        self.assertEqual(readb(self.auth), before)


class Packaging(unittest.TestCase):
    def test_xinit_script(self):
        src = readt(XINIT)
        # nacita ho /bin/sh (/etc/lightdm/Xsession) prikazem ".": zadne exit, bashismy, ani vystup
        self.assertEqual(subprocess.run(["sh", "-n", XINIT]).returncode, 0)
        self.assertNotRegex(src, r"(?m)^\s*exit\b")
        self.assertIn("/usr/lib/luxos/luxos-xauth-wildcard >/dev/null 2>&1", src)
        self.assertTrue(os.access(XINIT, os.X_OK) and os.access(HELPER, os.X_OK))

    def test_installed_and_called(self):
        pkg = readt(os.path.join(HERE, "..", "PKGBUILD"))
        self.assertIn('"$f/xinit/10-luxos-xauth.sh" "$pkgdir/etc/X11/xinit/xinitrc.d/10-luxos-xauth.sh"', pkg)
        self.assertIn('"$f/session/luxos-xauth-wildcard"', pkg)
        self.assertRegex(pkg, r"\bxorg-xauth\b")
        session = readt(os.path.join(FILES, "bin", "luxos-session"))
        self.assertIn("/usr/lib/luxos/luxos-xauth-wildcard", session)
        inst = readt(os.path.join(HERE, "..", "luxos-desktop.install"))
        self.assertRegex(inst, r"post_upgrade\(\) \{[^}]*_luxos_xauth_now")

    def test_install_hook_syntax(self):
        inst = os.path.join(HERE, "..", "luxos-desktop.install")
        self.assertEqual(subprocess.run(["bash", "-n", inst]).returncode, 0)
        # bez bezicich relaci nic nespusti (pgrep nic nenajde) a nikdy neselze
        r = subprocess.run(["bash", "-c", '. "$1"; pgrep() { return 1; }; runuser() { echo RUNUSER; }; '
                            '_luxos_xauth_now; echo rc=$?', "x", inst], capture_output=True, text=True)
        self.assertEqual(r.stdout.strip(), "rc=0")


if __name__ == "__main__":
    unittest.main()
