"""Testy luxwm pres harness scripts/wl-test (headless pixman a vnoreny Xvfb, nikdy skutecna obrazovka).

Spusteni (stavba libluxcomp + luxwm proti sysrootu harnessu, pak testy):
  scripts/wl-test/fetch-sysroot.sh && packages/luxwm/tests/build-host.sh
  env -u DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u XAUTHORITY DBUS_SYSTEM_BUS_ADDRESS=unix:path=/nonexistent \
    systemd-run --user --scope -p TasksMax=300 -- timeout 900 python3 -m unittest -v packages/luxwm/tests/test_luxwm.py
Stav luxwm se cte z vypisu na SIGUSR2 v compositor.log, snimky a mereni jdou do out/luxwm-test/results.
"""
import os
import re
import signal
import statistics
import subprocess
import time
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
WLT = os.path.join(ROOT, "scripts", "wl-test", "wlt")
BUILD = os.environ.get("LUXWM_BUILD", os.path.join(ROOT, "out", "luxwm-test", "build"))
SYSROOT = os.path.join(ROOT, "out", "wl-test", "sysroot")
RESULTS = os.path.join(ROOT, "out", "luxwm-test", "results")
CONF = os.path.join(ROOT, "packages", "luxwm", "luxwm.conf")

BAR = 30
TITLE = 32          # tokens.LIGHT_SIZE + 2 * SPACE["s"]
W, H = 1280, 800


def wlt(*args, check=True):
    return subprocess.run([WLT, *args], check=check, capture_output=True, text=True, timeout=120).stdout.strip()


def children(pid):
    out = []
    for task in os.listdir(f"/proc/{pid}/task"):
        with open(f"/proc/{pid}/task/{task}/children") as f:
            out += [int(p) for p in f.read().split()]
    return out


def pss_kb(pid):
    with open(f"/proc/{pid}/smaps_rollup") as f:
        return int(re.search(r"^Pss:\s+(\d+)", f.read(), re.M).group(1))


class Session:
    def __init__(self, program="luxwm", mode="headless", env=""):
        envs = (f"LUXCOMP_VIRTUAL_INPUT=1 LUXWM_TRACE=1 LUXWM_SYSTEM_CONFIG={CONF} "
                f"LD_LIBRARY_PATH={BUILD}:{SYSROOT}/usr/lib {env}")
        out = subprocess.run([WLT, "start", "--mode", mode, "--size", f"{W}x{H}", "--", os.path.join(BUILD, program)],
                             check=True, capture_output=True, text=True, timeout=120,
                             env={**os.environ, "WLT_COMPOSITOR_ENV": envs}).stdout
        self.dir = out.strip().splitlines()[-1]
        with open(os.path.join(self.dir, "compositor.pid")) as f:
            top = int(f.read())
        # systemd-run a env se nahradi, timeout spusti kompozitor jako potomka
        kids = children(top)
        self.pid = kids[0] if kids else top
        self.log_path = os.path.join(self.dir, "compositor.log")

    def stop(self):
        wlt("stop", self.dir, check=False)

    def log(self):
        with open(self.log_path, errors="replace") as f:
            return f.read()

    def client(self, title, app="test", size="400x300", color=None, wait=0.6):
        args = ["run", self.dir, "--bg", "wlt-client", "--events", "--title", title, "--app-id", app, "--size", size]
        if color:
            args += ["--color", color]
        wlt(*args)
        time.sleep(wait)

    def bar(self, height=BAR):
        wlt("run", self.dir, "--bg", "wlt-bar", "--height", str(height))
        time.sleep(0.6)

    def input(self, *commands, wait=0.4):
        wlt("input", self.dir, *commands)
        time.sleep(wait)

    def state(self):
        """Posledni vypis stavu (SIGUSR2): {"workspace": n, "views": {titulek: {...}}, "mru": [...]}"""
        before = self.log().count("luxwm: end")
        os.kill(self.pid, signal.SIGUSR2)
        for _ in range(50):
            text = self.log()
            if text.count("luxwm: end") > before:
                break
            time.sleep(0.05)
        block = text[text.rfind("luxwm: workspace "):]
        state = {"views": {}, "ids": {}}
        for line in block.splitlines():
            if line.startswith("luxwm: workspace "):
                state["workspace"] = int(line.split()[2].split("/")[0])
            elif line.startswith("luxwm: output "):
                m = re.search(r"usable=(-?\d+),(-?\d+),(\d+)x(\d+)", line)
                state["usable"] = tuple(int(v) for v in m.groups())
            elif line.startswith("luxwm: view "):
                fields = dict(f.split("=", 1) for f in line.split()[3:])
                view = {k: (int(v) if re.fullmatch(r"-?\d+", v) else v) for k, v in fields.items()}
                view["id"] = int(line.split()[2])
                state["views"][view["title"]] = view
                state["ids"][view["id"]] = view["title"]
            elif line.startswith("luxwm: mru"):
                state["mru"] = [state["ids"].get(int(v), v) for v in line.split()[2:]]
        return state

    def focused(self):
        return [t for t, v in self.state()["views"].items() if v["focused"] == 1]

    def shot(self, name):
        os.makedirs(RESULTS, exist_ok=True)
        path = os.path.join(RESULTS, name)
        wlt("shot", self.dir, path)
        return path

    def pixel(self, x, y):
        path = self.shot("probe.ppm")
        with open(path, "rb") as f:
            data = f.read()
        # P6 W H MAX\n data
        parts = data.split(maxsplit=4)
        width = int(parts[1])
        off = len(data) - int(parts[1]) * int(parts[2]) * 3
        i = off + (y * width + x) * 3
        return tuple(data[i:i + 3])


