"""IPC luxwm, rozlozeni klavesnice, zkratky a vzhled pres harness scripts/wl-test (headless pixman).

Spusteni:
  scripts/wl-test/fetch-sysroot.sh && packages/luxwm/tests/build-host.sh
  env -u DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u XAUTHORITY DBUS_SYSTEM_BUS_ADDRESS=unix:path=/nonexistent \
    systemd-run --user --scope -p TasksMax=300 -- timeout 900 python3 -m unittest -v packages/luxwm/tests/test_luxwm_ipc.py

Protokol: docs/developers/luxwm-ipc.md. Lista (luxos-bar) a luxos-settings (luxos-keyboard-settings je odkaz
na nej) se prekladaji z packages/luxos-desktop/files/lsl do docasneho adresare. Jiny uid se simuluje pres
podman unshare + setpriv (subuid); kdyz neni k dispozici, test se preskoci.
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
WLT = os.path.join(ROOT, "scripts", "wl-test", "wlt")
BUILD = os.environ.get("LUXWM_BUILD", os.path.join(ROOT, "out", "luxwm-test", "build"))
SYSROOT = os.path.join(os.environ.get("WLT_OUT") or os.path.join(ROOT, "out", "wl-test"), "sysroot")
RESULTS = os.path.join(ROOT, "out", "luxwm-test", "results")
CONF = os.path.join(ROOT, "packages", "luxwm", "luxwm.conf")
DESKTOP = os.path.join(ROOT, "packages", "luxos-desktop")
XFCE_DEFAULTS = os.path.join(DESKTOP, "files/xdg/xfce4/xfconf/xfce-perchannel-xml/xfce4-keyboard-shortcuts.xml")
MSG = os.path.join(BUILD, "luxwm-msg")
W, H = 1280, 800
TITLE = 30          # TITLEBAR height_compact (wlt-client is a foreign app)
MARGIN = 8          # luxwm PLACE_MARGIN


def ppm(path):
    data = open(path, "rb").read()
    _, size, _, pixels = data.split(b"\n", 3)
    width, height = map(int, size.split())
    return width, height, pixels


def pixel(image, x, y):
    width, _, pixels = image
    i = (y * width + x) * 3
    return tuple(pixels[i:i + 3])


class Session:
    """luxwm v headless relaci; systemovy luxwm.conf s xwayland = no (XWayland tu netestujeme)."""

    def __init__(self, name, user_conf=""):
        os.makedirs(RESULTS, exist_ok=True)
        self.conf = os.path.join(RESULTS, f"luxwm-{name}.conf")
        with open(self.conf, "w") as f:
            with open(CONF) as conf:
                lines = [line for line in conf.read().splitlines() if not line.startswith("displays_command")]
            # bez displays_command: luxos-displays hostitele by menil monitory testovaci relace
            f.write("xwayland = no\n" + "\n".join(lines) + "\n")
        envs = (f"LUXCOMP_VIRTUAL_INPUT=1 LUXWM_TRACE=1 LUXWM_SYSTEM_CONFIG={self.conf} "
                f"LD_LIBRARY_PATH={BUILD}:{SYSROOT}/usr/lib")
        out = subprocess.run([WLT, "start", "--mode", "headless", "--size", f"{W}x{H}", "--name", name, "--",
                              os.path.join(BUILD, "luxwm")], check=True, capture_output=True, text=True, timeout=120,
                             env={**os.environ, "WLT_COMPOSITOR_ENV": envs}).stdout
        self.dir = out.strip().splitlines()[-1]
        self.env = {}
        for line in subprocess.run([WLT, "env", self.dir], check=True, capture_output=True, text=True).stdout.splitlines():
            key, _, value = line.removeprefix("export ").partition("=")
            self.env[key] = value
        # GTK a LSL programy z hostitele, ne knihovny sysrootu kompozitoru
        self.env.pop("LD_LIBRARY_PATH", None)
        self.env.update(GDK_BACKEND="wayland", NO_AT_BRIDGE="1", GTK_A11Y="none", LUXWM_SYSTEM_CONFIG=self.conf)
        self.sock = os.path.join(self.env["XDG_RUNTIME_DIR"], "luxwm-wayland-0.sock")
        self.procs = []
        if user_conf:
            self.write_user_conf(user_conf)
            self.msg("reload")

    def stop(self):
        for p in self.procs:
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(5)
                except subprocess.TimeoutExpired:
                    p.kill()
        subprocess.run([WLT, "stop", self.dir], capture_output=True)

    def path(self, *parts):
        return os.path.join(self.env["XDG_CONFIG_HOME"], *parts)

    def write_user_conf(self, text):
        os.makedirs(self.path("luxwm"), exist_ok=True)
        with open(self.path("luxwm", "luxwm.conf"), "w") as f:
            f.write(text)

    def log(self):
        return open(os.path.join(self.dir, "compositor.log"), errors="replace").read()

    def wait_log(self, text, timeout=5.0, start=0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.log().find(text, start) >= 0:
                return True
            time.sleep(0.05)
        return False

    def msg(self, *args, exe=MSG, check=True):
        r = subprocess.run([exe, *args], env=self.env, capture_output=True, text=True, timeout=20)
        if check and r.returncode != 0:
            raise AssertionError(f"luxwm-msg {args}: rc={r.returncode} {r.stderr}")
        return r

    def state(self):
        return json.loads(self.msg("get-state").stdout)["state"]

    def spawn(self, *cmd, env=None, out=subprocess.DEVNULL):
        p = subprocess.Popen(list(cmd), env=env or self.env, stdout=out, stderr=subprocess.STDOUT)
        self.procs.append(p)
        return p

    def client(self, title, app="test", size="400x300", wait=0.6):
        subprocess.run([WLT, "run", self.dir, "--bg", "wlt-client", "--events", "--title", title, "--app-id", app,
                        "--size", size], check=True, capture_output=True, timeout=30)
        time.sleep(wait)

    def clients_log(self):
        return open(os.path.join(self.dir, "clients.log"), errors="replace").read()

    def input(self, *commands, env=None, wait=0.3):
        subprocess.run([WLT, "input", self.dir, *commands], check=True, capture_output=True, timeout=60,
                       env={**os.environ, **(env or {})})
        time.sleep(wait)

    def shot(self, name):
        path = os.path.join(RESULTS, name)
        subprocess.run([WLT, "shot", self.dir, path], check=True, capture_output=True, timeout=30)
        return ppm(path)

    def allow(self, exe):
        """Program na allowlist privilegovanych protokolu a prikazu IPC teto relace."""
        with open(os.path.join(self.dir, "privileged.conf"), "a") as f:
            f.write(os.path.realpath(exe) + "\n")
        self.msg("reload")


class Raw:
    """Primy klient soketu (radky JSON), aby slo poslat i nesmysly."""

    def __init__(self, path):
        self.s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.s.settimeout(5)
        self.s.connect(path)
        self.buf = b""

    def send(self, text):
        self.s.sendall(text.encode() + b"\n")

    def line(self):
        while b"\n" not in self.buf:
            chunk = self.s.recv(65536)
            if not chunk:
                raise EOFError
            self.buf += chunk
        line, _, self.buf = self.buf.partition(b"\n")
        return json.loads(line)

    def close(self):
        self.s.close()


def lslc(src_dir, name, out):
    r = subprocess.run(["lslc", "--target", "linux-x86_64-gnu", "--system-bindings", src_dir,
                        os.path.join(src_dir, name + ".lsl"), out],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(name + ": " + r.stdout + r.stderr)


@unittest.skipUnless(os.path.exists(os.path.join(BUILD, "luxwm")) and os.path.exists(MSG) and shutil.which("lslc"),
                     "build first: packages/luxwm/tests/build-host.sh")
class LuxwmIpc(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.makedirs(RESULTS, exist_ok=True)
        cls.tmp = tempfile.mkdtemp(prefix="ipc-", dir=RESULTS)
        src = os.path.join(cls.tmp, "lsl")
        shutil.copytree(os.path.join(DESKTOP, "files", "lsl"), src)
        shutil.copy(os.path.join(DESKTOP, "tests", "lsl", "luxos-wm-config-probe.lsl"), src)
        r = subprocess.run(["make", "-s", "-C", os.path.join(DESKTOP, "files/src/luxos-wl"), f"OUT={cls.tmp}"],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError("libluxos-wl: " + r.stdout + r.stderr)
        cls.wl_lib = os.path.join(cls.tmp, "libluxos-wl.so.0")
        for name in ("luxos-bar", "luxos-settings", "luxos-wm-config-probe"):
            lslc(src, name, os.path.join(cls.tmp, name))
        os.symlink("luxos-settings", os.path.join(cls.tmp, "luxos-keyboard-settings"))
        # druha kopie luxwm-msg: na allowlist jde jen ona, prvni zustava neprivilegovana
        cls.msg_priv = os.path.join(cls.tmp, "luxwm-msg-priv")
        shutil.copy(MSG, cls.msg_priv)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, True)

    def setUp(self):
        self.s = None

    def tearDown(self):
        if self.s:
            self.s.stop()

    def session(self, user_conf=""):
        name = f"i{os.getpid() % 10000}{self._testMethodName[5:13]}"
        self.s = Session(name, user_conf)
        return self.s

    # ---- protokol --------------------------------------------------------------------------------

    def test_socket_and_state(self):
        s = self.session()
        st = os.stat(s.sock)
        self.assertEqual(st.st_mode & 0o777, 0o600, "soket jen pro vlastnika")
        state = s.state()
        self.assertEqual(sorted(state), ["keyboard", "output", "theme", "workspace"], "bez window pro neprivilegovane")
        self.assertEqual(state["workspace"], {"event": "workspace", "current": 1, "count": 4})
        self.assertEqual(state["output"]["outputs"][0]["width"], W)
        self.assertEqual(state["keyboard"]["layouts"][0]["code"], "us")
        self.assertEqual(state["theme"]["theme"], "light")
        # LUXWM_SOCK pro programy, ktere luxwm spusti
        self.assertIn("ipc " + s.sock, s.log())

    def test_subscribe_commands_and_bad_input(self):
        s = self.session()
        c = Raw(s.sock)
        c.send('{"id": 1, "cmd": "subscribe", "events": ["workspace", "theme"]}')
        self.assertEqual(c.line(), {"id": 1, "ok": True})
        self.assertEqual(c.line()["event"], "workspace", "po odberu hned aktualni stav")
        self.assertEqual(c.line()["event"], "theme")
        t0 = time.monotonic()
        s.msg("switch-workspace", "3")
        ev = c.line()
        latency = (time.monotonic() - t0) * 1000
        self.assertEqual(ev, {"event": "workspace", "current": 3, "count": 4})
        print(f"\n  switch-workspace -> event {latency:.1f} ms (vcetne startu luxwm-msg)")
        c.send('{"id": 2, "cmd": "switch_workspace", "delta": -1}')
        self.assertEqual(c.line(), {"id": 2, "ok": True})
        self.assertEqual(c.line()["current"], 2)
        s.msg("set-theme", "dark")
        self.assertEqual(c.line(), {"event": "theme", "theme": "dark"})
        # nesmysly: odpoved s chybou, spojeni zustava
        c.send("this is not json")
        self.assertEqual(c.line(), {"ok": False, "error": "bad request"})
        c.send('[1, 2]')
        self.assertEqual(c.line()["error"], "bad request")
        c.send('{"id": 5, "cmd": "fly"}')
        self.assertEqual(c.line(), {"id": 5, "ok": False, "error": "unknown command"})
        c.send('{"id": 6, "cmd": "subscribe", "events": ["nope"]}')
        self.assertFalse(c.line()["ok"])
        c.send('{"id": 7, "cmd": "switch_workspace", "number": 99}')
        self.assertFalse(c.line()["ok"])
        c.send('{"id": 8, "cmd": "set_theme", "theme": "pink"}')
        self.assertFalse(c.line()["ok"])
        c.send('{"id": 9, "cmd": "get_state"}')
        self.assertTrue(c.line()["ok"])
        # luxwm-msg: kody konce
        self.assertEqual(s.msg("set-theme", "pink", check=False).returncode, 2)
        self.assertEqual(s.msg("switch-layout", "xx", check=False).returncode, 1)
        # prilis dlouhy radek = odpojeni, luxwm bezi dal
        c.send("x" * 70000)
        with self.assertRaises((EOFError, ConnectionResetError, BrokenPipeError)):
            c.line()
        self.assertIn("line too long", s.log())
        self.assertEqual(s.state()["workspace"]["current"], 2)
        c.close()

    def test_privileged_commands_need_allowlist(self):
        s = self.session()
        s.client("Alpha", app="alpha")
        s.client("Beta", app="beta")
        r = s.msg("list-windows", check=False)
        self.assertEqual(r.returncode, 1)
        self.assertIn("permission denied", r.stderr)
        r = s.msg("--watch", "window", check=False)
        self.assertEqual(r.returncode, 1, "tema window jen pro allowlist")
        self.assertIn("permission denied", r.stderr)
        self.assertEqual(s.msg("focus-window", "1", check=False).returncode, 1)
        s.allow(self.msg_priv)
        windows = json.loads(s.msg("list-windows", exe=self.msg_priv).stdout)["windows"]
        self.assertEqual([w["title"] for w in windows], ["Beta", "Alpha"], "od naposledy zamereneho")
        self.assertTrue(windows[0]["focused"])
        self.assertEqual(windows[1]["app_id"], "alpha")
        # privilegovany odber okna: udalost pri zmene zamereni
        out = os.path.join(s.dir, "watch.txt")
        with open(out, "w") as f:
            s.spawn(self.msg_priv, "--watch", "window", out=f)
        time.sleep(0.5)
        s.msg("focus-window", str(windows[1]["id"]), exe=self.msg_priv)
        time.sleep(0.5)
        events = [json.loads(line) for line in open(out) if line.strip()]
        self.assertEqual(events[0]["title"], "Beta", "aktualni stav po odberu")
        self.assertEqual({k: v for k, v in events[-1].items() if k != "frame"},
                         {"event": "window", "id": windows[1]["id"], "app_id": "alpha", "title": "Alpha"})
        self.assertEqual(len(events[-1]["frame"]), 4, "ram zamereneho okna pro Dock")
        # neprivilegovany porad nic: allowlist je podle programu, ne podle relace
        self.assertEqual(s.msg("list-windows", check=False).returncode, 1)

    def window_event(self, c, title, pred=lambda f: True, timeout=5.0):
        """Dalsi udalost window okna title, jehoz ram splnuje pred."""
        c.s.settimeout(timeout)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            ev = c.line()
            if ev.get("event") == "window" and ev["title"] == title and pred(ev["frame"]):
                return ev["frame"]
        self.fail(f"no window event for {title}")

    def test_dock_zone_placement_and_focused_frame(self):
        """Dock bez exkluzivni zony (uhyba oknum) hlasi svou vysku: nova okna lezi nad nim, vysoka se zmensi.
        Udalost window nese ram zamereneho okna i po maximalizaci, presunu mysi a konci Docku."""
        s = self.session()
        zone = 90
        r = s.msg("--raw", json.dumps({"cmd": "dock_zone", "output": "HEADLESS-1", "height": zone}), check=False)
        self.assertEqual(r.returncode, 1, "dock_zone jen pro allowlist")
        s.allow(sys.executable)
        c = Raw(s.sock)
        c.send('{"id": 1, "cmd": "subscribe", "events": ["window"]}')
        self.assertEqual(c.line(), {"id": 1, "ok": True})
        self.assertEqual(c.line(), {"event": "window", "id": 0, "app_id": "", "title": "", "frame": []})
        c.send(json.dumps({"id": 2, "cmd": "dock_zone", "output": "HEADLESS-1", "height": zone}))
        self.assertEqual(c.line(), {"id": 2, "ok": True})
        c.send('{"id": 3, "cmd": "dock_zone", "output": "HEADLESS-1", "height": -5}')
        self.assertFalse(c.line()["ok"])
        # vysoke okno (Nastaveni, Pruvodce): cele nad Dockem, i tlacitka dole
        s.client("Tall", app="tall", size="500x780")
        f = self.window_event(c, "Tall", lambda f: f[1] + f[3] <= H - zone)
        self.assertEqual((f[1], f[3]), (MARGIN, H - zone - 2 * MARGIN), f)
        self.assertEqual(f[0], (W - 500) // 2)
        # male okno na stred plochy nad Dockem
        s.client("Small", app="small", size="400x300")
        f = self.window_event(c, "Small")
        self.assertEqual(f[2:], [400, 300 + TITLE])
        self.assertLessEqual(f[1] + f[3], H - zone)
        # maximalizace: ram pres celou pouzitelnou plochu (Dock se schova)
        s.input("key super+Up")
        f = self.window_event(c, "Small", lambda f: f[3] == H)
        self.assertEqual(f, [0, 0, W, H])
        s.input("key super+Up")
        f = self.window_event(c, "Small", lambda f: f[2] == 400)
        # presun za zahlavi: udalost az po pusteni tlacitka
        x, y = f[0] + 200, f[1] + 10
        s.input(f"drag {x} {y} {x + 100} {y + 250} 300", wait=0.5)
        moved = self.window_event(c, "Small", lambda g: g[1] != f[1])
        self.assertEqual((moved[0] - f[0], moved[1] - f[1]), (100, 250))
        # Dock skoncil: misto se uz nedrzi
        c.close()
        time.sleep(0.3)
        c = Raw(s.sock)
        c.send('{"id": 1, "cmd": "subscribe", "events": ["window"]}')
        c.line()
        s.client("Tall2", app="tall2", size="500x780")
        f = self.window_event(c, "Tall2", lambda f: f[3] == H - 2 * MARGIN)
        self.assertEqual(f[1], MARGIN)
        c.close()
        self.assertNotIn("error in", s.log())

    def test_other_uid_is_rejected(self):
        if not shutil.which("podman") or not shutil.which("setpriv"):
            self.skipTest("podman unshare / setpriv chybi")
        s = self.session()
        # soket i adresar otevrit vsem: jinak by jiny uid zastavila uz prava souboru a SO_PEERCRED by se
        # neotestoval
        os.chmod(s.env["XDG_RUNTIME_DIR"], 0o755)
        os.chmod(s.sock, 0o666)
        probe = ("import socket,sys\n"
                 "c=socket.socket(socket.AF_UNIX);c.settimeout(3);c.connect(sys.argv[1])\n"
                 "c.sendall(b'{\"cmd\":\"get_state\"}\\n')\n"
                 "try:\n d=c.recv(100)\nexcept ConnectionResetError:\n d=b''\n"
                 "print('reply', len(d), d[:40])\n")
        r = subprocess.run(["podman", "unshare", "setpriv", "--reuid", "1000", "--regid", "1000", "--clear-groups",
                            "python3", "-I", "-c", probe, s.sock], capture_output=True, text=True, timeout=60)
        if "reply" not in r.stdout:
            self.skipTest("podman unshare nefunguje: " + r.stderr[-200:])
        self.assertIn("reply 0 ", r.stdout, "jiny uid nesmi dostat odpoved: " + r.stdout)
        self.assertRegex(s.log(), r"ipc: rejected uid (?!%d\b)\d+" % os.getuid())
        # stejny uid funguje dal
        self.assertEqual(s.state()["workspace"]["current"], 1)

    # ---- rozlozeni klavesnice ---------------------------------------------------------------------------

    def test_layout_switch_changes_typed_keys(self):
        s = self.session("xwayland = no\nxkb_layout = us,cz\nxkb_options = grp:shifts_toggle\n")
        kb = s.state()["keyboard"]
        self.assertEqual([l["code"] for l in kb["layouts"]], ["us", "cz"])
        self.assertEqual(kb["layouts"][1]["name"], "Czech")
        out = os.path.join(s.dir, "watch.txt")
        with open(out, "w") as f:
            s.spawn(MSG, "--watch", "keyboard", out=f)
        s.client("Typing")
        env = {"WLT_XKB_LAYOUT": "us,cz"}
        s.input("type 2y", env=env)
        s.msg("switch-layout", "cz")
        s.input("type 2y", env=env)
        s.msg("next-layout")
        s.input("type 2y", env=env)
        s.msg("switch-layout", "1")
        s.input("type 2y", env=env)
        keys = [line.split()[1] for line in s.clients_log().splitlines() if line.startswith("key ") and line.endswith(" down")]
        self.assertEqual(keys, ["2", "y", "ecaron", "z", "2", "y", "ecaron", "z"])
        events = [json.loads(line)["current"] for line in open(out) if line.strip()]
        self.assertEqual(events, [0, 1, 0, 1])
        # zkratky s latinkou funguji i v ceskem rozlozeni: Ctrl+Super+Right prepne plochu
        s.input("keydown ctrl", "keydown super", "key Right", "keyup super", "keyup ctrl", env=env)
        self.assertEqual(s.state()["workspace"]["current"], 2)

    def test_keyboard_from_config_reload_and_bad_layout(self):
        s = self.session()
        self.assertEqual(len(s.state()["keyboard"]["layouts"]), 1)
        s.write_user_conf("xkb_layout = de,cz,us\nxkb_variant = ,qwerty,\n")
        s.msg("reload")
        kb = s.state()["keyboard"]
        self.assertEqual([(l["code"], l["variant"]) for l in kb["layouts"]], [("de", ""), ("cz", "qwerty"), ("us", "")])
        self.assertEqual(kb["layouts"][1]["name"], "Czech (QWERTY)")
        s.msg("switch-layout", "2")
        self.assertEqual(s.state()["keyboard"]["current"], 2)
        # mene rozlozeni po reload: aktivni index se vrati do rozsahu
        s.write_user_conf("xkb_layout = cz\n")
        s.msg("reload")
        self.assertEqual(s.state()["keyboard"]["current"], 0)
        # neexistujici rozlozeni nesmi nechat system bez klavesnice
        s.write_user_conf("xkb_layout = nosuchlayout\n")
        s.msg("reload")
        self.assertGreaterEqual(len(s.state()["keyboard"]["layouts"]), 1)
        s.client("Still")
        s.input("type a")
        self.assertIn("key a down", s.clients_log())

    def test_input_config_reload_and_get_input(self):
        """Mys a touchpad z luxwm.conf; headless nema zarizeni libinput (ty overuje test_luxwm_libinput_vm.py)."""
        s = self.session()
        info = json.loads(s.msg("get-input").stdout)
        self.assertEqual(info["devices"], [])
        self.assertEqual(set(info["config"]), {"mouse", "touchpad"})
        self.assertTrue(all(v is None for kind in info["config"].values() for v in kind.values()), "bez polozek = vychozi zarizeni")
        s.write_user_conf("mouse_speed = -40\nmouse_accel = flat\nmouse_natural_scroll = yes\ntouchpad_speed = 250\n"
                          "touchpad_tap = yes\ntouchpad_tap_drag = no\ntouchpad_scroll_method = edge\n"
                          "touchpad_click_method = clickfinger\ntouchpad_disable_while_typing = maybe\n")
        s.msg("reload")
        config = json.loads(s.msg("get-input").stdout)["config"]
        self.assertEqual(config["mouse"]["speed"], -40)
        self.assertEqual(config["mouse"]["accel"], "flat")
        self.assertIs(config["mouse"]["natural_scroll"], True)
        self.assertIsNone(config["mouse"]["tap"])
        self.assertEqual(config["touchpad"]["speed"], 100, "mimo rozsah = hranice")
        self.assertIs(config["touchpad"]["tap"], True)
        self.assertIs(config["touchpad"]["tap_drag"], False)
        self.assertEqual(config["touchpad"]["scroll_method"], "edge")
        self.assertEqual(config["touchpad"]["click_method"], "clickfinger")
        self.assertIsNone(config["touchpad"]["disable_while_typing"])
        self.assertIn("bad touchpad_disable_while_typing = maybe", s.log())
        # smazana polozka vraci vychozi hodnotu zarizeni
        s.write_user_conf("touchpad_tap = yes\n")
        s.msg("reload")
        config = json.loads(s.msg("get-input").stdout)["config"]
        self.assertIsNone(config["mouse"]["speed"])
        self.assertIs(config["touchpad"]["tap"], True)

    def test_bar_badge_follows_layout_and_menu_switches(self):
        s = self.session("xwayland = no\nxkb_layout = us,cz\n")
        bar_exe = os.path.join(self.tmp, "luxos-bar")
        s.allow(bar_exe)
        conf = s.path("luxos")
        os.makedirs(conf, exist_ok=True)
        open(os.path.join(conf, "appearance"), "w").write("light\n")
        env = {**s.env, "LUXOS_WL_LIB": self.wl_lib, "LUXOS_BAR_TRACE": "1", "LUXOS_BAR_NOW": "2026-11-20 09:41"}
        log = os.path.join(s.dir, "bar.log")
        with open(log, "w") as f:
            s.spawn(bar_exe, env=env, out=f)

        def bar_lines():
            return open(log, errors="replace").read().splitlines()

        def wait_bar(text, timeout=8.0, start=0):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if any(text in line for line in bar_lines()[start:]):
                    return True
                time.sleep(0.05)
            raise AssertionError(f"{text!r} not in bar log:\n" + "\n".join(bar_lines()[-40:]))

        wait_bar("status keyboard US")
        t0 = time.monotonic()
        s.msg("switch-layout", "cz")
        wait_bar("status keyboard CZ")
        print(f"\n  badge US -> CZ {(time.monotonic() - t0) * 1000:.0f} ms")
        s.msg("switch-layout", "us")
        time.sleep(0.3)
        lines = [l for l in bar_lines() if l.startswith("status keyboard")]
        self.assertEqual(lines[-1], "status keyboard US")
        wait_bar("badge keyboard ")
        x, w = [int(v) for l in bar_lines() if l.startswith("badge keyboard ") for v in l.split()[2:4]][-2:]
        s.client("Focused", app="focused")
        # jeden klik na kod rozlozeni prepne hned na dalsi rozlozeni (bez nabidky), druhy zpet
        mark = len(bar_lines())
        t0 = time.monotonic()
        s.input(f"move {x + w // 2} 16", "click", wait=0.2)
        wait_bar("layout next 1", start=mark)
        wait_bar("status keyboard CZ", start=mark)
        print(f"  click US -> CZ {(time.monotonic() - t0) * 1000:.0f} ms")
        self.assertEqual(s.state()["keyboard"]["current"], 1)
        self.assertFalse(any("layout menu" in l for l in bar_lines()[mark:]), "klik neotevira nabidku")
        mark = len(bar_lines())
        s.input(f"move {x + w // 2} 16", "click", wait=0.2)
        wait_bar("status keyboard US", start=mark)
        self.assertEqual(s.state()["keyboard"]["current"], 0)
        # prave tlacitko: nabidka rozlozeni (xdg_popup s grabem) dostane klavesnici, i kdyz lista zadnou nema;
        # Esc ji zavre a klavesnice se vrati oknu (jedna virtualni klavesnice pro cely scenar)
        mark = len(bar_lines())
        s.input(f"move {x + w // 2} 16", "click right", "sleep 0.6", "key Escape", "sleep 0.4", "type q", wait=0.6)
        wait_bar("layout menu 2", start=mark)
        self.assertIn("key q down", s.clients_log(), "po zavreni nabidky pise okno")
        self.assertEqual(s.state()["keyboard"]["current"], 0, "prave tlacitko neprepina")
        before = s.clients_log().count("key Down down")
        s.input(f"move {x + w // 2} 16", "click right", "sleep 0.6", "key Down", "key Down", "key Return", wait=0.6)
        s.shot("bar-layout-menu.ppm")
        wait_bar("layout switch 1")
        self.assertEqual(s.clients_log().count("key Down down"), before, "sipky dostala nabidka, ne okno")
        self.assertEqual(s.state()["keyboard"]["current"], 1)
        wait_bar("status keyboard CZ")
        s.input("key Escape", wait=0.3)
        # podrzeni (500 ms) = nabidka misto prepnuti
        mark = len(bar_lines())
        s.input(f"move {x + w // 2} 16", "down", "sleep 0.8", "up", "sleep 0.3", "key Escape", wait=0.4)
        wait_bar("layout menu 2", start=mark)
        self.assertFalse(any("layout next" in l for l in bar_lines()[mark:]), "podrzeni neprepina")
        self.assertEqual(s.state()["keyboard"]["current"], 1)
        self.assertIsNone(s.procs[-1].poll(), "lista bezi")

    # ---- zkratky -----------------------------------------------------------------------------------------

    def probe(self, s, *args):
        r = subprocess.run([os.path.join(self.tmp, "luxos-wm-config-probe"), *args], env={
            **s.env, "LUXOS_SHORTCUTS_DEFAULTS": XFCE_DEFAULTS}, capture_output=True, text=True, timeout=20)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r.stdout

    def xfce_user(self, s, entries_cmd, entries_wm):
        def props(entries):
            return "".join(f'      <property name="{k.replace("<", "&lt;").replace(">", "&gt;")}" type="string" value="{v}"/>\n'
                           for k, v in entries)
        d = s.path("xfce4/xfconf/xfce-perchannel-xml")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "xfce4-keyboard-shortcuts.xml"), "w") as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n<channel name="xfce4-keyboard-shortcuts" version="1.0">\n'
                    '  <property name="commands" type="empty">\n    <property name="default" type="empty">\n'
                    '      <property name="&lt;Alt&gt;F2" type="string" value="xfce4-appfinder"/>\n    </property>\n'
                    '    <property name="custom" type="empty">\n' + props(entries_cmd) + '      <property name="override" type="bool" value="true"/>\n'
                    '    </property>\n  </property>\n  <property name="xfwm4" type="empty">\n    <property name="custom" type="empty">\n'
                    + props(entries_wm) + '    </property>\n  </property>\n</channel>\n')

    def test_shortcut_conversion_cases(self):
        s = self.session()
        self.xfce_user(s, [
            ("<Super>e", "nautilus"),                      # zmeneny prikaz
            ("<Super>l", ""),                              # vypnuta vychozi zkratka
            ("<Primary><Alt>k", "xfce4-terminal --drop-down"),  # vlastni zkratka
            ("<Super>t", "luxos-terminal"),                # stejne jako vychozi -> nic
            ("<Super>k", "xflock4"),                       # prikaz Xfce -> nahrada na Waylandu
            ("<Super>x", "xfce4-session-logout"),          # jen X11 -> preskocit
            ("<Super>F9", ""),                             # vypnuta zkratka, kterou luxwm nema -> nic
            ("<Shift><Super>Return", "luxos-terminal"),    # poradi modifikatoru
            ("<Super>space", "luxos-spotlight"),           # stary nazev Hledani = vychozi luxwm -> nic
        ], [
            ("<Super>Up", "fullscreen_key"),               # jina akce xfwm4
            ("<Super>w", "raise_window_key"),              # akce, kterou luxwm nema -> preskocit
            ("<Super><Primary>Left", "right_workspace_key"),  # jine poradi modifikatoru, jina akce
            ("<Alt>F4", "close_window_key"),               # stejne jako vychozi -> nic
        ])
        out = json.loads(self.probe(s, "overrides", s.path("xfce4/xfconf/xfce-perchannel-xml/xfce4-keyboard-shortcuts.xml"),
                                    XFCE_DEFAULTS, s.conf))
        self.assertEqual(out["keys"], {
            "<Super>e": "exec nautilus",
            "<Super>l": "",
            "<Primary><Alt>k": "exec xfce4-terminal --drop-down",
            "<Super>k": "exec loginctl lock-session",
            "<Shift><Super>Return": "exec luxos-terminal",
            "<Super>Up": "fullscreen_key",
            "<Primary><Super>Left": "right_workspace_key",
        })
        self.assertEqual(sorted(out["skipped"]), ["<Super>w = raise_window_key", "<Super>x = xfce4-session-logout"])

        # import do luxwm.conf: jen jednou, vlastni polozky luxwm maji prednost, komentare zustanou
        s.write_user_conf("# moje\nxwayland = no\n\n[keys]\n# vlastni\n<Super>e = exec gedit\n")
        self.assertEqual(self.probe(s, "import").strip(), "6")
        text = open(s.path("luxwm", "luxwm.conf")).read()
        self.assertIn("# moje\n", text)
        self.assertIn("# vlastni\n", text)
        self.assertIn("<Super>e = exec gedit\n", text)
        self.assertIn("<Super>l =\n", text)
        self.assertIn("<Primary><Super>Left = right_workspace_key\n", text)
        self.assertEqual(self.probe(s, "import").strip(), "0", "podruhe nic")
        self.assertEqual(text, open(s.path("luxwm", "luxwm.conf")).read())

        # luxwm prevedene zkratky opravdu pouziva
        s.msg("reload")
        s.client("One")
        s.client("Two")
        s.input("keydown ctrl", "keydown super", "key Left", "keyup super", "keyup ctrl")
        self.assertEqual(s.state()["workspace"]["current"], 2, "Ctrl+Super+Left = dalsi plocha")
        s.msg("switch-workspace", "1")
        s.input("keydown super", "key l", "keyup super")
        self.assertNotIn("exec loginctl", s.log().split("configuration reloaded")[-1], "Super+L vypnuta")

    def test_config_save_keeps_other_lines(self):
        s = self.session()
        s.write_user_conf("# hlava\nworkspaces = 3\n[keys]\n<Super>e = exec gedit\n# konec\n")
        self.probe(s, "save", json.dumps({"xkb_layout": "cz,us", "workspaces": None}),
                   json.dumps({"<Super><Primary>x": "exec foo", "<Super>e": None, "<Alt>F4": ""}))
        self.assertEqual(open(s.path("luxwm", "luxwm.conf")).read(),
                         "# hlava\nxkb_layout = cz,us\n[keys]\n# konec\n<Alt>F4 =\n<Primary><Super>x = exec foo\n")
        self.assertEqual(self.probe(s, "normalize", "<Super><Control>A").strip(), "<Primary><Super>a")
        self.assertEqual(self.probe(s, "normalize", "<Hyper>a").strip(), "")

    def test_settings_app_changes_shortcut_with_capture(self):
        s = self.session()
        app = os.path.join(self.tmp, "luxos-keyboard-settings")
        # "Zmenit..." u Zavrit okno (prvni radek karty Zkratky) stiskne skript stranky; klavesy jdou skutecnym vstupem
        script = os.path.join(s.dir, "ui-test")
        with open(script, "w") as f:
            f.write("wait 1500\nclick Change…\n")
        s.spawn(app, "--shortcuts", env={**s.env, "LUXOS_SHORTCUTS_DEFAULTS": XFCE_DEFAULTS, "LUXOS_UI_TEST": script})
        time.sleep(2.5)
        s.shot("keyboard-settings-shortcuts.ppm")
        self.assertTrue(s.wait_log("shortcuts suspended"), "luxwm vypne zkratky behem zadavani")
        s.input("keydown ctrl", "keydown alt", "key k", "keyup alt", "keyup ctrl", wait=1.0)
        conf = open(s.path("luxwm", "luxwm.conf")).read()
        self.assertIn("<Primary><Alt>k = close_window_key", conf)
        self.assertIn("<Alt>F4 =", conf)
        self.assertIn("<Super>q =", conf)
        self.assertTrue(s.wait_log("shortcuts resumed"))
        # nova zkratka zavre okno
        s.client("Victim", app="victim")
        s.input("keydown ctrl", "keydown alt", "key k", "keyup alt", "keyup ctrl", wait=0.8)
        s.allow(self.msg_priv)
        titles = [w["title"] for w in json.loads(s.msg("list-windows", exe=self.msg_priv).stdout)["windows"]]
        self.assertNotIn("Victim", titles)

    def test_suspend_shortcuts_until_disconnect(self):
        s = self.session()
        s.client("Keep", app="keep")
        c = Raw(s.sock)
        c.send('{"id": 1, "cmd": "suspend_shortcuts", "on": true}')
        self.assertTrue(c.line()["ok"])
        s.input("keydown ctrl", "keydown super", "key Right", "keyup super", "keyup ctrl")
        self.assertEqual(s.state()["workspace"]["current"], 1, "zkratky vypnute")
        c.close()
        time.sleep(0.3)
        s.input("keydown ctrl", "keydown super", "key Right", "keyup super", "keyup ctrl")
        self.assertEqual(s.state()["workspace"]["current"], 2, "po odpojeni klienta zase plati")

    # ---- vzhled ------------------------------------------------------------------------------------------

    def test_theme_switch_updates_titlebar_and_bar(self):
        s = self.session()
        bar_exe = os.path.join(self.tmp, "luxos-bar")
        s.allow(bar_exe)
        conf = s.path("luxos")
        os.makedirs(conf, exist_ok=True)
        open(os.path.join(conf, "appearance"), "w").write("light\n")
        log = os.path.join(s.dir, "bar.log")
        env = {**s.env, "LUXOS_WL_LIB": self.wl_lib, "LUXOS_BAR_TRACE": "1", "LUXOS_BAR_NOW": "2026-11-20 09:41"}
        with open(log, "w") as f:
            s.spawn(bar_exe, env=env, out=f)
        time.sleep(1.5)
        s.client("Themed", size="500x300")
        s.allow(self.msg_priv)
        windows = json.loads(s.msg("list-windows", exe=self.msg_priv).stdout)["windows"]
        self.assertEqual(windows[0]["title"], "Themed")
        before = s.shot("theme-light.ppm")
        # stred zahlavi okna 500x300 v horni tretine pouzitelne plochy s okrajem (pod listou)
        u = s.state()["output"]["outputs"][0]["usable"]
        cx = u[0] + u[2] // 2
        top = u[1] + MARGIN + (u[3] - 2 * MARGIN - 300 - TITLE) // 3
        probe = (cx - 150, top + TITLE // 2)
        light = pixel(before, *probe)
        open(os.path.join(conf, "appearance"), "w").write("dark\n")
        t0 = time.monotonic()
        s.msg("set-theme", "dark")
        after = s.shot("theme-dark.ppm")
        dark = pixel(after, *probe)
        print(f"\n  zahlavi {light} -> {dark}, {(time.monotonic() - t0) * 1000:.0f} ms vcetne snimku")
        self.assertGreater(sum(light), 600, "svetle zahlavi")
        self.assertLess(sum(dark), 200, "tmave zahlavi")
        self.assertIn("theme dark", s.log())
        deadline = time.monotonic() + 5
        while "ink=white" not in open(log).read() and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertIn("ink=white", open(log).read(), "lista v tmavem rezimu bile pismo")
        s.msg("set-theme", "light")
        self.assertEqual(pixel(s.shot("theme-light2.ppm"), *probe), light)


if __name__ == "__main__":
    unittest.main()
