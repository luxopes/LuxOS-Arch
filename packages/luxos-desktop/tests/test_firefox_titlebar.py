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
                  'pref("browser.newtabpage.activity-stream.showSponsoredTopSites", false);',
                  # uvitaci stranka slibuje "zadna technicka data Mozille": ani zeme, test portalu, doporuceni
                  'pref("browser.region.update.enabled", false);',
                  'pref("network.captive-portal-service.enabled", false);',
                  'pref("network.connectivity-service.enabled", false);',
                  'pref("browser.discovery.enabled", false);',
                  'pref("browser.newtabpage.activity-stream.feeds.section.topstories", false);'):
            self.assertIn(p, js)
        # domovska stranka se nevnucuje (uvitaci stranka jen pri prvnim spusteni profilu)
        self.assertNotIn("browser.startup.homepage\"", js)

    def test_ublock_origin_by_default(self):
        """uBlock Origin z balicku Archu (doplnek v adresari aplikace), zapnuty bez dotazu, bez policies.json."""
        pb = read(PKGBUILD)
        deps = re.search(r"\ndepends=\((.*?)\n\)", pb, re.S).group(1)
        self.assertRegex(deps, r"\n    firefox-ublock-origin\n")
        js = read(os.path.join(FF, "luxos.js"))
        m = re.search(r'pref\("extensions\.autoDisableScopes", (\d+)\);', js)
        self.assertTrue(m)
        self.assertFalse(int(m.group(1)) & 4, "application scope (browser/extensions) must not be auto-disabled")
        self.assertNotIn("enabledScopes", js)
        cfg = read(os.path.join(FF, "luxos.cfg"))
        self.assertIn('getAddonByID("uBlock0@raymondhill.net")', cfg)

    def test_welcome_handshake(self):
        """Stranka vi, jestli luxos.cfg odpovida (#hello -> #ok); bez odpovedi web a navod, ne ticho."""
        cfg = read(os.path.join(FF, "luxos.cfg"))
        js = read(os.path.join(FF, "welcome", "welcome.js"))
        html = read(os.path.join(FF, "welcome", "index.html"))
        self.assertIn('"#ok-" + stamp + flags', cfg)
        self.assertIn("LOAD_FLAGS_REPLACE_HISTORY", cfg)
        self.assertIn('location.replace("#hello-" + Date.now())', js)
        self.assertIn('window.open(a.href, "_blank", "noopener,noreferrer")', js)
        self.assertRegex(html, r'<p class="import-help" id="import-help" role="status"[^>]* hidden')
        self.assertRegex(html, r'<li class="card badge" id="badge-ubo" hidden>')

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

    def test_welcome_small_and_accessible(self):
        d = os.path.join(FF, "welcome")
        total = sum(os.path.getsize(os.path.join(d, n)) for n in os.listdir(d))
        self.assertLess(total, 300 * 1024, "welcome page must stay small")
        html = read(os.path.join(d, "index.html"))
        self.assertIn('<html lang="en">', html)
        self.assertIn('<meta name="viewport"', html)
        # zadne obrazky ani pisma zvenku ani ze souboru: ikony jsou inline SVG, pismo Inter je systemove
        self.assertNotRegex(html, r"<img\b|@font-face")
        # animace jen s ohledem na prefers-reduced-motion, viditelny fokus pro klavesnici
        rm = re.search(r"@media \(prefers-reduced-motion: reduce\) \{(.*?)\n  \}", html, re.S)
        self.assertTrue(rm and "animation: none" in rm.group(1) and "transition: none" in rm.group(1))
        self.assertRegex(html, r"\.button:focus-visible, \.tile:focus-visible \{\s*outline: 3px solid")
        self.assertIn("@media (prefers-color-scheme: dark)", html)
        # kazda sekce ma nadpis (aria-labelledby ukazuje na existujici id)
        for ref in re.findall(r'aria-labelledby="([^"]+)"', html):
            self.assertIn('id="%s"' % ref, html)
        # ceska verze s diakritikou
        src = read(os.path.join(d, "strings.js"))
        cs = re.search(r"\n  cs: \{(.*?)\n  \},", src, re.S).group(1)
        for word in ("Vítejte", "záložky", "Soukromí", "Nápověda", "Žádné sledování"):
            self.assertIn(word, cs)

    def test_welcome_apps_match_cfg(self):
        """Dlazdice aplikaci (data-app) maji v luxos.cfg aplikaci a webovou napovedu, ktera existuje."""
        html = read(os.path.join(FF, "welcome", "index.html"))
        cfg = read(os.path.join(FF, "luxos.cfg"))
        apps = re.findall(r'data-app="([a-z]+)"', html)
        self.assertEqual(sorted(apps), ["keys", "luxai", "report", "store"])
        for app in apps:
            self.assertRegex(cfg, r'\n      %s: \["(luxos-[a-z]+|luxai)", ' % app)
        docs = os.path.join(HERE, "..", "..", "apps", "luxos-docs", "docs", "luxos")
        site = os.path.join(HERE, "..", "..", "..", "site", "content", "en", "luxos")
        pages = re.findall(r'(?:docs \+ "|"https://luxos\.lux-ai\.cz/docs/luxos/)([a-z-]+)\.html"', cfg) + \
            re.findall(r'href="https://luxos\.lux-ai\.cz/docs/luxos/([a-z-]+)\.html"', html)
        self.assertEqual(len(pages), 6)
        if os.path.isdir(docs):
            for page in pages:
                self.assertTrue(os.path.exists(os.path.join(docs, page + ".md")) or
                                os.path.exists(os.path.join(site, page + ".md")), page)
        # ceska verze webu (/cs/docs/) jen u stranek, ktere cesky existuji (obchod cesky neni -> 404)
        cs_site = os.path.join(HERE, "..", "..", "..", "site", "content", "cs", "luxos")
        cs_pages = re.findall(r'docs \+ "([a-z-]+)\.html"', cfg) + [
            m for m in re.findall(r'<a [^>]*data-cs[^>]*href="https://luxos\.lux-ai\.cz/docs/(?:luxos/([a-z-]+)\.html)?"',
                                  html) if m]
        self.assertEqual(len(cs_pages), 4)
        if os.path.isdir(cs_site):
            for page in cs_pages:
                self.assertTrue(os.path.exists(os.path.join(cs_site, page + ".md")), page)
        self.assertNotRegex(html, r'<a [^>]*id="link-store"[^>]*data-cs')
        # akce jen ze stranky uvitani, jen cerstve a jednou
        self.assertIn("location.spec.startsWith(welcome)", cfg)
        self.assertIn("Date.now() - t) < 60000", cfg)

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


