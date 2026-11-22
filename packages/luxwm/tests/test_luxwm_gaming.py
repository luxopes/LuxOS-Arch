"""Hry v luxwm (headless pixman, volitelne GPU render node): globaly protokolu pro hry, zamceny a omezeny ukazatel
s relativnim pohybem (Wayland i hra pod XWayland), keyboard-shortcuts-inhibit s unikem Super+Esc, tearing jen na cele
obrazovce, primy scanout celoobrazovkoveho okna (bez zahlavi, stinu, rohu a materialu nad nim) a necinnost pod
celoobrazovkovou hrou. Klienti: clients/game-probe.c, clients/x11-mouselook.c.

  packages/luxwm/tests/build-host.sh
  scripts/wl-test/isolate python3 -m unittest -v packages/luxwm/tests/test_luxwm_gaming.py
GPU (dmabuf s feedbackem, linux-drm-syncobj, PRIME offload, vnoreny gamescope): GAMING_RENDER_NODE=/dev/dri/renderD128
(jen render node, nikdy card*); gamescope z packages/luxwm/tests/fetch-gamescope.sh (out/gamescope/root).
"""
import os
import re
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(__file__))
from test_luxwm import BUILD, ROOT, SYSROOT, WLT, Session, children, test_conf  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
XWAYLAND = os.path.join(SYSROOT, "usr/bin/Xwayland")
GAMESCOPE = os.environ.get("GAMESCOPE_ROOT", os.path.join(ROOT, "out/gamescope/root"))
PROTOCOLS = ["stable/xdg-shell/xdg-shell.xml", "unstable/pointer-constraints/pointer-constraints-unstable-v1.xml",
             "unstable/relative-pointer/relative-pointer-unstable-v1.xml",
             "unstable/keyboard-shortcuts-inhibit/keyboard-shortcuts-inhibit-unstable-v1.xml",
             "staging/tearing-control/tearing-control-v1.xml", "staging/content-type/content-type-v1.xml",
             "staging/ext-idle-notify/ext-idle-notify-v1.xml"]
KEY_TAB, KEY_ESC = 15, 1


class Probe:
    """Klient ve vlastnim procesu, radky jeho vystupu v self.lines"""

    def __init__(self, test, s, *cmd):
        self.test = test
        self.p = subprocess.Popen([WLT, "run", s.dir, *cmd], stdout=subprocess.PIPE)
        test.addCleanup(lambda: (self.p.poll() is None and self.p.terminate(), self.p.wait(5)))
        self.buf = b""
        self.lines = []

    def read(self, timeout):
        if select.select([self.p.stdout], [], [], max(0.0, timeout))[0]:
            chunk = os.read(self.p.stdout.fileno(), 65536)
            if not chunk:
                return False
            self.buf += chunk
            while b"\n" in self.buf:
                line, self.buf = self.buf.split(b"\n", 1)
                self.lines.append(line.decode())
        return True

    def wait(self, line, timeout=10):
        end = time.monotonic() + timeout
        while line not in self.lines:
            left = end - time.monotonic()
            self.test.assertGreater(left, 0, f"no {line!r}: {self.lines[-30:]}")
            self.test.assertTrue(self.read(left), f"probe quit before {line!r}: {self.lines[-30:]}")

    def drain(self, seconds=0.3):
        end = time.monotonic() + seconds
        while (left := end - time.monotonic()) > 0 and self.read(left):
            pass

    def since(self, mark):
        return self.lines[mark:]


def kill_tree(pid):
    """wlt run -> env -> timeout -> klient: SIGTERM celemu stromu (timeout signal klientovi nepreda)"""
    for kid in children(pid):
        kill_tree(kid)
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass


def outputs(s):
    """Vystupy z posledniho vypisu stavu: {jmeno: {pole: hodnota}}"""
    s.state()
    text = s.log()
    block = text[text.rfind("luxwm: workspace "):]
    result = {}
    for line in block.splitlines():
        if line.startswith("luxwm: output "):
            parts = line.split()
            result[parts[3]] = {k: int(v) for k, v in (f.split("=", 1) for f in parts[5:] if "=" in f)
                                if re.fullmatch(r"-?\d+", v)}
        elif line.startswith("luxwm: workspace "):
            result["_"] = {k: int(v) for k, v in (f.split("=", 1) for f in line.split()[3:] if "=" in f)
                           if re.fullmatch(r"-?\d+", v)}
    return result


