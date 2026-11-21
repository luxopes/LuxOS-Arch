#!/usr/bin/env python3
"""LuxOS - O tomto pocitaci (files/lsl/luxos-about.lsl): udaje o pocitaci, pamet jako na krabici, kratke nazvy
grafiky, zadny zargon ("Shell lsh") a okno se otevre i bez UTF-8 locale (LANG=C / POSIX - drive yad padal
s "Invalid byte sequence in conversion input").

    env -u DISPLAY python3 -m unittest packages/luxos-desktop/tests/test_luxos_about.py -v

Prekladac lslc (balik lsl) je potreba; bez nej se testy preskoci. Udaje jsou z falesne slozky
(LUXOS_ABOUT_ROOT, falesne lspci a df) - nic se necte ze skutecneho pocitace. Okno jen ve vlastnim Xvfb.
"""
# LuxOS: testy GUI nikdy na skutecne obrazovce a v relaci uzivatele (scripts/luxos_testguard.py)
import os as _tg_os, sys as _tg_sys  # noqa: E401
_tg_d = _tg_os.path.dirname(_tg_os.path.abspath(__file__))
while _tg_d != "/" and not _tg_os.path.exists(_tg_os.path.join(_tg_d, "scripts", "luxos_testguard.py")):
    _tg_d = _tg_os.path.dirname(_tg_d)
if _tg_d != "/":
    _tg_sys.path.insert(0, _tg_os.path.join(_tg_d, "scripts"))
    import luxos_testguard  # noqa: E402,F401
else:
    _tg_os.environ.pop("DISPLAY", None)
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.normpath(os.path.join(HERE, "..", "files", "lsl", "luxos-about.lsl"))
I18N = os.path.normpath(os.path.join(HERE, "..", "..", "luxos-i18n", "files"))
LSPCI = """00:00.0 Host bridge: Advanced Micro Devices, Inc. [AMD] Renoir/Cezanne Root Complex
01:00.0 VGA compatible controller: NVIDIA Corporation TU117M [GeForce GTX 1650 Mobile / Max-Q] (rev a1)
05:00.0 VGA compatible controller: Advanced Micro Devices, Inc. [AMD/ATI] Lucienne (rev c1)
06:00.0 3D controller: Intel Corporation Alder Lake-P GT2 [Iris Xe Graphics] (rev 0c)
"""
TMP = None
BINARY = None


def setUpModule():
    global TMP, BINARY
    if not shutil.which("lslc"):
        raise unittest.SkipTest("lslc (lsl) is not installed")
    TMP = tempfile.mkdtemp(prefix="luxos-about-", dir=luxos_testguard._private_dir())
    BINARY = os.path.join(TMP, "luxos-about")
    r = subprocess.run(["lslc", "--target", "linux-x86_64-gnu", SRC, BINARY], capture_output=True, text=True,
                       timeout=600)
    if r.returncode:
        raise AssertionError("lslc failed: " + r.stderr[-3000:])


def tearDownModule():
    if TMP:
        shutil.rmtree(TMP, True)


def write(path, text, mode=0o644):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)
    os.chmod(path, mode)


def fake_root(mem_kb=15681220, battery="87", vendor="AT&T <Inc>", model="Book 14"):
    root = tempfile.mkdtemp(prefix="root-", dir=TMP)
    write(root + "/etc/os-release", 'NAME="LuxOS"\nID=luxos\nVERSION="1.0.2 (Sirius)"\nVERSION_ID=1.0.2\nBUILD_ID=20261117\n')
    write(root + "/proc/cpuinfo", "processor\t: 0\nmodel name\t: AMD Ryzen 5   5500U with Radeon Graphics\n\n"
                                  "processor\t: 1\nmodel name\t: AMD Ryzen 5   5500U with Radeon Graphics\n")
    write(root + "/proc/meminfo", "MemTotal:       %d kB\nMemFree:         100000 kB\n" % mem_kb)
    write(root + "/proc/sys/kernel/osrelease", "7.3.3-1-luxos\n")
    write(root + "/sys/class/dmi/id/sys_vendor", vendor + "\n")
    write(root + "/sys/class/dmi/id/product_name", model + "\n")
    if battery is not None:
        write(root + "/sys/class/power_supply/BAT0/capacity", battery + "\n")
    write(root + "/sys/class/power_supply/AC/online", "1\n")
    write(root + "/bin/lspci", "#!/bin/sh\ncat <<'EOF'\n" + LSPCI + "EOF\n", 0o755)
    write(root + "/bin/df", "#!/bin/sh\nprintf 'Avail  Size\\n 166G  476G\\n'\n", 0o755)
    return root


