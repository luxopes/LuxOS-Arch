#!/usr/bin/env python3
"""LuxOS Sandbox - nedůvěryhodné spojení okna sandboxu (Xephyr) s displejem plochy.

    env -u DISPLAY -u XAUTHORITY python3 packages/luxos-sandbox/tests/test_x11_untrusted.py -v

Jen na vlastním Xvfb (displej :600-:699, soubor autorizace v dočasné složce pod out/ repozitáře nebo
v TMPDIR), přes pojistku testů (scripts/luxos_testguard.py) - skutečná obrazovka ani ~/.Xauthority se
nikdy nepoužijí. Nic se nespouští jako root.

Aplikace v sandboxu vidí jen vlastní Xephyr; jediný klient displeje plochy, kterého luxos-sandbox
spouští, je Xephyr. Test proto na místo Xephyru (stejný příkaz, stejné omezení, stejné prostředí
a autorizace) podstrčí sondu x11-probe.c a ta zkusí na důvěryhodném okně "oběti" (má fokus, uživatel
v něm píše): odposlech kláves (XQueryKeymap, XSelectInput na cizí okno, RECORD, XInput2 raw
události), snímek (XGetImage okna i obrazovky) a vkládání (XSendEvent, XTest). Na staré cestě
(Xephyr s prostředím uživatele = důvěryhodný cookie) vše projde a test selže.
XGrabKeyboard rozšíření SECURITY nebrání (aktivní převzetí klávesnice je viditelné - okno oběti přestane
dostávat znaky); test ho jen zaznamená, viz SECURITY.md.

Dál ověřuje: skutečný Xephyr s nedůvěryhodným spojením funguje (kreslí, dostává klávesy), autorizace
se po skončení zruší, volba důvěryhodného displeje (trusted-display) a že Xvfb/Xorg má rozšíření SECURITY.
"""
import importlib.machinery
import importlib.util
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
CLI = os.path.join(HERE, "..", "files", "luxos-sandbox")
sys.path.insert(0, os.path.join(REPO, "scripts"))
import luxos_testguard  # noqa: E402,F401  - pojistka: nikdy skutečná obrazovka ani relace

TOOLS = ("Xvfb", "Xephyr", "bwrap", "gcc", "xdotool")
MISSING = [t for t in TOOLS if not shutil.which(t)]


