"""Testy Snimku obrazovky v LSL (files/lsl/luxos_shot*.lsl, luxos-screenshot.lsl, luxos-screenshot-ui.lsl).

Cista logika (volby, nazvy souboru, vyrez, zkratky, ffmpeg, prepinace, protokol) se testuje pres maly
testovaci program tests/lsl/luxos-shot-test.lsl; klient a cesta pozadavku k serveru (hub) a samostatny
proces bez hubu; pod Xvfb lista, Esc/Enter bez zabrani klavesnice, nahled, odpocet, poradi oken,
schranka a nahravani.

Spusteni:  python3 -m unittest packages/luxos-desktop/tests/test_luxos_screenshot.py -v
GUI cast:  env -u DISPLAY xvfb-run -a -s "-screen 0 1280x800x24" python3 -m unittest packages/luxos-desktop/tests/test_luxos_screenshot.py -v
LUXOS_LSLC: prekladac lslc (LSL >= 0.10.6, jinak se testy preskoci). GUI nikdy na skutecne obrazovce
(jen virtualni X z xvfb-run, nebo vyslovne LUXOS_TEST_X=1 ve VM).
"""
import ctypes
import ctypes.util
import glob
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
LSL = os.path.join(HERE, "..", "files", "lsl")
SHORTCUTS = os.path.join(HERE, "..", "files", "xdg", "xfce4", "xfconf", "xfce-perchannel-xml",
                         "xfce4-keyboard-shortcuts.xml")
I18N = os.path.normpath(os.path.join(HERE, "..", "..", "luxos-i18n", "files"))
TMP = tempfile.mkdtemp(prefix="luxos-shot-test-")
LSLC = os.environ.get("LUXOS_LSLC") or shutil.which("lslc")
HAVE_DISPLAY = bool(os.environ.get("DISPLAY")) and (
    "xvfb-run" in os.environ.get("XAUTHORITY", "") or os.environ.get("LUXOS_TEST_X") == "1")


