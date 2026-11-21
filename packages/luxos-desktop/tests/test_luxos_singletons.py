#!/usr/bin/env python3
"""LuxOS - jedine instance v relaci (files/lsl/luxos_sys.lsl: instance_name, same_session).

    scripts/wl-test/run-all packages/luxos-desktop/tests/test_luxos_singletons.py

Abstraktni sockety jsou jen per UID a XDG_RUNTIME_DIR sdileji vsechny relace uzivatele (logind). Dve relace
stejneho uzivatele vedle sebe (jiny XDG_RUNTIME_DIR, jiny displej Waylandu nebo X) musi mit kazda svou instanci
a zadna nesmi druhou najit, nahradit ani ukoncit; druhe spusteni ve stejne relaci instanci najde.
Maly program v LSL nad modulem luxos_sys (bez GUI), prekladac lslc z PATH nebo LUXOS_LSLC.
"""
import os
import shutil
import subprocess
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
LSL = os.path.join(HERE, "..", "files", "lsl")
LSLC = os.environ.get("LUXOS_LSLC") or shutil.which("lslc")
TMP = tempfile.mkdtemp(prefix="luxos-singletons-")

PROBE = '''load luxos_sys
mode = arg(1)
if mode == "name":
    print luxos_sys.instance_name(arg(2))
elif mode == "same":
    print String(luxos_sys.same_session(Int(arg(2))))
elif mode == "hold":
    fd = luxos_sys.unix_listen(luxos_sys.instance_name(arg(2)))
    if fd < 0:
        print "busy"
        exit(3)
    end
    call luxos_sys.out("listening\\n")
    # do zavreni stdin
    call luxos_sys.wait_readable(0, -1)
elif mode == "ping":
    fd = luxos_sys.unix_connect(luxos_sys.instance_name(arg(2)))
    if fd < 0:
        print "nobody"
        exit(1)
    end
    print "connected"
end
'''


