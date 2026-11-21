"""LuxOS - spolecne pomucky testu aplikaci v LSL (files/lsl), ktere nahradily programy v Pythonu.

  build(nazev, tmp)        prelozi files/lsl/<nazev>.lsl (lslc z PATH nebo LUXOS_LSLC); bez lslc SkipTest
  Xvfb()                   vlastni Xvfb na volnem cisle :90-:199 (nikdy skutecna obrazovka), .display, .stop()
  Bus()                    soukromy dbus-daemon, .address, .stop()
  App(argv, env)           aplikace s LUXOS_TEST_CONTROL=1 (luxos_testctl): send(prikaz), line(predpona),
                           dump() -> okna, find(okna, ...) -> widget, wait(podminka), pss_kb(), stop()
  shot(display, cesta)     snimek cele obrazovky Xvfb do PNG

Testy jinak pouzivaji scripts/luxos_testguard.py (import v hlavicce testu): skutecna relace, systemova sbernice
ani kamery nejsou dostupne.
"""
import json
import os
import select
import shutil
import signal
import subprocess
import sys
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
LSL_DIR = os.path.normpath(os.path.join(HERE, "..", "files", "lsl"))
I18N = os.path.normpath(os.path.join(HERE, "..", "..", "luxos-i18n", "files"))


def build(name, tmp):
    lslc = os.environ.get("LUXOS_LSLC") or shutil.which("lslc")
    if not lslc:
        raise unittest.SkipTest("lslc (lsl) is not installed")
    out = os.path.join(tmp, name)
    r = subprocess.run([lslc, "--target", "linux-x86_64-gnu", "--system-bindings", LSL_DIR,
                        os.path.join(LSL_DIR, name + ".lsl"), out], capture_output=True, text=True, timeout=900)
    if r.returncode:
        raise AssertionError("lslc failed: " + (r.stdout + r.stderr)[-3000:])
    return out


def _die_with_parent():
    try:
        import ctypes
        ctypes.CDLL("libc.so.6").prctl(1, signal.SIGTERM)
    except (OSError, AttributeError):
        pass


class Xvfb:
    def __init__(self, size="1366x768"):
        if not shutil.which("Xvfb"):
            raise unittest.SkipTest("Xvfb is missing")
        for n in range(90, 200):
            if not os.path.exists("/tmp/.X11-unix/X%d" % n) and not os.path.exists("/tmp/.X%d-lock" % n):
                break
        else:
            raise unittest.SkipTest("no free display")
        self.display = ":%d" % n
        self.proc = subprocess.Popen(["Xvfb", self.display, "-screen", "0", size + "x24", "-nolisten", "tcp"],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     preexec_fn=_die_with_parent)
        for _ in range(200):
            if os.path.exists("/tmp/.X11-unix/X%d" % n):
                break
            time.sleep(0.05)

    def stop(self):
        self.proc.terminate()
        self.proc.wait(5)


class Bus:
    def __init__(self):
        if not shutil.which("dbus-daemon"):
            raise unittest.SkipTest("dbus-daemon is missing")
        self.proc = subprocess.Popen(["dbus-daemon", "--session", "--nofork", "--print-address=1"],
                                     stdout=subprocess.PIPE, text=True, preexec_fn=_die_with_parent)
        self.address = self.proc.stdout.readline().strip()

    def stop(self):
        self.proc.terminate()
        self.proc.wait(5)


class App:
    """Aplikace rizena pres stdin (luxos_testctl); stdout se cte po radcich bez vlaken."""

    def __init__(self, argv, env):
        env = dict(env, LUXOS_TEST_CONTROL="1", NO_AT_BRIDGE="1", GTK_USE_PORTAL="0")
        env.setdefault("LUXOS_I18N_DIR", I18N)
        self.proc = subprocess.Popen(argv, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, start_new_session=True)
        self.buf = b""
        self.lines = []
        self.err = None

    def send(self, command):
        self.proc.stdin.write((command + "\n").encode())
        self.proc.stdin.flush()

    def _read(self, timeout):
        r, _, _ = select.select([self.proc.stdout], [], [], timeout)
        if not r:
            return False
        chunk = os.read(self.proc.stdout.fileno(), 65536)
        if not chunk:
            return False
        self.buf += chunk
        while b"\n" in self.buf:
            line, self.buf = self.buf.split(b"\n", 1)
            self.lines.append(line.decode("utf-8", "replace"))
        return True

    def line(self, prefix, timeout=10.0):
        """Prvni dosud neprectena radka s predponou (ostatni se zahodi)."""
        end = time.monotonic() + timeout
        while True:
            while self.lines:
                line = self.lines.pop(0)
                if line.startswith(prefix):
                    return line[len(prefix):].lstrip()
            left = end - time.monotonic()
            if left <= 0 or (not self._read(left) and self.proc.poll() is not None):
                raise AssertionError("no line %r; stderr: %s" % (prefix, self.stderr()))

    def ask(self, command, prefix=None, timeout=10.0):
        self.send(command)
        if prefix:
            return self.line(prefix, timeout)
        return self.line("done " + command.split(" ")[0], timeout)

    def dump(self):
        self.send("dump")
        return json.loads(self.line("dump "))

    def wait(self, cond, timeout=8.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if cond():
                return True
            time.sleep(0.1)
        return cond()

    def pss_kb(self):
        with open("/proc/%d/smaps_rollup" % self.proc.pid) as f:
            for line in f:
                if line.startswith("Pss:"):
                    return int(line.split()[1])
        return 0

    def stderr(self):
        if self.proc.poll() is None:
            return "(running)"
        if self.err is None:
            self.err = self.proc.stderr.read().decode("utf-8", "replace")[-3000:]
        return self.err

    def stop(self):
        if self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        try:
            self.proc.wait(10)
        except subprocess.TimeoutExpired:
            os.killpg(self.proc.pid, signal.SIGKILL)
            self.proc.wait(5)
        self.stderr()
        for f in (self.proc.stdin, self.proc.stdout, self.proc.stderr):
            try:
                f.close()
            except OSError:
                pass


def widgets(windows, dialog=None):
    out = []
    for w in windows:
        if dialog is None or w["dialog"] == dialog:
            out.extend(w["widgets"])
    return out


def find(windows, name=None, text=None, kind=None, dialog=None):
    for w in widgets(windows, dialog):
        if name is not None and w.get("name") != name:
            continue
        if text is not None and w.get("text") != text and w.get("tip") != text:
            continue
        if kind is not None and w["t"] != kind:
            continue
        return w
    return None


def texts(windows, dialog=None):
    return [w["text"] for w in widgets(windows, dialog) if w["t"] == "GtkLabel" and w["vis"]]


SHOT_CODE = ("import sys, gi; gi.require_version('Gdk', '3.0'); from gi.repository import Gdk; "
             "r = Gdk.get_default_root_window(); "
             "Gdk.pixbuf_get_from_window(r, 0, 0, r.get_width(), r.get_height()).savev(sys.argv[1], 'png', [], [])")


def shot(display, path):
    env = {k: v for k, v in os.environ.items() if k not in ("WAYLAND_DISPLAY", "XAUTHORITY")}
    env["DISPLAY"] = display
    subprocess.run([sys.executable, "-c", SHOT_CODE, path], env=env, timeout=20, check=True)