def build():
    """Prelozi testovaci program, klienta a samostatny proces; None bez prekladace."""
    if not LSLC:
        return None
    src = os.path.join(TMP, "src")
    os.makedirs(src, exist_ok=True)
    for f in glob.glob(os.path.join(LSL, "*.lsl")) + [os.path.join(HERE, "lsl", "luxos-shot-test.lsl")]:
        shutil.copy(f, src)
    out = os.path.join(TMP, "bin")
    os.makedirs(out, exist_ok=True)
    for name in ("luxos-shot-test", "luxos-screenshot", "luxos-screenshot-ui"):
        r = subprocess.run([LSLC, "--target", "linux-x86_64-gnu", os.path.join(src, name + ".lsl"), os.path.join(out, name)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            print(r.stdout + r.stderr)
            return None
    return out


BIN = build()


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


def base_env(home, **extra):
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": home, "XDG_CONFIG_HOME": os.path.join(home, ".config"),
           "XDG_RUNTIME_DIR": os.path.join(home, "run"), "XDG_DATA_HOME": os.path.join(home, ".local", "share"),
           "LANG": "en_US.UTF-8", "LUXOS_I18N_DIR": I18N, "NO_AT_BRIDGE": "1",
           # zadna sezeni D-Bus uzivatele: notifikace ani spravce souboru se nesmi objevit na skutecne obrazovce
           "DBUS_SESSION_BUS_ADDRESS": "unix:path=" + os.path.join(home, "no-bus"),
           "XDG_CONFIG_DIRS": "/nonexistent", "GTK_THEME": "Adwaita",
           "LUXOS_SCREENSHOT_UI": os.path.join(BIN or "/nonexistent", "luxos-screenshot-ui")}
    for k in ("DISPLAY", "XAUTHORITY"):
        if k in os.environ:
            env[k] = os.environ[k]
    os.makedirs(env["XDG_RUNTIME_DIR"], mode=0o700, exist_ok=True)
    env.update(extra)
    return env


HOME = os.path.join(TMP, "home")
os.makedirs(HOME, exist_ok=True)


def drv(*args, env=None):
    r = subprocess.run([os.path.join(BIN, "luxos-shot-test"), *[str(a) for a in args]], capture_output=True, text=True,
                       env=env or base_env(HOME), timeout=20)
    if r.returncode != 0:
        raise AssertionError(r.stderr)
    return json.loads(r.stdout)


def png_size(path):
    with open(path, "rb") as f:
        head = f.read(24)
    assert head[:8] == b"\x89PNG\r\n\x1a\n", path
    return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")


DEFAULTS = {"save_to": "screenshots", "other_dir": "", "timer": 0, "pointer": False, "remember": True,
            "selection": None, "mode": "portion"}


@unittest.skipUnless(BIN, "chybi lslc (LSL >= 0.10.6, LUXOS_LSLC)")
class TestNames(unittest.TestCase):
    def test_file_name(self):
        self.assertEqual(drv("file_name", 2026, 10, 22, 11, 12, 3, 0), "Screenshot 2026-10-22 at 11.12.03.png")
        self.assertEqual(drv("file_name", 2026, 10, 22, 11, 12, 3, 1), "Screen Recording 2026-10-22 at 11.12.03.mp4")

    def test_file_name_translated(self):
        env = base_env(HOME, LANG="cs_CZ.UTF-8")
        self.assertEqual(drv("file_name", 2026, 1, 2, 3, 4, 5, 0, env=env), "Snímek obrazovky 2026-01-02 v 03.04.05.png")
        # Poskozeny preklad (chybi %s) nesmi shodit program; lomitko v prekladu neni slozka
        d = tempfile.mkdtemp(dir=TMP)
        with open(os.path.join(d, "cs.tsv"), "w") as f:
            f.write("Screenshot %s at %s\tBroken %d\nScreen Recording %s at %s\tA/B %s %s\n")
        env = base_env(HOME, LANG="cs_CZ.UTF-8", LUXOS_I18N_DIR=d)
        self.assertEqual(drv("file_name", 2026, 1, 2, 3, 4, 5, 0, env=env), "Screenshot 2026-01-02 at 03.04.05.png")
        self.assertEqual(drv("file_name", 2026, 1, 2, 3, 4, 5, 1, env=env), "A-B 2026-01-02 03.04.05.mp4")

    def test_unique_path(self):
        d = tempfile.mkdtemp(dir=TMP)
        self.assertEqual(drv("unique_path", d, "a b.png"), os.path.join(d, "a b.png"))
        open(os.path.join(d, "a b.png"), "w").close()
        self.assertEqual(drv("unique_path", d, "a b.png"), os.path.join(d, "a b (2).png"))
        open(os.path.join(d, "a b (2).png"), "w").close()
        self.assertEqual(drv("unique_path", d, "a b.png"), os.path.join(d, "a b (3).png"))
        os.symlink("/nonexistent", os.path.join(d, "x.png"))         # rozbity odkaz je obsazene jmeno
        self.assertEqual(drv("unique_path", d, "x.png"), os.path.join(d, "x (2).png"))


@unittest.skipUnless(BIN, "chybi lslc")
class TestOptions(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(dir=TMP), "luxos", "screenshot.json")

    def write_raw(self, data):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w") as f:
            f.write(data if isinstance(data, str) else json.dumps(data))

    def test_defaults_when_missing(self):
        self.assertEqual(drv("load_options", self.path), DEFAULTS)

    def test_roundtrip_and_format(self):
        other = tempfile.mkdtemp(dir=TMP)
        o = dict(DEFAULTS, save_to="other", other_dir=other, timer=10, pointer=True, remember=False,
                 selection=[1, 2, 30, 40], mode="rec_portion")
        self.assertTrue(drv("save_options", self.path, json.dumps(o)))
        self.assertEqual(drv("load_options", self.path), o)
        self.assertFalse(os.path.exists(self.path + ".tmp"))
        # stejny soubor jako drive z Pythonu (json.dump indent=1, klic version)
        with open(self.path) as f:
            text = f.read()
        self.assertEqual(json.loads(text), dict(o, version=2))
        self.assertEqual(text, json.dumps(dict(o, version=2), indent=1))

    def test_invalid_values(self):
        self.write_raw({"save_to": "nowhere", "timer": 7, "pointer": "yes", "remember": 1,
                        "selection": [0, 0, 0, 10], "mode": "x", "other_dir": 5})
        self.assertEqual(drv("load_options", self.path), DEFAULTS)
        self.write_raw({"timer": True, "selection": [True, 0, 5, 5]})
        self.assertEqual(drv("load_options", self.path), DEFAULTS)
        self.write_raw("{broken")
        self.assertEqual(drv("load_options", self.path), DEFAULTS)
        self.write_raw("[1, 2]")
        self.assertEqual(drv("load_options", self.path), DEFAULTS)

    def test_other_without_dir_falls_back(self):
        self.write_raw({"save_to": "other"})
        self.assertEqual(drv("load_options", self.path)["save_to"], "screenshots")

    def test_old_desktop_default_migrated(self):
        """Do 0.9.10 se "desktop" ukladal jako vychozi i bez volby uzivatele -> nova vychozi slozka."""
        self.write_raw({"save_to": "desktop", "timer": 5, "mode": "screen"})
        o = drv("load_options", self.path)
        self.assertEqual((o["save_to"], o["timer"], o["mode"]), ("screenshots", 5, "screen"))
        for to, extra in (("pictures", {}), ("clipboard", {}), ("other", {"other_dir": TMP})):
            self.write_raw(dict({"save_to": to}, **extra))
            self.assertEqual(drv("load_options", self.path)["save_to"], to)

    def test_desktop_chosen_after_update_kept(self):
        drv("save_options", self.path, json.dumps(dict(DEFAULTS, save_to="desktop")))
        self.assertEqual(drv("load_options", self.path)["save_to"], "desktop")
        self.write_raw({"save_to": "desktop", "version": 1})        # neznama starsi verze = stary soubor
        self.assertEqual(drv("load_options", self.path)["save_to"], "screenshots")

    def test_save_dir(self):
        home = tempfile.mkdtemp(dir=TMP)
        env = base_env(home)
        shots = os.path.join(home, "Pictures", "Screenshots")
        self.assertEqual(drv("screenshots_dir", env=env), shots)
        o = dict(DEFAULTS)
        sd = lambda opts, video=0, *over: drv("save_dir", json.dumps(opts), video, *over, env=env)   # noqa: E731
        self.assertIsNone(sd(dict(o, save_to="clipboard")))
        self.assertEqual(sd(dict(o, save_to="clipboard"), 1), shots)        # video do schranky nejde
        self.assertEqual(sd(dict(o, save_to="screenshots")), shots)
        self.assertEqual(sd(dict(o, save_to="desktop")), os.path.join(home, "Desktop"))
        self.assertEqual(sd(dict(o, save_to="pictures")), os.path.join(home, "Pictures"))
        d = tempfile.mkdtemp(dir=TMP)
        self.assertEqual(sd(dict(o, save_to="other", other_dir=d)), d)
        self.assertEqual(sd(dict(o, save_to="other", other_dir=d + "-gone")), shots)   # smazana slozka
        self.assertEqual(sd(dict(o, save_to="clipboard"), 0, d), d)


@unittest.skipUnless(BIN, "chybi lslc")
class TestScreenshotsFolder(unittest.TestCase):
    def folder(self, lang, pictures=None):
        home = tempfile.mkdtemp(dir=TMP)
        cfg = os.path.join(home, ".config")
        os.makedirs(cfg)
        if pictures:
            with open(os.path.join(cfg, "user-dirs.dirs"), "w", encoding="utf-8") as f:
                f.write('XDG_PICTURES_DIR="$HOME/%s"\n' % pictures)
        return home, drv("screenshots_dir", env=base_env(home, LANG=lang))

    def test_english_default(self):
        home, d = self.folder("en_US.UTF-8")
        self.assertEqual(d, os.path.join(home, "Pictures", "Screenshots"))
        self.assertFalse(os.path.exists(os.path.join(home, "Pictures")))       # vytvori se az pri ulozeni

    def test_localized_pictures_and_name(self):
        home, d = self.folder("cs_CZ.UTF-8", "Obrázky")
        self.assertEqual(d, os.path.join(home, "Obrázky", "Snímky obrazovky"))
        home, d = self.folder("de_DE.UTF-8", "Bilder")
        self.assertEqual(d, os.path.join(home, "Bilder", "Bildschirmfotos"))

    def test_every_language_has_folder_name(self):
        for tsv in sorted(os.listdir(I18N)):
            if not tsv.endswith(".tsv"):
                continue
            with open(os.path.join(I18N, tsv), encoding="utf-8") as f:
                names = [ln.rstrip("\n").split("\t", 1)[1] for ln in f if ln.startswith("Screenshots\t")]
            self.assertEqual(len(names), 1, tsv)
            self.assertTrue(names[0].strip() and "/" not in names[0], tsv)


@unittest.skipUnless(BIN, "chybi lslc")
class TestGeometryAndArgs(unittest.TestCase):
    def test_clamp(self):
        self.assertEqual(drv("clamp_rect", 10, 20, 30, 40, 100, 100), [10, 20, 30, 40])
        self.assertEqual(drv("clamp_rect", -10, -10, 30, 40, 100, 100), [0, 0, 20, 30])
        self.assertEqual(drv("clamp_rect", 90, 90, 30, 40, 100, 100), [90, 90, 10, 10])
        self.assertEqual(drv("clamp_rect", 50, 50, -20, -10, 100, 100), [30, 40, 20, 10])     # tazeni doleva nahoru
        self.assertIsNone(drv("clamp_rect", 200, 0, 10, 10, 100, 100))
        self.assertIsNone(drv("clamp_rect", 5, 5, 0, 10, 100, 100))

    def test_parse_region(self):
        self.assertEqual(drv("parse_region", "10,20,300,200"), [10, 20, 300, 200])
        self.assertEqual(drv("parse_region", " 1, 2 ,3,4 "), [1, 2, 3, 4])
        self.assertEqual(drv("parse_region", "-5,-6,3,4"), [-5, -6, 3, 4])
        for bad in ("", "1,2,3", "1,2,0,4", "a,b,c,d", "1,2,-3,4", "1,2,3,4,5"):
            self.assertIsNone(drv("parse_region", bad), bad)

    def test_parse_args(self):
        a = drv("parse_args")
        self.assertEqual(a["action"], "toolbar")
        a = drv("parse_args", "--portion", "--clipboard", "--region", "1,2,3,4", "--output", "/x/../y")
        self.assertEqual((a["action"], a["clipboard"], a["region"], a["output"]), ("portion", True, [1, 2, 3, 4], "/y"))
        self.assertTrue(drv("parse_args", "--stop")["stop"])
        self.assertTrue(drv("parse_args", "--close")["close"])
        self.assertEqual(drv("parse_args", "--selection")["action"], "portion")
        self.assertEqual(drv("parse_args", "--output", "~/Pics")["output"], os.path.join(HOME, "Pics"))
        self.assertIn("error", drv("parse_args", "--bogus"))
        self.assertIn("error", drv("parse_args", "--region", "1,2"))
        self.assertEqual(drv("canonical_args", "--record-portion", "--region", " 1, 2,3,4", "--no-thumbnail"),
                         ["--record-portion", "--no-thumbnail", "--region", "1,2,3,4"])

    def test_client_errors_and_help(self):
        cl = os.path.join(BIN, "luxos-screenshot")
        r = subprocess.run([cl, "--bogus"], capture_output=True, text=True, env=base_env(HOME))
        self.assertEqual((r.returncode, r.stderr.strip()), (1, "luxos-screenshot: unknown option --bogus"))
        r = subprocess.run([cl, "--region", "1,2"], capture_output=True, text=True, env=base_env(HOME))
        self.assertEqual((r.returncode, r.stderr.strip()), (1, "luxos-screenshot: --region X,Y,W,H"))
        r = subprocess.run([cl, "--help"], capture_output=True, text=True, env=base_env(HOME))
        self.assertEqual(r.returncode, 0)
        self.assertIn("--record-screen", r.stdout)


@unittest.skipUnless(BIN, "chybi lslc")
class TestFfmpegAndShortcuts(unittest.TestCase):
    LIST = """Encoders:
 V..... = Video
 ------
 V....D libx264              libx264 H.264 / AVC / MPEG-4 AVC / MPEG-4 part 10 (codec h264)
 V....D libx264rgb           libx264 H.264 RGB (codec h264)
 V.S..D mpeg4                MPEG-4 part 2
"""

    def pick(self, text):
        p = os.path.join(tempfile.mkdtemp(dir=TMP), "enc.txt")
        with open(p, "w") as f:
            f.write(text)
        return drv("pick_encoder", p)

    def test_prefers_h264_and_fallbacks(self):
        self.assertEqual(self.pick(self.LIST)[:2], ["-c:v", "libx264"])
        no264 = "\n".join(line for line in self.LIST.splitlines() if "libx264" not in line)
        self.assertEqual(self.pick(no264)[:2], ["-c:v", "mpeg4"])
        self.assertEqual(self.pick(" V....D libopenh264  OpenH264\n V.S..D mpeg4  x\n")[:2], ["-c:v", "libopenh264"])
        self.assertIsNone(self.pick(" A....D aac  AAC\n"))
        self.assertIsNone(self.pick(""))
        self.assertIsNone(self.pick(" V....D libx264rgb  x\n"))     # libx264rgb neni libx264

    def test_cmd_even_size(self):
        cmd = drv("ffmpeg_cmd", ":1", 5, 7, 301, 199, "/t/o.mp4", 0, "-c:v", "mpeg4")
        self.assertIn("300x198", cmd)
        self.assertEqual(cmd[cmd.index("-i") + 1], ":1+5,7")
        self.assertEqual(cmd[cmd.index("-draw_mouse") + 1], "0")
        self.assertEqual(cmd[-1], "/t/o.mp4")
        self.assertEqual(cmd[cmd.index("-f", cmd.index("-i")) + 1], "mp4")
        self.assertEqual(cmd[cmd.index("-i") + 1:cmd.index("-i") + 3], [":1+5,7", "-c:v"])

    def test_pretty(self):
        self.assertEqual(drv("pretty_accel", "<Super><Shift>3"), "Super+Shift+3")
        self.assertEqual(drv("pretty_accel", "<Shift><Primary>a"), "Ctrl+Shift+A")
        self.assertEqual(drv("pretty_accel", "<Shift>Print"), "Shift+Print")
        self.assertEqual(drv("pretty_accel", "Print"), "Print")
        self.assertIsNone(drv("pretty_accel", "<Super>"))
        self.assertIsNone(drv("pretty_accel", ""))

    def test_defaults_from_luxos(self):
        self.assertEqual(drv("global_shortcut", "luxos-screenshot --screen", SHORTCUTS), "Super+Shift+3")
        # vic zkratek pro jeden prikaz: prvni (Super+Shift+4, ne Shift+Print)
        self.assertEqual(drv("global_shortcut", "luxos-screenshot --portion", SHORTCUTS), "Super+Shift+4")
        self.assertIsNone(drv("global_shortcut", "luxos-screenshot --window", SHORTCUTS))

    def test_user_overrides_defaults(self):
        d = tempfile.mkdtemp(dir=TMP)
        user, broken = os.path.join(d, "user.xml"), os.path.join(d, "broken.xml")
        with open(user, "w") as f:
            f.write('''<?xml version="1.0"?><channel name="xfce4-keyboard-shortcuts" version="1.0">
<property name="commands" type="empty"><property name="custom" type="empty">
<property name="override" type="bool" value="true"/>
<property name="&lt;Primary&gt;&lt;Alt&gt;3" type="string" value="luxos-screenshot --screen"/>
</property></property></channel>''')
        with open(broken, "w") as f:
            f.write("<channel")
        files = [os.path.join(d, "missing.xml"), broken, user, SHORTCUTS]
        self.assertEqual(drv("global_shortcut", "luxos-screenshot --screen", *files), "Ctrl+Alt+3")
        self.assertIsNone(drv("global_shortcut", "luxos-screenshot --portion", *files))   # uzivatel ji odebral
        self.assertIsNone(drv("global_shortcut", "luxos-screenshot --screen", broken))

    def test_trash_real(self):
        """Skutecny Kos s HOME v TMP (nikdy Kos uzivatele)."""
        home = tempfile.mkdtemp(dir=TMP)
        path = os.path.join(home, "Screenshot x.png")
        open(path, "w").close()
        self.assertEqual(drv("trash", path, env=base_env(home)), "trash")
        self.assertFalse(os.path.exists(path))
        self.assertTrue(os.path.exists(os.path.join(home, ".local", "share", "Trash", "files", "Screenshot x.png")))


# ---- protokol klient -> server (hub) ---------------------------------------------------------------
class FakeServer(threading.Thread):
    """Server na abstraktnim socketu jako luxos-hub: zaznamena pozadavek a odpovi podle `replies`."""

    def __init__(self, runtime, replies):
        super().__init__(daemon=True)
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.bind("\0" + runtime + "/luxos-screenshot")
        self.sock.listen(4)
        self.replies, self.requests = replies, []
        self.start()

    def run(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            data = b""
            while not data.endswith(b"\n\n"):
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data += chunk
            self.requests.append(data.decode())
            if self.replies is not None:
                for line in self.replies:
                    conn.sendall(line.encode())
                conn.close()
            else:
                time.sleep(5)                       # neodpovida (zaseknuty hub)
                conn.close()

    def close(self):
        self.sock.close()


@unittest.skipUnless(BIN, "chybi lslc")
class TestProtocol(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(dir=TMP)
        self.env = base_env(self.home)
        # samostatny proces nahradi skript, ktery zapise sve argumenty a promennou fallback
        self.marker = os.path.join(self.home, "ui-called")
        fake = os.path.join(self.home, "fake-ui")
        with open(fake, "w") as f:
            f.write('#!/bin/sh\necho "$LUXOS_SCREENSHOT_FALLBACK|$*" > "%s"\n' % self.marker)
        os.chmod(fake, 0o755)
        self.env["LUXOS_SCREENSHOT_UI"] = fake

    def client(self, *args, timeout=20):
        return subprocess.run([os.path.join(BIN, "luxos-screenshot"), *args], capture_output=True, text=True,
                              env=self.env, cwd=self.home, timeout=timeout)

    def test_request_text_roundtrip(self):
        self.assertEqual(drv("request", "--screen", "--output", "/a b"), ["--screen", "--output", "/a b"])
        self.assertIsNone(drv("request_raw", "other 1\\n--screen\\n\\n"))
        self.assertIsNone(drv("request_raw", "luxos-screenshot 1\\n--screen\\n"))     # neuplna zprava

    def test_client_to_server(self):
        srv = FakeServer(self.env["XDG_RUNTIME_DIR"], ["ok\n", "out /x/Shot 1.png\n", "exit 3\n"])
        try:
            r = self.client("--portion", "--output", "sub", "--no-thumbnail")
        finally:
            srv.close()
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assertEqual(r.stdout, "/x/Shot 1.png\n")
        self.assertEqual(srv.requests, ["luxos-screenshot 1\n--portion\n--no-thumbnail\n--output\n%s/sub\n\n" % self.home])
        self.assertFalse(os.path.exists(self.marker))

    def test_fallback_without_server(self):
        t0 = time.monotonic()
        r = self.client("--screen", "--clipboard")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertLess(time.monotonic() - t0, 1)
        with open(self.marker) as f:
            self.assertEqual(f.read().strip(), "|--screen --clipboard")

    def test_fallback_when_server_hangs(self):
        srv = FakeServer(self.env["XDG_RUNTIME_DIR"], None)
        try:
            t0 = time.monotonic()
            r = self.client("--window")
            took = time.monotonic() - t0
        finally:
            srv.close()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertGreater(took, 2.5)
        with open(self.marker) as f:
            self.assertEqual(f.read().strip(), "1|--window")        # samostatny proces bez serveru

    def test_client_is_small_and_fast(self):
        out = subprocess.run(["ldd", os.path.join(BIN, "luxos-screenshot")], capture_output=True, text=True).stdout
        self.assertNotIn("gtk", out)
        self.assertNotIn("glib", out)


# ---- GUI (Xvfb) --------------------------------------------------------------------------------
X11 = ctypes.CDLL(ctypes.util.find_library("X11") or "libX11.so.6") if HAVE_DISPLAY else None


class Attr(ctypes.Structure):
    _fields_ = [("x", ctypes.c_int), ("y", ctypes.c_int), ("width", ctypes.c_int), ("height", ctypes.c_int),
                ("border_width", ctypes.c_int), ("depth", ctypes.c_int), ("visual", ctypes.c_void_p),
                ("root", ctypes.c_ulong), ("class_", ctypes.c_int), ("bit_gravity", ctypes.c_int),
                ("win_gravity", ctypes.c_int), ("backing_store", ctypes.c_int), ("backing_planes", ctypes.c_ulong),
                ("backing_pixel", ctypes.c_ulong), ("save_under", ctypes.c_int), ("colormap", ctypes.c_ulong),
                ("map_installed", ctypes.c_int), ("map_state", ctypes.c_int), ("all_event_masks", ctypes.c_long),
                ("your_event_mask", ctypes.c_long), ("do_not_propagate_mask", ctypes.c_long),
                ("override_redirect", ctypes.c_int), ("screen", ctypes.c_void_p)]


def stacking():
    """Namapovana okna korenoveho okna od spodu: [(id, override_redirect, x, y, w, h)]."""
    x = X11
    x.XOpenDisplay.restype = ctypes.c_void_p
    x.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x.XDefaultRootWindow.restype = ctypes.c_ulong
    x.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
    x.XQueryTree.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong),
                             ctypes.POINTER(ctypes.POINTER(ctypes.c_ulong)), ctypes.POINTER(ctypes.c_uint)]
    x.XGetWindowAttributes.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(Attr)]
    x.XCloseDisplay.argtypes = [ctypes.c_void_p]
    d = x.XOpenDisplay(None)
    root = x.XDefaultRootWindow(d)
    r, p, n = ctypes.c_ulong(), ctypes.c_ulong(), ctypes.c_uint()
    ch = ctypes.POINTER(ctypes.c_ulong)()
    x.XQueryTree(d, root, ctypes.byref(r), ctypes.byref(p), ctypes.byref(ch), ctypes.byref(n))
    out = []
    for i in range(n.value):
        a = Attr()
        x.XGetWindowAttributes(d, ch[i], ctypes.byref(a))
        if a.map_state == 2:
            out.append((ch[i], bool(a.override_redirect), a.x, a.y, a.width, a.height))
    x.XCloseDisplay(d)
    return out


