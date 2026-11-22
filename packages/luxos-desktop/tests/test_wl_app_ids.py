#!/usr/bin/env python3
"""Identita oken aplikaci LuxOS na Waylandu: app_id okna = nazev jeho souboru .desktop, jinak lista ukaze syrovy
nazev programu (luxos-displays-settings) a Dock obecnou ikonu misto ikony aplikace.

Staticky: kazdy .desktop z files/applications -> Exec -> program z PKGBUILD (lslc, odkazy v /usr/bin, obalove
skripty v files/bin) -> zdroj v LSL; ve zdroji se glib.set_prgname("<id>") (GTK 3 z nej bere app_id pri
realizaci okna) vola drive, nez blok vytvori okno. Kazdy .desktop ma po prekladu (luxos-i18n desktop-i18n.py,
stejne jako pri sestaveni) Name[cs].
Za behu: kazda aplikace s oknem se spusti pod luxwm headless (scripts/wl-test) a app_id se cte z luxwm-msg.

    packages/luxwm/tests/build-host.sh
    env -u DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u XAUTHORITY DBUS_SYSTEM_BUS_ADDRESS=unix:path=/nonexistent \\
      systemd-run --user --scope -p TasksMax=300 -p MemoryMax=2G -- timeout 900 \\
      python3 -m unittest packages/luxos-desktop/tests/test_wl_app_ids.py -v
"""
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import lsl_app  # noqa: E402

PKG = HERE.parent
REPO = PKG.parent.parent
FILES = PKG / "files"
LSL = FILES / "lsl"
APPS = FILES / "applications"
I18N = REPO / "packages/luxos-i18n/files"
WLT = REPO / "scripts/wl-test/wlt"
OUT = Path(os.environ.get("WLT_OUT") or REPO / "out/wl-test")
SYSROOT = Path(os.environ.get("WLT_SYSROOT") or OUT / "sysroot")
LUXWM_BUILD = Path(os.environ.get("LUXWM_BUILD") or REPO / "out/luxwm-test/build")

# Polozky bez vlastniho okna (toplevel): prikaz, vrstva shellu nebo okno jineho programu
NO_WINDOW = {
    "luxos-appearance": "Exec toggle only switches light/dark",
    "luxos-control-center": "Control Center is a bar popup (layer-shell) on Wayland",
    "luxos-launchpad": "Launchpad is a layer-shell surface",
    "luxos-search": "Search opens the Launchpad panel over D-Bus",
    "luxos-network-login": "opens the captive portal page in the browser",
}
# Maly klient spusti okno jako samostatny proces
UI_PROCESS = {"luxos-emoji": "luxos-emoji-ui", "luxos-screenshot": "luxos-screenshot-ui"}
# Okno se ukaze az po akci uzivatele (vyber oblasti), za behu se nekontroluje
NOT_AT_START = {"luxos-screenshot"}


def desktop_entry(path):
    entry = {}
    for line in path.read_text(encoding="utf-8").split("\n"):
        if line.startswith("[") and line.strip() != "[Desktop Entry]":
            break
        key, sep, value = line.partition("=")
        if sep and key not in entry:
            entry[key] = value
    return entry