def build():
    if not LSLC:
        return None
    src = os.path.join(TMP, "probe.lsl")
    with open(src, "w") as f:
        f.write(PROBE)
    out = os.path.join(TMP, "probe")
    r = subprocess.run([LSLC, "--target", "linux-x86_64-gnu", "--system-bindings", LSL, src, out],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise AssertionError(r.stderr + r.stdout)
    return out


PROG = build()


@unittest.skipUnless(PROG, "needs lslc with the linux-x86_64-gnu target")
class Singletons(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp(prefix="s-", dir=TMP)
        self.addCleanup(shutil.rmtree, self.t, True)
        self.run_a = os.path.join(self.t, "run-a")
        self.run_b = os.path.join(self.t, "run-b")
        for d in (self.run_a, self.run_b):
            os.makedirs(d, 0o700)
        self.procs = []
        self.addCleanup(self.stop_all)

    def stop_all(self):
        for p in self.procs:
            if p.poll() is None:
                p.kill()
            p.wait(timeout=5)

    @staticmethod
    def session(**env):
        """Prostredi jedne relace: jen to, co klic urcuje (nic ze skutecne relace)."""
        return dict({"PATH": "/usr/bin:/bin"}, **env)

    def probe(self, env, *args):
        return subprocess.run([PROG, *args], env=env, capture_output=True, text=True, timeout=10)

    def name(self, **env):
        r = self.probe(self.session(**env), "name", "luxos-test")
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def hold(self, **env):
        """Instance drzici jmeno; [proces, "listening" nebo "busy"]."""
        p = subprocess.Popen([PROG, "hold", "luxos-test"], env=self.session(**env), stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, text=True)
        self.procs.append(p)
        return p, p.stdout.readline().strip()

    def test_names_per_session(self):
        a = self.name(XDG_RUNTIME_DIR=self.run_a, WAYLAND_DISPLAY="wayland-0")
        self.assertTrue(a.startswith("luxos-test-%d-" % os.getuid()), a)
        # tataz relace jinak zapsana: absolutni cesta socketu, XWayland navic, obrazovka X
        self.assertEqual(a, self.name(XDG_RUNTIME_DIR=self.run_a, WAYLAND_DISPLAY=self.run_a + "/wayland-0"))
        self.assertEqual(a, self.name(XDG_RUNTIME_DIR=self.run_a, WAYLAND_DISPLAY="wayland-0", DISPLAY=":4"))
        self.assertEqual(self.name(XDG_RUNTIME_DIR=self.run_a, DISPLAY=":0"),
                         self.name(XDG_RUNTIME_DIR=self.run_a, DISPLAY=":0.0"))
        others = [self.name(XDG_RUNTIME_DIR=self.run_b, WAYLAND_DISPLAY="wayland-0"),
                  self.name(XDG_RUNTIME_DIR=self.run_a, WAYLAND_DISPLAY="wayland-1"),
                  self.name(XDG_RUNTIME_DIR=self.run_a, DISPLAY=":0"),
                  self.name(XDG_RUNTIME_DIR=self.run_a, DISPLAY=":1"),
                  self.name(XDG_RUNTIME_DIR=self.run_a),
                  self.name()]
        self.assertEqual(len(set(others + [a])), len(others) + 1, others)

    def test_long_runtime_dir_keeps_short_distinct_names(self):
        # abstraktni jmeno se orizne na 100 bajtu: dlouha cesta (testy pod ~/...) nesmi splynout s jinou
        deep = os.path.join(self.t, "x" * 120)
        a = self.name(XDG_RUNTIME_DIR=deep + "a", WAYLAND_DISPLAY="wayland-0")
        b = self.name(XDG_RUNTIME_DIR=deep + "b", WAYLAND_DISPLAY="wayland-0")
        self.assertNotEqual(a, b)
        self.assertLess(len(a), 60)

    def test_two_sessions_side_by_side(self):
        a, state = self.hold(XDG_RUNTIME_DIR=self.run_a, WAYLAND_DISPLAY="wayland-0")
        self.assertEqual(state, "listening")
        # jine relace stejneho uzivatele: kazda vlastni instance
        for env in ({"XDG_RUNTIME_DIR": self.run_b, "WAYLAND_DISPLAY": "wayland-0"},
                    {"XDG_RUNTIME_DIR": self.run_a, "WAYLAND_DISPLAY": "wayland-1"},
                    {"XDG_RUNTIME_DIR": self.run_a, "DISPLAY": ":1"}):
            # klient jine relace instanci A nenajde
            r = self.probe(self.session(**env), "ping", "luxos-test")
            self.assertEqual(r.stdout.strip(), "nobody", env)
            p, state = self.hold(**env)
            self.assertEqual(state, "listening", env)
            r = self.probe(self.session(**env), "ping", "luxos-test")
            self.assertEqual(r.stdout.strip(), "connected", env)
        # stejna relace: jmeno je obsazene (druha instance preda pozadavek), klient se spoji
        p, state = self.hold(XDG_RUNTIME_DIR=self.run_a, WAYLAND_DISPLAY=self.run_a + "/wayland-0")
        self.assertEqual(state, "busy")
        self.assertEqual(p.wait(timeout=5), 3)
        r = self.probe(self.session(XDG_RUNTIME_DIR=self.run_a, WAYLAND_DISPLAY="wayland-0"), "ping", "luxos-test")
        self.assertEqual(r.stdout.strip(), "connected")
        for p in self.procs[:4]:
            self.assertIsNone(p.poll(), "zadna instance neskoncila")
        # A skonci: jeji jmeno je volne, ostatni relace beze zmeny
        a.stdin.close()
        a.wait(timeout=5)
        r = self.probe(self.session(XDG_RUNTIME_DIR=self.run_a, WAYLAND_DISPLAY="wayland-0"), "ping", "luxos-test")
        self.assertEqual(r.stdout.strip(), "nobody")
        for p in self.procs[1:4]:
            self.assertIsNone(p.poll())

    def test_same_session_of_process(self):
        env_a = self.session(XDG_RUNTIME_DIR=self.run_a, WAYLAND_DISPLAY="wayland-0", DISPLAY=":0")
        p = subprocess.Popen(["sleep", "30"], env=env_a)
        self.procs.append(p)
        time.sleep(0.1)
        same = lambda **env: self.probe(self.session(**env), "same", str(p.pid)).stdout.strip()  # noqa: E731
        self.assertEqual(same(XDG_RUNTIME_DIR=self.run_a, WAYLAND_DISPLAY="wayland-0"), "True")
        self.assertEqual(same(XDG_RUNTIME_DIR=self.run_a, WAYLAND_DISPLAY=self.run_a + "/wayland-0"), "True")
        self.assertEqual(same(XDG_RUNTIME_DIR=self.run_a, WAYLAND_DISPLAY="wayland-1"), "False")
        self.assertEqual(same(XDG_RUNTIME_DIR=self.run_b, WAYLAND_DISPLAY="wayland-0"), "False")
        self.assertEqual(same(XDG_RUNTIME_DIR=self.run_a, DISPLAY=":0"), "False")
        # mrtvy proces a neplatne PID: nikdy "stejna relace"
        p.kill()
        p.wait()
        self.assertEqual(same(XDG_RUNTIME_DIR=self.run_a, WAYLAND_DISPLAY="wayland-0"), "False")
        self.assertEqual(self.probe(env_a, "same", "0").stdout.strip(), "False")


BIN = os.path.join(HERE, "..", "files", "bin")


class SessionScripts(unittest.TestCase):
    """Skripty relace X11 (Dock, rofi Launchpadu) hledaji a ukoncuji jen procesy sveho displeje."""

    def setUp(self):
        self.t = tempfile.mkdtemp(prefix="x-", dir=TMP)
        self.addCleanup(shutil.rmtree, self.t, True)
        self.fake = os.path.join(self.t, "fake")
        os.makedirs(self.fake)
        self.log = os.path.join(self.t, "calls")
        self.procs = []
        self.addCleanup(self.stop_all)

    def stop_all(self):
        for p in self.procs:
            if p.poll() is None:
                p.kill()
            p.wait(timeout=5)

    def running(self, name, display):
        """Proces se jmenem name (kopie sleep) na displeji display - jako Plank nebo rofi jine relace."""
        d = os.path.join(self.t, "proc-" + display.strip(":"))
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, name)
        shutil.copy(shutil.which("sleep"), path)
        p = subprocess.Popen([path, "60"], env={"PATH": "/usr/bin:/bin", "DISPLAY": display})
        self.procs.append(p)
        time.sleep(0.2)
        return p

    def script(self, name, body):
        path = os.path.join(self.fake, name)
        with open(path, "w") as f:
            f.write("#!/bin/sh\n" + body)
        os.chmod(path, 0o755)

    def run_script(self, name, display, *args):
        env = {"PATH": self.fake + ":/usr/bin:/bin", "HOME": self.t, "USER": os.environ.get("USER") or "user",
               "XDG_RUNTIME_DIR": self.t, "DISPLAY": display, "FAKE_LOG": self.log}
        return subprocess.run([os.path.join(BIN, name), *args], env=env, capture_output=True, text=True, timeout=20)

    def calls(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log) as f:
            return f.read().split()

    def test_dock_ignores_plank_of_another_session(self):
        self.script("plank", 'echo "plank-$DISPLAY" >>"$FAKE_LOG"\n')
        self.script("xprop", "exit 1\n")
        other = self.running("plank", ":7")
        self.assertEqual(self.run_script("luxos-dock", ":5").returncode, 0)
        self.assertEqual(self.calls(), ["plank-:5"], "Dock teto relace se spusti")
        # Plank teto relace uz bezi: nic dalsiho
        self.running("plank", ":5")
        self.assertEqual(self.run_script("luxos-dock", ":5").returncode, 0)
        self.assertEqual(self.calls(), ["plank-:5"])
        self.assertIsNone(other.poll())

    def test_launchpad_toggle_closes_only_own_rofi(self):
        other = self.running("rofi", ":7")
        own = self.running("rofi", ":5")
        self.assertEqual(self.run_script("luxos-launchpad", ":5").returncode, 0)
        self.assertEqual(own.wait(timeout=5), -15, "rofi teto relace se zavre (prepinac)")
        self.assertIsNone(other.poll(), "rofi jine relace bezi dal")


if __name__ == "__main__":
    unittest.main()
