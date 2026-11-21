"""Material okna (sklo pod panelem Nastaveni): IPC set_window_material a luxcomp_view_set_material.

Spusteni (stavba libluxcomp + luxwm proti sysrootu harnessu, pak testy):
  scripts/wl-test/fetch-sysroot.sh && packages/luxwm/tests/build-host.sh
  scripts/wl-test/run-all packages/luxwm/tests/test_luxwm_window_material.py

Pod oknem material-probe (pruhledny panel vlevo, zbytek nepruhledny) je okno s cerno-bilymi pruhy 4 px.
Rozmazani se meri jako prumerny rozdil jasu sousednich pixelu v radku (ripple): ostre pruhy ~64, sklo < 3.
Pixman vzdy, gles2 jen s render node (/dev/dri/renderD128, WLT_RENDER_NODE jinak). Snimky:
out/luxwm-test/results/material-*.png
"""
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
WLT = os.path.join(ROOT, "scripts", "wl-test", "wlt")
BUILD = os.environ.get("LUXWM_BUILD", os.path.join(ROOT, "out", "luxwm-test", "build"))
WLT_OUT = os.environ.get("WLT_OUT") or os.path.join(ROOT, "out", "wl-test")
SYSROOT = os.path.join(WLT_OUT, "sysroot")
RESULTS = os.path.join(ROOT, "out", "luxwm-test", "results")
CONF = os.path.join(ROOT, "packages", "luxwm", "luxwm.conf")
MSG = os.path.join(BUILD, "luxwm-msg")
W, H = 1280, 800
TITLE = 30          # nizke zahlavi kompozitoru: cizi aplikace
SIDEBAR = 120       # material-probe: pruhledny pruh vlevo v geometrii 360x260
GEO = (360, 260)


def render_node():
    node = os.environ.get("WLT_RENDER_NODE", "/dev/dri/renderD128")
    return node if os.path.exists(node) and os.access(node, os.R_OK | os.W_OK) else ""


def ppm(path):
    data = open(path, "rb").read()
    _, size, _, pixels = data.split(b"\n", 3)
    width, height = map(int, size.split())
    return width, height, pixels


def pixel(image, x, y):
    width, _, pixels = image
    i = (y * width + x) * 3
    return tuple(pixels[i:i + 3])


def ripple(image, y, x0, x1):
    vals = [0.2126 * p[0] + 0.7152 * p[1] + 0.0722 * p[2] for p in (pixel(image, x, y) for x in range(x0, x1))]
    return sum(abs(vals[i + 1] - vals[i]) for i in range(len(vals) - 1)) / (len(vals) - 1)