def load_module(env):
    """luxos-sandbox ze zdrojového stromu jako modul (testovací režim)."""
    os.environ.update(env)
    loader = importlib.machinery.SourceFileLoader("luxos_sandbox_cli", CLI)
    spec = importlib.util.spec_from_loader("luxos_sandbox_cli", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def xauth_entry(cookie, num):
    import struct

    def f(b):
        return struct.pack(">H", len(b)) + b
    return struct.pack(">H", 0xFFFF) + f(b"") + f(str(num).encode()) + f(b"MIT-MAGIC-COOKIE-1") + f(cookie)


@unittest.skipIf(MISSING, "missing tools: %s" % ", ".join(MISSING))
class UntrustedX11(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        out = os.path.join(REPO, "out")
        cls.t = tempfile.mkdtemp(prefix="luxos-x11sec-", dir=out if os.path.isdir(out) else None)
        os.chmod(cls.t, 0o700)
        cls.probe = os.path.join(cls.t, "x11-probe")
        r = subprocess.run(["gcc", "-O2", "-o", cls.probe, os.path.join(HERE, "x11-probe.c"),
                            "-lX11", "-lXext", "-lXtst", "-lXi"], capture_output=True, text=True)
        if r.returncode:
            shutil.rmtree(cls.t, ignore_errors=True)
            raise unittest.SkipTest("x11-probe build failed (X11/Xtst/Xi headers?): " + r.stderr[-300:])
        cls.num = next(n for n in range(600, 700) if not os.path.exists("/tmp/.X11-unix/X%d" % n)
                       and not os.path.exists("/tmp/.X%d-lock" % n))
        cls.auth = os.path.join(cls.t, "Xauthority")
        with open(cls.auth, "wb") as f:
            os.fchmod(f.fileno(), 0o600)
            f.write(xauth_entry(secrets.token_bytes(16), cls.num))
        cls.xlog = open(os.path.join(cls.t, "xvfb.log"), "w+")
        cls.xvfb = subprocess.Popen(["Xvfb", ":%d" % cls.num, "-auth", cls.auth, "-nolisten", "tcp",
                                     "-screen", "0", "1600x1000x24", "-audit", "4"],
                                    stdout=cls.xlog, stderr=cls.xlog)
        for _i in range(100):
            if os.path.exists("/tmp/.X11-unix/X%d" % cls.num):
                break
            time.sleep(0.05)
        run = os.path.join(cls.t, "run")
        os.mkdir(run, 0o700)
        cls.env = {"DISPLAY": ":%d" % cls.num, "XAUTHORITY": cls.auth, "XDG_RUNTIME_DIR": run,
                   "XDG_CONFIG_HOME": os.path.join(cls.t, "config"), "LUXOS_SANDBOX_TESTING": "1"}
        cls.mod = load_module(cls.env)

    @classmethod
    def tearDownClass(cls):
        cls.xvfb.terminate()
        cls.xvfb.wait(5)
        cls.xlog.close()
        shutil.rmtree(cls.t, ignore_errors=True)

    def xenv(self):
        e = dict(os.environ)
        e.update(self.env)
        return e

    def start_victim(self):
        v = subprocess.Popen([self.probe, "victim"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
                             env=self.xenv())
        wid = v.stdout.readline().split()[1]
        held = v.stdout.readline().split()[1]
        return v, wid, held

    def attack_through_sandbox_path(self, trusted=False):
        """Spustí sondu tam, kde luxos-sandbox spouští Xephyr (Popen v modulu)."""
        victim, wid, held = self.start_victim()
        rfd, wfd = os.pipe()
        real_popen = subprocess.Popen
        seen = {}

        def fake_popen(cmd, *a, pass_fds=(), **kw):
            i = cmd.index("Xephyr")
            pre = list(cmd[:i])
            if pre and pre[0] == "bwrap":
                self.assertEqual(pre[-1], "--")
                pre = pre[:-1] + ["--ro-bind", self.probe, self.probe, "--"]   # sonda vidět i v omezení
            seen["cmd"] = cmd
            new = pre + [self.probe, "attack", "--victim", wid, "--held", held, "--result-fd", str(wfd)] + cmd[i + 1:]
            return real_popen(new, *a, pass_fds=tuple(pass_fds) + (wfd,), **kw)

        self.mod.subprocess.Popen = fake_popen
        xe = self.mod.Xephyr("Sandbox - probe", trusted=trusted) if trusted else self.mod.Xephyr("Sandbox - probe")  # stará cesta: bez parametru
        try:
            xe.start()
        finally:
            self.mod.subprocess.Popen = real_popen
            os.close(wfd)
        res = {}
        with os.fdopen(rfd) as f:
            for line in f:
                parts = line.split(None, 2)
                if len(parts) >= 2:
                    res[parts[0]] = (parts[1], parts[2].strip() if len(parts) > 2 else "")
        xe.stop()
        victim.stdin.close()
        got = victim.stdout.read()
        victim.wait(10)
        m = re.search(r"GOT send_event=(\d+) xtest=(\d+)", got)
        res["VICTIM_GOT_SENDEVENT"] = int(m.group(1))
        res["VICTIM_GOT_XTEST"] = int(m.group(2))
        return res, seen["cmd"]

    # ---------------------------------------------------------------------------------------------
    def test_00_server_has_security_extension(self):
        """Xvfb z xorg-server (stejné sestavení jako Xorg plochy) má rozšíření SECURITY."""
        out = subprocess.run([self.probe, "attack"], env=self.xenv(), capture_output=True, text=True).stdout
        self.assertIn("SECURITY", re.search(r"EXTENSIONS (.*)", out).group(1).split(","))
        xorg = "/usr/lib/Xorg"
        if os.path.exists(xorg):
            with open(xorg, "rb") as f:
                self.assertIn(b"SECURITY", f.read(), "Xorg built without the SECURITY extension?")

    def test_10_sandbox_xephyr_link_cannot_spy_or_inject(self):
        res, cmd = self.attack_through_sandbox_path()
        detail = "\n".join("%s %s" % (k, v) for k, v in sorted(res.items()))
        self.assertEqual(res["CONNECT"][0], "OK", detail)       # spojení samo funguje (Xephyr musí kreslit)
        # (a) odposlech kláves
        for name in ("QUERYKEYMAP", "SELECTINPUT_VICTIM", "RECORD", "XI2_RAWKEYS"):
            self.assertEqual(res[name][0], "DENIED", "%s must be denied:\n%s" % (name, detail))
        # (b) snímky
        for name in ("GETIMAGE_VICTIM", "GETIMAGE_ROOT"):
            self.assertEqual(res[name][0], "DENIED", "%s must be denied:\n%s" % (name, detail))
        # (c) vkládání - rozhoduje, co oběť skutečně dostala
        self.assertEqual(res["VICTIM_GOT_SENDEVENT"], 0, detail)
        self.assertEqual(res["VICTIM_GOT_XTEST"], 0, detail)
        self.assertEqual(res["XTEST_CALL"][0], "DENIED", detail)
        # nedůvěryhodný klient vidí jen základní rozšíření
        exts = set(filter(None, res["EXTENSIONS"][0].split(","))) | set(filter(None, res["EXTENSIONS"][1].split(",")))
        self.assertFalse(exts & {"RECORD", "XTEST", "XInputExtension", "MIT-SHM", "XKEYBOARD"}, detail)
        # klient na straně hostitele nikdy nedostane cookie uživatele ani jeho soubor autorizace
        self.assertEqual(cmd[0], "bwrap", "Xephyr must run confined")
        self.assertNotIn(self.auth, cmd)
        self.assertIn("--clearenv", cmd)
        print("\n  untrusted results:\n    " + detail.replace("\n", "\n    "), file=sys.stderr)

    def test_20_trusted_opt_in_is_trusted(self):
        """Kontrola sondy: s vyslovně povoleným důvěryhodným displejem útoky projdou (sonda měří správně)."""
        res, cmd = self.attack_through_sandbox_path(trusted=True)
        self.assertEqual(cmd[0], "bwrap")
        self.assertNotIn(self.auth, cmd)
        self.assertEqual(res["GETIMAGE_VICTIM"][0], "OK", res)
        self.assertEqual(res["QUERYKEYMAP"][0], "OK", res)

    def test_30_real_xephyr_works_untrusted_and_auth_is_revoked(self):
        xe = self.mod.Xephyr("Sandbox - luxos-x11-test")
        sock = xe.start()
        try:
            self.assertTrue(os.path.exists(sock), sock)
            self.assertTrue(sock.startswith(self.env["XDG_RUNTIME_DIR"]), sock)
            iauth = os.path.join(self.t, "inner-auth")
            with open(iauth, "wb") as f:
                f.write(self.mod.xauth_record(xe.cookie))
            # aplikace "v sandboxu": jen soket Xephyru jako :0 (jako bwrap sandboxu)
            app = subprocess.Popen(
                ["bwrap", "--unshare-all", "--die-with-parent", "--ro-bind", "/usr", "/usr",
                 "--symlink", "usr/lib", "/lib64", "--symlink", "usr/lib", "/lib", "--symlink", "usr/bin", "/bin",
                 "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--bind", sock, "/tmp/.X11-unix/X0",
                 "--ro-bind", iauth, "/run/xauth", "--ro-bind", self.probe, "/run/x11-probe",
                 "--clearenv", "--setenv", "DISPLAY", ":0", "--setenv", "XAUTHORITY", "/run/xauth",
                 "--", "/run/x11-probe", "listen"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
            self.assertEqual(app.stdout.readline().strip(), "READY")
            env = self.xenv()
            wid = subprocess.run(["xdotool", "search", "--sync", "--name", "luxos-x11-test"], env=env,
                                 capture_output=True, text=True, timeout=10).stdout.split()[0]
            subprocess.run(["xdotool", "windowfocus", "--sync", wid], env=env, check=True, timeout=10)
            time.sleep(0.5)
            # Xephyr kreslí bez MIT-SHM: v okně na ploše je modré okno aplikace
            px = subprocess.run([self.probe, "pixel", wid, "100", "100"], env=env, capture_output=True,
                                text=True).stdout.strip()
            self.assertEqual(px, "0000ff")
            subprocess.run(["xdotool", "type", "--delay", "40", "hello"], env=env, check=True, timeout=10)
            time.sleep(0.8)
            app.stdin.close()
            keys = [ln.split()[1] for ln in app.stdout.read().splitlines() if ln.startswith("KEY ")]
            app.wait(10)
            self.assertEqual("".join(keys), "hello")
        finally:
            xe.stop()
        time.sleep(0.3)
        self.xlog.flush()
        with open(self.xlog.name) as f:
            log = f.read()
        gen = re.findall(r"generated authorization (\d+) trust (\d) timeout (\d+)", log)
        self.assertTrue(gen, log[-2000:])
        last_id, trust, timeout = gen[-1]
        self.assertEqual((trust, timeout), ("1", "0"))
        self.assertIn("revoked authorization ID %s" % last_id, log)
        self.assertFalse(os.path.exists(xe_dir := os.path.dirname(sock)), xe_dir)

    def test_35_real_xephyr_trusted_opt_in(self):
        """Vyslovně povolený důvěryhodný displej: i tak jen dočasný cookie (trust 0), po skončení zrušený."""
        xe = self.mod.Xephyr("Sandbox - luxos-x11-trusted", trusted=True)
        sock = xe.start()
        try:
            self.assertTrue(os.path.exists(sock), sock)
            wid = subprocess.run(["xdotool", "search", "--sync", "--name", "luxos-x11-trusted"], env=self.xenv(),
                                 capture_output=True, text=True, timeout=10).stdout.split()
            self.assertTrue(wid)
        finally:
            xe.stop()
        time.sleep(0.3)
        self.xlog.flush()
        with open(self.xlog.name) as f:
            log = f.read()
        last_id, trust, timeout = re.findall(r"generated authorization (\d+) trust (\d) timeout (\d+)", log)[-1]
        self.assertEqual((trust, timeout), ("0", "0"))
        self.assertIn("revoked authorization ID %s" % last_id, log)

    def test_40_trusted_display_setting(self):
        env = self.xenv()
        run = lambda *a: subprocess.run([sys.executable, CLI, *a], env=env, capture_output=True, text=True)  # noqa: E731
        self.assertEqual(run("trusted-display", "--json").stdout.strip(), '{"trusted_display": []}')
        r = run("trusted-display", "game", "on")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("game", run("trusted-display", "--json").stdout)
        path = os.path.join(self.env["XDG_CONFIG_HOME"], "luxos", "sandbox", "trusted-display")
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        self.assertNotEqual(run("trusted-display", "../x", "on").returncode, 0)
        self.assertNotEqual(run("trusted-display", "game", "maybe").returncode, 0)
        run("trusted-display", "game", "off")
        self.assertEqual(run("trusted-display", "--json").stdout.strip(), '{"trusted_display": []}')


if __name__ == "__main__":
    unittest.main()