def switch_tab(mn, needle):
    """Marionette (obsah) na kartu, jejiz adresa obsahuje needle; vybere ji i v okne."""
    mn.cmd("Marionette:SetContext", {"value": "content"})
    try:
        for h in mn.cmd("WebDriver:GetWindowHandles"):
            mn.cmd("WebDriver:SwitchToWindow", {"handle": h, "focus": True})
            url = mn.cmd("WebDriver:GetCurrentURL")
            if needle in (url.get("value", url) if isinstance(url, dict) else url):
                return True
        return False
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
        self.assertIn("/cs/docs/", content_js(s.mn, "return document.getElementById('link-luxai').href"))
        # Obchod cesky na webu neni: anglicka stranka (ne 404)
        self.assertIn("lux-ai.cz/docs/luxos/store.html", content_js(s.mn, "return document.getElementById('link-store').href"))
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


@unittest.skipUnless(GUI, NEEDS_GUI)
class TouchPrefs(unittest.TestCase):
    """Dotykova obrazovka (luxos-touch: ~/.config/luxos/touch-state): dotyk jako dotyk (posouvani stranky
    prstem), bez ni vychozi chovani Firefoxu."""

    @classmethod
    def setUpClass(cls):
        cls.root = tl.build_root(os.path.join(tl.OUT, "ffroot-touch"), PKG)
        cls.s = tl.Session(name="touch")

    @classmethod
    def tearDownClass(cls):
        cls.s.stop()

    def prefs(self):
        return self.s.mn.js("return [Services.prefs.getIntPref('dom.w3c_touch_events.enabled', -1), "
                            "Services.prefs.prefHasUserValue('dom.w3c_touch_events.enabled'), "
                            "Services.prefs.getDefaultBranch('').getIntPref('browser.tabs.inTitlebar', -1)]")

    def test_touch_events_only_with_touchscreen(self):
        s = self.s
        state = os.path.join(s.env["XDG_CONFIG_HOME"], "luxos", "touch-state")
        os.makedirs(os.path.dirname(state), exist_ok=True)
        for text, want in (("touchscreen=0 keyboard=1 accel=0\n", False), ("touchscreen=1 keyboard=0 accel=1\n", True)):
            with self.subTest(state=text.strip()):
                with open(state, "w") as f:
                    f.write(text)
                s.start_firefox(self.root)
                value, user, titlebar = wait_for(self.prefs)
                s.quit_firefox()
                self.assertFalse(user)                    # vychozi hodnota, uzivatel ji muze zmenit
                if want:
                    self.assertEqual(value, 1)
                    # dotyk: zahlavi xfwm4 (tazeni okna prstem pres Firefox rozbijelo dotyk ve Firefoxu); vychozi
                    # hodnota - harness si do profilu zapisuje vlastni inTitlebar=1
                    self.assertEqual(titlebar, 0)
                else:
                    self.assertNotEqual(value, 1)
                    self.assertNotEqual(titlebar, 0)


