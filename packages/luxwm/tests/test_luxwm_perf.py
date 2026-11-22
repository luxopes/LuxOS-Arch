"""Vykon luxwm pod pixman (pripominka 41: v QEMU bez 3D je Xfce rychlejsi): posouvani maximalizovaneho okna (wl_shm,
cele poskozeni jako Firefox), psani (male poskozeni jako terminal) a presun okna, s listou a Dockem s materialem.

Meri se cas snimku kompozitoru (LUXCOMP_STATS: prepocet materialu + vykresleni), pocet prepoctu materialu, CPU
kompozitoru a snimky klienta za sekundu. Vypis: radky "perf ..." (pro porovnani pred/po), meze jen hrube.

  packages/luxwm/tests/build-host.sh
  scripts/wl-test/run-all packages/luxwm/tests/test_luxwm_perf.py
"""
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_luxwm_window_material import BUILD, HERE, RESULTS, SYSROOT, Session, render_node  # noqa: E402

PROBE = ""
SIZE = os.environ.get("LUXWM_PERF_SIZE", "1920x1080")
SECONDS = float(os.environ.get("LUXWM_PERF_SECONDS", "5"))


def build_probe():
    global PROBE
    if PROBE:
        return
    os.makedirs(RESULTS, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="perf-", dir=RESULTS)
    scanner = os.path.join(SYSROOT, "usr/bin/wayland-scanner")
    env = {**os.environ, "LD_LIBRARY_PATH": os.path.join(SYSROOT, "usr/lib")}
    code = []
    for xml in (os.path.join(SYSROOT, "usr/share/wayland-protocols/stable/xdg-shell/xdg-shell.xml"),
                os.path.join(HERE, "..", "..", "luxcomp", "protocols", "wlr-layer-shell-unstable-v1.xml")):
        base = os.path.basename(xml)[:-4]
        subprocess.run([scanner, "client-header", xml, os.path.join(tmp, base + "-client-protocol.h")], check=True, env=env)
        code.append(os.path.join(tmp, base + ".c"))
        subprocess.run([scanner, "private-code", xml, code[-1]], check=True, env=env)
    PROBE = os.path.join(tmp, "perf-probe")
    subprocess.run(["gcc", "-O2", "-Wall", "-I", tmp, "-o", PROBE, os.path.join(HERE, "perf-probe.c"), *code,
                    "-lwayland-client"], check=True)


def cpu_ticks(pid):
    with open(f"/proc/{pid}/stat") as f:
        fields = f.read().rsplit(")", 1)[1].split()
    return int(fields[11]) + int(fields[12])


STATS = re.compile(r"blur stats tier (\d) frames (\d+) max ([\d.]+) ms avg ([\d.]+) ms over 8 ms (\d+), "
                   r"updates (\d+) max ([\d.]+) ms avg ([\d.]+) ms")


@unittest.skipUnless(os.path.exists(os.path.join(BUILD, "luxwm")), "build first: packages/luxwm/tests/build-host.sh")
class Base:
    render = ""
    label = "pixman"

    @classmethod
    def setUpClass(cls):
        build_probe()

    def setUp(self):
        import test_luxwm_window_material as m
        m.W, m.H = map(int, SIZE.split("x"))
        self.s = Session(f"perf{os.getpid() % 10000}-{self.label}-{self._testMethodName[5:12]}", self.render)
        self.addCleanup(self.s.stop)
        for args in (("perf-bar@bar:0", "30"), ("perf-dock@dock:24", "64", "640")):
            p = self.s.spawn(PROBE, "panel", *args)
            self.assertEqual(p.stdout.readline().strip(), "mapped")
        time.sleep(0.5)

    def measure(self, name, run):
        log0 = len(self.s.log())
        t0, c0 = time.monotonic(), cpu_ticks(self.s.pid)
        extra = run()
        took, cpu = time.monotonic() - t0, cpu_ticks(self.s.pid) - c0
        log = self.s.log()[log0:]
        stats = [tuple(float(v) for v in m) for m in STATS.findall(log)]
        frames = sum(s[1] for s in stats)
        avg = sum(s[1] * s[3] for s in stats) / frames if frames else 0
        worst = max((s[2] for s in stats), default=0)
        updates = sum(s[5] for s in stats)
        upd_ms = sum(s[5] * s[7] for s in stats) / updates if updates else 0
        cpu_pct = 100 * cpu / os.sysconf("SC_CLK_TCK") / took
        line = (f"perf {self.label} {name}: frame avg {avg:.2f} ms max {worst:.2f} ms, {int(frames)} frames, "
                f"material updates {int(updates)} avg {upd_ms:.2f} ms, compositor cpu {cpu_pct:.0f}%{extra or ''}")
        print("\n" + line, flush=True)
        with open(os.path.join(RESULTS, "perf.txt"), "a") as f:
            f.write(line + "\n")
        return avg, cpu_pct

    def client(self, mode):
        p = self.s.spawn(PROBE, mode, str(SECONDS))
        self.assertEqual(p.stdout.readline().strip(), "mapped")

        def run():
            time.sleep(1)
            self.s.shot(f"perf-{self.label}-{mode}.png")
            out = p.stdout.readline().strip()
            self.fps = float(out.split()[-1])
            return f", client {out}"
        return run

    def test_scroll(self):
        # ~ posouvani ve Firefoxu: cele okno kazdy snimek
        self.measure("scroll", self.client("scroll"))
        self.assertGreater(self.fps, 20)

    def test_typing(self):
        self.measure("typing", self.client("type"))

    def test_move(self):
        p = self.s.spawn(PROBE, "type", "60")
        self.assertEqual(p.stdout.readline().strip(), "mapped")
        time.sleep(0.3)
        self.s.input("key super+Up")      # z maximalizovaneho do normalniho
        time.sleep(0.5)
        v = self.s.views()["type"]
        x, y = v["x"] + v["w"] // 2, v["y"] - 15

        def run():
            ms = int(SECONDS * 1000 / 2)
            self.s.input(f"drag {x} {y} {x - 300} {y + 200} {ms}", f"drag {x - 300} {y + 200} {x} {y} {ms}")
        self.measure("move", run)


class Pixman(Base, unittest.TestCase):
    pass


@unittest.skipUnless(render_node(), "no accessible render node")
class Gles2(Base, unittest.TestCase):
    render = render_node()
    label = "gles2"


if __name__ == "__main__":
    unittest.main()