def env_for(root, **extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("LC_", "LANG", "LANGUAGE"))}
    env.update(LUXOS_ABOUT_ROOT=root, LUXOS_ABOUT_LSPCI=root + "/bin/lspci", LUXOS_ABOUT_DF=root + "/bin/df",
               LUXOS_I18N_DIR=I18N)
    env.update(extra)
    luxos_testguard.check_env(env)
    return env


def info(root, **extra):
    r = subprocess.run([BINARY, "--print"], env=env_for(root, **extra), capture_output=True, text=True, timeout=30)
    if r.returncode:
        raise AssertionError(r.stderr)
    return dict(line.split("\t", 1) for line in r.stdout.splitlines() if "\t" in line)


class Info(unittest.TestCase):
    def test_rows(self):
        rows = info(fake_root(), LC_ALL="C")
        self.assertEqual(rows["Computer"], "AT&T <Inc> Book 14")       # obycejny text, ne Pango markup
        self.assertEqual(rows["Processor"], "AMD Ryzen 5 5500U with Radeon Graphics")
        self.assertEqual(rows["Memory"], "16 GB")
        # kratke nazvy, nejvys dve grafiky (dlouhe nazvy z lspci roztahly okno pres pul obrazovky)
        self.assertEqual(rows["Graphics"], "NVIDIA GeForce GTX 1650 Mobile / Max-Q, AMD Lucienne")
        self.assertEqual(rows["Storage"], "166G available of 476G")
        self.assertEqual(rows["Battery"], "87 %")
        self.assertEqual(rows["Linux kernel"], "7.3.3-1-luxos")
        # zargon "Shell lsh 1.0.0" pryc
        self.assertNotIn("Shell", rows)
        self.assertFalse(any("lsh" in v for v in rows.values()), rows)

    def identity(self, root):
        r = subprocess.run([BINARY, "--identity"], env=env_for(root, LC_ALL="C"), capture_output=True, text=True,
                           timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.splitlines()

    def test_identity_luxos(self):
        self.assertEqual(self.identity(fake_root()),
                         ["LuxOS", "Rolling release · based on Arch Linux", "luxos-app", "1"])

    def test_identity_lux_desktop_on_fedora(self):
        # LuxOS Desktop na jine distribuci: jeji nazev a logo, verze desktopu, bez odkazu a aktualizace LuxOS
        root = fake_root()
        write(root + "/etc/os-release", 'NAME="Fedora Linux"\nID=fedora\nVERSION="43 (Workstation Edition)"\n'
                                        'VERSION_ID=43\nLOGO=fedora-logo-icon\n')
        write(root + "/usr/lib/lux-desktop/version", "VERSION=1.0.5\nCOMMIT=abc\n")
        self.assertEqual(self.identity(root), ["Fedora Linux", "LuxOS Desktop 1.0.5", "fedora-logo-icon", "0"])
        # bez LOGO a bez souboru verze
        root = fake_root()
        write(root + "/etc/os-release", 'NAME="Arch Linux"\nID=arch\n')
        self.assertEqual(self.identity(root), ["Arch Linux", "LuxOS Desktop", "luxos-app", "0"])

    def test_memory_as_installed(self):
        # 16GB notebook s integrovanou grafikou: MemTotal 14,95 GiB - drive "15.0 GB"
        for kb, want in ((15681220, "16 GB"), (7500000, "8 GB"), (32500000, "32 GB"), (11800000, "12 GB"),
                         (1900000, "2 GB"), (16777216, "16 GB")):
            with self.subTest(kb=kb):
                self.assertEqual(info(fake_root(mem_kb=kb), LC_ALL="C")["Memory"], want)

    def test_no_battery(self):
        rows = info(fake_root(battery=None), LC_ALL="C")
        self.assertNotIn("Battery", rows)

    def test_locales(self):
        # bez UTF-8 locale (C, POSIX, nic) i s ceskym prostredim
        root = fake_root()
        for extra in ({"LC_ALL": "C"}, {"LC_ALL": "POSIX"}, {}, {"LANG": "C"}):
            with self.subTest(env=extra):
                self.assertEqual(info(root, **extra)["Memory"], "16 GB")
        cs = info(root, LANG="cs_CZ.UTF-8")
        self.assertEqual(cs["Paměť"], "16 GB")
        self.assertIn("Linuxové jádro", cs)


def free_display():
    for n in range(500, 600):
        if not os.path.exists("/tmp/.X11-unix/X%d" % n) and not os.path.exists("/tmp/.X%d-lock" % n):
            return n
    raise RuntimeError("no free display")


SHOT_CODE = ("import sys, gi; gi.require_version('Gdk', '3.0'); from gi.repository import Gdk; "
             "r = Gdk.get_default_root_window(); "
             "Gdk.pixbuf_get_from_window(r, 0, 0, r.get_width(), r.get_height()).savev(sys.argv[1], 'png', [], [])")


@unittest.skipUnless(shutil.which("Xvfb") and shutil.which("xdotool"), "Xvfb/xdotool missing")
class Window(unittest.TestCase):
    """Okno se otevre (i s LANG=C) a vejde se na obrazovku 1366x768."""

    def open_window(self, **extra):
        n = free_display()
        xvfb = subprocess.Popen(["Xvfb", ":%d" % n, "-screen", "0", "1366x768x24", "-nolisten", "tcp"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: (xvfb.terminate(), xvfb.wait(5)))
        for _ in range(200):
            if os.path.exists("/tmp/.X11-unix/X%d" % n):
                break
            time.sleep(0.05)
        env = env_for(fake_root(), DISPLAY=":%d" % n, NO_AT_BRIDGE="1", GTK_USE_PORTAL="0", **extra)
        env.pop("DBUS_SESSION_BUS_ADDRESS", None)
        app = subprocess.Popen(["dbus-run-session", "--", BINARY], env=env, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, start_new_session=True)

        def stop():
            # vlastni skupina procesu (dbus-run-session, okno, dbus-daemon) - nikdy podle jmena
            try:
                os.killpg(app.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            app.communicate(timeout=10)
        self.addCleanup(stop)
        wid = ""
        for _ in range(100):
            if app.poll() is not None:
                break
            r = subprocess.run(["xdotool", "search", "--onlyvisible", "--class", "luxos-about"], env=env,
                               capture_output=True, text=True)
            wid = r.stdout.split()[0] if r.stdout.split() else ""
            if wid:
                break
            time.sleep(0.1)
        self.assertTrue(wid, "window did not open: %s" % (app.stderr.read() if app.poll() is not None else ""))
        time.sleep(0.5)
        geo = subprocess.run(["xdotool", "getwindowgeometry", "--shell", wid], env=env, capture_output=True,
                             text=True).stdout
        vals = dict(line.split("=", 1) for line in geo.split() if "=" in line)
        shots = os.environ.get("LUXOS_FIT_SHOTS")
        if shots:
            os.makedirs(shots, exist_ok=True)
            name = "luxos-about-%s.png" % (extra.get("LANG") or extra.get("LC_ALL") or "default")
            subprocess.run([sys.executable, "-c", SHOT_CODE, os.path.join(shots, name)], env=env, timeout=20)
        return int(vals["WIDTH"]), int(vals["HEIGHT"])

    def test_opens_with_c_locale(self):
        w, h = self.open_window(LC_ALL="C")
        self.assertLessEqual(w, 1366)
        self.assertLessEqual(h, 768 - 16)
        self.assertGreater(h, 300)

    def test_opens_in_czech(self):
        w, h = self.open_window(LANG="cs_CZ.UTF-8")
        self.assertLessEqual(w, 1366)
        self.assertLessEqual(h, 768 - 16)


if __name__ == "__main__":
    unittest.main()