class Session:
    def __init__(self, name, render=""):
        os.makedirs(RESULTS, exist_ok=True)
        self.conf = os.path.join(RESULTS, f"luxwm-{name}.conf")
        with open(CONF) as conf:
            lines = [line for line in conf.read().splitlines() if not line.startswith("displays_command")]
        with open(self.conf, "w") as f:
            f.write("xwayland = no\n" + "\n".join(lines) + "\n")
        envs = (f"LUXCOMP_VIRTUAL_INPUT=1 LUXWM_TRACE=1 LUXCOMP_STATS=1 LUXWM_SYSTEM_CONFIG={self.conf} "
                f"LD_LIBRARY_PATH={BUILD}:{SYSROOT}/usr/lib")
        env = {**os.environ, "WLT_COMPOSITOR_ENV": envs}
        env.pop("WLT_RENDER_NODE", None)
        if render:
            env["WLT_RENDER_NODE"] = render
        out = subprocess.run([WLT, "start", "--mode", "headless", "--size", f"{W}x{H}", "--name", name, "--",
                              os.path.join(BUILD, "luxwm")], check=True, capture_output=True, text=True, timeout=120,
                             env=env).stdout
        self.dir = out.strip().splitlines()[-1]
        with open(os.path.join(self.dir, "compositor.pid")) as f:
            top = int(f.read())
        kids = []
        for task in os.listdir(f"/proc/{top}/task"):
            with open(f"/proc/{top}/task/{task}/children") as f:
                kids += [int(p) for p in f.read().split()]
        self.pid = kids[0] if kids else top
        self.env = {}
        for line in subprocess.run([WLT, "env", self.dir], check=True, capture_output=True, text=True).stdout.splitlines():
            key, _, value = line.removeprefix("export ").partition("=")
            self.env[key] = value
        self.sock = os.path.join(self.env["XDG_RUNTIME_DIR"], "luxwm-wayland-0.sock")
        self.procs = []

    def stop(self):
        for p in self.procs:
            if p.poll() is None:
                p.kill()
                p.wait(5)
        subprocess.run([WLT, "stop", self.dir], capture_output=True)

    def log(self):
        with open(os.path.join(self.dir, "compositor.log"), errors="replace") as f:
            return f.read()

    def spawn(self, *cmd):
        p = subprocess.Popen([WLT, "run", self.dir, *cmd], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        self.procs.append(p)
        return p

    def views(self):
        """Okna z vypisu stavu luxwm (SIGUSR2): titulek -> {x, y, w, h, ...} (x, y = levy horni roh obsahu)"""
        before = self.log().count("luxwm: end")
        os.kill(self.pid, signal.SIGUSR2)
        for _ in range(50):
            text = self.log()
            if text.count("luxwm: end") > before:
                break
            time.sleep(0.05)
        views = {}
        for line in text[text.rfind("luxwm: workspace "):].splitlines():
            if line.startswith("luxwm: view "):
                fields = dict(f.split("=", 1) for f in line.split()[3:])
                views[fields["title"]] = {k: int(v) if re.fullmatch(r"-?\d+", v) else v for k, v in fields.items()}
        return views

    def shot(self, name):
        path = os.path.join(RESULTS, name)
        subprocess.run([WLT, "shot", self.dir, path], check=True, capture_output=True, timeout=30)
        return path

    def image(self, name):
        path = self.shot(name + ".ppm")
        subprocess.run([WLT, "shot", self.dir, os.path.join(RESULTS, name + ".png")], capture_output=True, timeout=30)
        return ppm(path)

    def input(self, *commands):
        subprocess.run([WLT, "input", self.dir, *commands], check=True, capture_output=True, timeout=60)
        time.sleep(0.4)

    def msg(self, *args):
        return subprocess.run([MSG, *args], env=self.env, capture_output=True, text=True, timeout=20)


class Probe:
    """material-probe glass: okno a spojeni IPC ve stejnem procesu"""

    def __init__(self, session, *args):
        self.p = session.spawn(PROBE, "glass", APP, *args)

    def line(self, prefix, timeout=10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            line = self.p.stdout.readline()
            if not line:
                break
            if line.startswith(prefix):
                return line[len(prefix):].strip()
        raise AssertionError(f"material-probe: no {prefix!r}")

    def send(self, text):
        self.p.stdin.write(text + "\n")
        self.p.stdin.flush()

    def request(self, **fields):
        self.send(json.dumps({"cmd": "set_window_material", "app_id": APP, "material": "popup", "radius": 0, **fields}))
        return json.loads(self.line("reply "))


APP = "glass-test"
PROBE = ""


def build_probe():
    global PROBE
    if PROBE:
        return
    os.makedirs(RESULTS, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="material-", dir=RESULTS)
    protocols = os.path.join(SYSROOT, "usr/share/wayland-protocols")
    scanner = os.path.join(SYSROOT, "usr/bin/wayland-scanner")
    env = {**os.environ, "LD_LIBRARY_PATH": os.path.join(SYSROOT, "usr/lib")}
    code = []
    for xml in ("staging/security-context/security-context-v1.xml", "stable/xdg-shell/xdg-shell.xml"):
        base = os.path.basename(xml)[:-4]
        subprocess.run([scanner, "client-header", os.path.join(protocols, xml),
                        os.path.join(tmp, base + "-client-protocol.h")], check=True, env=env)
        code.append(os.path.join(tmp, base + ".c"))
        subprocess.run([scanner, "private-code", os.path.join(protocols, xml), code[-1]], check=True, env=env)
    PROBE = os.path.join(tmp, "material-probe")
    subprocess.run(["gcc", "-O1", "-Wall", "-I", tmp, "-o", PROBE, os.path.join(HERE, "material-probe.c"),
                    *code, "-lwayland-client"], check=True)


@unittest.skipUnless(os.path.exists(os.path.join(BUILD, "luxwm")) and os.path.exists(MSG),
                     "build first: packages/luxwm/tests/build-host.sh")
class Base:
    render = ""
    label = "pixman"

    @classmethod
    def setUpClass(cls):
        build_probe()

    def setUp(self):
        self.s = Session(f"mat{os.getpid() % 10000}-{self.label}-{self._testMethodName[5:14]}", self.render)
        self.addCleanup(self.s.stop)
        # pozadi: pruhy pres skoro celou obrazovku, material-probe nad nimi
        stripes = self.s.spawn(PROBE, "stripes", "1200", "700")
        self.assertEqual(stripes.stdout.readline().strip(), "mapped")
        time.sleep(0.5)

    def tearDown(self):
        log = self.s.log()
        self.assertNotIn("error in", log)
        self.assertNotIn("LSL callback error", log)
        self.assertNotIn("blur failed", log)

    def glass(self, *args):
        probe = Probe(self.s, *args)
        if "--late" not in args:
            self.assertEqual(probe.line(""), "mapped")
            time.sleep(0.6)
        return probe

    def sidebar(self, image, view):
        """ripple radku uprostred panelu (bez okraju 8 px, kde se mohou michat sousedni oblasti)"""
        return ripple(image, view["y"] + GEO[1] // 2, view["x"] + 8, view["x"] + SIDEBAR - 8)

    def test_material_under_sidebar(self):
        probe = self.glass()
        view = self.s.views()["glass"]
        self.assertEqual((view["w"], view["h"]), GEO)
        sharp = self.sidebar(self.s.image(f"material-{self.label}-before"), view)
        self.assertGreater(sharp, 30)
        self.assertEqual(probe.request(x=0, y=0, w=SIDEBAR, h=GEO[1], id=7), {"ok": True, "id": 7})
        time.sleep(0.5)
        img = self.s.image(f"material-{self.label}-on")
        blurred = self.sidebar(img, view)
        print(f"\n{self.label}: ripple sharp {sharp:.1f}, glass {blurred:.2f}", flush=True)
        self.assertLess(blurred, 3)
        # sklo je jen pod panelem: nepruhledna cast okna zustava, jak ji klient nakreslil
        self.assertEqual(pixel(img, view["x"] + 200, view["y"] + 130), (0x80, 0x80, 0xa0))
        # pozadi skla je sede (prumer pruhu), ne barva nahradni nepruhledne vyplne
        r, g, b = pixel(img, view["x"] + SIDEBAR // 2, view["y"] + 130)
        self.assertTrue(90 < r < 170 and abs(r - g) < 12 and abs(g - b) < 12, (r, g, b))
        # rohy okna (CSD: vsechny zaoblene) material zaobli s nim, vnitrni rohy panelu ne
        for x, y in ((1, 1), (1, GEO[1] - 2)):
            self.assertGreater(abs(pixel(img, view["x"] + x, view["y"] + y)[0] - r), 25, (x, y))
        for x, y in ((SIDEBAR - 2, 1), (SIDEBAR - 2, GEO[1] - 2)):
            self.assertLess(abs(pixel(img, view["x"] + x, view["y"] + y)[0] - r), 12, (x, y))
        # mimo geometrii okna (pruhledny okraj klienta) material neni, i kdyz obdelnik pretece
        self.assertEqual(probe.request(x=-50, y=-50, w=5000, h=5000), {"ok": True})
        time.sleep(0.5)
        img = self.s.image(f"material-{self.label}-clip")
        self.assertLess(ripple(img, view["y"] + 130, view["x"] + 8, view["x"] + SIDEBAR - 8), 3)
        self.assertGreater(ripple(img, view["y"] + 130, view["x"] - 18, view["x"] - 2), 10)
        self.assertGreater(ripple(img, view["y"] + GEO[1] + 6, view["x"] + 8, view["x"] + SIDEBAR - 8), 10)
        # w = 0 material zrusi
        self.assertEqual(probe.request(x=0, y=0, w=0, h=0), {"ok": True})
        time.sleep(0.5)
        self.assertGreater(self.sidebar(self.s.image(f"material-{self.label}-off"), view), 30)

    def test_follows_move_and_workspace(self):
        probe = self.glass()
        view = self.s.views()["glass"]
        self.assertEqual(probe.request(x=0, y=0, w=SIDEBAR, h=GEO[1]), {"ok": True})
        # presun tazenim (material-probe zacne presun jako zahlavi CSD)
        x, y = view["x"] + 240, view["y"] + 100
        self.s.input(f"drag {x} {y} {x + 180} {y + 70} 400")
        time.sleep(0.5)
        moved = self.s.views()["glass"]
        self.assertNotEqual((moved["x"], moved["y"]), (view["x"], view["y"]))
        img = self.s.image(f"material-{self.label}-moved")
        self.assertLess(self.sidebar(img, moved), 3)
        # stare misto panelu ukazuje zase ostre pruhy (cast, kterou okno uz nezakryva)
        old = ripple(img, view["y"] + 130, view["x"] + 8, min(view["x"] + SIDEBAR - 8, moved["x"] - 2))
        self.assertGreater(old, 10)
        # jina plocha: material odjede s oknem a s nim se vrati
        probe.send(json.dumps({"cmd": "switch_workspace", "number": 2}))
        self.assertTrue(json.loads(probe.line("reply "))["ok"])
        time.sleep(0.8)
        img = self.s.image(f"material-{self.label}-ws2")
        self.assertEqual(pixel(img, moved["x"] + SIDEBAR // 2, moved["y"] + 130), pixel(img, 2, H - 3))
        probe.send(json.dumps({"cmd": "switch_workspace", "number": 1}))
        self.assertTrue(json.loads(probe.line("reply "))["ok"])
        time.sleep(0.8)
        self.assertLess(self.sidebar(self.s.image(f"material-{self.label}-ws1"), moved), 3)

    def test_only_own_windows(self):
        probe = self.glass()
        view = self.s.views()["glass"]
        # jiny proces (tento test) okno se stejnym app_id nedostane
        raw = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        raw.settimeout(5)
        raw.connect(self.s.sock)
        raw.sendall(json.dumps({"cmd": "set_window_material", "app_id": APP, "material": "popup",
                                "x": 0, "y": 0, "w": SIDEBAR, "h": GEO[1]}).encode() + b"\n")
        self.assertEqual(json.loads(raw.recv(4096).split(b"\n")[0]), {"ok": False, "error": "no such window"})
        raw.close()
        # cizi app_id ani spatne pozadavky ne
        self.assertEqual(probe.request(app_id="luxos-other", x=0, y=0, w=SIDEBAR, h=GEO[1]),
                         {"ok": False, "error": "no such window"})
        self.assertEqual(probe.request(material="nonsense", x=0, y=0, w=SIDEBAR, h=GEO[1]),
                         {"ok": False, "error": "unknown material"})
        self.assertEqual(probe.request(x="0", y=0, w=SIDEBAR, h=GEO[1]), {"ok": False, "error": "bad request"})
        self.assertEqual(probe.request(radius=8, x=0, y=0, w=SIDEBAR, h=GEO[1]), {"ok": False, "error": "bad request"})
        time.sleep(0.3)
        self.assertGreater(self.sidebar(self.s.image(f"material-{self.label}-foreign"), view), 30)
        # okno ze sandboxu nikdy, ani kdyz o nej pozada vlastni proces
        sandboxed = self.glass("--sandbox")
        self.assertEqual(sandboxed.request(x=0, y=0, w=SIDEBAR, h=GEO[1]), {"ok": False, "error": "no such window"})
        self.s.views()
        self.assertIn("sandbox=org.luxos.material", self.s.log())

    def test_lifetime(self):
        # pozadavek pred namapovanim: odpoved ne, material se ale da pri namapovani
        probe = self.glass("--late")
        time.sleep(0.3)
        self.assertEqual(probe.request(x=0, y=0, w=SIDEBAR, h=GEO[1]), {"ok": False, "error": "no such window"})
        probe.send("map")
        self.assertEqual(probe.line(""), "mapped")
        time.sleep(0.8)
        view = self.s.views()["glass"]
        self.assertLess(self.sidebar(self.s.image(f"material-{self.label}-late"), view), 3)
        # konec spojeni IPC material zrusi (klient bez spojeni kresli panel nepruhledne)
        probe.send("disconnect")
        self.assertEqual(probe.line(""), "disconnected")
        time.sleep(0.6)
        self.assertGreater(self.sidebar(self.s.image(f"material-{self.label}-disconnected"), view), 30)
        # blur = no: odpoved ne (klient zustane nepruhledny)
        again = self.glass()
        os.makedirs(os.path.join(self.s.env["XDG_CONFIG_HOME"], "luxwm"), exist_ok=True)
        with open(os.path.join(self.s.env["XDG_CONFIG_HOME"], "luxwm", "luxwm.conf"), "w") as f:
            f.write("blur = no\n")
        self.assertEqual(self.s.msg("reload").returncode, 0)
        self.assertEqual(again.request(x=0, y=0, w=SIDEBAR, h=GEO[1]), {"ok": False, "error": "blur off"})


class Pixman(Base, unittest.TestCase):
    def test_pixman_cost(self):
        """Prepocet skla pri tazeni okna pod pixman: cas snimku z LUXCOMP_STATS"""
        probe = self.glass()
        view = self.s.views()["glass"]
        self.assertEqual(probe.request(x=0, y=0, w=SIDEBAR, h=GEO[1]), {"ok": True})
        x, y = view["x"] + 240, view["y"] + 100
        # ~2,5 s tazeni (krok 8 ms), tam a zpet
        self.s.input(f"drag {x} {y} {x + 300} {y + 150} 1200", f"drag {x + 300} {y + 150} {x} {y} 1200")
        time.sleep(0.5)
        stats = re.findall(r"blur stats tier (\d) frames (\d+) max ([\d.]+) ms avg ([\d.]+) ms over 8 ms (\d+), "
                           r"updates (\d+) max ([\d.]+) ms avg ([\d.]+) ms", self.s.log())
        print("\npixman blur stats: " + "; ".join(" ".join(s) for s in stats), flush=True)
        self.assertTrue(stats)
        self.assertNotIn("solid material from now on", self.s.log())


@unittest.skipUnless(render_node(), "no GPU render node")
class Gles2(Base, unittest.TestCase):
    render = render_node()
    label = "gles2"


DESIGN = os.path.join(os.path.dirname(ROOT) if os.path.basename(os.path.dirname(ROOT)) == "out" else
                      os.path.join(ROOT, "out"), "design", "settings")


@unittest.skipUnless(os.path.exists(os.path.join(BUILD, "luxwm")) and shutil.which("lslc"),
                     "build first: packages/luxwm/tests/build-host.sh; lslc")
class SettingsGlass(unittest.TestCase):
    """Skutecny luxos-settings: panel pozada o sklo, luxwm odpovi ok, panel je pruhledny a pod nim rozmazano"""

    @classmethod
    def setUpClass(cls):
        import sys
        sys.path.insert(0, os.path.join(ROOT, "packages", "luxos-desktop", "tests"))
        import lsl_app
        cls.lsl_app = lsl_app
        build_probe()
        cls.tmp = tempfile.mkdtemp(prefix="settings-glass-", dir=RESULTS)
        cls.binary = lsl_app.build("luxos-settings", cls.tmp)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, True)

    def settings(self, s):
        env = {k: v for k, v in s.env.items() if k not in ("LD_LIBRARY_PATH", "PATH", "HOME")}
        env = dict(os.environ, **env, GDK_BACKEND="wayland", GTK_A11Y="none")
        env.pop("DISPLAY", None)
        env.pop("GTK_THEME", None)
        app = self.lsl_app.App([self.binary, "desktop"], env)
        self.addCleanup(app.stop)
        self.assertTrue(app.wait(lambda: app.dump(), 20), app.stderr())
        return app

    def state(self, app):
        return json.loads(app.ask("state", "state "))

    def test_settings_sidebar_glass(self):
        s = Session(f"mat{os.getpid() % 10000}-settings")
        self.addCleanup(s.stop)
        stripes = s.spawn(PROBE, "stripes", "1200", "700")
        self.assertEqual(stripes.stdout.readline().strip(), "mapped")
        time.sleep(0.4)
        app = self.settings(s)
        self.assertTrue(app.wait(lambda: self.state(app)["glass"], 10), self.state(app))
        st = self.state(app)
        x, y, w, h = st["region"]
        view = next(v for v in s.views().values() if v["app"] == "luxos-settings")
        # panel zacina pod HeaderBar u leveho okraje geometrie okna a siaha k jejimu spodku
        self.assertEqual((x, w >= 200, y > 20, y + h), (0, True, True, view["h"]), (st, view))
        time.sleep(0.8)
        img = s.image("material-settings-stripes")
        # levy okraj panelu (pred radky seznamu, okraj 10 px): pruhy pod sklem zmizi
        sx, sy = view["x"] + x, view["y"] + y
        rows = [sy + h // 3, sy + h // 2, sy + 2 * h // 3]
        glass = max(ripple(img, r, sx + 1, sx + 9) for r in rows)
        # kontrola: stejny pruh tesne vlevo od okna ukazuje ostre pruhy
        sharp = ripple(img, sy + h // 2, sx - 30, sx - 22)
        print(f"\nluxos-settings sidebar: ripple glass {glass:.2f}, outside {sharp:.1f}", flush=True)
        self.assertLess(glass, 3)
        self.assertGreater(sharp, 20)
        # obsah stranky vpravo zustava nepruhledny (zadne pruhy)
        cx = sx + w + 8
        self.assertLess(max(ripple(img, r, cx, cx + 8) for r in rows), 1)
        # snimky pro navrh: barevne pozadi, svetly a tmavy vzhled
        stripes.kill()
        colors = s.spawn(PROBE, "colors", "1200", "700")
        self.assertEqual(colors.stdout.readline().strip(), "mapped")
        time.sleep(0.4)
        app.ask("page desktop")
        os.makedirs(DESIGN, exist_ok=True)
        for theme in ("light", "dark"):
            os.makedirs(os.path.join(s.env["XDG_CONFIG_HOME"], "luxos"), exist_ok=True)
            with open(os.path.join(s.env["XDG_CONFIG_HOME"], "luxos", "appearance"), "w") as f:
                f.write(theme + "\n")
            raw = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            raw.connect(s.sock)
            raw.sendall(json.dumps({"cmd": "set_theme", "theme": theme}).encode() + b"\n")
            raw.recv(4096)
            raw.close()
            self.assertTrue(app.wait(lambda: self.state(app)["dark"] == (theme == "dark"), 10))
            # okno Nastaveni dopredu (prekryva ho barevne okno, ktere se prave otevrelo)
            s.input(f"move {view['x'] + view['w'] - 40} {view['y'] + 10}", "click")
            time.sleep(1.0)
            self.assertTrue(self.state(app)["glass"])
            path = s.shot(f"material-settings-{theme}.png")
            shutil.copy(path, os.path.join(DESIGN, f"glass-{theme}.png"))

if __name__ == "__main__":
    unittest.main()