def esc_free():
    """Muze jiny program globalne zabrat Esc? (False = drzi ho Snimek obrazovky)."""
    code = ("import ctypes, ctypes.util, sys\nx = ctypes.CDLL(ctypes.util.find_library('X11'))\n"
            "x.XOpenDisplay.restype = ctypes.c_void_p\nx.XOpenDisplay.argtypes = [ctypes.c_char_p]\n"
            "d = x.XOpenDisplay(None)\nx.XDefaultRootWindow.restype = ctypes.c_ulong\nx.XDefaultRootWindow.argtypes = [ctypes.c_void_p]\n"
            "err = []\nH = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)\n"
            "h = H(lambda a, b: err.append(1) or 0)\nx.XSetErrorHandler(h)\n"
            "x.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]\n"
            "code = x.XKeysymToKeycode(d, 0xff1b)\n"
            "x.XGrabKey.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_uint, ctypes.c_ulong, ctypes.c_int, ctypes.c_int, ctypes.c_int]\n"
            "x.XGrabKey(d, code, 0, x.XDefaultRootWindow(d), 0, 1, 1)\nx.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]\nx.XSync(d, 0)\n"
            "print('taken' if err else 'free')\n")
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=10).stdout.strip() == "free"


def xdo(*args):
    subprocess.run(["xdotool", *[str(a) for a in args]], check=True, timeout=10)


