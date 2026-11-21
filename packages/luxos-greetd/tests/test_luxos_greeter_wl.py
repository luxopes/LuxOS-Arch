"""Testy prihlasovaci obrazovky v LSL (luxos-greeter pod `luxwm --greeter`) proti napodobenemu greetd.

Harness scripts/wl-test (headless pixman, nikdy skutecna obrazovka), luxwm z packages/luxwm/tests/build-host.sh,
greeter z packages/luxos-greetd/tests/build.sh. Napodobeny greetd v tomto procesu odpovida na zpravy IPC
(delka u32 + JSON) a zapisuje pozadavky; greeter vypisuje udalosti na stdout (LUXOS_GREETER_TRACE=1).

  scripts/wl-test/fetch-sysroot.sh && packages/luxwm/tests/build-host.sh && packages/luxos-greetd/tests/build.sh
  env -u DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u XAUTHORITY DBUS_SYSTEM_BUS_ADDRESS=unix:path=/nonexistent \
    systemd-run --user --scope -p TasksMax=300 -p MemoryMax=1G -- timeout 900 \
    python3 -m unittest -v packages/luxos-greetd/tests/test_luxos_greeter_wl.py
Snimky a mereni: out/greeter-test/results.
"""
import json
import os
import re
import shlex
import socket
import struct
import subprocess
import threading
import time
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
WLT = os.path.join(ROOT, "scripts", "wl-test", "wlt")
LUXWM_BUILD = os.environ.get("LUXWM_BUILD", os.path.join(ROOT, "out", "luxwm-test", "build"))
GREETER = os.environ.get("LUXOS_GREETER_BIN", os.path.join(ROOT, "out", "greeter-build", "luxos-greeter"))
SYSROOT = os.path.join(ROOT, "out", "wl-test", "sysroot")
RESULTS = os.path.join(ROOT, "out", "greeter-test", "results")
W, H = 1280, 800
PASSWORDS = {"luxos": "luxos", "eva": "heslo", "jan@firma.local": "tajne", "otisk": "luxos"}

PASSWD = """root:x:0:0::/root:/usr/bin/bash
luxos:x:1000:1000:LuxOS:/home/luxos:/usr/bin/lsh
eva:x:1001:1001:Eva Novakova:/home/eva:/usr/bin/bash
otisk:x:1002:1002:Otisk Prstu:/home/otisk:/usr/bin/bash
greeter:x:964:964::/var/lib/greetd:/usr/bin/nologin
nobody:x:65534:65534:Nobody:/:/usr/bin/nologin
"""


def px(u, v, lo):
    return max(float(lo), float(int(v * u + 0.5)))


class FakeGreetd:
    """greetd na socketu: vyzva k heslu, spatne heslo = auth_error, start_session si zapise."""

    def __init__(self, path):
        self.path = path
        self.requests = []
        self.sessions = []
        self.lock = threading.Lock()
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(path)
        self.server.listen(4)
        self.user = None
        self.steps = []
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        while True:
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            threading.Thread(target=self.client, args=(conn,), daemon=True).start()

    def recv(self, conn):
        head = conn.recv(4, socket.MSG_WAITALL)
        if len(head) < 4:
            return None
        n = struct.unpack("=I", head)[0]
        return json.loads(conn.recv(n, socket.MSG_WAITALL))

    def send(self, conn, msg):
        data = json.dumps(msg).encode()
        conn.sendall(struct.pack("=I", len(data)) + data)

    def question(self):
        if self.steps:
            kind, text = self.steps.pop(0)
            return {"type": "auth_message", "auth_message_type": kind, "auth_message": text}
        return {"type": "auth_message", "auth_message_type": "secret", "auth_message": "Password: "}

    def client(self, conn):
        while True:
            req = self.recv(conn)
            if req is None:
                return
            with self.lock:
                self.requests.append(req)
            t = req.get("type")
            if t == "create_session":
                self.user = req["username"]
                self.steps = [("info", "Place your finger on the fingerprint reader"),
                              ("error", "Failed to match fingerprint")] if self.user == "otisk" else []
                self.send(conn, self.question())
            elif t == "post_auth_message_response":
                if "response" not in req or req["response"] is None:
                    if self.steps == [] and self.user == "otisk":
                        time.sleep(0.3)
                    self.send(conn, self.question())
                    continue
                time.sleep(0.2)   # pam_unix zdrzi i spravne heslo
                if PASSWORDS.get(self.user) == req["response"]:
                    self.send(conn, {"type": "success"})
                else:
                    self.send(conn, {"type": "error", "error_type": "auth_error", "description": "Authentication failed"})
            elif t == "start_session":
                with self.lock:
                    self.sessions.append(req)
                self.send(conn, {"type": "success"})
            elif t == "cancel_session":
                self.user = None
                self.send(conn, {"type": "success"})
            else:
                self.send(conn, {"type": "error", "error_type": "error", "description": "unknown"})

    def close(self):
        self.server.close()

    def kinds(self):
        with self.lock:
            return [r["type"] for r in self.requests]


