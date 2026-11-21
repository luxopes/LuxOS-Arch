"""Monitory na Waylandu: luxos-displays (pomocnik), luxos-displays-settings (odkaz na luxos-settings: stranka
Monitory a rychla volba) a luxwm s libluxcomp pres harness scripts/wl-test (headless pixman, dva vystupy).

Spusteni:
  scripts/wl-test/fetch-sysroot.sh && packages/luxwm/tests/build-host.sh
  env -u DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u XAUTHORITY DBUS_SYSTEM_BUS_ADDRESS=unix:path=/nonexistent \
    systemd-run --user --scope -p TasksMax=300 -p MemoryMax=2G -- timeout 1200 \
    python3 -m unittest -v packages/luxos-desktop/tests/test_luxos_displays_wl.py

Programy v LSL a libluxos-wl se prekladaji do out/luxos-displays-test. Allowlist privilegovanych protokolu
dostane jen prelozeny pomocnik a luxwm-msg (WLT_PRIVILEGED); okno Nastaveni privilegovane neni.
Pripojeni a odpojeni monitoru simuluje prikaz IPC test_output (jen headless backend).
"""
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lsl_app  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
ROOT = os.path.dirname(os.path.dirname(PKG))
WLT = os.path.join(ROOT, "scripts", "wl-test", "wlt")
BUILD = os.environ.get("LUXWM_BUILD", os.path.join(ROOT, "out", "luxwm-test", "build"))
SYSROOT = os.path.join(ROOT, "out", "wl-test", "sysroot")
OUT = os.path.join(ROOT, "out", "luxos-displays-test")
CONF = os.path.join(ROOT, "packages", "luxwm", "luxwm.conf")
MSG = os.path.join(BUILD, "luxwm-msg")
LSLC = os.environ.get("LUXOS_LSLC") or shutil.which("lslc")
HELPER = os.path.join(OUT, "luxos-displays")
SETTINGS = os.path.join(OUT, "luxos-displays-settings")
NOTIFY = os.path.join(OUT, "luxos-notify")
LIB = os.path.join(OUT, "libluxos-wl.so.0")

READY = os.path.exists(os.path.join(BUILD, "luxwm")) and os.path.exists(SYSROOT) and LSLC


def ppm(path):
    with open(path, "rb") as f:
        data = f.read()
    _, size, _, pixels = data.split(b"\n", 3)
    width, height = map(int, size.split())
    return width, height, pixels


def pixel(image, x, y):
    width, _, pixels = image
    i = (y * width + x) * 3
    return tuple(pixels[i:i + 3])