@unittest.skipUnless(BIN and HAVE_DISPLAY and shutil.which("xdotool"), "needs lslc, X (xvfb-run) and xdotool")
class TestGui(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # pozadi se znamou barvou (bez WM obycejne okno pres celou obrazovku)
        cls.bg = subprocess.Popen([sys.executable, "-c", BG_WINDOW], env=dict(os.environ, NO_AT_BRIDGE="1"))
        time.sleep(1.0)

    @classmethod
    def tearDownClass(cls):
        cls.bg.terminate()
        cls.bg.wait(5)

    def setUp(self):
        self.home = tempfile.mkdtemp(dir=TMP)
        self.log = os.path.join(self.home, "ui.log")
        self.env = base_env(self.home, LUXOS_SCREENSHOT_TEST_LOG=self.log)
        self.out = os.path.join(self.home, "out")
        self.procs = []
        self.server = None

    def tearDown(self):
        subprocess.run([os.path.join(BIN, "luxos-screenshot"), "--close"], env=self.env, timeout=10, capture_output=True)
        for p in self.procs + ([self.server] if self.server else []):
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(5)
                except subprocess.TimeoutExpired:
                    p.kill()
            for f in (p.stdout, p.stderr):
                if f:
                    f.close()

    def opts(self, **o):
        os.makedirs(os.path.join(self.home, ".config", "luxos"), exist_ok=True)
        with open(os.path.join(self.home, ".config", "luxos", "screenshot.json"), "w") as f:
            json.dump(dict(o, version=2), f)

    def options(self):
        with open(os.path.join(self.home, ".config", "luxos", "screenshot.json")) as f:
            return json.load(f)

    def resident(self):
        """Server s pripravenymi okny jako v luxos-hub."""
        self.server = subprocess.Popen([os.path.join(BIN, "luxos-screenshot-ui")], env=dict(self.env, LUXOS_SCREENSHOT_RESIDENT="1"))
        time.sleep(1.2)

    def start(self, *args):
        p = subprocess.Popen([os.path.join(BIN, "luxos-screenshot"), *args], env=self.env, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True)
        self.procs.append(p)
        return p

    def run_cli(self, *args, timeout=20):
        return subprocess.run([os.path.join(BIN, "luxos-screenshot"), *args], env=self.env, capture_output=True,
                              text=True, timeout=timeout)

    def ui_log(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log) as f:
            return f.read().splitlines()

    def wait_for(self, cond, timeout=5.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if cond():
                return True
            time.sleep(0.03)
        return cond()

    def toolbar(self):
        lines = [ln for ln in self.ui_log() if ln.startswith("toolbar ")]
        return [int(v) for v in lines[-1].split()[1:5]] if lines else None

    def files(self, folder=None):
        folder = folder or self.out
        return sorted(os.path.join(folder, f) for f in os.listdir(folder)) if os.path.isdir(folder) else []

    # ---- lista a cesta pozadavku -----------------------------------------------------------
    def test_toolbar_from_server_is_instant_and_toggles(self):
        self.opts(mode="screen")
        self.resident()
        t0 = time.monotonic()
        p = self.start("--output", self.out)
        self.assertTrue(self.wait_for(lambda: any(w[1] and w[4] > 300 and w[5] < 80 for w in stacking()), 2))
        took = time.monotonic() - t0
        self.assertLess(took, 0.3, "toolbar from a running server must show at once")
        x, y, w, h = self.toolbar()
        self.assertLessEqual(abs(x + w / 2 - 640), 2)            # dole uprostred
        self.assertGreater(y, 400)
        self.assertIn("caption Capture Entire Screen||", self.ui_log())
        # znovu stejna zkratka listu zavre
        self.assertEqual(self.run_cli().returncode, 0)
        self.assertEqual(p.wait(5), 0)
        self.assertEqual(self.ui_log()[-1], "end")
        self.assertEqual(self.files(), [])

    def test_toolbar_leaves_keyboard_free_esc_and_enter(self):
        """Lista nezabira klavesnici; Esc ji zavre a Enter vyfoti globalne (jen tyto klavesy), pak Esc pusti."""
        self.opts(mode="screen")
        self.resident()
        self.assertTrue(esc_free())
        p = self.start("--output", self.out, "--no-thumbnail")
        self.assertTrue(self.wait_for(lambda: self.toolbar() is not None))
        # jiny program muze zabrat klavesnici (lista ji nedrzi), ale Esc drzi Snimek obrazovky
        code = ("import gi\ngi.require_version('Gtk', '3.0')\nfrom gi.repository import Gtk, Gdk\n"
                "w = Gtk.Window(); w.show_all()\nwhile Gtk.events_pending(): Gtk.main_iteration()\n"
                "s = Gdk.Display.get_default().get_default_seat()\n"
                "print(int(s.grab(w.get_window(), Gdk.SeatCapabilities.KEYBOARD, True, None, None, None, None)))\ns.ungrab()\n")
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=20)
        self.assertEqual(r.stdout.strip(), "0", r.stderr)       # GDK_GRAB_SUCCESS
        self.assertFalse(esc_free())
        xdo("key", "Return")
        self.assertEqual(p.wait(10), 0)
        files = self.files()
        self.assertEqual(len(files), 1)
        self.assertEqual(png_size(files[0]), (1280, 800))
        self.assertIn(files[0], p.stdout.read())
        self.assertTrue(esc_free())
        # Esc zavre listu
        p = self.start("--output", self.out)
        self.assertTrue(self.wait_for(lambda: len([ln for ln in self.ui_log() if ln.startswith("toolbar ")]) == 2))
        xdo("key", "Escape")
        self.assertEqual(p.wait(5), 0)
        self.assertEqual(len(self.files()), 1)
        self.assertTrue(esc_free())

    def test_caption_follows_pointer_and_ctrl(self):
        """Popisek nad listou: rezim a zkratka, pod mysi hned jiny rezim; Ctrl prepne Zachytit na Kopirovat."""
        shortcuts = os.path.join(self.home, ".config", "xfce4", "xfconf", "xfce-perchannel-xml")
        os.makedirs(shortcuts)
        shutil.copy(SHORTCUTS, shortcuts)
        self.opts(mode="screen")
        self.resident()
        self.start("--output", self.out)
        self.assertTrue(self.wait_for(lambda: self.toolbar() is not None))
        x, y, w, h = self.toolbar()
        self.assertIn("caption Capture Entire Screen|Super+Shift+3|", self.ui_log())
        for rel, want in ((234, "caption Capture Selected Portion|Super+Shift+4|"), (386, "caption Record Selected Portion||"),
                          (168, "caption Capture Selected Window||Click a window to capture it"), (28, "caption Close|Esc|"),
                          (490, "caption Save to: Screenshots||")):
            xdo("mousemove", x + rel, y + h // 2)
            self.assertTrue(self.wait_for(lambda: self.ui_log()[-1] == want, 1), (want, self.ui_log()[-3:]))
        xdo("mousemove", x + 596, y + h // 2)
        self.assertTrue(self.wait_for(lambda: self.ui_log()[-1].startswith("caption Capture Entire Screen|Enter|Hold Ctrl"), 1))
        # klik na rezim vyrez: zivy prekryv a volba se ulozi
        xdo("mousemove", x + 234, y + h // 2, "click", 1)
        self.assertTrue(self.wait_for(lambda: self.options()["mode"] == "portion"))
        self.assertTrue(self.wait_for(lambda: any(ln.startswith("overlay portion") for ln in self.ui_log())))
        xdo("mousemove", x + 320, y + h // 2, "click", 1)
        self.assertTrue(self.wait_for(lambda: "label Record" in self.ui_log()))

    def test_ctrl_enter_copies_portion(self):
        if not shutil.which("xclip"):
            self.skipTest("xclip missing")
        subprocess.run(["xclip", "-selection", "clipboard", "-i"], input=b"before", timeout=10)
        self.opts(mode="portion", selection=[100, 120, 77, 55])
        self.resident()
        p = self.start("--output", self.out, "--no-thumbnail")
        self.assertTrue(self.wait_for(lambda: self.toolbar() is not None))
        xdo("key", "ctrl+Return")
        self.assertEqual(p.wait(10), 0)
        self.assertEqual(self.files(), [])          # Ctrl: nic se neulozilo, jen schranka
        data = subprocess.run(["xclip", "-o", "-selection", "clipboard", "-t", "image/png"], capture_output=True,
                              timeout=10).stdout
        self.assertEqual((int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")), (77, 55))
        self.assertEqual(self.options()["selection"], [100, 120, 77, 55])

    def test_portion_from_toolbar_is_live(self):
        """S listou se obrazovka nezmrazi: vyrez bere zivou obrazovku bez ztmaveni prekryvem."""
        self.opts(mode="portion", selection=[100, 120, 200, 150])
        self.resident()
        p = self.start("--output", self.out, "--no-thumbnail")
        self.assertTrue(self.wait_for(lambda: self.toolbar() is not None))
        xdo("key", "Return")
        self.assertEqual(p.wait(10), 0)
        files = self.files()
        self.assertEqual(png_size(files[0]), (200, 150))
        self.assertEqual(pixel(files[0], 5, 5), BG)

    def test_countdown_and_esc_cancels(self):
        self.opts(mode="screen", timer=5)
        self.resident()
        p = self.start("--output", self.out)
        self.assertTrue(self.wait_for(lambda: self.toolbar() is not None))
        xdo("key", "Return")
        self.assertTrue(self.wait_for(lambda: "countdown 4" in self.ui_log(), 3), self.ui_log())
        self.assertFalse(esc_free())
        xdo("key", "Escape")
        self.assertEqual(p.wait(5), 0)
        time.sleep(1)
        self.assertEqual(self.files(), [])
        self.assertTrue(esc_free())

    def test_thumbnail_actions_esc_and_menu_delete(self):
        self.resident()
        p = self.start("--screen", "--output", self.out)
        self.assertTrue(self.wait_for(lambda: any(ln.startswith("thumb ") for ln in self.ui_log()), 5))
        thumb = [ln for ln in self.ui_log() if ln.startswith("thumb ")][-1]
        self.assertEqual(thumb.split()[1], "copy,reveal,save_as,delete,close")
        self.assertFalse(esc_free())
        xdo("key", "Escape")                    # Esc zavre nahled, soubor zustane
        self.assertEqual(p.wait(5), 0)
        self.assertEqual(len(self.files()), 1)
        self.assertTrue(esc_free())
        # nabidka pravym tlacitkem: Esc zavre jen nabidku, Smazat presune soubor do Kose
        p = self.start("--screen", "--output", self.out)
        self.assertTrue(self.wait_for(lambda: len([ln for ln in self.ui_log() if ln.startswith("thumb ")]) == 2, 5))
        tw, th = [int(v) for v in [ln for ln in self.ui_log() if ln.startswith("thumb ")][-1].split()[2:4]]
        tx, ty = 1280 - tw - 24, 800 - th - 96
        xdo("mousemove", tx + 60, ty + th // 2, "click", 3)
        time.sleep(0.5)
        xdo("key", "Escape")
        time.sleep(0.4)
        self.assertIsNone(p.poll())
        xdo("mousemove", tx + 60, ty + th // 2, "click", 3)
        time.sleep(0.5)
        xdo("key", "Down", "Down", "Down", "Down", "Down", "Return")       # Open, Copy, Show in Files, Save As, Delete
        self.assertEqual(p.wait(5), 0)
        self.assertEqual(len(self.files()), 1)
        trash = os.path.join(self.home, ".local", "share", "Trash", "files")
        self.assertEqual(len(os.listdir(trash)), 1)

    def thumb_menu(self, p, count, *keys):
        """Pravym tlacitkem nabidka nahledu (count-ty nahled v logu) a klavesy v ni."""
        self.assertTrue(self.wait_for(lambda: len([ln for ln in self.ui_log() if ln.startswith("thumb ")]) == count, 5))
        tw, th = [int(v) for v in [ln for ln in self.ui_log() if ln.startswith("thumb ")][-1].split()[2:4]]
        xdo("mousemove", 1280 - tw - 24 + 60, 800 - th - 96 + th // 2, "click", 3)
        time.sleep(0.5)
        xdo("key", *keys)

    def test_thumbnail_copy_save_as_and_timeout(self):
        if not shutil.which("xclip"):
            self.skipTest("xclip missing")
        self.resident()
        subprocess.run(["xclip", "-selection", "clipboard", "-i"], input=b"before", timeout=10)
        p = self.start("--portion", "--region", "10,10,64,48", "--output", self.out)
        self.thumb_menu(p, 1, "Down", "Down", "Return")              # Open, Copy
        time.sleep(0.5)
        data = subprocess.run(["xclip", "-o", "-selection", "clipboard", "-t", "image/png"], capture_output=True,
                              timeout=10).stdout
        self.assertEqual((int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")), (64, 48))
        self.assertIsNone(p.poll())                                  # nahled zustava
        # Ulozit jako: dialog, cesta s priponou .jpg = JPEG
        dest = os.path.join(self.home, "copy.jpg")
        self.thumb_menu(p, 1, "Down", "Down", "Down", "Down", "Return")
        time.sleep(1.5)
        xdo("key", "ctrl+a")
        xdo("type", dest)
        xdo("key", "Return")
        self.assertEqual(p.wait(10), 0)
        with open(dest, "rb") as f:
            self.assertEqual(f.read(3), b"\xff\xd8\xff")
        # bez akce se nahled sam zavre po 5 s (mys mimo nahled: najeti cas zastavi)
        xdo("mousemove", 600, 100)
        t0 = time.monotonic()
        p = self.start("--portion", "--region", "10,10,64,48", "--output", self.out)
        self.assertEqual(p.wait(12), 0)
        self.assertGreater(time.monotonic() - t0, 4.5)

    def test_thumbnail_drag_and_drop(self):
        """Nahled jde pretahnout do jine aplikace (URI souboru); pak se zavre."""
        got = os.path.join(self.home, "dropped.txt")
        target = subprocess.Popen([sys.executable, "-c", DROP_WINDOW, got], env=dict(os.environ, NO_AT_BRIDGE="1"))
        try:
            time.sleep(1.0)
            self.resident()
            p = self.start("--portion", "--region", "10,10,64,48", "--output", self.out)
            self.assertTrue(self.wait_for(lambda: any(ln.startswith("thumb ") for ln in self.ui_log()), 5))
            tw, th = [int(v) for v in [ln for ln in self.ui_log() if ln.startswith("thumb ")][-1].split()[2:4]]
            x, y = 1280 - tw - 24 + 40, 800 - th - 96 + th // 2
            xdo("mousemove", x, y, "mousedown", 1)
            for i in range(1, 11):
                xdo("mousemove", x - i * 40, y - i * 40)
                time.sleep(0.05)
            xdo("mousemove", 200, 200)
            time.sleep(0.3)
            xdo("mouseup", 1)
            self.assertEqual(p.wait(5), 0)
            self.assertTrue(self.wait_for(lambda: os.path.exists(got), 3))
            with open(got) as f:
                self.assertEqual(f.read().strip(), "file://" + self.files()[0].replace(" ", "%20"))
        finally:
            target.terminate()
            target.wait(5)

    def test_clipboard_option_shows_copied_thumbnail(self):
        self.opts(mode="screen", save_to="clipboard")
        self.resident()
        p = self.start("--screen")
        self.assertTrue(self.wait_for(lambda: any(ln.startswith("thumb ") for ln in self.ui_log()), 5))
        thumb = [ln for ln in self.ui_log() if ln.startswith("thumb ")][-1]
        self.assertEqual(thumb.split()[1], "save_as,close")
        self.run_cli("--close")
        self.assertEqual(p.wait(5), 0)

    def test_our_windows_stay_on_top(self):
        """Okno jineho programu namapovane nad listu (aktivace, nove okno) se hned dostane pod nase okna."""
        self.opts(mode="portion", selection=[100, 120, 200, 150])
        self.resident()
        self.start("--output", self.out)
        self.assertTrue(self.wait_for(lambda: self.toolbar() is not None))
        other = subprocess.Popen([sys.executable, "-c", OR_WINDOW], env=dict(os.environ, NO_AT_BRIDGE="1"))
        try:
            time.sleep(1.2)
            top = stacking()[-3:]
            sizes = [(w[4], w[5]) for w in top]
            self.assertNotIn((900, 300), sizes, top)       # cizi okno uz neni nahore
            self.assertIn((900, 300), [(w[4], w[5]) for w in stacking()])
        finally:
            other.terminate()
            other.wait(5)

    # ---- bez listy (zkratky) -----------------------------------------------------------------
    def test_quick_portion_drag_and_space_escape(self):
        p = self.start("--portion", "--output", self.out, "--no-thumbnail")
        self.assertTrue(self.wait_for(lambda: any(ln.startswith("overlay portion quick=True") for ln in self.ui_log())))
        time.sleep(0.3)
        xdo("mousemove", 300, 200, "mousedown", 1, "mousemove", 200, 150, "mousemove", 50, 60, "mouseup", 1)
        self.assertEqual(p.wait(10), 0)
        self.assertEqual(png_size(self.files()[0]), (250, 140))
        # mezernik = vyber okna, Esc nic neulozi
        p = self.start("--portion", "--output", self.out + "2")
        self.assertTrue(self.wait_for(lambda: len([ln for ln in self.ui_log() if ln.startswith("overlay")]) == 2))
        time.sleep(0.3)
        xdo("key", "space")
        time.sleep(0.2)
        xdo("key", "Escape")
        self.assertEqual(p.wait(5), 0)
        self.assertEqual(self.files(self.out + "2"), [])

    def test_cli_full_region_and_default_location(self):
        r = self.run_cli("--screen", "--output", self.out, "--no-thumbnail")
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.run_cli("--portion", "--region", "10,20,300,200", "--output", self.out, "--no-thumbnail")
        self.assertEqual(r.returncode, 0, r.stderr)
        sizes = sorted(png_size(f) for f in self.files())
        self.assertEqual(sizes, [(300, 200), (1280, 800)])
        self.assertIn(r.stdout.strip(), self.files())
        # cesky: Obrazky/Snimky obrazovky az pri ulozeni, Plocha ne
        self.env["LANG"] = "cs_CZ.UTF-8"
        r = self.run_cli("--portion", "--region", "1,2,30,20", "--no-thumbnail")
        self.assertEqual(r.returncode, 0, r.stderr)
        folder = os.path.join(self.home, "Pictures", "Snímky obrazovky")
        self.assertEqual([png_size(f) for f in self.files(folder)], [(30, 20)])
        self.assertTrue(os.path.basename(self.files(folder)[0]).startswith("Snímek obrazovky "))
        self.assertFalse(os.path.exists(os.path.join(self.home, "Desktop")))

    def test_old_desktop_setting_goes_to_screenshots(self):
        self.opts(save_to="desktop")
        with open(os.path.join(self.home, ".config", "luxos", "screenshot.json"), "w") as f:
            json.dump({"save_to": "desktop", "other_dir": "", "timer": 0, "pointer": False,
                       "remember": True, "selection": None, "mode": "portion"}, f)     # soubor z 0.9.10
        self.assertEqual(self.run_cli("--screen", "--no-thumbnail").returncode, 0)
        self.assertEqual(len(self.files(os.path.join(self.home, "Pictures", "Screenshots"))), 1)
        self.assertFalse(os.path.exists(os.path.join(self.home, "Desktop")))
        self.opts(save_to="desktop")
        self.assertEqual(self.run_cli("--screen", "--no-thumbnail").returncode, 0)
        self.assertEqual(len(self.files(os.path.join(self.home, "Desktop"))), 1)

    def test_pointer_option_adds_cursor(self):
        xdo("mousemove", 640, 400)
        self.opts(pointer=False)
        self.run_cli("--portion", "--region", "620,380,40,40", "--output", self.out + "/a", "--no-thumbnail")
        self.opts(pointer=True)
        self.run_cli("--portion", "--region", "620,380,40,40", "--output", self.out + "/b", "--no-thumbnail")
        a, b = self.files(self.out + "/a")[0], self.files(self.out + "/b")[0]
        self.assertEqual(png_size(a), png_size(b))
        self.assertEqual(pixel(a, 20, 20), BG)
        self.assertNotEqual(pixels(a), pixels(b))

    def test_clipboard_survives_exit(self):
        if not shutil.which("xclip"):
            self.skipTest("xclip missing")
        subprocess.run(["xclip", "-selection", "clipboard", "-i"], input=b"before", timeout=10)
        r = self.run_cli("--portion", "--region", "5,6,77,55", "--clipboard", "--no-thumbnail", timeout=15)
        self.assertEqual(r.returncode, 0, r.stderr)
        data = subprocess.run(["xclip", "-o", "-selection", "clipboard", "-t", "image/png"], capture_output=True,
                              timeout=10).stdout
        self.assertEqual((int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")), (77, 55))

    def test_record_and_stop(self):
        if not shutil.which("ffmpeg"):
            self.skipTest("ffmpeg missing")
        fmts = subprocess.run(["ffmpeg", "-hide_banner", "-devices"], capture_output=True, text=True).stdout
        if "x11grab" not in fmts:
            self.skipTest("ffmpeg without x11grab")
        p = self.start("--record-portion", "--region", "0,0,321,241", "--output", self.out, "--no-thumbnail")
        time.sleep(2.5)
        self.assertIsNone(p.poll())
        self.assertTrue(esc_free())                  # pri nahravani se Esc nezabira
        self.assertEqual(self.run_cli("--stop").returncode, 0)
        self.assertEqual(p.wait(20), 0)
        files = os.listdir(self.out)
        self.assertEqual(len(files), 1, files)
        self.assertTrue(files[0].startswith("Screen Recording ") and files[0].endswith(".mp4"))
        probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                "stream=width,height,codec_name", "-of", "csv=p=0", os.path.join(self.out, files[0])],
                               capture_output=True, text=True).stdout.strip()
        self.assertEqual(probe, "h264,320,240")
        # dalsi spusteni nahravani zastavi
        p = self.start("--record-screen", "--region", "0,0,200,100", "--output", self.out + "2", "--no-thumbnail")
        time.sleep(2)
        self.assertEqual(self.run_cli("--portion").returncode, 0)
        self.assertEqual(p.wait(20), 0)
        self.assertEqual(len([f for f in os.listdir(self.out + "2") if f.endswith(".mp4")]), 1)


BG = (40, 160, 90)
BG_WINDOW = ("import gi\ngi.require_version('Gtk', '3.0')\nfrom gi.repository import Gtk, Gdk\n"
             "w = Gtk.Window(); w.set_decorated(False); w.move(0, 0)\n"
             "r = Gdk.get_default_root_window(); w.set_default_size(r.get_width(), r.get_height())\n"
             "w.set_app_paintable(True)\n"
             "w.connect('draw', lambda _w, cr: (cr.set_source_rgb(40 / 255, 160 / 255, 90 / 255), cr.paint()) and False)\n"
             "w.show_all(); Gtk.main()\n")
DROP_WINDOW = ("import sys, gi\ngi.require_version('Gtk', '3.0')\nfrom gi.repository import Gtk, Gdk\n"
               "w = Gtk.Window(type=Gtk.WindowType.POPUP); w.set_default_size(400, 400); w.move(0, 0)\n"
               "w.drag_dest_set(Gtk.DestDefaults.ALL, [], Gdk.DragAction.COPY); w.drag_dest_add_uri_targets()\n"
               "def got(_w, _c, _x, _y, data, _i, _t):\n    open(sys.argv[1], 'w').write('\\n'.join(data.get_uris()))\n"
               "w.connect('drag-data-received', got)\nw.show_all(); Gtk.main()\n")
OR_WINDOW = ("import gi\ngi.require_version('Gtk', '3.0')\nfrom gi.repository import Gtk\n"
             "w = Gtk.Window(type=Gtk.WindowType.POPUP); w.set_default_size(900, 300); w.move(150, 450)\n"
             "w.show_all(); Gtk.main()\n")


def pixels(path):
    import gi
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf
    return bytes(GdkPixbuf.Pixbuf.new_from_file(path).get_pixels())


def pixel(path, x, y):
    import gi
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf
    pb = GdkPixbuf.Pixbuf.new_from_file(path)
    px = pb.get_pixels()
    off = y * pb.get_rowstride() + x * pb.get_n_channels()
    return tuple(px[off:off + 3])


if __name__ == "__main__":
    unittest.main()