def programs():
    """Nainstalovany nazev programu -> [zdroj LSL, argumenty] podle PKGBUILD a files/bin"""
    pkgbuild = (PKG / "PKGBUILD").read_text()
    built = {}
    for src, out in re.findall(r'files/lsl/(\S+?)\.lsl"\s+"?([\w$.-]+)"?', pkgbuild):
        built[out] = src
    for loop, body in re.findall(r"for p in ([^;]+);\s*do\s*\n(.*?)\bdone", pkgbuild, re.S):
        if "files/lsl/$p.lsl" in body:
            for name in loop.replace("\\\n", " ").split():
                built[name] = name
    built.pop("$p", None)
    installed = dict((name, [src, []]) for name, src in built.items())
    for out, dest in re.findall(r'install -Dm755 ([\w-]+) "\$pkgdir/usr/lib/luxos/([\w-]+)"', pkgbuild):
        if out in built:
            installed["/usr/lib/luxos/" + dest] = [built[out], []]
    # stare programy nastaveni = odkazy na luxos-settings (stranka podle jmena)
    for names in re.findall(r'for alias in ([^;]+);\s*do\s*\n\s*ln -s luxos-settings "\$pkgdir/usr/bin/\$alias"', pkgbuild):
        for name in names.replace("\\\n", " ").split():
            installed[name] = installed["luxos-settings"]
    for link in re.findall(r'ln -s \S*luxos-settings "\$pkgdir/usr/lib/luxos/([\w-]+)"', pkgbuild):
        installed["/usr/lib/luxos/" + link] = installed["luxos-settings"]
    for target, link in re.findall(r'ln -s (\S+) "\$pkgdir/usr/bin/([\w-]+)"', pkgbuild):
        key = "/usr/lib/luxos/" + target.split("/")[-1] if "/" in target else target
        if key in installed:
            installed[link] = installed[key]
    for script in (FILES / "bin").iterdir():
        if not script.is_file():    # __pycache__ po testech, ktere skripty z bin importuji
            continue
        m = re.search(r"^exec (/usr/lib/luxos/[\w-]+)((?: --?[\w-]+)*) \"\$@\"$", script.read_text(errors="replace"), re.M)
        if m and m.group(1) in installed:
            installed[script.name] = [installed[m.group(1)][0], m.group(2).split()]
    return installed


def window_id(app, src):
    """app_id okna: stranky Nastaveni maji jedno okno luxos-settings"""
    return "luxos-settings" if src == "luxos-settings" else app


def luxos_apps():
    """[(id .desktop, zdroj LSL, argumenty)] pro aplikace s oknem"""
    progs = programs()
    out = []
    for path in sorted(APPS.glob("*.desktop")):
        app = path.stem
        if app in NO_WINDOW:
            continue
        argv = desktop_entry(path)["Exec"].split()
        name = UI_PROCESS.get(app, argv[0])
        src, args = progs.get(name, [None, []])
        out.append((app, src, args + [a for a in argv[1:] if not a.startswith("%")]))
    return out


def blocks(lines):
    """Pro kazdy radek prvni radek jeho bloku: telo funkce, nebo 0 = hlavni program (bez tel funkci)"""
    owner, start = [], 0
    for i, line in enumerate(lines):
        if line.startswith("function "):
            start = i
        owner.append(start)
        if line.rstrip() == "end" and start:
            start = 0
    return owner


