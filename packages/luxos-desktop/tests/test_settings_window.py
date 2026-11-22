#!/usr/bin/env python3
"""LuxOS - okno Nastaveni (files/lsl/luxos-settings.lsl): postranni panel a hledani, odkazy starymi jmeny
programu (luxos-power ...) a `luxos-settings STRANKA`, jedna instance v relaci (druhe spusteni jen prepne
stranku), samostatne aplikace z panelu, posledni stranka, radky jen pro jednu relaci. X11 ve vlastnim Xvfb,
Wayland pod luxwm headless (titulek okna, app_id).

    scripts/wl-test/run-all packages/luxos-desktop/tests/test_settings_window.py
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import lsl_app  # noqa: E402

REPO = HERE.parent.parent.parent
WLT = REPO / "scripts/wl-test/wlt"
OUT = Path(os.environ.get("WLT_OUT") or REPO / "out/wl-test")
SYSROOT = Path(os.environ.get("WLT_SYSROOT") or OUT / "sysroot")
LUXWM_BUILD = Path(os.environ.get("LUXWM_BUILD") or REPO / "out/luxwm-test/build")
FAKE = "#!/bin/sh\necho \"$(basename \"$0\") $*\" >> \"$FAKE_LOG\"\n"


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="settings-win-"))
        cls.binary = lsl_app.build("luxos-settings", str(cls.tmp))
        os.symlink(cls.binary, cls.tmp / "luxos-power")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, True)

    def setUp(self):
        self.apps = []
        self.home = Path(tempfile.mkdtemp(prefix="home-", dir=self.tmp))
        self.bin = self.home / "bin"
        self.bin.mkdir()
        for name in ("luxos-router", "luxos-about"):
            (self.bin / name).write_text(FAKE)
            (self.bin / name).chmod(0o755)
        self.bus = lsl_app.Bus()
        self.env = dict(os.environ, HOME=str(self.home), XDG_CONFIG_HOME=str(self.home / "config"),
                        XDG_CACHE_HOME=str(self.home / "cache"), PATH=str(self.bin) + ":" + os.environ["PATH"],
                        FAKE_LOG=str(self.home / "fake.log"), DBUS_SESSION_BUS_ADDRESS=self.bus.address,
                        GTK_A11Y="none", GTK_THEME="Adwaita", LANG="C.UTF-8", LC_ALL="C.UTF-8")
        self.env.pop("LUXOS_UI_TEST", None)

    def tearDown(self):
        for app in self.apps:
            app.stop()
        self.bus.stop()

    def open(self, *argv, program=None, **env):
        app = lsl_app.App([str(program or self.binary), *argv], dict(self.env, **env))
        self.apps.append(app)
        self.assertTrue(app.wait(lambda: app.dump(), 15), app.stderr())
        return app

    def state(self, app):
        return json.loads(app.ask("state", "state"))

    def sidebar(self, app):
        return json.loads(app.ask("sidebar", "sidebar"))

    def fake_calls(self):
        log = self.home / "fake.log"
        return log.read_text().splitlines() if log.exists() else []


class Common:
    def test_sidebar_and_search(self):
        app = self.open("desktop")
        ids = self.sidebar(app)
        for page in ("wifi", "bluetooth", "notifications", "appearance", "accessibility", "desktop", "windows",
                     "displays", "lock", "power", "keyboard", "mouse", "default-apps", "login-items", "drives"):
            self.assertIn(page, ids)
        self.assertIn("network", ids)              # luxos-router v PATH (falesny)
        app.ask("search wallpaper")
        self.assertEqual(self.sidebar(app), ["desktop"])
        app.ask("search natural scroll")
        self.assertEqual(self.sidebar(app), ["mouse"])
        app.ask("search qwxyz")
        self.assertEqual(self.sidebar(app), [])
        app.ask("search ")
        self.assertEqual(self.sidebar(app), ids)

    def test_sidebar_glyphs(self):
        # owner 2026-11-22 (shot 80): Appearance had a small colour icon on a black tile in a theme without the
        # symbolic name; the glyphs come from WhiteSur-light whatever icon theme the user picked, every page in colour
        if not Path("/usr/share/icons/WhiteSur-light/index.theme").exists():
            self.skipTest("WhiteSur-light icon theme is not installed")
        (self.home / "config/gtk-3.0").mkdir(parents=True)
        (self.home / "config/gtk-3.0/settings.ini").write_text("[Settings]\ngtk-icon-theme-name=Adwaita\n")
        app = self.open("desktop")
        glyphs = json.loads(app.ask("glyphs", "glyphs"))
        self.assertGreaterEqual(len(glyphs), 20)
        for page, path in glyphs.items():
            self.assertTrue(path.startswith("/usr/share/icons/WhiteSur-light/") and path.endswith("-symbolic.svg"),
                            (page, path))
        pages = (REPO / "packages/luxos-desktop/files/lsl/luxos_settings_pages.lsl").read_text()
        for grey in ("#8e8e93", "#48484a", "#636366"):
            self.assertNotIn(grey, pages)

    def test_search_czech_without_diacritics(self):
        app = self.open("desktop", LANG="cs_CZ.UTF-8", LC_ALL="cs_CZ.UTF-8")
        app.ask("search tapeta")
        self.assertIn("desktop", self.sidebar(app))
        app.ask("search klavesnice")
        self.assertEqual(self.sidebar(app), ["keyboard"])
        self.assertIn("Klávesnice", lsl_app.texts(app.dump()))

    def test_deep_links(self):
        app = self.open(program=self.tmp / "luxos-power")
        self.assertEqual(self.state(app)["page"], "power")
        app.stop()
        app = self.open("mouse")
        self.assertEqual(self.state(app)["page"], "mouse")
        self.assertEqual(self.state(app)["built"], ["mouse"])     # ostatni stranky az pri otevreni

    def test_single_instance(self):
        app = self.open("desktop")
        p = subprocess.Popen([str(self.binary), "lock"], env=dict(self.env, LUXOS_TEST_CONTROL="0"),
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            out, err = p.communicate(timeout=20)
        except subprocess.TimeoutExpired:
            p.kill()
            out, err = p.communicate()
        self.assertEqual(p.returncode, 0, err)
        self.assertTrue(app.wait(lambda: self.state(app)["page"] == "lock"))
        r = subprocess.run([str(self.tmp / "luxos-power")], env=self.env, timeout=20, capture_output=True)
        self.assertEqual(r.returncode, 0)
        self.assertTrue(app.wait(lambda: self.state(app)["page"] == "power"))

    def test_app_rows_open_their_app(self):
        app = self.open("lock")
        app.ask("page network")
        self.assertTrue(app.wait(lambda: "luxos-router " in self.fake_calls()), self.fake_calls())
        self.assertEqual(self.state(app)["page"], "lock")

    def test_last_page_remembered(self):
        app = self.open("lock")
        app.ask("page displays")
        app.stop()
        app = self.open()
        self.assertEqual(self.state(app)["page"], "displays")

    def test_unknown_page_opens_default(self):
        app = self.open("no-such-page")
        self.assertEqual(self.state(app)["page"], "appearance")


@unittest.skipUnless(lsl_app.shutil.which("Xvfb"), "Xvfb is missing")
class X11(Base, Common):
    def setUp(self):
        super().setUp()
        self.x = lsl_app.Xvfb()
        self.env.update(DISPLAY=self.x.display, GDK_BACKEND="x11")
        self.env.pop("WAYLAND_DISPLAY", None)
        self.env.pop("XAUTHORITY", None)

    def tearDown(self):
        super().tearDown()
        self.x.stop()

    def test_xfce_manager_row_only_on_x11(self):
        app = self.open("desktop")
        self.assertEqual("xfce" in self.sidebar(app), os.access("/usr/bin/xfce4-settings-manager", os.X_OK))


@unittest.skipUnless((LUXWM_BUILD / "luxwm").exists() and WLT.exists(), "luxwm (build-host.sh) or harness missing")
class Wayland(Base, Common):
    def setUp(self):
        super().setUp()
        conf = self.home / "luxwm.conf"
        conf.write_text("xwayland = no\n" + "".join(line for line in (REPO / "packages/luxwm/luxwm.conf").read_text()
                                                    .splitlines(True) if not line.startswith("xwayland")))
        env = dict(os.environ, WLT_PRIVILEGED=str(LUXWM_BUILD / "luxwm-msg"),
                   WLT_COMPOSITOR_ENV=f"LUXWM_SYSTEM_CONFIG={conf} LD_LIBRARY_PATH={LUXWM_BUILD}:{SYSROOT}/usr/lib")
        r = subprocess.run([str(WLT), "start", "--mode", "headless", "--size", "1280x800", "--timeout", "600",
                            "--name", f"sw{os.getpid() % 10000}-{self._testMethodName[5:15]}", "--", str(LUXWM_BUILD / "luxwm")],
                           env=env, capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            self.fail("wlt start: " + r.stdout + r.stderr)
        self.session = Path(r.stdout.strip().splitlines()[-1])
        for line in subprocess.run([str(WLT), "env", str(self.session)], capture_output=True, text=True).stdout.splitlines():
            key, _, value = line.removeprefix("export ").partition("=")
            if key not in ("LD_LIBRARY_PATH", "PATH", "HOME", "DBUS_SESSION_BUS_ADDRESS"):
                self.env[key] = value
        self.env["GDK_BACKEND"] = "wayland"
        self.env.pop("DISPLAY", None)

    def tearDown(self):
        super().tearDown()
        subprocess.run([str(WLT), "stop", str(self.session)], capture_output=True)
        shutil.rmtree(self.session, True)

    def windows(self):
        return subprocess.run([str(LUXWM_BUILD / "luxwm-msg"), "list-windows"], env=self.env, capture_output=True,
                              text=True, timeout=10).stdout

    def test_window_title_follows_page(self):
        app = self.open("lock")
        self.assertTrue(app.wait(lambda: "luxos-settings" in self.windows()), self.windows())
        self.assertIn("Screen Lock", self.windows())
        app.ask("page displays")
        self.assertTrue(app.wait(lambda: "Displays" in self.windows()), self.windows())
        self.assertNotIn("xfce", self.sidebar(app))
        # panel posle oblast skla luxwm (pod HeaderBar, sirka panelu)
        region = self.state(app)["region"]
        self.assertEqual(region[0], 0)
        self.assertGreater(region[1], 20)
        self.assertGreaterEqual(region[2], 200)

    def test_pss(self):
        app = self.open("desktop")
        time.sleep(1.5)
        pss = app.pss_kb()
        print(f"luxos-settings PSS {pss} kB (Desktop & Dock)", file=sys.stderr)
        self.assertLess(pss, 80 * 1024)


if __name__ == "__main__":
    unittest.main()