def wlt(*args, check=True):
    return subprocess.run([WLT, *args], check=check, capture_output=True, text=True, timeout=120).stdout.strip()


def children(pid):
    out = []
    try:
        for task in os.listdir(f"/proc/{pid}/task"):
            with open(f"/proc/{pid}/task/{task}/children") as f:
                out += [int(p) for p in f.read().split()]
    except OSError:
        pass   # proces mezitim skoncil
    return out


def descendants(pid):
    out = []
    for c in children(pid):
        out += [c] + descendants(c)
    return out


def comm(pid):
    try:
        with open(f"/proc/{pid}/comm") as f:
            return f.read().strip()
    except OSError:
        return ""


def pss_kb(pid):
    with open(f"/proc/{pid}/smaps_rollup") as f:
        return int(re.search(r"^Pss:\s+(\d+)", f.read(), re.M).group(1))


class Greeter:
    """luxwm --greeter s luxos-greeter v harnessu; napodobeny greetd na S/greetd.sock."""

    def __init__(self, name, env=None, state=None, sessions=True):
        self.base = os.path.join(ROOT, "out", "greeter-test", name)
        subprocess.run(["rm", "-rf", self.base], check=True)
        os.makedirs(os.path.join(self.base, "state"))
        os.makedirs(os.path.join(self.base, "icons"))
        with open(os.path.join(self.base, "passwd"), "w") as f:
            f.write(PASSWD)
        if state:
            with open(os.path.join(self.base, "state", "state"), "w") as f:
                f.write(state)
        wl = os.path.join(self.base, "wayland-sessions")
        xs = os.path.join(self.base, "xsessions")
        os.makedirs(wl)
        os.makedirs(xs)
        if sessions:
            with open(os.path.join(wl, "luxos.desktop"), "w") as f:
                f.write("[Desktop Entry]\nName=LuxOS\nExec=luxos-wayland-session\nDesktopNames=LuxOS\nType=Application\n")
            with open(os.path.join(xs, "luxos.desktop"), "w") as f:
                f.write("[Desktop Entry]\nName=LuxOS (X11)\nExec=startxfce4\nDesktopNames=XFCE\nType=Application\n")
            with open(os.path.join(xs, "xfce.desktop"), "w") as f:
                f.write("[Desktop Entry]\nName=Xfce Session\nExec=startxfce4\nType=Application\n")
        self.sock = os.path.join(self.base, "greetd.sock")
        self.greetd = FakeGreetd(self.sock)
        self.out = os.path.join(self.base, "greeter.out")
        genv = {"GREETD_SOCK": self.sock, "LUXOS_GREETER_TRACE": "1", "LUXOS_GREETER_PASSWD": os.path.join(self.base, "passwd"),
                "LUXOS_GREETER_ICONS": os.path.join(self.base, "icons"), "LUXOS_GREETER_STATE_DIR": os.path.join(self.base, "state"),
                "LUXOS_GREETER_WAYLAND_SESSIONS": wl, "LUXOS_GREETER_X_SESSIONS": xs,
                "LUXOS_GREETER_SYS": os.path.join(self.base, "sys"), "LUXOS_GREETER_POWER": "fake",
                "LUXOS_GREETER_NOW": "9:41", "LUXOS_GREETER_FPRINT": "0", "LUXOS_GREETER_CONF": "/nonexistent",
                "LUXOS_LOCK_POWER_SUPPLY": os.path.join(self.base, "power")}
        genv.update(env or {})
        # greeter s knihovnami systemu (ne ze sysrootu harnessu), luxwm s libluxcomp z build-host.sh
        cmd = "exec env -u LD_LIBRARY_PATH " + " ".join(f"{k}={shlex.quote(v)}" for k, v in genv.items()) \
            + f" {GREETER} >{self.out} 2>&1"
        envs = f"LUXCOMP_VIRTUAL_INPUT=1 LUXWM_TRACE=1 LD_LIBRARY_PATH={LUXWM_BUILD}:{SYSROOT}/usr/lib"
        t0 = time.monotonic()
        out = subprocess.run([WLT, "start", "--mode", "headless", "--size", f"{W}x{H}", "--",
                              os.path.join(LUXWM_BUILD, "luxwm"), "--greeter", cmd],
                             check=True, capture_output=True, text=True, timeout=120,
                             env={**os.environ, "WLT_COMPOSITOR_ENV": envs}).stdout
        self.dir = out.strip().splitlines()[-1]
        with open(os.path.join(self.dir, "compositor.pid")) as f:
            self.top = int(f.read())
        self.wait_for("ready ")
        self.ready_s = time.monotonic() - t0
        self.keys = None
        time.sleep(0.8)   # prvni snimek, vystup prenastaveny na 1280x800

    def trace(self):
        try:
            with open(self.out, errors="replace") as f:
                return f.read()
        except OSError:
            return ""

    def wait_for(self, needle, timeout=10.0, after=0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            t = self.trace()
            if needle in t[after:]:
                return t
            time.sleep(0.05)
        raise AssertionError(f"'{needle}' not in greeter output:\n{self.trace()}\n--- compositor:\n{self.log()}")

    def log(self):
        with open(os.path.join(self.dir, "compositor.log"), errors="replace") as f:
            return f.read()

    def input(self, *commands):
        # jedna klavesnice po cely test (nova klavesnice by GTK sebrala prvni klavesu)
        if self.keys is None:
            self.keys = subprocess.Popen([WLT, "input", self.dir], stdin=subprocess.PIPE, text=True)
            time.sleep(0.3)
        for c in commands:
            self.keys.stdin.write(c + "\n")
        self.keys.stdin.flush()
        time.sleep(0.15 * len(commands) + 0.2)

    def shot(self, name):
        os.makedirs(RESULTS, exist_ok=True)
        path = os.path.join(RESULTS, name + ".png")
        wlt("shot", self.dir, path)
        return path

    def alive(self):
        return os.path.exists(f"/proc/{self.top}") and comm(self.top) != ""

    def wait_exit(self, timeout=10.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if not any(comm(p) in ("luxwm", "luxos-greeter") for p in descendants(self.top)) and not self.alive():
                return True
            if not os.path.exists(f"/proc/{self.top}"):
                return True
            time.sleep(0.1)
        return False

    def stop(self):
        if self.keys:
            try:
                self.keys.stdin.close()
            except OSError:
                pass
            self.keys.wait(timeout=10)
        wlt("stop", self.dir, check=False)
        self.greetd.close()


# Rozmisteni jako luxos_lock_draw (tokens.LOCK, meritko u = vyska / 1080, nejmene 0.75)
U = max(0.75, H / 1080.0)


def bottom_row():
    d = px(U, 44.0, 34)
    label = float(int(px(U, 12.0, 10) * 1.35 + 0.5))
    return H - px(U, 40.0, 26) - label - px(U, 8.0, 5) - d / 2.0


def session_button():
    return int(px(U, 32.0, 20) + 20), int(bottom_row())


def session_item(i, count=2):
    row = px(U, 30.0, 24)
    pad = px(U, 5.0, 4)
    top = bottom_row() - px(U, 32.0, 26) / 2.0 - px(U, 6.0, 4) - (count * row + 2 * pad)
    return int(px(U, 32.0, 20) + 50), int(top + pad + row * (i + 0.5))


def power_buttons():
    pitch = px(U, 96.0, 70)
    x = W / 2.0 - pitch
    cy = bottom_row()
    return {"suspend": (int(x), int(cy)), "reboot": (int(x + pitch), int(cy)), "poweroff": (int(x + 2 * pitch), int(cy))}


def field_rect():
    d = px(U, 96.0, 64)
    ay = float(int(H * 0.62))
    name_y = ay + d / 2.0 + px(U, 14.0, 9)
    fy = name_y + float(int(px(U, 17.0, 13) * 1.3 + 0.5)) + px(U, 14.0, 9)
    fw = px(U, 300.0, 220)
    return int((W - fw) / 2.0), int(fy), int(fw), int(px(U, 40.0, 30))


def ppm_pixels(path):
    with open(path, "rb") as f:
        magic, size, depth, data = f.read().split(b"\n", 3)
    w, h = map(int, size.split())
    return w, data


def region(path, x0, y0, x1, y1):
    w, data = ppm_pixels(path)
    return [tuple(data[(y * w + x) * 3:(y * w + x) * 3 + 3]) for y in range(y0, y1) for x in range(x0, x1)]


class GreeterTest(unittest.TestCase):
    def setUp(self):
        self.g = None

    def tearDown(self):
        if self.g:
            if self._outcome.result.failures or self._outcome.result.errors:
                print(self.g.trace())
            self.g.stop()

    def test_login_ok_starts_wayland_session(self):
        self.g = g = Greeter("login")
        t = g.trace()
        self.assertIn("session=wayland:luxos.desktop", t)
        self.assertIn("users=3", t)           # luxos, eva, otisk (bez systemovych a nologin)
        print(f"greeter_ready_s={g.ready_s:.2f}")
        g.shot("login")
        # bez X serveru: luxwm --greeter XWayland nespousti
        procs = [comm(p) for p in descendants(g.top)]
        self.assertNotIn("Xwayland", procs)
        self.assertNotIn("Xorg", procs)
        pids = {comm(p): p for p in descendants(g.top) if comm(p) in ("luxwm", "luxos-greeter")}
        pss = {k: pss_kb(v) for k, v in pids.items()}
        print("pss_kb " + " ".join(f"{k}={v}" for k, v in sorted(pss.items())))
        g.input("type luxos", "key Return")
        g.wait_for("leaving")
        self.assertTrue(g.wait_exit(), "luxwm --greeter did not exit after start_session")
        self.assertEqual(g.greetd.kinds(), ["create_session", "post_auth_message_response", "start_session"])
        self.assertEqual(g.greetd.requests[0]["username"], "luxos")
        self.assertEqual(g.greetd.requests[1]["response"], "luxos")
        s = g.greetd.sessions[0]
        self.assertEqual(s["cmd"], ["luxos-wayland-session"])
        self.assertIn("XDG_SESSION_TYPE=wayland", s["env"])
        self.assertIn("XDG_CURRENT_DESKTOP=LuxOS", s["env"])
        with open(os.path.join(g.base, "state", "state")) as f:
            saved = f.read()
        self.assertIn("last-user=luxos", saved)
        self.assertIn("session.luxos=wayland:luxos.desktop", saved)
        self.assertIn("wayland-start=", saved)
        self.assertIn("greeter exited with status 0", g.log())

    def test_wrong_password_then_right(self):
        self.g = g = Greeter("wrong")
        fx, fy, fw, fh = field_rect()
        g.input("type spatne", "key Return")
        g.wait_for("hint error Incorrect password. Try again.")
        g.wait_for("shake")
        time.sleep(0.6)
        g.shot("wrong-password")
        # chyba je videt: cerveny okraj pole a svetle cervena hlaska pod nim (drive snimek = klidovy stav)
        shot = os.path.join(g.dir, "wrong.ppm")
        wlt("shot", g.dir, shot)
        rim = [p for p in region(shot, fx + 20, fy - 2, fx + fw - 20, fy) if p[0] > p[1] + 60 and p[0] > p[2] + 60]
        self.assertGreater(len(rim), 50)
        text = [p for p in region(shot, fx - 60, fy + fh + 6, fx + fw + 60, fy + fh + 30)
                if p[0] > 200 and 150 < p[1] < 200 and 150 < p[2] < 200]
        self.assertGreater(len(text), 20)
        self.assertIn("cancel_session", g.greetd.kinds())
        self.assertEqual(g.greetd.sessions, [])
        self.assertTrue(g.alive())
        n = len(g.trace())
        g.input("type luxos", "key Return")
        g.wait_for("leaving", after=n)
        self.assertEqual(g.greetd.sessions[0]["cmd"], ["luxos-wayland-session"])
        self.assertEqual([r.get("response") for r in g.greetd.requests if r["type"] == "post_auth_message_response"],
                         ["spatne", "luxos"])

    def test_caps_lock(self):
        self.g = g = Greeter("caps")
        g.input("key Caps_Lock")
        g.wait_for("caps True")
        g.shot("caps-lock")
        g.input("type SPATNE", "key Return")
        g.wait_for("hint error Incorrect password – Caps Lock is on")
        g.input("key Caps_Lock")
        g.wait_for("caps False")

    def test_domain_user(self):
        info = os.path.join(ROOT, "out", "greeter-test", "domain.json")
        os.makedirs(os.path.dirname(info), exist_ok=True)
        with open(info, "w") as f:
            json.dump({"joined": True, "domain": "firma.local", "short": "FIRMA", "online": True}, f)
        self.g = g = Greeter("domain", env={"LUXOS_GREETER_DOMAIN_INFO": info})
        self.assertIn("domain firma.local", g.trace())
        # luxos, eva, otisk, Jiny...: vpravo na konec
        g.input("key Right", "key Right", "key Right")
        g.wait_for("user  session")
        g.shot("domain-other")
        g.input("type jan@firma.local", "key Return")
        g.wait_for("send create_session")
        g.input("type tajne", "key Return")
        g.wait_for("leaving")
        self.assertEqual(g.greetd.requests[0], {"type": "create_session", "username": "jan@firma.local"})
        self.assertEqual(g.greetd.requests[1]["response"], "tajne")
        with open(os.path.join(g.base, "state", "state")) as f:
            self.assertIn("last-user=jan@firma.local", f.read())

    def test_session_choice_x11(self):
        self.g = g = Greeter("session")
        x, y = session_button()
        g.input(f"move {x} {y}", "click")
        g.wait_for("menu True")
        g.shot("session-menu")
        x, y = session_item(1)
        g.input(f"move {x} {y}", "click")
        g.wait_for("session x11:luxos.desktop")
        g.wait_for("click menu")
        g.shot("session-x11")
        g.input("type luxos", "key Return")
        g.wait_for("leaving")
        s = g.greetd.sessions[0]
        self.assertEqual(s["cmd"], ["/usr/lib/luxos/luxos-x11-session", "startxfce4"])
        self.assertIn("XDG_SESSION_TYPE=x11", s["env"])
        # Xfce Session (xfce.desktop) se nenabizi, dalsi klik vraci Wayland
        with open(os.path.join(g.base, "state", "state")) as f:
            saved = f.read()
        self.assertIn("session.luxos=x11:luxos.desktop", saved)
        self.assertNotIn("wayland-start", saved)

    def test_user_switch_remembers_session(self):
        self.g = g = Greeter("users", state="last-user=eva\nsession.eva=x11:luxos.desktop\n")
        self.assertIn("session=x11:luxos.desktop", g.trace())
        g.input("key Left")
        g.wait_for("user luxos session wayland:luxos.desktop")
        g.input("type luxos", "key Return")
        g.wait_for("leaving")
        self.assertEqual(g.greetd.requests[0]["username"], "luxos")

    def test_legacy_nvidia_defaults_to_x11(self):
        base = os.path.join(ROOT, "out", "greeter-test", "nvidia-sys")
        os.makedirs(os.path.join(base, "module", "nvidia"), exist_ok=True)
        with open(os.path.join(base, "module", "nvidia", "version"), "w") as f:
            f.write("470.256.02\n")
        self.g = g = Greeter("nvidia", env={"LUXOS_GREETER_SYS": base})
        self.assertIn("session=x11:luxos.desktop legacy_gpu=True", g.trace())

    def test_failed_wayland_start_selects_x11(self):
        self.g = g = Greeter("fallback", state=f"wayland-start={int(time.time())}\n")
        self.assertIn("wayland session failed, x11 selected", g.trace())
        self.assertIn("session=x11:luxos.desktop", g.trace())
        g.shot("fallback-notice")
        with open(os.path.join(g.base, "state", "state")) as f:
            self.assertNotIn("wayland-start", f.read())

    def test_fingerprint_messages(self):
        self.g = g = Greeter("fprint", env={"LUXOS_GREETER_FPRINT": "1"}, state="last-user=otisk\n")
        # otisk: relace se zaklada hned po vyberu uzivatele, info a error z pam_fprintd jsou hlasky
        g.wait_for("hint Touch the fingerprint sensor or enter your password")
        g.wait_for("hint error Fingerprint not recognized. Try again or enter your password.")
        g.input("type luxos", "key Return")
        g.wait_for("leaving")
        kinds = g.greetd.kinds()
        self.assertEqual(kinds[0], "create_session")
        self.assertEqual(kinds[-1], "start_session")

    def test_idle_then_prompt(self):
        """Klid: jen tapeta, hodiny a stav (zadne pole); prvni klavesa ukaze vyzvu a je uz v poli."""
        self.g = g = Greeter("idle")
        fx, fy, fw, fh = field_rect()
        idle = os.path.join(g.dir, "idle.ppm")
        wlt("shot", g.dir, idle)
        g.shot("idle")
        g.input("type l")
        g.wait_for("prompt")
        time.sleep(0.6)
        typed = os.path.join(g.dir, "typed.ppm")
        wlt("shot", g.dir, typed)
        g.shot("prompt")
        box = (fx + 10, fy + 4, fx + fw - 10, fy + fh - 4)
        changed = sum(a != b for a, b in zip(region(idle, *box), region(typed, *box)))
        self.assertGreater(changed, 500)
        g.input("type uxos", "key Return")
        g.wait_for("leaving")
        self.assertEqual(g.greetd.requests[1]["response"], "luxos")

    def test_power_buttons(self):
        self.g = g = Greeter("power")
        x, y = power_buttons()["reboot"]
        g.input(f"move {x} {y}", "click")
        g.wait_for("power reboot")
        x, y = power_buttons()["poweroff"]
        g.input(f"move {x} {y}", "click")
        g.wait_for("power poweroff")


if __name__ == "__main__":
    unittest.main()