@unittest.skipUnless(GUI, NEEDS_GUI)
class WelcomeActions(unittest.TestCase):
    """Dlazdice otevrou aplikace LuxOS (testovaci napodobeniny), bez aplikace web; tlacitko Zpet akci
    neopakuje; prefers-reduced-motion vypne animace; fokus z klavesnice je videt."""

    @classmethod
    def setUpClass(cls):
        cls.root = tl.build_root(os.path.join(tl.OUT, "ffroot-actions"), PKG)
        cls.apps = os.path.join(tl.OUT, "fake-apps")
        cls.marker = os.path.join(tl.OUT, "fake-apps.log")
        shutil.rmtree(cls.apps, ignore_errors=True)
        os.makedirs(cls.apps)
        if os.path.exists(cls.marker):
            os.unlink(cls.marker)
        for name in ("luxos-store", "luxai", "luxos-shortcuts"):      # luxos-feedback schvalne chybi
            path = os.path.join(cls.apps, name)
            with open(path, "w") as f:
                f.write("#!/bin/sh\necho %s >> '%s'\n" % (name, cls.marker))
            os.chmod(path, 0o755)
        cls.s = tl.Session(name="welcome-actions")
        cls.prefs = prefs = ('user_pref("luxos.welcome.appdir", "%s");\n' % cls.apps +
                 # zadna skutecna sit: nahradni stranka webu jen jako adresa nove karty
                 'user_pref("network.proxy.type", 1);\nuser_pref("network.proxy.http", "127.0.0.1");\n'
                 'user_pref("network.proxy.http_port", 9);\nuser_pref("network.proxy.ssl", "127.0.0.1");\n'
                 'user_pref("network.proxy.ssl_port", 9);\nuser_pref("ui.prefersReducedMotion", 1);\n')
        try:
            cls.s.start_firefox(cls.root, prefs, size=(1200, 860))
        except Exception:
            cls.s.stop()
            raise
        cls.page = "file://" + os.path.join(cls.root, "luxos", "welcome", "index.html")

    @classmethod
    def tearDownClass(cls):
        cls.s.stop()

    def load(self, lang="en"):
        self.s.mn.js("gBrowser.selectedTab = gBrowser.tabs[0]; gBrowser.selectedBrowser.fixupAndLoadURIString("
                     "arguments[0], {triggeringPrincipal: Services.scriptSecurityManager.getSystemPrincipal()})",
                     self.page + "?lang=" + lang)
        time.sleep(0.5)
        wait_for(lambda: content_js(self.s.mn, "return document.readyState == 'complete' && "
                                               "document.documentElement.lang") == lang)

    def launched(self):
        if not os.path.exists(self.marker):
            return []
        with open(self.marker) as f:
            return f.read().split()

    def click(self, element_id):
        content_js(self.s.mn, "document.getElementById(%r).click()" % element_id)

    def test_0_handshake(self):
        self.load()
        st = wait_for(lambda: content_js(self.s.mn, "return document.documentElement.dataset.hook"), 5)
        self.assertEqual(st, "on")
        # odpoved jen zmenila # (zadne nove nacteni), adresa je zase cista, uBlock tu neni -> bez odznaku
        content_js(self.s.mn, "window.__luxos_mark = 7")
        time.sleep(0.6)
        self.assertEqual(content_js(self.s.mn, "return [window.__luxos_mark, location.hash, "
                                               "document.getElementById('badge-ubo').hidden, history.length]"),
                         [7, "", True, 2])

    def test_1_tiles_open_apps(self):
        self.load()
        for tile, app in (("link-store", "luxos-store"), ("link-luxai", "luxai"), ("link-keys", "luxos-shortcuts")):
            before = len(self.launched())
            tabs = len(self.s.tab_urls())
            self.click(tile)
            self.assertTrue(wait_for(lambda: len(self.launched()) > before, 10), tile)
            self.assertEqual(self.launched()[-1], app)
            time.sleep(0.8)
            self.assertEqual(len(self.s.tab_urls()), tabs, "app opened, no extra tab")
        # adresa stranky je zase bez # (Zpet / obnoveni relace nic neopakuje)
        self.assertTrue(wait_for(lambda: "#" not in self.s.tab_urls()[0], 5), self.s.tab_urls())

    def test_2_missing_app_opens_help_page(self):
        self.load("cs")
        self.click("link-report")
        urls = wait_for(lambda: [u for u in self.s.tab_urls() if "/luxopes/LuxOS-Arch/issues" in u], 10)
        self.assertTrue(urls, self.s.tab_urls())
        self.assertNotIn("luxos-feedback", self.launched())
        self.s.mn.js("for (const t of gBrowser.tabs.slice(1)) gBrowser.removeTab(t)")

    def test_3_stale_or_repeated_links_ignored(self):
        self.load()
        n = len(self.launched())
        old = self.page + "?lang=en#open-store-1000"                    # stary cas (napr. obnovena relace)
        self.s.mn.js("gBrowser.selectedBrowser.fixupAndLoadURIString(arguments[0], "
                     "{triggeringPrincipal: Services.scriptSecurityManager.getSystemPrincipal()})", old)
        time.sleep(1.5)
        self.assertEqual(len(self.launched()), n)
        # stejny odkaz podruhe (tlacitko Zpet na adresu s #): nic
        ref = "open-luxai-%d" % int(time.time() * 1000)
        content_js(self.s.mn, "location.replace('#%s')" % ref)
        self.assertTrue(wait_for(lambda: len(self.launched()) == n + 1, 10))
        content_js(self.s.mn, "location.replace('#x')")
        time.sleep(0.3)
        content_js(self.s.mn, "location.replace('#%s')" % ref)
        time.sleep(1.5)
        self.assertEqual(len(self.launched()), n + 1)
        # cizi nazev aplikace: nic nespusti, zadna nova karta
        tabs = len(self.s.tab_urls())
        content_js(self.s.mn, "location.replace('#open-sh-' + Date.now())")
        time.sleep(1.5)
        self.assertEqual(len(self.launched()), n + 1)
        self.assertEqual(len(self.s.tab_urls()), tabs)

    def test_5_new_window(self):
        """Hak funguje i v dalsim okne otevrenem pozdeji."""
        before = set(self.s.mn.windows())
        main = self.s.mn.cmd("WebDriver:GetWindowHandle")
        main = main.get("value", main) if isinstance(main, dict) else main
        self.s.mn.js("OpenBrowserWindow()")
        new = wait_for(lambda: set(self.s.mn.windows()) - before, 10)
        self.s.mn.switch(new.pop())
        try:
            self.s.wait_window()
            self.load("sk")
            self.assertEqual(wait_for(lambda: content_js(self.s.mn, "return document.documentElement.dataset.hook"), 5),
                             "on")
            n = len(self.launched())
            self.click("link-store")
            self.assertTrue(wait_for(lambda: len(self.launched()) > n, 10))
        finally:
            self.s.mn.js("window.close()")
            self.s.mn.switch(main)
            time.sleep(1.0)

    def test_9_after_session_restore(self):
        """Po obnoveni relace (restart Firefoxu) odpovida luxos.cfg obnovene strance znovu."""
        self.load("pl")
        time.sleep(1.0)
        self.s.quit_firefox()
        self.s.start_firefox(self.root, self.prefs + 'user_pref("browser.startup.page", 3);\n', size=(1200, 860),
                             url=None)
        self.assertTrue(wait_for(lambda: any("/luxos/welcome/" in u for u in self.s.tab_urls()), 15), self.s.tab_urls())
        self.s.mn.js("gBrowser.selectedTab = gBrowser.tabs.find(t => t.linkedBrowser.currentURI.spec.includes('/luxos/welcome/'))")
        self.assertEqual(wait_for(lambda: content_js(self.s.mn, "return document.readyState == 'complete' && "
                                                                "document.documentElement.dataset.hook"), 10), "on")
        n = len(self.launched())
        self.click("link-keys")
        self.assertTrue(wait_for(lambda: len(self.launched()) > n, 10))
        self.assertEqual(self.launched()[-1], "luxos-shortcuts")

    def test_4_reduced_motion_and_focus(self):
        self.load("de")
        st = content_js(self.s.mn, "return [matchMedia('(prefers-reduced-motion: reduce)').matches,"
                                   " document.getAnimations().length,"
                                   " getComputedStyle(document.querySelector('h1')).opacity]")
        self.assertEqual(st, [True, 0, "1"])
        # Tab z klavesnice: prvni prvek je tlacitko importu s viditelnym obrysem
        xid = self.s.xid("Mozilla Firefox")[0]
        self.s.xdo("windowactivate", "--sync", xid)
        self.s.mn.js("gBrowser.selectedBrowser.focus()")
        time.sleep(0.4)
        self.s.xdo("key", "Tab")
        time.sleep(0.5)
        focus = content_js(self.s.mn, "const e = document.activeElement, c = getComputedStyle(e);"
                                      " return [e.id, e.matches(':focus-visible'), c.outlineStyle, c.outlineWidth]")
        self.assertEqual(focus, ["import-button", True, "solid", "3px"])
        shot(self.s, "welcome-focus-import")