def build():
    os.makedirs(os.path.join(OUT, "src"), exist_ok=True)
    subprocess.run(["make", "-s", "-C", os.path.join(PKG, "files/src/luxos-wl"), f"OUT={OUT}"], check=True)
    lsl = lsl_app.LSL_DIR
    for f in os.listdir(lsl):
        if f.endswith(".lsl") and os.path.exists(os.path.join(lsl, f)):
            shutil.copy(os.path.join(lsl, f), os.path.join(OUT, "src"))
    shutil.copy(os.path.join(HERE, "lsl", "luxos-displays-test.lsl"), os.path.join(OUT, "src"))
    for name, exe in (("luxos-displays", HELPER), ("luxos-settings", os.path.join(OUT, "luxos-settings")),
                      ("luxos-notify", NOTIFY), ("luxos-displays-test", os.path.join(OUT, "unit"))):
        r = subprocess.run([LSLC, "--target", "linux-x86_64-gnu", "--system-bindings", os.path.join(OUT, "src"),
                            os.path.join(OUT, "src", name + ".lsl"), exe], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(name + ": " + r.stdout + r.stderr)
    # stary program je odkaz na luxos-settings (stranka Monitory, --menu = rychla volba)
    if os.path.lexists(SETTINGS):
        os.unlink(SETTINGS)
    os.symlink("luxos-settings", SETTINGS)


class Session:
    """luxwm se dvema headless vystupy 1280x720; displays_command spousti prelozeny pomocnik."""

    def __init__(self, name, internal=""):
        self.conf = os.path.join(OUT, f"luxwm-{name}.conf")
        extra = ""
        if internal:
            extra = f"LUXOS_DISPLAYS_INTERNAL={internal} "
        hook = f"env -u LD_LIBRARY_PATH {extra}LUXOS_WL_LIB={LIB} {HELPER} auto"
        with open(CONF) as f:
            lines = [line for line in f.read().splitlines() if not line.startswith("displays_command")]
        with open(self.conf, "w") as f:
            f.write(f"xwayland = no\ndisplays_command = {hook}\n" + "\n".join(lines) + "\n")
        envs = (f"LUXCOMP_VIRTUAL_INPUT=1 LUXWM_TRACE=1 LUXWM_SYSTEM_CONFIG={self.conf} "
                f"LD_LIBRARY_PATH={BUILD}:{SYSROOT}/usr/lib")
        out = subprocess.run([WLT, "start", "--mode", "headless", "--outputs", "2", "--name", name, "--",
                              os.path.join(BUILD, "luxwm")], check=True, capture_output=True, text=True, timeout=120,
                             env={**os.environ, "WLT_COMPOSITOR_ENV": envs, "WLT_PRIVILEGED": f"{HELPER} {MSG}"}).stdout
        self.dir = out.strip().splitlines()[-1]
        self.env = {"PATH": "/usr/bin:/bin", "HOME": f"{self.dir}/home", "XDG_RUNTIME_DIR": f"{self.dir}/run",
                    "XDG_CONFIG_HOME": f"{self.dir}/config", "LANG": "C.UTF-8", "WAYLAND_DISPLAY": "wayland-0",
                    "DBUS_SESSION_BUS_ADDRESS": "unix:path=/nonexistent",
                    "DBUS_SYSTEM_BUS_ADDRESS": "unix:path=/nonexistent", "GDK_BACKEND": "wayland",
                    "NO_AT_BRIDGE": "1", "GTK_A11Y": "none", "LUXOS_WL_LIB": LIB, "LUXOS_DISPLAYS_HELPER": HELPER}
        if internal:
            self.env["LUXOS_DISPLAYS_INTERNAL"] = internal
        self.store = os.path.join(self.dir, "config", "luxos", "displays-wayland.json")
        self.procs = []
        # prvni displays_command po startu (nova sada: nic se nemeni)
        self.wait(lambda: "displays: " in self.log(), 5)
        time.sleep(0.5)

    def stop(self):
        for p in self.procs:
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(5)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait()
        subprocess.run([WLT, "stop", self.dir], capture_output=True)

    def log(self):
        with open(os.path.join(self.dir, "compositor.log"), errors="replace") as f:
            return f.read()

    @staticmethod
    def wait(cond, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if cond():
                return True
            time.sleep(0.1)
        return False

    def run(self, *cmd, timeout=30, env=None):
        return subprocess.run(list(cmd), env=env or self.env, capture_output=True, text=True, timeout=timeout)

    def helper(self, *args, exe=HELPER):
        return self.run(exe, *args)

    def spawn(self, *cmd):
        p = subprocess.Popen(list(cmd), env=self.env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self.procs.append(p)
        return p

    def msg(self, *args):
        r = self.run(MSG, *args)
        if r.returncode != 0:
            raise AssertionError(f"luxwm-msg {args}: {r.stderr}")
        return json.loads(r.stdout) if r.stdout.strip().startswith("{") else r.stdout

    def outputs(self):
        """{nazev: vystup} podle luxwm IPC get-state"""
        state = self.msg("get-state")["state"]["output"]
        return {o["name"]: o for o in state["outputs"]}, state["primary"]

    def randr(self):
        """{nazev: {"mode", "pos", "scale", "transform", "enabled"}} podle wlr-randr"""
        text = subprocess.run([WLT, "outputs", self.dir], capture_output=True, text=True, timeout=30).stdout
        result, cur = {}, None
        for line in text.splitlines():
            if not line.startswith(" "):
                cur = result.setdefault(line.split()[0], {})
                continue
            line = line.strip()
            if line.endswith("(current)"):
                cur["mode"] = line.split()[0]
            elif ":" in line:
                key, _, value = line.partition(":")
                cur[key.lower()] = value.strip()
        return result

    def shot(self, name, output=None):
        path = os.path.join(OUT, name)
        subprocess.run([WLT, "shot", self.dir, path] + ([output] if output else []), check=True,
                       capture_output=True, timeout=30)
        return ppm(path)

    def input(self, *commands):
        subprocess.run([WLT, "input", self.dir, *commands], check=True, capture_output=True, timeout=60)

    def saved(self):
        try:
            with open(self.store) as f:
                return json.load(f)
        except OSError:
            return None


def config(**outputs):
    """config(HEADLESS_1=(w, h, x, y, scale, transform), ...)"""
    result = {}
    for key, value in outputs.items():
        name = key.replace("_", "-")
        if value is None:
            result[name] = {"enabled": False}
            continue
        w, h, x, y, scale, transform = value
        result[name] = {"enabled": True, "width": w, "height": h, "refresh": 0, "x": x, "y": y,
                        "transform": transform, "scale": scale}
    return result


@unittest.skipUnless(READY, "needs out/luxwm-test/build (build-host.sh), the wl-test sysroot and lslc")
class DisplaysWayland(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        build()

    def setUp(self):
        self.s = None

    def tearDown(self):
        if self.s:
            self.s.stop()

    def session(self, name, internal=""):
        self.s = Session(name, internal)
        return self.s

    def set(self, request):
        r = self.s.helper("set", json.dumps(request))
        self.assertEqual(r.returncode, 0, r.stderr)
        return r

    # ---- logika bez kompozitoru ----

    def test_logic_unit(self):
        r = subprocess.run([os.path.join(OUT, "unit")], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertGreaterEqual(r.stdout.count("\nok ") + 1, 27, r.stdout)

    # ---- rezim, meritko, otoceni, polohy ----

    def test_mode_and_fractional_scale(self):
        s = self.session("dsp-scale")
        self.set({"config": config(HEADLESS_1=(1920, 1080, 0, 0, 1500, 0), HEADLESS_2=(1280, 720, 1280, 0, 1000, 0)),
                  "primary": "HEADLESS-1"})
        randr = s.randr()
        self.assertEqual(randr["HEADLESS-1"]["mode"], "1920x1080")
        self.assertEqual(randr["HEADLESS-1"]["scale"], "1.500000")
        outs, primary = s.outputs()
        self.assertEqual((outs["HEADLESS-1"]["width"], outs["HEADLESS-1"]["height"], outs["HEADLESS-1"]["scale"]),
                         (1280, 720, 150))
        self.assertEqual(primary, "HEADLESS-1")
        self.assertTrue(outs["HEADLESS-1"]["primary"])
        # 125 % a 175 %: logicka velikost jako v kompozitoru
        for scale, width in ((1250, 1536), (1750, 1097)):
            self.set({"config": config(HEADLESS_1=(1920, 1080, 0, 0, scale, 0),
                                       HEADLESS_2=(1280, 720, width, 0, 1000, 0)), "primary": "HEADLESS-1"})
            outs, _ = s.outputs()
            self.assertEqual(outs["HEADLESS-1"]["width"], width)
            self.assertEqual(outs["HEADLESS-2"]["x"], width)
        saved = s.saved()
        self.assertEqual(saved["outputs"]["HEADLESS-1|Headless output 1"]["scale"], 1750)

    def test_arrangement_rotation_and_refused_layouts(self):
        s = self.session("dsp-arrange")
        # HEADLESS-2 pod HEADLESS-1 posunuty doprava, otoceny o 90 stupnu
        self.set({"config": config(HEADLESS_1=(1280, 720, 0, 0, 1000, 0), HEADLESS_2=(1280, 720, 400, 720, 1000, 1)),
                  "primary": "HEADLESS-2"})
        outs, primary = s.outputs()
        self.assertEqual((outs["HEADLESS-2"]["x"], outs["HEADLESS-2"]["y"]), (400, 720))
        self.assertEqual((outs["HEADLESS-2"]["width"], outs["HEADLESS-2"]["height"]), (720, 1280))
        self.assertEqual(s.randr()["HEADLESS-2"]["transform"], "90")
        self.assertEqual(primary, "HEADLESS-2")
        # mezera, prekryv, vsechno vypnute: pomocnik odmitne, nic se nezmeni
        for bad in (config(HEADLESS_1=(1280, 720, 0, 0, 1000, 0), HEADLESS_2=(1280, 720, 1400, 0, 1000, 0)),
                    config(HEADLESS_1=(1280, 720, 0, 0, 1000, 0), HEADLESS_2=(1280, 720, 600, 0, 1000, 0)),
                    config(HEADLESS_1=None, HEADLESS_2=None)):
            r = s.helper("set", json.dumps({"config": bad, "primary": "HEADLESS-1"}))
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertEqual(s.outputs()[0]["HEADLESS-2"]["y"], 720)

    # ---- zrcadleni ----

    def test_mirror_hides_layers_of_the_mirror(self):
        s = self.session("dsp-mirror")
        # lista na kazdem vystupu (layer-shell jde na vystup pod kurzorem), ruzne barvy; headless
        # vystupy zacinaji HEADLESS-2 vlevo, HEADLESS-1 vpravo
        s.input("move 100 300")
        subprocess.run([WLT, "run", s.dir, "--bg", "wlt-bar", "--color", "ff0000", "--height", "40"], check=True,
                       capture_output=True)
        time.sleep(0.5)
        s.input("move 1400 300")
        subprocess.run([WLT, "run", s.dir, "--bg", "wlt-bar", "--color", "00ff00", "--height", "40"], check=True,
                       capture_output=True)
        time.sleep(0.7)
        self.assertEqual(pixel(s.shot("mirror-before-1.ppm", "HEADLESS-1"), 640, 10), (0, 255, 0))
        self.assertEqual(pixel(s.shot("mirror-before-2.ppm", "HEADLESS-2"), 640, 10), (255, 0, 0))
        r = s.helper("mirror")
        self.assertEqual(r.returncode, 0, r.stderr)
        outs, primary = s.outputs()
        self.assertEqual({(o["x"], o["y"]) for o in outs.values()}, {(0, 0)})
        time.sleep(0.5)
        # stejne velke vystupy: vzor je jeden z nich, zrcadlo ukazuje jeho listu a vlastni ma schovanou
        a = s.shot("mirror-1.ppm", "HEADLESS-1")
        b = s.shot("mirror-2.ppm", "HEADLESS-2")
        self.assertIn(pixel(a, 640, 10), [(255, 0, 0), (0, 255, 0)])
        self.assertEqual(a[2], b[2], "mirrored outputs differ")
        self.assertEqual(primary, "HEADLESS-2")
        # zpet rozsirit: zelena lista je zase videt
        self.assertEqual(s.helper("extend").returncode, 0)
        time.sleep(0.5)
        self.assertEqual(pixel(s.shot("mirror-after-1.ppm", "HEADLESS-1"), 640, 10), (0, 255, 0))
        self.assertEqual(pixel(s.shot("mirror-after-2.ppm", "HEADLESS-2"), 640, 10), (255, 0, 0))
        self.assertEqual(s.saved()["sets"]["HEADLESS-1|Headless output 1+HEADLESS-2|Headless output 2"]["mode"], "extend")

    def test_mirror_other_aspect_is_centred(self):
        s = self.session("dsp-letterbox")
        s.input("move 100 300")
        subprocess.run([WLT, "run", s.dir, "--bg", "wlt-bar", "--color", "ff0000", "--height", "40"], check=True,
                       capture_output=True)
        time.sleep(0.5)
        s.input("move 1400 300")
        subprocess.run([WLT, "run", s.dir, "--bg", "wlt-bar", "--color", "00ff00", "--height", "40"], check=True,
                       capture_output=True)
        time.sleep(0.7)
        # 5:4 zrcadlo pod 16:9 vzorem: vzor uprostred vysky, nahore i dole pruh 152 px v barve pozadi
        self.set({"config": config(HEADLESS_1=(1280, 720, 0, 0, 1000, 0), HEADLESS_2=(1280, 1024, 0, -152, 1000, 0)),
                  "primary": "HEADLESS-1", "mirror": True})
        outs, primary = s.outputs()
        self.assertEqual((outs["HEADLESS-2"]["x"], outs["HEADLESS-2"]["y"]), (0, -152))
        self.assertEqual(primary, "HEADLESS-1")
        time.sleep(0.5)
        ref = s.shot("letterbox-1.ppm", "HEADLESS-1")
        mirror = s.shot("letterbox-2.ppm", "HEADLESS-2")
        self.assertEqual(mirror[:2], (1280, 1024))
        # lista vzoru (zelena) na zrcadle pod hornim pruhem, vlastni lista zrcadla (cervena) schovana
        self.assertEqual(pixel(ref, 640, 10), (0, 255, 0))
        self.assertEqual(pixel(mirror, 640, 152 + 10), (0, 255, 0))
        bars = {pixel(mirror, x, y) for x in (5, 640, 1275) for y in (5, 140, 1024 - 140, 1024 - 5)}
        self.assertEqual(len(bars), 1, bars)
        self.assertNotIn(pixel(mirror, 640, 152 + 10), bars)
        # stred zrcadla ukazuje stred vzoru
        self.assertEqual(pixel(mirror, 640, 512), pixel(ref, 640, 360))
        self.assertEqual(s.helper("extend").returncode, 0)
        time.sleep(0.5)
        self.assertEqual(pixel(s.shot("letterbox-after-2.ppm", "HEADLESS-2"), 640, 10), (255, 0, 0))

    # ---- rychla volba rezimu ----

    def test_quick_switcher_modes(self):
        s = self.session("dsp-modes", internal="HEADLESS-1")
        s.msg("--raw", json.dumps({"cmd": "set_primary", "output": "HEADLESS-1"}))
        expect = {"external": ({"HEADLESS-2"}, "HEADLESS-2"), "internal": ({"HEADLESS-1"}, "HEADLESS-1"),
                  "mirror": ({"HEADLESS-1", "HEADLESS-2"}, "HEADLESS-1"),
                  "extend": ({"HEADLESS-1", "HEADLESS-2"}, "HEADLESS-1")}
        for mode, (on, main) in expect.items():
            r = s.helper(mode)
            self.assertEqual(r.returncode, 0, r.stderr)
            outs, primary = s.outputs()
            self.assertEqual({n for n, o in outs.items() if o["width"] > 0}, on, mode)
            self.assertEqual(primary, main, mode)
            self.assertEqual(s.helper("mode").stdout.strip(), mode)
            if mode == "external":
                # vypnuty vystup nema plochu: okna z nej luxwm presune
                self.assertEqual(outs["HEADLESS-1"]["usable"], [0, 0, 0, 0])
                self.assertEqual(outs["HEADLESS-2"]["x"], 0)

    def test_menu_osd_by_keyboard(self):
        s = self.session("dsp-menu", internal="HEADLESS-1")
        # hlavni monitor HEADLESS-1 vpravo, kurzor vlevo na HEADLESS-2: karta je na hlavnim
        s.msg("--raw", json.dumps({"cmd": "set_primary", "output": "HEADLESS-1"}))
        s.input("move 100 300")
        p = s.spawn(SETTINGS, "--menu")
        time.sleep(3)
        shot = s.shot("menu.ppm")
        self.assertNotEqual(pixel(shot, 1280 + 640, 360), pixel(shot, 1280 + 5, 5))
        self.assertEqual(pixel(shot, 640, 360), pixel(shot, 5, 5))
        # vychozi rezim extend ma fokus, Right = zrcadlit
        s.input("key Right", "key Return")
        p.wait(10)
        self.assertTrue(s.wait(lambda: len({(o["x"], o["y"]) for o in s.outputs()[0].values()}) == 1, 5))
        self.assertEqual(s.helper("mode").stdout.strip(), "mirror")
        # Escape zavre bez zmeny
        p = s.spawn(SETTINGS, "--menu")
        time.sleep(2.5)
        s.input("key Escape")
        self.assertEqual(p.wait(10), 0)
        self.assertEqual(s.helper("mode").stdout.strip(), "mirror")

    @unittest.skipUnless(shutil.which("dbus-daemon") and shutil.which("notify-send"), "needs dbus-daemon and notify-send")
    def test_notifications_on_primary(self):
        s = self.session("dsp-notify")
        bus = os.path.join(s.dir, "bus")
        s.spawn("dbus-daemon", "--session", f"--address=unix:path={bus}", "--nofork", "--nopidfile")
        self.assertTrue(s.wait(lambda: os.path.exists(bus), 5))
        env = dict(s.env, DBUS_SESSION_BUS_ADDRESS=f"unix:path={bus}")
        s.procs.append(subprocess.Popen([NOTIFY], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        time.sleep(1.5)
        # kurzor vlevo (HEADLESS-2), hlavni vpravo: bublina vpravo nahore na hlavnim; po zmene hlavniho se presune
        s.input("move 100 300")
        before = s.shot("notify-before.ppm")
        s.msg("--raw", json.dumps({"cmd": "set_primary", "output": "HEADLESS-1"}))
        time.sleep(0.5)
        self.assertEqual(s.run("notify-send", "-t", "0", "Test", "primary", env=env).returncode, 0)
        for main, x, other in (("HEADLESS-1", 2560 - 60, 1280 - 60), ("HEADLESS-2", 1280 - 60, 2560 - 60)):
            s.msg("--raw", json.dumps({"cmd": "set_primary", "output": main}))
            self.assertTrue(s.wait(lambda: pixel(s.shot("notify.ppm"), x, 40) != pixel(before, x, 40), 5), main)
            self.assertTrue(s.wait(lambda: pixel(s.shot("notify.ppm"), other, 40) == pixel(before, other, 40), 5), main)

    # ---- ulozeni pro sadu monitoru a pripojeni ----

    def test_persistence_per_monitor_set_on_hotplug(self):
        s = self.session("dsp-hotplug")
        self.set({"config": config(HEADLESS_1=(1920, 1080, 1280, 0, 1500, 0), HEADLESS_2=(1280, 720, 0, 0, 1000, 0)),
                  "primary": "HEADLESS-1"})
        start = len(s.log())
        reply = s.msg("--raw", json.dumps({"cmd": "test_output", "add": "1024x768"}))
        self.assertEqual(reply["output"], "HEADLESS-3")
        self.assertTrue(s.wait(lambda: s.log().count("displays: ", start) >= 1, 5))
        time.sleep(1.0)
        outs, primary = s.outputs()
        # neznama sada: puvodni zustanou, novy vpravo v doporucenem rezimu
        self.assertEqual((outs["HEADLESS-3"]["x"], outs["HEADLESS-3"]["width"]), (2560, 1024))
        self.assertEqual(outs["HEADLESS-1"]["scale"], 150)
        self.assertEqual(primary, "HEADLESS-1")
        # pro sadu tri monitoru zrcadlit
        self.assertEqual(s.helper("mirror").returncode, 0)
        self.assertEqual({(o["x"], o["y"]) for o in s.outputs()[0].values()}, {(0, 0)})
        start = len(s.log())
        s.msg("--raw", json.dumps({"cmd": "test_output", "remove": "HEADLESS-3"}))
        self.assertTrue(s.wait(lambda: s.log().count("displays: ", start) >= 1, 5))
        time.sleep(1.0)
        outs, primary = s.outputs()
        # sada dvou: ulozene rozlozeni se vrati
        self.assertEqual(set(outs), {"HEADLESS-1", "HEADLESS-2"})
        self.assertEqual((outs["HEADLESS-2"]["x"], outs["HEADLESS-1"]["x"], outs["HEADLESS-1"]["scale"]), (0, 1280, 150))
        self.assertEqual(primary, "HEADLESS-1")
        sets = s.saved()["sets"]
        self.assertEqual(len(sets), 2)
        self.assertIn("mirror", [v["mode"] for v in sets.values()])

    # ---- zkusebni pouziti a vraceni ----

    def test_try_reverts_after_timeout_and_keeps_on_confirm(self):
        s = self.session("dsp-try")
        moved = {"config": config(HEADLESS_1=(1280, 720, 0, 0, 1000, 0), HEADLESS_2=(1024, 768, 0, 720, 1000, 0)),
                 "primary": "HEADLESS-1"}
        t0 = time.monotonic()
        p = s.spawn(HELPER, "try", "-s", "2", json.dumps(moved))
        self.assertEqual(p.stdout.readline().strip(), "applied")
        self.assertEqual(s.outputs()[0]["HEADLESS-2"]["y"], 720)
        self.assertEqual(p.wait(10), 3)
        took = time.monotonic() - t0
        self.assertIn("reverted", p.stdout.read())
        self.assertGreaterEqual(took, 2.0)
        self.assertLess(took, 5.0)
        outs, _ = s.outputs()
        self.assertEqual((outs["HEADLESS-2"]["x"], outs["HEADLESS-2"]["y"], outs["HEADLESS-2"]["width"]), (0, 0, 1280))
        self.assertEqual(outs["HEADLESS-1"]["x"], 1280)
        self.assertIsNone(s.saved())
        # okamzite vraceni (tlacitko Vratit)
        p = s.spawn(HELPER, "try", "-s", "30", json.dumps(moved))
        self.assertEqual(p.stdout.readline().strip(), "applied")
        p.send_signal(signal.SIGUSR2)
        self.assertEqual(p.wait(10), 3)
        self.assertEqual(s.outputs()[0]["HEADLESS-2"]["y"], 0)
        # potvrzeni
        p = s.spawn(HELPER, "try", "-s", "30", json.dumps(moved))
        self.assertEqual(p.stdout.readline().strip(), "applied")
        p.send_signal(signal.SIGUSR1)
        self.assertEqual(p.wait(10), 0)
        self.assertEqual(s.outputs()[0]["HEADLESS-2"]["y"], 720)
        self.assertEqual(s.saved()["outputs"]["HEADLESS-2|Headless output 2"]["width"], 1024)

    def page_state(self, app):
        return json.loads(app.ask("page-state", "state "))

    def test_settings_window_drag_and_revert(self):
        s = self.session("dsp-gui")
        app = lsl_app.App([SETTINGS], dict(s.env, LUXOS_DISPLAYS_CONFIRM_SECONDS="3"))
        try:
            self.assertTrue(app.wait(lambda: len(self.page_state(app)["rects"]) == 2, 15), app.stderr())
            dump = app.dump()
            self.assertEqual(dump[0]["title"], "Displays")
            self.assertIn("Arrangement", lsl_app.texts(dump))
            # obdelnik HEADLESS-1 (vpravo) pretazeny pod HEADLESS-2
            app.ask("drag HEADLESS-1 -1280 720")
            self.assertTrue(s.wait(lambda: self.page_state(app)["dialog"], 5))
            outs, _ = s.outputs()
            self.assertEqual((outs["HEADLESS-1"]["x"], outs["HEADLESS-1"]["y"]), (0, 720))
            # bez potvrzeni po 3 s zpet
            self.assertTrue(s.wait(lambda: s.outputs()[0]["HEADLESS-1"]["y"] == 0, 8))
            self.assertIsNone(s.saved())
            self.assertTrue(s.wait(lambda: not self.page_state(app)["dialog"], 5))
            # znovu a odchod ze stranky behem odpoctu: nepotvrzene nastaveni se vrati hned
            app.ask("drag HEADLESS-1 -1280 720")
            self.assertTrue(s.wait(lambda: s.outputs()[0]["HEADLESS-1"]["y"] == 720, 5))
            app.ask("page keyboard")
            self.assertTrue(s.wait(lambda: s.outputs()[0]["HEADLESS-1"]["y"] == 0, 2.5))
            self.assertIsNone(s.saved())
            self.assertIsNone(app.proc.poll())
        finally:
            app.stop()

    # ---- prava ----

    def test_copy_outside_allowlist_cannot_apply(self):
        s = self.session("dsp-deny")
        copy = os.path.join(OUT, "luxos-displays-copy")
        shutil.copy(HELPER, copy)
        r = s.helper("extend", exe=copy)
        self.assertEqual(r.returncode, 2)
        self.assertIn("no Wayland output management", r.stderr)
        r = s.helper("set", json.dumps({"config": config(HEADLESS_1=(1024, 768, 0, 0, 1000, 0),
                                                          HEADLESS_2=(1280, 720, 1024, 0, 1000, 0)),
                                         "primary": "HEADLESS-1"}), exe=copy)
        self.assertEqual(r.returncode, 2)
        self.assertEqual(s.randr()["HEADLESS-1"]["mode"], "1280x720")
        # set_primary a test_output jsou privilegovane prikazy IPC
        r = s.run(MSG, "--raw", json.dumps({"cmd": "set_primary", "output": "HEADLESS-2"}))
        self.assertEqual(r.returncode, 0)
        msg_copy = os.path.join(OUT, "luxwm-msg-copy")
        shutil.copy(MSG, msg_copy)
        r = s.run(msg_copy, "--raw", json.dumps({"cmd": "set_primary", "output": "HEADLESS-1"}))
        self.assertEqual(r.returncode, 1)
        self.assertIn("permission denied", r.stderr)
        self.assertEqual(s.outputs()[1], "HEADLESS-2")


if __name__ == "__main__":
    unittest.main()