def output0(s):
    return [v for k, v in outputs(s).items() if k != "_"][0]


def seat(s):
    return outputs(s)["_"]


@unittest.skipUnless(os.path.exists(os.path.join(BUILD, "luxwm")) and shutil.which("gcc"),
                     "build first: packages/luxwm/tests/build-host.sh")
class Gaming(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="luxwm-gaming-", dir=os.path.join(ROOT, "out"))
        scanner = os.path.join(SYSROOT, "usr/bin/wayland-scanner")
        env = {**os.environ, "LD_LIBRARY_PATH": os.path.join(SYSROOT, "usr/lib")}
        xmls = [os.path.join(SYSROOT, "usr/share/wayland-protocols", x) for x in PROTOCOLS]
        xmls.append(os.path.join(ROOT, "scripts/wl-test/protocol/wlr-virtual-pointer-unstable-v1.xml"))
        code = []
        for xml in xmls:
            base = os.path.basename(xml)[:-4]
            subprocess.run([scanner, "client-header", xml, os.path.join(cls.tmp, base + "-client-protocol.h")],
                           check=True, env=env)
            code.append(os.path.join(cls.tmp, base + ".c"))
            subprocess.run([scanner, "private-code", xml, code[-1]], check=True, env=env)
        cls.probe = os.path.join(cls.tmp, "game-probe")
        subprocess.run(["gcc", "-O1", "-Wall", "-I", cls.tmp, "-o", cls.probe,
                        os.path.join(HERE, "clients/game-probe.c"), *code, "-lwayland-client", "-lm"], check=True)
        cls.eglprobe = None
        if os.path.exists("/usr/include/EGL/egl.h") and os.path.exists("/usr/lib/libwayland-egl.so"):
            cls.eglprobe = os.path.join(cls.tmp, "egl-probe")
            subprocess.run(["gcc", "-O1", "-Wall", "-I", cls.tmp, "-o", cls.eglprobe,
                            os.path.join(HERE, "clients/egl-probe.c"), os.path.join(cls.tmp, "xdg-shell.c"),
                            "-lwayland-client", "-lwayland-egl", "-lEGL"], check=True)
        cls.xprobe = None
        if os.path.exists(XWAYLAND) and os.path.exists("/usr/include/X11/extensions/Xfixes.h"):
            cls.xprobe = os.path.join(cls.tmp, "x11-mouselook")
            subprocess.run(["gcc", "-O1", "-Wall", "-o", cls.xprobe, os.path.join(HERE, "clients/x11-mouselook.c"),
                            "-lX11", "-lXfixes"], check=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, True)

    def session(self, env="", **kw):
        s = Session(env=env, **kw)
        self.addCleanup(s.stop)
        self.addCleanup(lambda: self.assertNotIn("error in", s.log()))
        return s

    def game(self, s, *args, title="game"):
        p = Probe(self, s, self.probe, "--title", title, *args)
        p.wait("ready")
        p.wait("kbfocus 1")
        return p

    def view(self, s, title):
        for _ in range(50):
            v = s.state()["views"].get(title)
            if v and v["w"] > 0:
                return v
            time.sleep(0.1)
        self.fail(f"no view {title}")

    def center(self, s, title):
        v = self.view(s, title)
        return v["x"] + v["w"] // 2, v["y"] + v["h"] // 2

    def inject(self, s, dx, dy, n):
        out = subprocess.run([WLT, "run", s.dir, self.probe, "--inject", str(dx), str(dy), str(n)],
                             capture_output=True, text=True, timeout=60).stdout
        self.assertIn("injected", out)
        time.sleep(0.2)

    # ---- globaly ----

    def globals_of(self, s):
        out = subprocess.run([WLT, "run", s.dir, self.probe, "--globals"], capture_output=True, text=True,
                             timeout=30).stdout
        return {line.split()[1]: int(line.split()[2]) for line in out.splitlines() if line.startswith("global ")}

    def test_globals_pixman(self):
        g = self.globals_of(self.session())
        for name in ("zwp_pointer_constraints_v1", "zwp_relative_pointer_manager_v1",
                     "zwp_keyboard_shortcuts_inhibit_manager_v1", "wp_tearing_control_manager_v1",
                     "wp_content_type_manager_v1", "zwlr_gamma_control_manager_v1"):
            self.assertIn(name, g)
        # pixman bez DRM zarizeni: zadny dmabuf ani syncobj; headless: nic k pronajmu
        for name in ("zwp_linux_dmabuf_v1", "wp_linux_drm_syncobj_manager_v1", "wp_drm_lease_device_v1"):
            self.assertNotIn(name, g)
        print(f"\n  globals pixman: {len(g)}", file=sys.stderr)

    @unittest.skipUnless(os.environ.get("GAMING_RENDER_NODE", "").startswith("/dev/dri/renderD")
                         and os.access(os.environ.get("GAMING_RENDER_NODE", "/nonexistent"), os.R_OK | os.W_OK),
                         "GAMING_RENDER_NODE=/dev/dri/renderD12x for the GPU part")
    def test_globals_gpu_dmabuf_syncobj(self):
        s = self.gpu_session()
        self.assertIn("renderer gles2", s.log())
        g = self.globals_of(s)
        self.assertEqual(g.get("zwp_linux_dmabuf_v1"), 5)
        self.assertIn("wp_linux_drm_syncobj_manager_v1", g)
        # celoobrazovkova hra na GPU: scanout a dmabuf feedback sceny
        game = self.game(s, "--fullscreen")
        game.wait("configure 1280 800 1")
        x, y = 640, 400
        s.input(f"move {x} {y}")
        time.sleep(0.3)
        o = output0(s)
        self.assertEqual(o["scanout"], 1, o)
        print(f"\n  gpu: {[l for l in s.log().splitlines() if 'renderer' in l][:1]} dmabuf v5 syncobj scanout=1",
              file=sys.stderr)

    def gpu_session(self):
        os.environ["WLT_RENDER_NODE"] = os.environ["GAMING_RENDER_NODE"]
        try:
            return self.session()
        finally:
            del os.environ["WLT_RENDER_NODE"]

    @unittest.skipUnless(os.environ.get("GAMING_RENDER_NODE", "").startswith("/dev/dri/renderD")
                         and os.path.exists("/usr/share/glvnd/egl_vendor.d/10_nvidia.json")
                         and os.path.exists("/usr/include/EGL/egl.h"),
                         "GAMING_RENDER_NODE (compositor GPU) and the NVIDIA EGL vendor for PRIME offload")
    def test_prime_offload_egl_client(self):
        """Hybridni AMD+NVIDIA: kompozitor na GPU z GAMING_RENDER_NODE, klient vykresli na NVIDIA (prime-run)"""
        s = self.gpu_session()
        results = {}
        for name, env, color in (("default", [], "20c040"),
                                 ("offload", ["__NV_PRIME_RENDER_OFFLOAD=1", "__GLX_VENDOR_LIBRARY_NAME=nvidia",
                                              "__EGL_VENDOR_LIBRARY_FILENAMES=/usr/share/glvnd/egl_vendor.d/10_nvidia.json"],
                                  "c02060")):
            p = Probe(self, s, "env", "-u", "LD_LIBRARY_PATH", *env, self.eglprobe, "--color", color)
            p.wait("frames 30", 30)
            renderer = [l for l in p.lines if l.startswith("renderer ")][0][9:]
            time.sleep(0.3)
            x, y = self.center(s, "egl")
            s.input(f"move {x + 100} {y + 100}")
            px = s.pixel(x, y)
            want = tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))
            self.assertTrue(all(abs(a - b) <= 4 for a, b in zip(px, want)), f"{name}: {px} != {want}")
            results[name] = renderer
            kill_tree(p.p.pid)
            p.p.wait(5)
            time.sleep(0.3)
        # bez offloadu klient kresli na GPU kompozitoru (main_device z dmabuf feedbacku)
        compositor = s.log().split("renderer gles2 on ")[1].splitlines()[0]
        self.assertEqual("NVIDIA" in results["default"], "NVIDIA" in compositor, (results, compositor))
        self.assertIn("NVIDIA", results["offload"])
        print(f"\n  prime: compositor {os.environ['GAMING_RENDER_NODE']}, client default {results['default']!r}, "
              f"offload {results['offload']!r}", file=sys.stderr)

    @unittest.skipUnless(os.environ.get("GAMING_RENDER_NODE", "").startswith("/dev/dri/renderD")
                         and os.path.exists(os.path.join(GAMESCOPE, "usr/bin/gamescope")) and os.path.exists(XWAYLAND),
                         "GAMING_RENDER_NODE and gamescope (packages/luxwm/tests/fetch-gamescope.sh)")
    def test_gamescope_nested(self):
        """gamescope --backend wayland jako okno luxwm (Vulkan na GPU kompozitoru, dmabuf), uvnitr X11 klient"""
        s = self.gpu_session()
        env = ["env", f"LD_LIBRARY_PATH={GAMESCOPE}/usr/lib:{SYSROOT}/usr/lib",
               f"PATH={GAMESCOPE}/usr/bin:{SYSROOT}/usr/bin:/usr/bin", f"WLR_XWAYLAND={XWAYLAND}"]
        size = ["-W", "800", "-H", "600", "-w", "800", "-h", "600"]
        g = Probe(self, s, *env, os.path.join(GAMESCOPE, "usr/bin/gamescope"), "--backend", "wayland", *size,
                  "--", os.path.join(SYSROOT, "usr/bin/xeyes"))
        v = None
        for _ in range(100):
            v = s.state()["views"].get("xeyes")
            if v:
                break
            time.sleep(0.1)
        self.assertIsNotNone(v, "no gamescope window")
        self.assertEqual((v["app"], v["w"], v["h"], v["x11"]), ("gamescope", 800, 600, 0))
        time.sleep(1.0)
        s.input("move 5 5")
        s.shot("gaming-gamescope-nested.png")
        # xeyes: bila oci na cernem pozadi, obraz prochazi z vnitrniho Xwayland pres gamescope az do luxwm
        self.assertEqual(s.pixel(v["x"] + 5, v["y"] + 5), (0, 0, 0))
        self.assertEqual(s.pixel(v["x"] + 200, v["y"] + 300), (255, 255, 255))
        kill_tree(g.p.pid)
        g.p.wait(5)
        # gamescope -f: cela obrazovka luxwm a primy scanout jeho bufferu
        g = Probe(self, s, *env, os.path.join(GAMESCOPE, "usr/bin/gamescope"), "--backend", "wayland", *size, "-f",
                  "--", os.path.join(SYSROOT, "usr/bin/xeyes"))
        for _ in range(100):
            v = s.state()["views"].get("xeyes")
            if v and v["fullscreen"] == 1 and v["w"] == 1280:
                break
            time.sleep(0.1)
        self.assertEqual((v["w"], v["h"], v["fullscreen"]), (1280, 800, 1))
        time.sleep(1.0)
        s.input("move 640 400", "move 641 401")
        o = output0(s)
        s.shot("gaming-gamescope-fullscreen.png")
        print(f"\n  gamescope: nested 800x600 shown, fullscreen 1280x800 scanout={o['scanout']}", file=sys.stderr)

    # ---- ukazatel ----

    def test_pointer_lock_relative_motion(self):
        s = self.session()
        game = self.game(s, "--lock")
        x, y = self.center(s, "game")
        s.input(f"move {x} {y}")
        game.wait("locked")
        self.assertEqual(seat(s)["pointer"], 1)
        mark = len(game.lines)
        self.inject(s, 10, 5, 5)
        game.drain()
        got = game.since(mark)
        rel = [tuple(map(int, l.split()[1:])) for l in got if l.startswith("rel ")]
        self.assertEqual(rel, [(10, 5)] * 5, got)
        # zamceny ukazatel stoji: klient nedostane zadny pohyb kurzoru
        self.assertEqual([l for l in got if l.startswith("motion")], [])
        # absolutni pohyb (tablet, VM) jde taky jako relativni a kurzor zustava
        mark = len(game.lines)
        s.input(f"move {x + 30} {y - 20}")
        game.drain()
        self.assertIn("rel 30 -20", game.since(mark))
        self.assertEqual([l for l in game.since(mark) if l.startswith("motion")], [])
        # jine okno vezme zamereni: zamek konci, kurzor na miste podle cursor hint (stred okna)
        Probe(self, s, self.probe, "--title", "other", "--size", "200x150").wait("ready")
        game.wait("unlocked")
        self.assertEqual(seat(s)["pointer"], 0)
        print(f"\n  lock: 5 rel events {rel[0]} each, 0 motion while locked", file=sys.stderr)

    def test_pointer_lock_needs_focus(self):
        s = self.session()
        game = self.game(s, "--lock", "--size", "300x200")
        other = Probe(self, s, self.probe, "--title", "other", "--size", "300x200")
        other.wait("kbfocus 1")
        game.wait("kbfocus 0")
        gx, gy = self.center(s, "game")
        ox, oy = self.center(s, "other")
        # kurzor jen projede pres nezamerenou hru: zadny zamek
        s.input(f"move {gx} {gy}")
        game.drain(0.5)
        self.assertNotIn("locked", game.lines)
        s.input("click")
        game.wait("kbfocus 1")
        game.wait("locked")

    def test_pointer_confine(self):
        s = self.session()
        game = self.game(s, "--confine")
        v = self.view(s, "game")
        x, y = self.center(s, "game")
        s.input(f"move {x} {y}")
        game.wait("confined")
        self.assertEqual(seat(s)["pointer"], 2)
        mark = len(game.lines)
        self.inject(s, 100, 0, 6)
        self.inject(s, 0, 100, 6)
        game.drain()
        motion = [tuple(map(int, l.split()[1:])) for l in game.since(mark) if l.startswith("motion")]
        self.assertTrue(motion)
        self.assertLessEqual(max(m[0] for m in motion), v["w"] - 1)
        self.assertLessEqual(max(m[1] for m in motion), v["h"] - 1)
        self.assertEqual(motion[-1], (v["w"] - 1, v["h"] - 1), game.since(mark))
        # relativni pohyb jde dal i za okrajem
        self.assertEqual(len([l for l in game.since(mark) if l.startswith("rel ")]), 12)
        print(f"\n  confine: last motion {motion[-1]} in {v['w']}x{v['h']}", file=sys.stderr)

    @unittest.skipUnless(os.path.exists(XWAYLAND) and os.path.exists("/usr/include/X11/extensions/Xfixes.h"),
                         "Xwayland in the sysroot and libXfixes headers")
    def test_xwayland_game_pointer_lock(self):
        wrapper = os.path.join(ROOT, "packages/luxcomp/xwayland-sw")
        s = self.session(env=f"LUXCOMP_XWAYLAND_WRAPPER={wrapper}")
        display = s.log().split("xwayland ")[1].split()[0]
        x = Probe(self, s, "env", f"DISPLAY={display}", self.xprobe)
        x.wait("mapped", 20)
        cx, cy = self.center(s, "xgame")
        s.input(f"move {cx} {cy}")
        x.wait("grab 0")
        for _ in range(30):
            if seat(s)["pointer"] == 1:
                break
            time.sleep(0.1)
        self.assertEqual(seat(s)["pointer"], 1, "Xwayland did not lock the Wayland pointer")
        x.drain(0.3)
        mark = len(x.lines)
        self.inject(s, 7, -4, 10)
        x.drain(0.5)
        deltas = [tuple(map(int, l.split()[1:])) for l in x.since(mark) if l.startswith("delta ")]
        total = (sum(d[0] for d in deltas), sum(d[1] for d in deltas))
        self.assertEqual(total, (70, -40), x.since(mark))
        print(f"\n  xwayland: locked, {len(deltas)} X motion events, sum {total}", file=sys.stderr)

    def test_fullscreen_from_start(self):
        """Hra (SDL, mpv --fs) chce celou obrazovku uz pred prvnim commitem: prvni configure v plne velikosti"""
        s = self.session()
        game = Probe(self, s, self.probe, "--title", "game", "--fullscreen")
        game.wait("ready")
        game.wait("configure 1280 800 1")
        v = self.view(s, "game")
        self.assertEqual((v["x"], v["y"], v["w"], v["h"], v["fullscreen"]), (0, 0, 1280, 800, 1))
        s.input("key F11", wait=0.6)
        v = self.view(s, "game")
        self.assertEqual(v["fullscreen"], 0)
        # po startu na cele obrazovce okno na 2/3 plochy uprostred
        self.assertTrue(0.6 * 1280 < v["w"] < 0.7 * 1280 and 0.6 * 800 < v["h"] < 0.7 * 800, v)

    @unittest.skipUnless(os.path.exists(XWAYLAND) and os.path.exists("/usr/include/X11/extensions/Xfixes.h"),
                         "Xwayland in the sysroot and libXfixes headers")
    def test_xwayland_fullscreen_from_start(self):
        wrapper = os.path.join(ROOT, "packages/luxcomp/xwayland-sw")
        s = self.session(env=f"LUXCOMP_XWAYLAND_WRAPPER={wrapper}")
        display = s.log().split("xwayland ")[1].split()[0]
        x = Probe(self, s, "env", f"DISPLAY={display}", self.xprobe, "--fullscreen")
        x.wait("mapped", 20)
        time.sleep(0.5)
        v = self.view(s, "xgame")
        self.assertEqual((v["x"], v["y"], v["w"], v["h"], v["fullscreen"]), (0, 0, 1280, 800, 1))
        self.assertEqual(output0(s)["fullscreen"], v["id"])
        # zpet do okna: velikost, kterou si okno samo zadalo, umistene jako jine okno
        s.input("key F11", wait=0.6)
        v = self.view(s, "xgame")
        self.assertEqual((v["w"], v["h"], v["fullscreen"]), (400, 300, 0))

    # ---- klavesnice ----

    def test_shortcuts_inhibit_and_escape(self):
        s = self.session()
        Probe(self, s, self.probe, "--title", "other", "--size", "300x200").wait("kbfocus 1")
        game = self.game(s, "--inhibit", "--size", "300x200")
        game.wait("inhibit active")
        # Alt+Tab jde hre, zamereni zustava
        mark = len(game.lines)
        s.input("key alt+Tab")
        game.drain()
        self.assertIn(f"key {KEY_TAB} 1", game.since(mark))
        self.assertEqual(s.focused(), ["game"])
        # Super+Esc: zkratky zpet, hra Esc nedostane
        mark = len(game.lines)
        s.input("key super+Escape")
        game.wait("inhibit inactive")
        self.assertNotIn(f"key {KEY_ESC} 1", game.since(mark))
        mark = len(game.lines)
        s.input("key alt+Tab", wait=0.8)
        self.assertEqual(s.focused(), ["other"])
        game.drain()
        self.assertNotIn(f"key {KEY_TAB} 1", game.since(mark))
        # znovu zamerena hra ma zkratky zase pro sebe
        x, y = self.center(s, "game")
        s.input(f"move {x} {y}", "click")
        game.wait("kbfocus 1")
        mark = len(game.lines)
        game.wait("inhibit active")
        # druhe Super+Esc v tomtez zamereni vrati zkratky hre
        s.input("key super+Escape")
        game.wait("inhibit inactive")
        mark = len(game.lines)
        s.input("key super+Escape")
        game.drain()
        self.assertIn("inhibit active", game.since(mark))
        print("\n  inhibit: Alt+Tab to the game, Super+Esc releases and re-grabs", file=sys.stderr)

    # ---- tearing, scanout, necinnost ----

    def test_tearing_only_fullscreen_and_setting(self):
        s = self.session()
        game = self.game(s, "--tearing")
        self.assertEqual(self.view(s, "game")["tearing"], 1)
        s.input("move 5 5")
        o = output0(s)
        self.assertEqual((o["fullscreen"], o["torn"]), (0, 0), o)
        s.input("key F11", wait=0.6)
        game.wait("configure 1280 800 1")
        x, y = self.center(s, "game")
        s.input(f"move {x} {y}", "move 100 100")
        o = output0(s)
        self.assertNotEqual(o["fullscreen"], 0)
        self.assertEqual((o["torn"], o["tearing"], o["vrr"]), (1, 1, 1), o)
        # celoobrazovkove okno bez pozadavku na tearing: synchronne
        plain = self.session()
        self.game(plain, "--fullscreen", title="plain")
        plain.input("move 100 100", "move 200 200")
        self.assertEqual(output0(plain)["torn"], 0)
        # tearing = no v luxwm.conf
        conf = test_conf("luxwm-notearing.conf")
        with open(conf) as f:
            text = f.read().replace("tearing = yes", "tearing = no").replace("vrr = fullscreen", "vrr = always")
        with open(conf, "w") as f:
            f.write(text)
        off = self.session(env=f"LUXWM_SYSTEM_CONFIG={conf}")
        self.game(off, "--tearing", "--fullscreen", title="off")
        off.input("move 100 100", "move 200 200")
        o = output0(off)
        self.assertEqual((o["torn"], o["tearing"], o["vrr"]), (0, 0, 2), o)
        print("\n  tearing: windowed 0, fullscreen+async 1, fullscreen sync 0, tearing=no 0", file=sys.stderr)

    def test_fullscreen_direct_scanout(self):
        s = self.session(env="LUXCOMP_DEBUG=1")
        s.bar()
        subprocess.run([WLT, "run", s.dir, "--bg", "wlt-popups", "--count", "0", "--dim"], check=True)
        time.sleep(0.5)
        game = self.game(s)
        x, y = self.center(s, "game")
        s.input(f"move {x} {y}", "move 300 300")
        windowed = output0(s)
        self.assertEqual(windowed["scanout"], 0, windowed)
        s.input("key F11", wait=0.6)
        game.wait("configure 1280 800 1")
        s.input("move 640 400", "move 641 401")
        o = output0(s)
        v = self.view(s, "game")
        self.assertEqual(o["fullscreen"], v["id"])
        self.assertEqual(v["top"], 0)
        self.assertEqual(o["scanout"], 1, f"{o} (title bar, shadow, bar or dim drawn over the game?)")
        self.assertIn("Direct scan-out enabled", s.log())
        s.shot("gaming-fullscreen-scanout.png")
        # plocha nad hrou (oznameni, popup ve vrstve overlay): kompozice, po zavreni zase scanout
        pop = subprocess.Popen([WLT, "run", s.dir, "wlt-popups", "--count", "1", "--size", "200x100"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: (pop.poll() is None and pop.terminate(), pop.wait(5)))
        time.sleep(0.8)
        s.input("move 642 402")
        self.assertEqual(output0(s)["scanout"], 0)
        kill_tree(pop.pid)
        pop.wait(5)
        time.sleep(0.3)
        s.input("move 643 403")
        self.assertEqual(output0(s)["scanout"], 1)
        # konec cele obrazovky: zahlavi a stin zpet, zadny scanout
        s.input("key F11", wait=0.6)
        s.input("move 300 300")
        o = output0(s)
        self.assertEqual((o["fullscreen"], o["scanout"]), (0, 0), o)
        print("\n  scanout: windowed 0, fullscreen 1 (wlroots: Direct scan-out enabled), overlay 0, back 1",
              file=sys.stderr)

    def test_idle_inhibit_fullscreen_game(self):
        s = self.session()
        watch = Probe(self, s, self.probe, "--idle", "700")
        watch.wait("watching")
        # okno s hrou: necinnost bezi
        game = self.game(s, "--content", "game")
        self.assertEqual(self.view(s, "game")["content"], 3)
        s.input("move 10 10")
        watch.wait("idled", 5)
        self.assertEqual(seat(s)["idle_inhibit"], 0)
        # cela obrazovka: obrazovka nezhasne
        s.input("key F11", wait=0.3)
        watch.wait("resumed", 5)
        game.wait("configure 1280 800 1")
        self.assertEqual(seat(s)["idle_inhibit"], 1)
        mark = len(watch.lines)
        watch.drain(2.0)
        self.assertNotIn("idled", watch.since(mark))
        # zpet do okna: necinnost zase bezi
        s.input("key F11", wait=0.3)
        watch.wait("idled", 5)
        self.assertEqual(seat(s)["idle_inhibit"], 0)
        # celoobrazovkove okno bez typu obsahu (prohlizec, kancelar): obrazovka smi zhasnout
        plain = self.session()
        w2 = Probe(self, plain, self.probe, "--idle", "700")
        w2.wait("watching")
        self.game(plain, "--fullscreen", title="plain")
        w2.wait("idled", 5)
        print("\n  idle: game windowed idles, fullscreen game inhibits >2 s, plain fullscreen idles", file=sys.stderr)


if __name__ == "__main__":
    unittest.main()