@unittest.skipUnless(GUI, NEEDS_GUI)
class WelcomeWithoutAnswer(unittest.TestCase):
    """Firefox spusteny pred aktualizaci LuxOS (starsi luxos.cfg bez odpovedi na #hello) a stranka otevrena
    pozdeji: dlazdice vedou na web, import zkusi pruvodce a ukaze navod - nic nezustane bez reakce."""

    @classmethod
    def setUpClass(cls):
        cls.root = tl.build_root(os.path.join(tl.OUT, "ffroot-noanswer"), PKG)
        cfg = os.path.join(cls.root, "luxos.cfg")
        with open(cfg) as f:
            text = f.read()
        os.unlink(cfg)
        with open(cfg, "w") as f:
            f.write(text.replace("m = /^hello-", "m = /^nohello-"))
        cls.apps = os.path.join(tl.OUT, "fake-apps-noanswer")
        cls.marker = os.path.join(tl.OUT, "fake-apps-noanswer.log")
        shutil.rmtree(cls.apps, ignore_errors=True)
        os.makedirs(cls.apps)
        if os.path.exists(cls.marker):
            os.unlink(cls.marker)
        with open(os.path.join(cls.apps, "luxos-store"), "w") as f:
            f.write("#!/bin/sh\necho luxos-store >> '%s'\n" % cls.marker)
        os.chmod(os.path.join(cls.apps, "luxos-store"), 0o755)
        cls.s = tl.Session(name="welcome-noanswer")
        prefs = ('user_pref("luxos.welcome.appdir", "%s");\n' % cls.apps +
                 'user_pref("network.proxy.type", 1);\nuser_pref("network.proxy.http", "127.0.0.1");\n'
                 'user_pref("network.proxy.http_port", 9);\nuser_pref("network.proxy.ssl", "127.0.0.1");\n'
                 'user_pref("network.proxy.ssl_port", 9);\n')
        try:
            cls.s.start_firefox(cls.root, prefs, size=(1200, 860))
        except Exception:
            cls.s.stop()
            raise
        page = "file://" + os.path.join(cls.root, "luxos", "welcome", "index.html") + "?lang=cs"
        # jako "firefox URL" do bezici instance
        subprocess.run([os.path.join(cls.root, "firefox"), "--profile", cls.s.profile, page], env=cls.s.env,
                       capture_output=True, timeout=60)

    @classmethod
    def tearDownClass(cls):
        cls.s.stop()

    def welcome(self):
        self.assertTrue(switch_tab(self.s.mn, "/luxos/welcome/"), self.s.tab_urls())

    def test_1_tiles_fall_back_to_web(self):
        self.assertTrue(wait_for(lambda: any("/luxos/welcome/" in u for u in self.s.tab_urls()), 15), self.s.tab_urls())
        self.welcome()
        self.assertEqual(wait_for(lambda: content_js(self.s.mn, "return document.documentElement.dataset.hook"), 5), "off")
        self.assertEqual(content_js(self.s.mn, "return location.hash"), "")
        content_js(self.s.mn, "document.getElementById('link-store').click()")
        urls = wait_for(lambda: [u for u in self.s.tab_urls() if u.endswith("/docs/luxos/store.html")], 10)
        self.assertTrue(urls, self.s.tab_urls())
        self.assertFalse(os.path.exists(self.marker), "no app launched without the answer")
        self.s.mn.js("for (const t of gBrowser.tabs.filter(t => t.linkedBrowser.currentURI.spec.includes('store.html')))"
                     " gBrowser.removeTab(t)")

    def test_2_import_shows_instructions(self):
        self.welcome()
        content_js(self.s.mn, "document.getElementById('import-button').click()")
        time.sleep(1.0)
        st = content_js(self.s.mn, "const h = document.getElementById('import-help');"
                                   " return [h.hidden, h.textContent, document.activeElement === h]")
        self.assertFalse(st[0])
        self.assertIn("Nastavení → Obecné → Importovat data prohlížeče", st[1])
        self.assertTrue(st[2])
        # starsi luxos.cfg import umel: pruvodce se otevre i tak
        self.assertTrue(wait_for(lambda: [u for u in self.s.tab_urls() if u.startswith("about:preferences")], 10))
        shot(self.s, "welcome-noanswer-import")