def frame(view):
    return (view["x"], view["y"] - view["top"], view["w"], view["h"] + view["top"])


def overlap(a, b):
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


@unittest.skipUnless(os.path.exists(os.path.join(BUILD, "luxwm")), "build first: packages/luxwm/tests/build-host.sh")
class LuxwmHeadless(unittest.TestCase):
    def setUp(self):
        self.s = Session()

    def tearDown(self):
        self.s.stop()
        self.assertNotIn("error in", self.s.log())
        self.assertNotIn("LSL callback error", self.s.log())

    def test_placement_below_bar_and_cascade(self):
        s = self.s
        s.bar()
        self.assertEqual(s.state()["usable"], (0, BAR, W, H - BAR))
        s.client("A")
        a = s.state()["views"]["A"]
        # 1. stred pouzitelne plochy (pod listou)
        self.assertEqual(frame(a), ((W - 400) // 2, BAR + (H - BAR - 300 - TITLE) // 2, 400, 300 + TITLE))
        # 2. volne misto bez prekryti
        s.client("B")
        views = s.state()["views"]
        self.assertFalse(overlap(frame(views["A"]), frame(views["B"])))
        self.assertGreaterEqual(frame(views["B"])[1], BAR)
        # 3. kaskada: velka okna stejne aplikace o 28 px vpravo dolu, nikdy na sebe
        for title in ("C1", "C2", "C3"):
            s.client(title, app="cascade", size="900x560")
        views = s.state()["views"]
        c = [frame(views[t]) for t in ("C1", "C2", "C3")]
        self.assertEqual((c[1][0] - c[0][0], c[1][1] - c[0][1]), (28, 28))
        self.assertEqual((c[2][0] - c[1][0], c[2][1] - c[1][1]), (28, 28))
        for f in c:
            self.assertGreaterEqual(f[1], BAR)
        s.shot("placement-bar-cascade.png")

    def test_bar_appearing_pushes_windows_down(self):
        s = self.s
        s.client("Big", size="600x760")
        s.bar()
        big = s.state()["views"]["Big"]
        self.assertGreaterEqual(frame(big)[1], BAR)

    def test_fullscreen_covers_bar(self):
        s = self.s
        s.bar()
        s.client("V", color="10a010")
        before = s.state()["views"]["V"]
        s.input("key F11", wait=0.6)
        v = s.state()["views"]["V"]
        self.assertEqual((v["x"], v["y"], v["w"], v["h"], v["fullscreen"], v["layer"]), (0, 0, W, H, 1, 2))
        # lista (f4f4f8) je pod oknem: nahore obsah okna
        r, g, b = s.pixel(10, 10)
        self.assertTrue(g > 120 and r < 60, (r, g, b))
        s.shot("fullscreen-above-bar.png")
        # jine okno zamerene => celoobrazovkove pod listu (NORMAL)
        s.client("Other")
        self.assertEqual(s.state()["views"]["V"]["layer"], 2, "new window must not steal focus from fullscreen")
        s.input("key alt+Tab")
        st = s.state()["views"]
        self.assertEqual(st["Other"]["focused"], 1)
        self.assertEqual(st["V"]["layer"], 0)
        s.input("key alt+Tab")
        s.input("key F11", wait=0.6)
        v = s.state()["views"]["V"]
        self.assertEqual((v["x"], v["y"], v["w"], v["h"], v["layer"]), (before["x"], before["y"], before["w"], before["h"], 0))
        # maximalizovane okno po cele obrazovce zase maximalizovane pod listou (zahlavi se vrati)
        s.input("key super+Up", wait=0.5)
        s.input("key F11", wait=0.5)
        s.input("key F11", wait=0.6)
        v = s.state()["views"]["V"]
        self.assertEqual(frame(v), (0, BAR, W, H - BAR))

    def test_maximize_minimize(self):
        s = self.s
        s.bar()
        s.client("A")
        s.client("B")
        s.input("key super+Up", wait=0.6)
        b = s.state()["views"]["B"]
        self.assertEqual(frame(b), (0, BAR, W, H - BAR))
        s.input("key super+Up", wait=0.6)
        self.assertEqual(s.state()["views"]["B"]["w"], 400)
        s.input("key super+m")
        st = s.state()
        self.assertEqual(st["views"]["B"]["visible"], 0)
        self.assertEqual(st["views"]["A"]["focused"], 1)
        # minimalizovane okno se vrati pres Alt+Tab
        s.input("key alt+Tab")
        st = s.state()["views"]
        self.assertEqual((st["B"]["visible"], st["B"]["focused"]), (1, 1))

    def test_focus_after_close(self):
        s = self.s
        for t in ("A", "B", "C"):
            s.client(t)
        s.input("move 5 790", "click")      # klik na plochu nic nezmeni
        self.assertEqual(s.focused(), ["C"])
        s.input("key alt+F4")
        self.assertEqual(s.focused(), ["B"], "focus goes to the most recent window")
        views = s.state()["views"]
        a, b = views["A"], views["B"]
        s.input(f"move {a['x'] + a['w'] // 2 + 100} {a['y'] - TITLE // 2}", "click")
        self.assertEqual(s.focused(), ["A"], "click on the title bar focuses")
        # cerveny semafor neaktivniho okna zavre bez prevzeti zamereni
        s.input(f"move {b['x'] + 14} {b['y'] - TITLE // 2}", "click")
        st = s.state()
        self.assertNotIn("B", st["views"])
        self.assertEqual(s.focused(), ["A"])
        s.client("D")
        s.input("key super+q")
        self.assertEqual(s.focused(), ["A"])
        s.input("key super+q")
        self.assertEqual(s.focused(), [])

    def test_alt_tab_order(self):
        s = self.s
        for t in ("A", "B", "C"):
            s.client(t)
        self.assertEqual(s.state()["mru"], ["C", "B", "A"])
        s.input("key alt+Tab")
        self.assertEqual(s.state()["mru"], ["B", "C", "A"])
        s.input("keydown alt", "key Tab", "key Tab", "keyup alt")
        self.assertEqual(s.state()["mru"], ["A", "B", "C"])
        s.input("key alt+shift+Tab")
        self.assertEqual(s.state()["mru"], ["C", "A", "B"])
        # Esc zrusi vyber a vrati puvodni okno
        s.input("keydown alt", "key Tab", "key Escape", "keyup alt")
        self.assertEqual(s.focused(), ["C"])
        self.assertEqual(s.state()["mru"], ["C", "A", "B"])

    def test_alt_grave_within_app(self):
        s = self.s
        s.client("T1", app="term")
        s.client("Web", app="web")
        s.client("T2", app="term")
        s.input("key alt+grave")
        self.assertEqual(s.focused(), ["T1"], "Alt+` skips other apps")
        s.input("key alt+grave")
        self.assertEqual(s.focused(), ["T2"])
        s.input("key alt+Tab")
        self.assertEqual(s.focused(), ["T1"])

    def test_workspaces(self):
        s = self.s
        s.bar()
        s.client("A")
        s.client("B")
        s.input("key ctrl+super+Right", wait=0.8)
        st = s.state()
        self.assertEqual(st["workspace"], 2)
        self.assertEqual(s.focused(), [])
        s.client("C")
        st = s.state()["views"]
        self.assertEqual((st["C"]["ws"], st["C"]["focused"]), (2, 1))
        s.shot("workspace-2.png")
        s.input("key ctrl+super+Left", wait=0.8)
        self.assertEqual(s.state()["workspace"], 1)
        self.assertEqual(s.focused(), ["B"])
        # okno na jinou plochu: odejde, zamereni prevezme dalsi
        s.input("key ctrl+super+shift+3", wait=0.6)
        st = s.state()["views"]
        self.assertEqual((st["B"]["ws"], st["A"]["focused"]), (3, 1))
        s.input("key ctrl+super+3", wait=0.8)
        st = s.state()
        self.assertEqual(st["workspace"], 3)
        self.assertEqual(s.focused(), ["B"])
        # krajni plocha bez prechodu dokola
        s.input("key ctrl+super+4", wait=0.8)
        s.input("key ctrl+super+Right", wait=0.8)
        self.assertEqual(s.state()["workspace"], 4)

    def red_left_edge(self, path, y):
        """Levy okraj obsahu okna (cervene pruhy d03030 / 681818) v radku y, None kdyz neni videt"""
        with open(path, "rb") as f:
            data = f.read()
        parts = data.split(maxsplit=4)
        width, height = int(parts[1]), int(parts[2])
        off = len(data) - width * height * 3 + y * width * 3
        for x in range(width):
            r, g, b = data[off + 3 * x:off + 3 * x + 3]
            if r > 90 and g < 70 and b < 70:
                return x
        return None

    def test_workspace_slide(self):
        s = self.s
        s.bar()
        s.client("A", color="d03030", size="300x200")
        a = s.state()["views"]["A"]
        frames = os.path.join(RESULTS, "slide-frames")
        subprocess.run(["rm", "-rf", frames])
        cap = subprocess.Popen([WLT, "capture", s.dir, frames, "30", "3"])
        time.sleep(0.5)
        s.input("key ctrl+super+Right", wait=1.0)
        s.input("key ctrl+super+Left", wait=1.0)
        cap.wait(timeout=60)
        names = sorted(os.listdir(frames))
        edges = [self.red_left_edge(os.path.join(frames, n), a["y"] + 100) for n in names]
        # okno stoji, odjede doleva az zmizi, pak se vrati zleva doprava; nikdy necukne zpet
        out = edges
        moves = [(p, q) for p, q in zip(out, out[1:]) if p != q]
        self.assertTrue(moves, "the window never moved")
        leaving = True
        for p, q in moves:
            if leaving and p is None:
                leaving = False
            if leaving:
                self.assertTrue(q is None or (p is not None and q < p), (p, q, out))
            else:
                self.assertTrue(p is None or (q is not None and q > p), (p, q, out))
        self.assertIn(None, out, "the window must leave the screen during the slide")
        self.assertEqual(out[-1], a["x"])
        r = subprocess.run([WLT, "check", "--max-run", "0", frames], capture_output=True, text=True)
        with open(os.path.join(RESULTS, "slide-check.txt"), "w") as f:
            f.write(" ".join(str(e) for e in out) + "\n" + r.stdout + r.stderr)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_workspace_switch_instant_no_flicker(self):
        s = self.s
        cfg = os.path.join(s.dir, "config", "luxwm")
        os.makedirs(cfg, exist_ok=True)
        with open(os.path.join(cfg, "luxwm.conf"), "w") as f:
            f.write("slide_ms = 0\n")
        os.kill(s.pid, signal.SIGHUP)
        s.bar()
        s.client("A", color="d03030")
        frames = os.path.join(RESULTS, "switch-frames")
        subprocess.run(["rm", "-rf", frames])
        cap = subprocess.Popen([WLT, "capture", s.dir, frames, "30", "3"])
        time.sleep(0.5)
        s.input("key ctrl+super+Right", wait=1.0)
        s.input("key ctrl+super+Left", wait=1.0)
        cap.wait(timeout=60)
        r = subprocess.run([WLT, "check", frames], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_theme_light_dark(self):
        s = self.s
        s.client("Theme")
        v = s.state()["views"]["Theme"]
        probe = (v["x"] + v["w"] // 2 + 120, v["y"] - 4)
        s.shot("theme-light.png")
        self.assertEqual(s.pixel(*probe), (242, 242, 247))
        cfg = os.path.join(s.dir, "config", "luxos")
        os.makedirs(cfg, exist_ok=True)
        with open(os.path.join(cfg, "appearance"), "w") as f:
            f.write("dark\n")
        os.kill(s.pid, signal.SIGUSR1)
        time.sleep(0.5)
        s.shot("theme-dark.png")
        self.assertEqual(s.pixel(*probe), (33, 36, 43))

    def test_user_config_and_reload(self):
        s = self.s
        cfg = os.path.join(s.dir, "config", "luxwm")
        os.makedirs(cfg, exist_ok=True)
        with open(os.path.join(cfg, "luxwm.conf"), "w") as f:
            f.write("[keys]\n<Alt>Tab =\n<Super>F12 = cycle_windows_key\n<Super>Tab = bogus_action\n")
        os.kill(s.pid, signal.SIGHUP)
        time.sleep(0.3)
        s.client("A")
        s.client("B")
        s.input("key alt+Tab")
        self.assertEqual(s.focused(), ["B"], "<Alt>Tab disabled by the user file")
        s.input("key super+F12")
        self.assertEqual(s.focused(), ["A"])
        self.assertIn("configuration reloaded", s.log())

    def test_clean_shutdown(self):
        s = self.s
        s.client("A")
        os.kill(s.pid, signal.SIGTERM)
        for _ in range(50):
            if not os.path.exists(f"/proc/{s.pid}") or "luxwm: stopped" in s.log():
                break
            time.sleep(0.1)
        self.assertIn("luxwm: stopped", s.log())


@unittest.skipUnless(os.path.exists(os.path.join(BUILD, "luxwm")), "build first")
class LuxwmNested(unittest.TestCase):
    """Vnoreny backend x11 v soukromem Xvfb: stejne chovani jako headless."""

    def test_nested_placement_and_alt_tab(self):
        s = Session(mode="nested")
        try:
            s.bar()
            s.client("A")
            s.client("B")
            views = s.state()["views"]
            self.assertFalse(overlap(frame(views["A"]), frame(views["B"])))
            self.assertGreaterEqual(frame(views["A"])[1], BAR)
            s.input("key alt+Tab")
            self.assertEqual(s.focused(), ["A"])
            s.shot("nested.png")
        finally:
            s.stop()
        self.assertNotIn("error in", s.log())


@unittest.skipUnless(os.path.exists(os.path.join(BUILD, "luxwm")), "build first")
class Measurements(unittest.TestCase):
    """PSS luxwm proti C demu (stejne 2 okna, 5 s v klidu) a prodleva zkratka -> zamereni."""

    def idle_pss(self, program):
        s = Session(program=program)
        try:
            s.client("A")
            s.client("B")
            time.sleep(5)
            return pss_kb(s.pid)
        finally:
            s.stop()

    def test_memory_and_latency(self):
        demo = statistics.median(self.idle_pss("luxcomp-demo") for _ in range(3))
        luxwm = statistics.median(self.idle_pss("luxwm") for _ in range(3))
        s = Session()
        try:
            s.client("A")
            s.client("B")
            for _ in range(20):
                s.input("key alt+Tab", wait=0.15)
            time.sleep(0.5)
            log = s.log()
            with open(os.path.join(s.dir, "clients.log")) as f:
                focus = [int(m) for m in re.findall(r"^focus (\d+)$", f.read(), re.M)]
        finally:
            s.stop()
        keys = [(int(t), int(d)) for t, d in re.findall(r"key cycle_windows_key t=(\d+) took_us=(\d+)", log)]
        policy = [d for _, d in keys]
        # zamereni klienta po kazde zkratce: prvni udalost "focus" po case zkratky
        e2e = []
        for t, _ in keys:
            after = [f - t for f in focus if f >= t]
            if after:
                e2e.append(min(after))
        report = (f"idle PSS, 2 windows, median of 3 (kB): luxcomp-demo {demo:.0f}, luxwm {luxwm:.0f}, "
                  f"difference {luxwm - demo:.0f}\n"
                  f"Alt+Tab policy in LSL (us): median {statistics.median(policy):.0f}, max {max(policy)}\n"
                  f"KEYBIND -> client keyboard focus (us): median {statistics.median(e2e):.0f}, max {max(e2e)}, n={len(e2e)}\n")
        os.makedirs(RESULTS, exist_ok=True)
        with open(os.path.join(RESULTS, "measurements.txt"), "w") as f:
            f.write(report)
        print("\n" + report)
        self.assertLessEqual(luxwm - demo, 15 * 1024)
        self.assertEqual(len(keys), 20)


if __name__ == "__main__":
    unittest.main()
