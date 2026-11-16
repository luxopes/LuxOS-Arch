#!/usr/bin/env python3
"""Firefox: tlacitka okna jako barevna kolecka LuxOS (luxos.cfg + titlebar.css) a uvitaci stranka LuxOS.

Bez displeje bezi kontroly souboru a hlidac selektoru proti nainstalovanemu Firefoxu (omni.ja): kdyz
nova verze Firefoxu prejmenuje prvky tlacitek, test selze. Se skutecnym Firefoxem jen pod Xvfb:

    env -u DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u XAUTHORITY xvfb-run -a -s "-screen 0 1400x900x24" \\
        python3 packages/luxos-desktop/tests/test_firefox_titlebar.py

LUXOS_FIREFOX_PKG=<rozbaleny balicek luxos-desktop> testuje soubory z balicku misto files/,
LUXOS_FIREFOX_SHOTS=<slozka> ulozi snimky obrazovky.
"""
import os
import re
import shutil
import subprocess
import sys
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import firefox_tl as tl  # noqa: E402

FF = os.path.join(tl.FILES, "firefox")
PKGBUILD = os.path.join(HERE, "..", "PKGBUILD")
BRANDING_LOGO = os.path.join(HERE, "..", "..", "luxos-branding", "files", "logo", "luxos-logo.svg")
PKG = os.environ.get("LUXOS_FIREFOX_PKG") or None
SHOTS = os.environ.get("LUXOS_FIREFOX_SHOTS") or None
LANGS = ["en", "cs", "sk", "de", "es", "fr", "hu", "it", "nl", "pl", "pt", "sv", "uk"]

# barvy xfwm4 WhiteSur (aktivni / neaktivni okno) - stejne hodnoty musi mit titlebar.css
LIGHT = {"close": (0xf2, 0x50, 0x56), "min": (0xfa, 0xc5, 0x36), "max": (0x39, 0xea, 0x49), "grey": (0xce, 0xce, 0xce)}
DARK = {"close": (0xe9, 0x52, 0x4a), "min": (0xf1, 0xae, 0x1b), "max": (0x59, 0xc8, 0x37), "grey": (0x5d, 0x5d, 0x5d)}


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def omni(jar, member):
    r = subprocess.run(["unzip", "-p", jar, member], capture_output=True)
    return r.stdout.decode("utf-8", "replace")


def kind(b):
    for k in ("close", "min", "max", "restore"):
        if "titlebar-" + k in b["cls"].split():
            return k
    return "?"