UBO_XPI = os.environ.get("LUXOS_UBO_XPI") or "/usr/lib/firefox/browser/extensions/uBlock0@raymondhill.net.xpi"
ADDON_JS = """return (async () => {
  const {AddonManager} = ChromeUtils.importESModule('resource://gre/modules/AddonManager.sys.mjs');
  const a = await AddonManager.getAddonByID('uBlock0@raymondhill.net');
  const {ExtensionsUI} = ChromeUtils.importESModule('resource:///modules/ExtensionsUI.sys.mjs');
  return [a && a.isActive, a && a.userDisabled, a && a.scope, ExtensionsUI.sideloaded.size,
          document.getElementById('PanelUI-menu-button').getAttribute('badge-status') || ''];
})()"""


@unittest.skipUnless(GUI and os.path.exists(UBO_XPI), NEEDS_GUI + " and firefox-ublock-origin (or LUXOS_UBO_XPI)")
class UBlockOrigin(unittest.TestCase):
    """uBlock Origin z balicku: zapnuty bez dotazu v novem i stavajicim profilu, blokuje reklamy bez site,
    uvitaci stranka ukaze odznak a funguje dal."""

    @classmethod
    def setUpClass(cls):
        cls.root = tl.build_root(os.path.join(tl.OUT, "ffroot-ubo"), PKG, extensions=[UBO_XPI])
        cls.plain = tl.build_root(os.path.join(tl.OUT, "ffroot-ubo-before"), PKG)
        # mistni "web s reklamami": vsechny nazvy -> 127.0.0.1 (network.dns.forceResolve), zadna skutecna sit
        cls.www = os.path.join(tl.OUT, "ad-test")
        shutil.rmtree(cls.www, ignore_errors=True)
        os.makedirs(os.path.join(cls.www, "pagead", "js"))
        cls.port = tl.free_port()
        with open(os.path.join(cls.www, "index.html"), "w") as f:
            f.write('<!doctype html><title>news</title><h1>News</h1>'
                    '<div id="bait" class="ad-slot google-ad" style="display:block;width:300px;height:250px">AD</div>'
                    '<script src="http://pagead2.googlesyndication.com:%d/pagead/js/adsbygoogle.js"></script>'
                    '<script src="/site.js"></script>' % cls.port)
        with open(os.path.join(cls.www, "pagead", "js", "adsbygoogle.js"), "w") as f:
            f.write("window.__ad_loaded = 1;")
        with open(os.path.join(cls.www, "site.js"), "w") as f:
            f.write("window.__site_loaded = 1;")
        cls.log = open(os.path.join(tl.OUT, "ad-test.log"), "w")
        cls.http = subprocess.Popen([sys.executable, "-m", "http.server", str(cls.port), "--bind", "127.0.0.1",
                                     "--directory", cls.www], stdout=cls.log, stderr=subprocess.STDOUT)
        cls.prefs = ('user_pref("network.dns.forceResolve", "127.0.0.1");\nuser_pref("network.proxy.type", 0);\n'
                     'user_pref("network.dns.disableIPv6", true);\n')
        cls.s = tl.Session(name="ubo")

    @classmethod
    def tearDownClass(cls):
        cls.s.stop()
        cls.http.terminate()
        cls.http.wait()
        cls.log.close()

    def ad_page(self, s):
        s.mn.js("gBrowser.selectedBrowser.fixupAndLoadURIString(arguments[0], "
                "{triggeringPrincipal: Services.scriptSecurityManager.getSystemPrincipal()})",
                "http://news.example:%d/?%d" % (self.port, time.time() * 1000))
        time.sleep(2.0)
        try:
            return content_js(s.mn, "return [document.title, !!window.__site_loaded, !!window.__ad_loaded,"
                                    " document.getElementById('bait').offsetHeight]")
        except RuntimeError:
            return None                                # jeste se nacita (uBlock pri startu pozdrzi sit)

    def test_1_existing_profile_gets_it_enabled(self):
        s = self.s
        s.start_firefox(self.plain, self.prefs)
        self.assertEqual(s.mn.js(ADDON_JS)[0], None, "not there before the update")
        # kontrola testu: bez uBlocku se reklama nacte
        st = wait_for(lambda: self.ad_page(s), 20)
        self.assertEqual(st, ["news", True, True, 250])
        s.quit_firefox()
        # "aktualizace": stejny profil, Firefox uz s doplnkem v browser/extensions
        s.start_firefox(self.root, self.prefs, size=(1200, 860))
        st = wait_for(lambda: s.mn.js(ADDON_JS)[0] and s.mn.js(ADDON_JS), 15)
        self.assertEqual(st, [True, False, 4, 0, ""], "enabled without any prompt or menu badge")
        s.quit_firefox()

    def test_2_new_profile_blocks_ads_offline(self):
        s = tl.Session(name="ubo-new")
        try:
            s.start_firefox(self.root, self.prefs, size=(1200, 860))
            st = wait_for(lambda: s.mn.js(ADDON_JS)[0] and s.mn.js(ADDON_JS), 15)
            self.assertEqual(st, [True, False, 4, 0, ""])
            # zadna stranka uBlocku navic, ikona na liste
            self.assertEqual([u for u in s.tab_urls() if u.startswith("moz-extension:")], [])
            self.assertTrue(s.mn.js("return !!document.querySelector('[data-extensionid=\"uBlock0@raymondhill.net\"]')"))

            with open(os.path.join(tl.OUT, "ad-test.log")) as f:
                seen = f.read().count("adsbygoogle.js")       # z kontroly bez uBlocku v testu 1

            def blocked():
                st = self.ad_page(s)
                return st if st and st[1] and not st[2] and st[3] == 0 else None
            st = wait_for(blocked, 40)
            self.assertTrue(st, "ad script and ad box blocked, the page itself loads")
            with open(os.path.join(tl.OUT, "ad-test.log")) as f:
                self.assertEqual(f.read().count("adsbygoogle.js"), seen, "the ad request never left Firefox")
            shot(s, "ublock-ad-test")
            # uvitaci stranka: odznak uBlocku, vse funguje
            page = "file://" + os.path.join(self.root, "luxos", "welcome", "index.html") + "?lang=de"
            s.mn.js("gBrowser.selectedBrowser.fixupAndLoadURIString(arguments[0], "
                    "{triggeringPrincipal: Services.scriptSecurityManager.getSystemPrincipal()})", page)
            st = wait_for(lambda: content_js(s.mn, "return document.documentElement.dataset.hook == 'on' && "
                                                   "[document.getElementById('badge-ubo').hidden,"
                                                   " document.querySelector('#badge-ubo strong').textContent,"
                                                   " getComputedStyle(document.querySelector('.mark svg')).display,"
                                                   " document.querySelectorAll('.badges > li:not([hidden])').length]"), 10)
            self.assertEqual(st, [False, "Werbung und Tracker blockiert", "block", 4])
            shot(s, "welcome-ublock-badge")
        finally:
            s.stop()


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
                for lang in ("cs", "en", "de", "uk") + (() if dark else tuple(sorted(set(LANGS) - {"cs", "en", "de", "uk"}))):
                    s.mn.js("gBrowser.selectedBrowser.fixupAndLoadURIString(arguments[0], "
                            "{triggeringPrincipal: Services.scriptSecurityManager.getSystemPrincipal()})",
                            page + "?lang=" + lang)
                    time.sleep(1.5)
                    titles[lang] = content_js(s.mn, "return [document.documentElement.lang, document.querySelector('h1').textContent,"
                                                    " matchMedia('(prefers-color-scheme: dark)').matches,"
                                                    " document.body.scrollWidth <= innerWidth]")
                    self.assertEqual(titles[lang][0], lang)
                    if lang != "en":
                        self.assertNotEqual(titles[lang][1], "Welcome to LuxOS", lang)
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