class StaticAppIds(unittest.TestCase):
    def test_every_app_maps_to_lsl_source(self):
        for app, src, _args in luxos_apps():
            with self.subTest(app=app):
                self.assertIsNotNone(src, "Exec of %s.desktop not found in PKGBUILD/files/bin" % app)
                self.assertTrue((LSL / (src + ".lsl")).exists(), src)

    def test_prgname_before_window(self):
        for app, src, args in luxos_apps():
            if src is None:
                continue
            lines = (LSL / (src + ".lsl")).read_text().split("\n")
            owner = blocks(lines)
            calls = [i for i, line in enumerate(lines) if "glib.set_prgname(" in line]
            with self.subTest(app=app):
                hit = None
                app = window_id(app, src)
                for i in calls:
                    head = [lines[j] for j in range(owner[i], i + 1) if owner[j] == owner[i]]
                    # id primo v argumentu, nebo v promenne nastavene v tomtez bloku pred volanim
                    if '"%s"' % app in lines[i] or any('"%s"' % app in line for line in head):
                        hit = i
                        break
                self.assertIsNotNone(hit, "%s.lsl never sets prgname %r" % (src, app))
                before = [lines[j] for j in range(owner[hit], hit) if owner[j] == owner[hit]]
                made = [line.strip() for line in before if re.search(r"window_new|widget_show", line)]
                self.assertEqual(made, [], "%s.lsl creates a window before set_prgname(%r)" % (src, app))

    def test_desktop_names_localized(self):
        spec = importlib.util.spec_from_file_location("desktop_i18n", I18N / "desktop-i18n.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        tabs = mod.load(str(I18N))
        for path in sorted(APPS.glob("*.desktop")):
            with self.subTest(app=path.stem):
                text = path.read_text(encoding="utf-8")
                done = mod.translate(text, tabs)
                done = done if isinstance(done, str) else text
                names = [line for line in done.split("\n") if line.startswith("Name[cs]=")]
                self.assertTrue(names, "%s has no Czech Name" % path.name)
                self.assertNotIn("luxos-", names[0], "raw id as name")


@unittest.skipUnless(lsl_app.shutil.which(os.environ.get("LUXOS_LSLC", "lslc")) and (LUXWM_BUILD / "luxwm").exists()
                     and WLT.exists(), "needs lslc, luxwm (packages/luxwm/tests/build-host.sh) and the wl-test harness")
class RuntimeAppIds(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        OUT.mkdir(parents=True, exist_ok=True)
        cls.tmp = Path(tempfile.mkdtemp(prefix="luxos-appid-", dir=OUT))
        conf = cls.tmp / "luxwm.conf"
        conf.write_text("xwayland = no\n" + "".join(line for line in (REPO / "packages/luxwm/luxwm.conf").read_text()
                                                    .splitlines(True) if not line.startswith("xwayland")))
        env = dict(os.environ, WLT_PRIVILEGED=str(LUXWM_BUILD / "luxwm-msg"),
                   WLT_COMPOSITOR_ENV=f"LUXCOMP_VIRTUAL_INPUT=1 LUXWM_SYSTEM_CONFIG={conf} "
                                      f"LD_LIBRARY_PATH={LUXWM_BUILD}:{SYSROOT}/usr/lib")
        r = subprocess.run([str(WLT), "start", "--mode", "headless", "--size", "1280x800", "--timeout", "800",
                            "--name", f"appid{os.getpid() % 10000}", "--", str(LUXWM_BUILD / "luxwm")],
                           env=env, capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            raise AssertionError("wlt start: " + r.stdout + r.stderr)
        cls.session = Path(r.stdout.strip().splitlines()[-1])
        cls.env = {}
        for line in subprocess.run([str(WLT), "env", str(cls.session)], capture_output=True, text=True).stdout.splitlines():
            key, _, value = line.removeprefix("export ").partition("=")
            cls.env[key] = value
        cls.env.pop("LD_LIBRARY_PATH", None)
        home = cls.tmp / "home"
        home.mkdir()
        cls.bus = lsl_app.Bus()
        cls.env.update(GDK_BACKEND="wayland", GTK_A11Y="none", GTK_THEME="Adwaita", HOME=str(home), LANG="en_US.UTF-8",
                       DBUS_SYSTEM_BUS_ADDRESS=cls.bus.address)

    @classmethod
    def tearDownClass(cls):
        cls.bus.stop()
        subprocess.run([str(WLT), "stop", str(cls.session)], capture_output=True)
        shutil.rmtree(cls.session, True)
        shutil.rmtree(cls.tmp, True)

    def windows(self):
        r = subprocess.run([str(LUXWM_BUILD / "luxwm-msg"), "list-windows"], env=self.env, capture_output=True,
                           text=True, timeout=10)
        return json.loads(r.stdout or '{"windows": []}')["windows"]

    def test_app_id_matches_desktop(self):
        built = {}
        for app, src, args in luxos_apps():
            if app in NOT_AT_START or src is None:
                continue
            with self.subTest(app=app):
                if src not in built:
                    built[src] = lsl_app.build(src, str(self.tmp))
                p = subprocess.Popen([built[src], *args], env=self.env, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.PIPE, text=True)
                try:
                    found = []
                    for _ in range(80):
                        time.sleep(0.25)
                        found = [w["app_id"] for w in self.windows()]
                        if found or p.poll() is not None:
                            break
                    self.assertTrue(found, "%s: no window (exit %s) %s" % (app, p.poll(),
                                                                           p.stderr.read()[-300:] if p.poll() is not None else ""))
                    self.assertEqual(found, [window_id(app, src)])
                finally:
                    p.terminate()
                    try:
                        p.wait(5)
                    except subprocess.TimeoutExpired:
                        p.kill()
                        p.wait(5)
                    p.stderr.close()
                for _ in range(20):
                    if not self.windows():
                        break
                    time.sleep(0.2)


if __name__ == "__main__":
    unittest.main()