class Files(unittest.TestCase):
    def test_cfg_is_safe_autoconfig(self):
        cfg = read(os.path.join(FF, "luxos.cfg"))
        self.assertTrue(cfg.startswith("//"), "autoconfig ignores the first line - it must be a comment")
        body = "\n".join(line for line in cfg.splitlines() if not line.startswith("//")).strip()
        self.assertTrue(body.startswith("try {") and body.rstrip().endswith("}"), "everything inside try/catch")
        if shutil.which("node"):
            r = subprocess.run(["node", "-e", "new Function(require('fs').readFileSync(process.argv[1], 'utf8'))",
                                os.path.join(FF, "luxos.cfg")], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            for name in ("welcome/welcome.js", "welcome/strings.js"):
                r = subprocess.run(["node", "--check", os.path.join(FF, name)], capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stderr)

    def test_autoconfig_prefs(self):
        js = read(os.path.join(FF, "luxos-autoconfig.js"))
        self.assertIn('pref("general.config.filename", "luxos.cfg");', js)
        self.assertIn('pref("general.config.obscure_value", 0);', js)
        # Firefox 160 jinak spousti luxos.cfg v sandboxu bez Components (styl by se nenacetl)
        self.assertIn('pref("general.config.sandbox_enabled", false);', js)
        self.assertIn('pref("luxos.titlebar.trafficlights", true);', js)

    def test_first_run_and_privacy_prefs(self):
        js = read(os.path.join(FF, "luxos.js"))
        for p in ('pref("datareporting.policy.firstRunURL", "");', 'pref("browser.aboutwelcome.enabled", false);',
                  'pref("startup.homepage_override_url", "");',
                  'pref("datareporting.healthreport.uploadEnabled", false);',
                  'pref("toolkit.telemetry.enabled", false);', 'pref("app.shield.optoutstudies.enabled", false);',
                  'pref("browser.newtabpage.activity-stream.showSponsored", false);',
                  'pref("browser.newtabpage.activity-stream.showSponsoredTopSites", false);'):
            self.assertIn(p, js)
        # domovska stranka se nevnucuje (uvitaci stranka jen pri prvnim spusteni profilu)
        self.assertNotIn("browser.startup.homepage\"", js)

    def test_pkgbuild_installs(self):
        pb = read(PKGBUILD)
        for s in ('"$f/firefox/luxos-autoconfig.js" "$pkgdir/usr/lib/firefox/defaults/pref/luxos-autoconfig.js"',
                  '"$f/firefox/luxos.cfg" "$pkgdir/usr/lib/firefox/luxos.cfg"',
                  '"$f/firefox/titlebar.css" "$pkgdir/usr/lib/firefox/luxos/titlebar.css"',
                  '"$pkgdir/usr/lib/firefox/luxos/welcome"'):
            self.assertIn(s, pb)

    def test_css_rules_target_only_button_icons(self):
        """Kazde pravidlo cili na .titlebar-button > .toolbarbutton-icon (nebo je jim podminene pres :has):
        po prejmenovani v nove verzi Firefoxu zustanou puvodni tlacitka, nikdy zadna."""
        css = re.sub(r"/\*.*?\*/", "", read(os.path.join(FF, "titlebar.css")), flags=re.S)
        # selektor = text pred "{" za poslednim "}", "{" nebo ";" (vnorene @media jsou pravidla podminky)
        sels = [m[1].split(";")[-1].strip() for m in re.findall(r"(^|\}|\{)\s*([^{}]+?)\s*\{", css)]
        sels = [s for s in sels if not s.startswith("@")]
        self.assertTrue(sels)
        for s in sels:
            if s.startswith(".titlebar-buttonbox:has("):
                self.assertIn("> .titlebar-button > .toolbarbutton-icon", s)
                continue
            self.assertTrue(s.endswith("> .toolbarbutton-icon"), s)
            self.assertIn(".titlebar-button", s)
        self.assertNotIn("display:", css.replace(" ", ""))
        self.assertNotIn("visibility", css)

    def test_welcome_strings_complete(self):
        src = read(os.path.join(FF, "welcome", "strings.js"))
        keys = set(re.findall(r'data-i18n="([a-z_0-9]+)"', read(os.path.join(FF, "welcome", "index.html"))))
        blocks = dict(re.findall(r"\n  ([a-z]{2}): \{(.*?)\n  \},", src, flags=re.S))
        self.assertEqual(sorted(blocks), sorted(LANGS))
        for lang, body in blocks.items():
            got = set(re.findall(r"\n    ([a-z_0-9]+): ", body))
            self.assertEqual(got, keys, lang)

    def test_welcome_local_only(self):
        html = read(os.path.join(FF, "welcome", "index.html"))
        # zadne vzdalene skripty, styly, obrazky ani pisma - jen odkazy <a>
        for tag in re.findall(r"<(?:script|link|img|iframe|source|video|audio)\b[^>]*>", html):
            self.assertNotRegex(tag, r"(src|href)=\"(https?:)?//", tag)
        self.assertNotIn("@import", html)
        self.assertNotRegex(html, r"url\((['\"])?https?:")
        for a in re.findall(r'<a [^>]*href="https://[^"]*"[^>]*>', html):
            self.assertIn('rel="noopener noreferrer"', a)

    @unittest.skipUnless(os.path.exists(BRANDING_LOGO), "needs the repository (luxos-branding)")
    def test_welcome_logo_is_branding_logo(self):
        logo = re.search(r' d="([^"]+)"', read(BRANDING_LOGO)).group(1)
        self.assertIn(logo, read(os.path.join(FF, "welcome", "index.html")))


@unittest.skipUnless(os.path.exists("/usr/lib/firefox/browser/omni.ja") and shutil.which("unzip"), "needs Firefox")
class SelectorGuard(unittest.TestCase):
    """Hlidac verze Firefoxu: prvky a tridy, na ktere styl cili, musi v Firefoxu existovat."""

    def test_titlebar_markup_exists(self):
        xhtml = omni("/usr/lib/firefox/browser/omni.ja", "chrome/browser/content/browser/browser.xhtml")
        self.assertIn("titlebar-buttonbox-container", xhtml)
        css = re.sub(r"/\*.*?\*/", "", read(os.path.join(FF, "titlebar.css")), flags=re.S)
        classes = set(re.findall(r"\.(titlebar-[a-z-]+)", css))
        self.assertGreaterEqual(classes, {"titlebar-buttonbox", "titlebar-button", "titlebar-close", "titlebar-min",
                                          "titlebar-max", "titlebar-restore"})
        for c in classes:
            self.assertRegex(xhtml, r'class="[^"]*\b%s\b' % re.escape(c), c)
        for c in ("titlebar-close", "titlebar-min", "titlebar-max", "titlebar-restore"):
            self.assertRegex(xhtml, r'<toolbarbutton class="titlebar-button %s"' % c)
        # ikona tlacitka (toolkit: toolbarbutton vklada <image class="toolbarbutton-icon">)
        toolkit = omni("/usr/lib/firefox/omni.ja", "chrome/global/elements/toolbarbutton.js") or \
            omni("/usr/lib/firefox/omni.ja", "chrome/toolkit/content/global/elements/toolbarbutton.js")
        self.assertIn("toolbarbutton-icon", toolkit)
        # Firefox stale bere stranu a poradi z GTK (gtk-decoration-layout)
        bcss = omni("/usr/lib/firefox/browser/omni.ja", "chrome/browser/skin/classic/browser/browser.css")
        self.assertIn("-moz-gtk-csd-reversed-placement", bcss)
        self.assertIn("--titlebar-button-size", bcss)


NEEDS_GUI = "needs Firefox, xfwm4 and xvfb-run (never the real display)"
GUI = tl.firefox_available() and tl.on_test_display() and bool(shutil.which("xdotool"))


def shot(s, name, rect=None):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        s.grab(os.path.join(SHOTS, name + ".png"), rect)


def find_circle(img, x0, y0, x1, y1, color, tol=10):
    """Stred shluku pixelu dane barvy v obdelniku (fyzicke pixely) nebo None."""
    pts = [(x, y) for y in range(max(0, y0), min(img.h, y1)) for x in range(max(0, x0), min(img.w, x1))
           if tl.close(img.px(x, y), color, tol)]
    if not pts:
        return None
    return (round(sum(p[0] for p in pts) / len(pts)), round(sum(p[1] for p in pts) / len(pts)), len(pts))


class GuiBase(unittest.TestCase):
    DARK = False
    SCALE = 1
    PREFS = ""
    NAME = "light"

    @classmethod
    def setUpClass(cls):
        cls.root = tl.build_root(os.path.join(tl.OUT, "ffroot-" + cls.NAME), PKG)
        cls.s = tl.Session(dark=cls.DARK, scale=cls.SCALE, name=cls.NAME)
        prefs = cls.PREFS
        if cls.DARK:
            prefs += 'user_pref("ui.systemUsesDarkTheme", 1);\n'
        try:
            cls.s.start_firefox(cls.root, prefs)
        except Exception:
            cls.s.stop()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.s.stop()

    def info(self):
        return self.s.buttons()

    def ours(self, b):
        return b["icon"] and round(b["icon"]["w"]) == 14 and b["radius"] == "50%"


@unittest.skipUnless(GUI, NEEDS_GUI)
class LightWindow(GuiBase):
    def test_1_buttons_like_xfwm4(self):
        info = self.info()
        bs = [b for b in info["buttons"] if b["toolbar"] == "TabsToolbar"]
        self.assertEqual([kind(b) for b in bs], ["close", "min", "max"], "LuxOS order: close, minimize, maximize")
        pal = DARK if self.DARK else LIGHT
        for b in bs:
            self.assertTrue(self.ours(b), b)
            self.assertEqual(tl.rgb(b["bg"]), pal[kind(b)], b)
            self.assertEqual(b["img"], "none")
        xs = [b["icon"]["x"] for b in bs]
        self.assertEqual([round(xs[1] - xs[0]), round(xs[2] - xs[1])], [24, 24], "24 px pitch like xfwm4")
        self.assertEqual(round(xs[0]), 15, "10 px button_offset + 5 px like xfwm4")
        for b in bs:                                   # svisle na stredu pruhu panelu
            self.assertAlmostEqual(b["icon"]["y"] + 7, b["y"] + b["h"] / 2, delta=1)
        shot(self.s, self.NAME + "-active")

    def test_2_screen_colors_match_xfwm4_window(self):
        """Pixely kolecek Firefoxu na obrazovce = pixely tlacitek okna dekorovaneho xfwm4."""
        self.s.open_gtk_window(x=40, y=640)
        info = self.info()
        s = info["scale"]
        # okno GTK ma ted fokus: obe okna neaktivni/aktivni se lisi - aktivujeme Firefox pro srovnani barev
        img_ref = self.s.grab()
        pal = DARK if self.DARK else LIGHT
        # tlacitka xfwm4: v horni casti okna reference (fokus ma reference -> barevna)
        ref = {k: find_circle(img_ref, 0, 560, 400, 760, pal[k], 3) for k in ("close", "min", "max")}
        for k, v in ref.items():
            self.assertIsNotNone(v, "xfwm4 %s button not found" % k)
        shot(self.s, self.NAME + "-vs-xfwm4-inactive-firefox")
        xid = self.s.xid("Mozilla Firefox")[0]
        self.s.xdo("windowactivate", "--sync", xid)
        time.sleep(0.8)
        img = self.s.grab()
        bs = [b for b in info["buttons"] if b["toolbar"] == "TabsToolbar"]
        for b in bs:
            x, y = self.s.screen_xy(info, b)
            k = kind(b)
            got = img.px(x, y)
            refpx = img_ref.px(ref[k][0], ref[k][1])
            self.assertTrue(tl.close(got, refpx, 3), "%s: Firefox %s vs xfwm4 %s" % (k, tl.hexrgb(got), tl.hexrgb(refpx)))
            area = find_circle(img, x - 12 * s, y - 12 * s, x + 12 * s, y + 12 * s, pal[k], 3)
            self.assertAlmostEqual(area[2], ref[k][2] * s * s, delta=ref[k][2] * s * s * 0.25, msg="circle size " + k)
        shot(self.s, self.NAME + "-vs-xfwm4")

    def test_3_inactive_grey_and_hover_glyph(self):
        pal = DARK if self.DARK else LIGHT
        self.s.open_gtk_window(title="focus thief", x=700, y=640)
        time.sleep(0.6)
        info = self.info()
        bs = [b for b in info["buttons"] if b["toolbar"] == "TabsToolbar"]
        for b in bs:
            self.assertEqual(tl.rgb(b["bg"]), pal["grey"], "inactive window -> grey: %s" % b)
        shot(self.s, self.NAME + "-inactive")
        xid = self.s.xid("Mozilla Firefox")[0]
        self.s.xdo("windowactivate", "--sync", xid)
        time.sleep(0.6)
        for b in bs:
            x, y = self.s.screen_xy(info, b)
            self.s.xdo("mousemove", x, y)
            time.sleep(0.4)
            now = [c for c in self.info()["buttons"] if c["cls"] == b["cls"]][0]
            self.assertIn("data:image/svg+xml", now["img"], "hover glyph on " + kind(b))
            others = [c for c in self.info()["buttons"] if c["cls"] != b["cls"] and c["toolbar"] == "TabsToolbar"]
            self.assertTrue(all(c["img"] == "none" for c in others), "only the hovered button shows its glyph")
            shot(self.s, "%s-hover-%s" % (self.NAME, kind(b)),
                 (max(0, x - 40 * info["scale"]), max(0, y - 20 * info["scale"]), 120 * info["scale"], 40 * info["scale"]))
        self.s.xdo("mousemove", 700, 450)
        time.sleep(0.3)

    def test_4_off_switch_and_back(self):
        self.s.mn.js("Services.prefs.setBoolPref('luxos.titlebar.trafficlights', false)")
        time.sleep(0.5)
        bs = [b for b in self.info()["buttons"] if b["toolbar"] == "TabsToolbar"]
        self.assertEqual(len(bs), 3)
        for b in bs:
            self.assertIn("-moz-symbolic-icon", b["img"], "Firefox default buttons back")
            self.assertGreaterEqual(b["icon"]["w"], 16)
        shot(self.s, self.NAME + "-off")
        self.s.mn.js("Services.prefs.setBoolPref('luxos.titlebar.trafficlights', true)")
        time.sleep(0.5)
        for b in [b for b in self.info()["buttons"] if b["toolbar"] == "TabsToolbar"]:
            self.assertTrue(self.ours(b))
            self.assertEqual(b["img"], "none")

    def test_5_private_window(self):
        before = set(self.s.mn.windows())
        self.s.mn.js("OpenBrowserWindow({private: true})")
        for _ in range(50):
            new = set(self.s.mn.windows()) - before
            if new:
                break
            time.sleep(0.2)
        h = new.pop()
        main = self.s.mn.cmd("WebDriver:GetWindowHandle")
        main = main.get("value", main) if isinstance(main, dict) else main
        try:
            self.s.mn.switch(h)
            time.sleep(2.0)
            info = self.info()
            self.assertTrue(self.s.mn.js("return PrivateBrowsingUtils.isWindowPrivate(window)"))
            bs = [b for b in info["buttons"] if b["toolbar"] == "TabsToolbar"]
            self.assertEqual([kind(b) for b in bs], ["close", "min", "max"])
            for b in bs:
                self.assertTrue(self.ours(b), b)
            shot(self.s, self.NAME + "-private")
        finally:
            self.s.mn.js("window.close()")
            self.s.mn.switch(main)
            time.sleep(1.0)

    def test_6_menubar_vertical_tabs_popup(self):
        self.s.mn.js("setToolbarVisibility(document.getElementById('toolbar-menubar'), true)")
        time.sleep(0.8)
        bs = self.info()["buttons"]
        self.assertTrue(bs and all(self.ours(b) for b in bs), bs)
        self.assertEqual({b["toolbar"] for b in bs}, {"toolbar-menubar"})
        shot(self.s, self.NAME + "-menubar")
        self.s.mn.js("setToolbarVisibility(document.getElementById('toolbar-menubar'), false)")
        time.sleep(0.6)
        self.s.mn.js("Services.prefs.setBoolPref('sidebar.revamp', true); Services.prefs.setBoolPref('sidebar.verticalTabs', true)")
        time.sleep(1.5)
        bs = self.info()["buttons"]
        self.assertEqual([kind(b) for b in bs], ["close", "min", "max"])
        self.assertTrue(all(self.ours(b) for b in bs), bs)
        shot(self.s, self.NAME + "-vertical-tabs")
        self.s.mn.js("Services.prefs.setBoolPref('sidebar.verticalTabs', false); Services.prefs.setBoolPref('sidebar.revamp', false)")
        time.sleep(1.0)
        # vyskakovaci okno bez panelu (window.open s rozmery)
        before = set(self.s.mn.windows())
        self.s.mn.js("window.openDialog(AppConstants.BROWSER_CHROME_URL, '_blank', 'chrome,popup=yes,width=500,height=300',"
                     " 'about:blank')")
        for _ in range(50):
            new = set(self.s.mn.windows()) - before
            if new:
                break
            time.sleep(0.2)
        main = self.s.mn.cmd("WebDriver:GetWindowHandle")
        main = main.get("value", main) if isinstance(main, dict) else main
        if new:
            self.s.mn.switch(new.pop())
            try:
                time.sleep(2.0)
                popup = self.s.mn.js("return document.documentElement.hasAttribute('popup-window')")
                bs = self.info()["buttons"]
                for b in bs:
                    self.assertTrue(self.ours(b), b)
                self.assertTrue(popup)
                shot(self.s, self.NAME + "-popup")
            finally:
                self.s.mn.js("window.close()")
                self.s.mn.switch(main)
                time.sleep(1.0)

    def sizemode(self, want, timeout=4):
        end = time.time() + timeout
        while True:
            got = self.s.mn.js("return document.documentElement.getAttribute('sizemode')")
            if got == want or time.time() > end:
                return got
            time.sleep(0.2)

    def test_7_clicks_minimize_maximize_close(self):
        xid = self.s.xid("Mozilla Firefox")[0]
        self.s.xdo("windowactivate", "--sync", xid)
        time.sleep(0.5)

        def press(k):
            info = self.info()
            b = [b for b in info["buttons"] if kind(b) == k and b["toolbar"] == "TabsToolbar"][0]
            x, y = self.s.screen_xy(info, b)
            self.s.xdo("mousemove", x, y)
            time.sleep(0.3)
            self.s.xdo("click", 1)
            time.sleep(1.2)
            if os.environ.get("LUXOS_FIREFOX_DEBUG"):
                print("press", k, x, y, info["mozInnerScreenX"], info["mozInnerScreenY"], b["icon"], file=sys.stderr)
                shot(self.s, "debug-after-" + k)

        press("max")
        self.assertEqual(self.sizemode("maximized"), "maximized")
        info = self.info()
        bs = [b for b in info["buttons"] if b["toolbar"] == "TabsToolbar"]
        self.assertEqual([kind(b) for b in bs], ["close", "min", "restore"])
        self.assertTrue(all(self.ours(b) for b in bs))
        shot(self.s, self.NAME + "-maximized")
        press("restore")
        self.assertEqual(self.sizemode("normal"), "normal")
        # dvojklik do prazdneho mista panelu = maximalizovat (Firefox/GTK), znovu = obnovit
        info = self.info()
        s = info["scale"]
        x = round((info["mozInnerScreenX"] + info["width"] - 160) * s)
        y = round((info["mozInnerScreenY"] + 12) * s)
        self.s.xdo("mousemove", x, y)
        time.sleep(0.3)
        self.s.xdo("click", "--repeat", "2", "--delay", "80", 1)
        time.sleep(1.2)
        self.assertEqual(self.sizemode("maximized"), "maximized",
                         "double-click on the tab strip maximizes")
        mi = self.info()
        self.s.xdo("mousemove", round((mi["mozInnerScreenX"] + mi["width"] - 160) * s),
                   round((mi["mozInnerScreenY"] + 12) * s))
        time.sleep(0.3)
        self.s.xdo("click", "--repeat", "2", "--delay", "80", 1)
        time.sleep(1.2)
        self.assertEqual(self.sizemode("normal"), "normal")
        # tazeni za panel posune okno
        before = (self.info()["mozInnerScreenX"], self.info()["mozInnerScreenY"])
        self.s.xdo("mousemove", x, y)
        self.s.xdo("mousedown", 1)
        for i in range(1, 11):
            self.s.xdo("mousemove", x - 8 * i, y + 5 * i)
            time.sleep(0.05)
        self.s.xdo("mouseup", 1)
        time.sleep(0.8)
        after = (self.info()["mozInnerScreenX"], self.info()["mozInnerScreenY"])
        self.assertNotEqual(before, after, "window dragged by the tab strip")
        # fullscreen: panel skryty (zadna viditelna tlacitka, dokud se nevysune)
        self.s.mn.js("window.fullScreen = true")
        time.sleep(1.5)
        fs = self.s.mn.js("return [document.documentElement.getAttribute('sizemode'), "
                          "[...document.querySelectorAll('.titlebar-button')].filter(b => {const r = b.getBoundingClientRect();"
                          " return r.width && r.bottom > 0}).length]")
        self.assertEqual(fs[0], "fullscreen")
        self.assertEqual(fs[1], 0, "no window buttons over the page in fullscreen")
        shot(self.s, self.NAME + "-fullscreen")
        self.s.mn.js("window.fullScreen = false")
        time.sleep(1.5)
        # minimalizovat
        press("min")
        state = subprocess.run(["xprop", "-id", str(xid), "_NET_WM_STATE", "WM_STATE"], env=self.s.env,
                               capture_output=True, text=True).stdout
        self.assertIn("Iconic", state + str(self.s.mn.js("return window.windowState")), state)
        self.assertEqual(self.s.mn.js("return window.windowState"), 2)        # STATE_MINIMIZED
        self.s.xdo("windowactivate", "--sync", xid)
        time.sleep(1.0)
        # zavrit: druhe okno zavrene klikem na cervene kolecko
        before = set(self.s.mn.windows())
        self.s.mn.js("OpenBrowserWindow()")
        for _ in range(50):
            new = set(self.s.mn.windows()) - before
            if new:
                break
            time.sleep(0.2)
        h = new.pop()
        main = self.s.mn.cmd("WebDriver:GetWindowHandle")
        main = main.get("value", main) if isinstance(main, dict) else main
        self.s.mn.switch(h)
        time.sleep(2.0)
        press("close")
        time.sleep(1.0)
        self.s.mn.switch(main)
        self.assertNotIn(h, self.s.mn.windows(), "red button closed the window")


@unittest.skipUnless(GUI, NEEDS_GUI)
class DarkWindow(LightWindow):
    DARK = True
    NAME = "dark"

    def test_6_menubar_vertical_tabs_popup(self):
        self.skipTest("covered by the light window")

    def test_7_clicks_minimize_maximize_close(self):
        self.skipTest("covered by the light window")


@unittest.skipUnless(GUI, NEEDS_GUI)
class HiDpiWindow(GuiBase):
    SCALE = 2
    NAME = "hidpi"

    def test_scaled(self):
        info = self.info()
        self.assertEqual(info["scale"], 2)
        bs = [b for b in info["buttons"] if b["toolbar"] == "TabsToolbar"]
        self.assertEqual([kind(b) for b in bs], ["close", "min", "max"])
        img = self.s.grab()
        for b in bs:
            self.assertTrue(self.ours(b))
            x, y = self.s.screen_xy(info, b)
            area = find_circle(img, x - 24, y - 24, x + 24, y + 24, LIGHT[kind(b)], 3)
            self.assertGreater(area[2], 380, "28 px circle on a 2x screen (about 4x the 1x area)")
        shot(self.s, "hidpi-2x")
        b = bs[0]
        x, y = self.s.screen_xy(info, b)
        self.s.xdo("mousemove", x, y)
        time.sleep(0.4)
        shot(self.s, "hidpi-2x-hover-close", (max(0, x - 60), max(0, y - 30), 200, 60))


@unittest.skipUnless(GUI, NEEDS_GUI)
class BrokenSelectors(GuiBase):
    """Nova verze Firefoxu prejmenuje prvky: styl nic nenajde, zustanou puvodni tlacitka (ne zadna)."""
    NAME = "broken"

    @classmethod
    def setUpClass(cls):
        cls.root = tl.build_root(os.path.join(tl.OUT, "ffroot-broken"), PKG)
        css = os.path.join(cls.root, "luxos", "titlebar.css")
        with open(css) as f:
            text = f.read()
        os.unlink(css)
        with open(css, "w") as f:
            f.write(text.replace("toolbarbutton-icon", "toolbarbutton-icon-renamed"))
        cls.s = tl.Session(name=cls.NAME)
        try:
            cls.s.start_firefox(cls.root)
        except Exception:
            cls.s.stop()
            raise

    def test_default_buttons_remain(self):
        bs = [b for b in self.info()["buttons"] if b["toolbar"] == "TabsToolbar"]
        self.assertEqual([kind(b) for b in bs], ["close", "min", "max"])
        for b in bs:
            self.assertIn("-moz-symbolic-icon", b["img"])
            self.assertGreaterEqual(b["icon"]["w"], 16)
        shot(self.s, "broken-selectors-fallback")


@unittest.skipUnless(GUI, NEEDS_GUI)
class UserChromeKept(GuiBase):
    """Vlastni userChrome.css uzivatele ma prednost (styl LuxOS ho neprepisuje)."""
    NAME = "userchrome"
    PREFS = 'user_pref("toolkit.legacyUserProfileCustomizations.stylesheets", true);\n'

    @classmethod
    def setUpClass(cls):
        cls.root = tl.build_root(os.path.join(tl.OUT, "ffroot-userchrome"), PKG)
        cls.s = tl.Session(name=cls.NAME)
        try:
            cls.s.start_firefox(cls.root, cls.PREFS, user_chrome=(
                ".titlebar-close > .toolbarbutton-icon { background-color: rgb(1, 2, 3) !important; }\n"))
        except Exception:
            cls.s.stop()
            raise

    def test_user_rule_wins(self):
        bs = {kind(b): b for b in self.info()["buttons"] if b["toolbar"] == "TabsToolbar"}
        self.assertEqual(tl.rgb(bs["close"]["bg"]), (1, 2, 3))
        self.assertEqual(tl.rgb(bs["min"]["bg"]), LIGHT["min"])


def content_js(mn, script):
    mn.cmd("Marionette:SetContext", {"value": "content"})
    try:
        return mn.js(script)
    finally:
        mn.cmd("Marionette:SetContext", {"value": "chrome"})


def wait_for(fn, timeout=15):
    end = time.time() + timeout
    while True:
        v = fn()
        if v or time.time() > end:
            return v
        time.sleep(0.3)


@unittest.skipUnless(GUI, NEEDS_GUI)
class FirstRunWelcome(unittest.TestCase):
    """Prvni spusteni noveho profilu: uvitaci stranka LuxOS v jazyce systemu (ne oznameni Mozilly),
    dalsi spusteni ani aktualizace Firefoxu ji uz neotevre."""

    @classmethod
    def setUpClass(cls):
        cls.root = tl.build_root(os.path.join(tl.OUT, "ffroot-firstrun"), PKG)
        cls.s = tl.Session(name="firstrun")

    @classmethod
    def tearDownClass(cls):
        cls.s.stop()

    def welcome_tabs(self):
        return [u for u in self.s.tab_urls() if "/luxos/welcome/index.html" in u]

    def test_once_per_profile(self):
        s = self.s
        s.start_firefox(self.root, first_run=True, env={"LANG": "cs_CZ.UTF-8"}, size=(1100, 800))
        urls = wait_for(lambda: self.welcome_tabs() and s.tab_urls())
        self.assertTrue(any(u.startswith("file://") and u.endswith("/luxos/welcome/index.html?lang=cs") for u in urls),
                        urls)
        time.sleep(2.0)
        urls = s.tab_urls()
        self.assertFalse([u for u in urls if "mozilla" in u or u.startswith("about:welcome")], urls)
        self.assertEqual(len(self.welcome_tabs()), 1)
        s.mn.js("gBrowser.selectedTab = gBrowser.tabs.find(t => t.linkedBrowser.currentURI.spec.includes('/luxos/welcome/'))")
        time.sleep(0.5)
        self.assertEqual(content_js(s.mn, "return document.querySelector('h1').textContent"), "Vítejte v LuxOS")
        self.assertEqual(content_js(s.mn, "return document.documentElement.lang"), "cs")
        self.assertIn("/cs/docs/", content_js(s.mn, "return document.getElementById('link-help').href"))
        # zadne vzdalene nacitani (jen mistni soubory stranky)
        res = content_js(s.mn, "return performance.getEntriesByType('resource').map(e => e.name)")
        self.assertTrue(all(r.startswith("file://") for r in res), res)   # skripty bezely: h1 je cesky
        shot(s, "welcome-first-run-cs")
        # Import: tlacitko otevre pruvodce importem Firefoxu (Nastaveni > Obecne > Import)
        content_js(s.mn, "document.getElementById('import-button').click()")
        prefs = wait_for(lambda: [u for u in s.tab_urls() if u.startswith("about:preferences")], 10)
        self.assertTrue(prefs, s.tab_urls())
        time.sleep(1.5)
        shot(s, "welcome-import-wizard")
        s.quit_firefox()
        # druhe spusteni: uz ne
        s.start_firefox(self.root, first_run=True, env={"LANG": "cs_CZ.UTF-8"})
        time.sleep(3.0)
        self.assertEqual(self.welcome_tabs(), [], s.tab_urls())
        s.quit_firefox()
        # po aktualizaci Firefoxu (jina verze v profilu): ani uvitani, ani stranka Mozilly
        pjs = os.path.join(s.profile, "prefs.js")
        with open(pjs) as f:
            text = f.read()
        self.assertIn("browser.startup.homepage_override.mstone", text)
        text = re.sub(r'user_pref\("browser.startup.homepage_override.mstone", "[^"]*"\);',
                      'user_pref("browser.startup.homepage_override.mstone", "150.0");', text)
        with open(pjs, "w") as f:
            f.write(text)
        s.start_firefox(self.root, first_run=True, env={"LANG": "cs_CZ.UTF-8"})
        time.sleep(3.0)
        urls = s.tab_urls()
        self.assertEqual(self.welcome_tabs(), [], urls)
        self.assertFalse([u for u in urls if "mozilla" in u], urls)
        s.quit_firefox()


class WelcomeShots(unittest.TestCase):
    DARK = False

    @unittest.skipUnless(GUI, NEEDS_GUI)
    def test_languages(self):
        root = tl.build_root(os.path.join(tl.OUT, "ffroot-welcome"), PKG)
        for dark in (False, True):
            s = tl.Session(dark=dark, name="welcome-dark" if dark else "welcome")
            try:
                s.start_firefox(root, 'user_pref("ui.systemUsesDarkTheme", 1);\n' if dark else "", size=(1200, 860))
                page = "file://" + os.path.join(root, "luxos", "welcome", "index.html")
                titles = {}
                for lang in ("cs", "en", "de", "uk") + (() if dark else ("sk", "fr", "pl")):
                    s.mn.js("gBrowser.selectedBrowser.fixupAndLoadURIString(arguments[0], "
                            "{triggeringPrincipal: Services.scriptSecurityManager.getSystemPrincipal()})",
                            page + "?lang=" + lang)
                    time.sleep(1.5)
                    titles[lang] = content_js(s.mn, "return [document.documentElement.lang, document.querySelector('h1').textContent,"
                                                    " matchMedia('(prefers-color-scheme: dark)').matches,"
                                                    " document.body.scrollWidth <= innerWidth]")
                    self.assertEqual(titles[lang][0], lang)
                    self.assertEqual(titles[lang][2], dark)
                    self.assertTrue(titles[lang][3], "no horizontal scroll")
                    shot(s, "welcome-%s-%s" % (lang, "dark" if dark else "light"))
                self.assertEqual(titles["de"][1], "Willkommen bei LuxOS")
                self.assertEqual(titles["uk"][1], "Ласкаво просимо до LuxOS")
                # uzke okno (telefon / pul obrazovky): bez vodorovneho posuvniku
                s.mn.js("window.resizeTo(420, 800)")
                time.sleep(1.5)
                narrow = content_js(s.mn, "return document.documentElement.scrollWidth <= innerWidth")
                self.assertTrue(narrow)
                shot(s, "welcome-narrow-%s" % ("dark" if dark else "light"))
            finally:
                s.stop()


if __name__ == "__main__":
    unittest.main()
