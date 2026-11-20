#!/usr/bin/env python3
"""luxos_tokens.lsl: hodnoty vzhledu pro desktop na Waylandu a generatory z nich.

    python3 -m unittest packages/luxos-desktop/tests/test_luxos_tokens.py -v

- vystupy generatoru (CSS GTK 3, tema labwc/luxwm, cast rc.xml, JSON) se shoduji se snimky v tokens-snapshots/
  (LUXOS_UPDATE_SNAPSHOTS=1 je prepise - jen po zamerne zmene hodnot a kontrole rozdilu)
- hodnoty se nerozesly s kodem, ze ktereho byly sebrane (lista, sklo, widgety, motivy, zamek, prechody)
- pomocne funkce: linearni sRGB, kontrast WCAG, hystereze pisma listy, zavoj, krivky
- CSS projde parserem GTK 3, tema pouziva jen klice labwc, SVG tlacitek jsou platne XML
LUXOS_LSLC: prekladac lslc (jinak lslc z PATH).
"""
import glob
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
FILES = PKG / "files"
REPO = PKG.parent.parent
SNAP = HERE / "tokens-snapshots"
LSLC = os.environ.get("LUXOS_LSLC") or shutil.which("lslc")
UPDATE = os.environ.get("LUXOS_UPDATE_SNAPSHOTS") == "1"
GPT_BRANCH = "gpt-features-1.1.1"


def srgb_linear(v):
    c = v / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def smoothstep(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def git_show(path):
    r = subprocess.run(["git", "-C", str(REPO), "show", GPT_BRANCH + ":" + path], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


@unittest.skipUnless(LSLC, "chybi lslc (LUXOS_LSLC)")
class Tokens(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="luxos-tokens-"))
        for f in glob.glob(str(FILES / "lsl" / "*.lsl")):
            shutil.copy(f, cls.tmp)
        shutil.copy(HERE / "lsl" / "luxos-tokens-test.lsl", cls.tmp)
        cls.gen = cls.tmp / "luxos-tokens"
        cls.helper = cls.tmp / "tokens-test"
        for src, out in (("luxos-tokens.lsl", cls.gen), ("luxos-tokens-test.lsl", cls.helper)):
            r = subprocess.run([LSLC, "--target", "linux-x86_64-gnu", str(cls.tmp / src), str(out)],
                               capture_output=True, text=True, timeout=300)
            if r.returncode:
                raise AssertionError(r.stdout + r.stderr)
        cls.tokens = json.loads(cls.run_gen("json"))
        cls.helpers = json.loads(subprocess.check_output([str(cls.helper)], text=True, timeout=30))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, True)

    @classmethod
    def run_gen(cls, *argv):
        return subprocess.check_output([str(cls.gen), *argv], text=True, timeout=30)

    def outputs(self):
        out = {"json.json": json.dumps(self.tokens, indent=1, sort_keys=True) + "\n"}
        for mode in ("light", "dark"):
            out["gtk3-%s.css" % mode] = self.run_gen("css", mode)
            out["rc-%s.xml" % mode] = self.run_gen("rc", mode)
            d = self.tmp / ("labwc-" + mode)
            self.run_gen("labwc", str(d), mode)
            for f in sorted(d.iterdir()):
                out["labwc-%s/%s" % (mode, f.name)] = f.read_text()
        return out

    # ---- snimky ----

    def test_generator_snapshots(self):
        out = self.outputs()
        if UPDATE:
            shutil.rmtree(SNAP, True)
            for name, text in out.items():
                (SNAP / name).parent.mkdir(parents=True, exist_ok=True)
                (SNAP / name).write_text(text)
        have = sorted(str(p.relative_to(SNAP)) for p in SNAP.rglob("*") if p.is_file())
        self.assertEqual(have, sorted(out), "sada souboru generatoru")
        for name, text in out.items():
            self.assertEqual((SNAP / name).read_text(), text, name)

    def test_usage_errors(self):
        for argv in ([], ["css"], ["css", "blue"], ["labwc", "x"], ["nic"]):
            r = subprocess.run([str(self.gen), *argv], capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 2, argv)

    # ---- generovane soubory jsou pouzitelne ----

    def test_css_parses_in_gtk3(self):
        script = r'''
import sys, json, gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk
out = []
for path in sys.argv[1:]:
    errs = []
    p = Gtk.CssProvider()
    p.connect("parsing-error", lambda p, s, e: errs.append(e.message))
    try:
        p.load_from_data(open(path, "rb").read())
    except Exception as e:
        errs.append(str(e))
    out.append(errs)
print(json.dumps(out))
'''
        paths = []
        for mode in ("light", "dark"):
            p = self.tmp / ("check-%s.css" % mode)
            p.write_text(self.run_gen("css", mode))
            paths.append(str(p))
        bad = self.tmp / "bad.css"
        bad.write_text(".lx { colr: red; border-radius: 4qx; }\n")
        env = {k: v for k, v in os.environ.items() if k not in ("DISPLAY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS")}
        r = subprocess.run(["python3", "-c", script, *paths, str(bad)], capture_output=True, text=True, timeout=60, env=env)
        if r.returncode or "No module named" in r.stderr:
            self.skipTest("python-gobject/GTK 3 neni k dispozici: " + r.stderr[-300:])
        light, dark, broken = json.loads(r.stdout)
        self.assertEqual(light, [])
        self.assertEqual(dark, [])
        self.assertTrue(broken, "kontrola parseru musi chybu odhalit")

    def test_labwc_keys_and_svg(self):
        docs = os.environ.get("LUXOS_LABWC_THEMERC") or next(iter(sorted(glob.glob(str(REPO / "out/wl2/dl/x/labwc-0.20*/docs/themerc")))), None)
        for mode in ("light", "dark"):
            d = self.tmp / ("labwc-" + mode)
            self.run_gen("labwc", str(d), mode)
            keys = []
            for line in (d / "themerc").read_text().splitlines():
                if line and not line.startswith("#"):
                    key, value = line.split(": ", 1)
                    keys.append(key)
                    if key.endswith(".color"):
                        self.assertRegex(value, r"^#[0-9a-f]{8}$", key)
            self.assertEqual(len(keys), len(set(keys)), "zadny klic dvakrat")
            if docs:
                known = set(re.findall(r"^#?\s*([a-z][\w.*-]+):", Path(docs).read_text(), re.M))
                self.assertEqual([k for k in keys if k not in known], [], "klice, ktere labwc 0.20 nezna")
            svgs = sorted(p.name for p in d.glob("*.svg"))
            self.assertEqual(len(svgs), 16)
            for name in ("close", "iconify", "max", "max_toggled"):
                for state in ("-active", "-inactive", "_hover-active", "_hover-inactive"):
                    self.assertIn(name + state + ".svg", svgs)
            for name in svgs:
                root = ET.fromstring((d / name).read_text())
                self.assertEqual(root.get("width"), "20")
                # znak jen pri najeti mysi
                self.assertEqual(any(e.tag.endswith("path") for e in root), "_hover" in name, name)
        rc = self.run_gen("rc", "light")
        ET.fromstring(rc)
        self.assertIn("<layout>close,iconify,max:</layout>", rc)
        if not docs:
            self.skipTest("bez zdroju labwc (LUXOS_LABWC_THEMERC): klice themerc neovereny")

    # ---- pomocne funkce ----

    def test_srgb_and_contrast(self):
        for v, got in enumerate(self.helpers["lut"]):
            self.assertAlmostEqual(got, srgb_linear(v), places=14)
        w0, w1, w2 = self.helpers["white_contrast"]
        self.assertAlmostEqual(w0, 21.0, places=12)
        self.assertAlmostEqual(w1, 1.0, places=12)
        self.assertAlmostEqual(w2, 1.05 / 0.25, places=12)
        # text popupu na bilem pozadi: WCAG AA
        self.assertGreaterEqual(self.helpers["contrast"], 4.5)

    def test_ink_hysteresis_like_bar(self):
        # luxos-bar.c want_dark_ink: na tmave pod 2,0, zpet na bile az nad 2,3
        expected, current = [], False
        for c in [3.0, 2.4, 2.1, 1.99, 1.5, 2.0, 2.2, 2.29, 2.3, 2.5, 2.1, 1.9]:
            current = c < 2.3 if current else c < 2.0
            expected.append(current)
        self.assertEqual(self.helpers["ink"], expected)
        self.assertEqual(expected, [False, False, False, True, True, True, True, True, False, False, False, True])

    def test_scrim_and_curves(self):
        for lum, got in zip([0.0, 0.2, 0.4, 0.45, 0.5, 0.6, 0.7, 0.75, 0.8, 1.0], self.helpers["scrim"]):
            c = 1.05 / (lum + 0.05)
            self.assertAlmostEqual(got, smoothstep((2.0 - c) / (2.0 - 1.3)), places=12)
        for i in range(11):
            t = i / 10
            self.assertAlmostEqual(self.helpers["profile"][i], 1 - smoothstep(t), places=12)
            ease = 4 * t ** 3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2
            self.assertAlmostEqual(self.helpers["ease"][i], ease, places=12)
        b = self.helpers["bezier"]
        self.assertAlmostEqual(b[0], 0.0, places=9)
        self.assertAlmostEqual(b[-1], 1.0, places=9)
        self.assertEqual(b, sorted(b), "krivka ease je monotonni")
        # CSS ease v polovine casu (referencni hodnota cubic-bezier(0.25, 0.1, 0.25, 1) ~ 0.8024)
        self.assertAlmostEqual(b[5], 0.8024, places=3)

    def test_color_formatting(self):
        self.assertEqual(self.helpers["css"], ["#3d7bff", "rgba(0, 0, 0, 0.1)", "#00000059", "#ffffffff"])
        r, g, b, a = self.helpers["rgb01"]
        self.assertEqual((r, g, b, a), (1.0, 0.0, 0.2, 0.5))

    # ---- hodnoty se nerozesly se zdroji ----

    def rgba(self, c, decimals=2):
        # zdroje pisi alfu jednou "0.60", jindy "0.6"
        if c[3] >= 1:
            return "#%02x%02x%02x" % tuple(c[:3])
        a = "%.2f" % c[3] if decimals == 2 else repr(c[3])
        return "rgba(%d, %d, %d, %s)" % (c[0], c[1], c[2], a)

    def assertColor(self, text, before, c, after, msg=None):
        forms = {before + self.rgba(c, d) + after for d in (1, 2)}
        self.assertTrue(any(f in text for f in forms), msg or sorted(forms))

    def test_values_match_bar_plugin(self):
        bar = (FILES / "src/luxos-bar.c").read_text()
        defines = dict(re.findall(r"^#define (\w+) ([\d.]+)", bar, re.M))
        ink = self.tokens["ink"]
        for key, name in (("dark_below", "INK_DARK_BELOW"), ("white_above", "INK_WHITE_ABOVE"),
                          ("readable_light", "READABLE_LIGHT_TEXT"), ("readable_dark", "READABLE_DARK_TEXT"),
                          ("readable_light_scrim", "READABLE_LIGHT_TEXT_SCRIM"), ("scrim_height", "SCRIM_HEIGHT"),
                          ("scrim_max", "SCRIM_MAX"), ("scrim_c_none", "SCRIM_C_NONE"), ("scrim_c_full", "SCRIM_C_FULL")):
            self.assertEqual(float(ink[key]), float(defines[name]), name)
        self.assertEqual(self.tokens["bar"]["opacity"], int(defines["DEFAULT_OPACITY"]))
        self.assertIn("(GdkRGBA) { 0.09, 0.09, 0.12, 1 } : (GdkRGBA) { 0.96, 0.96, 0.97, 1 }", bar)
        self.assertEqual(self.tokens["bar"]["tint_dark"], [0.09, 0.09, 0.12])
        self.assertEqual(self.tokens["bar"]["tint_light"], [0.96, 0.96, 0.97])
        self.assertIn("(faint ? %s : 1.0)" % self.tokens["bar"]["faint"], bar)

    def test_values_match_glass_and_widgets(self):
        glass = (FILES / "lsl/luxos_glass.lsl").read_text()
        widgets = (FILES / "lsl/luxos-widgets.lsl").read_text()
        ref = (HERE / "glass-ref/luxos-glass-material.c").read_text()
        g, wg, c = self.tokens["glass"], self.tokens["window_glass"], self.tokens["colors"]
        self.assertIn("RADIUS = %.1f" % self.tokens["radius"]["window"], glass)
        self.assertIn("BLUR_SIZE = %d" % wg["size"], glass)
        self.assertIn("BLUR_RADIUS = %d" % wg["blur"], glass)
        self.assertIn("pixbuf_saturate(pb, %s)" % wg["saturate"], glass)
        self.assertIn("set_source_rgba(cr, %s, %s, %s, %s)" % tuple(wg["tint_light"]), glass)
        self.assertIn("set_source_rgba(cr, %s, %s, %s, %s)" % tuple(wg["tint_dark"]), glass)
        self.assertIn("set_source_rgba(cr, 0.06, 0.07, 0.10, 0.52)", glass)
        self.assertEqual(wg["veil_dark"], [0.06, 0.07, 0.1, 0.52])
        self.assertIn("1.0, 1.0, 1.0, %s)" % wg["sheen"], glass)
        for name, cls in (("light_close", "lg-close"), ("light_min", "lg-min"), ("light_max", "lg-max")):
            self.assertIn("button.%s { background-color: %s; }" % (cls, self.rgba(c[name])), glass)
        self.assertIn("GLASS_RADIUS = %.1f" % self.tokens["radius"]["card"], widgets)
        for name in ("card_edge", "card_edge_top", "card_edge_bottom"):
            self.assertColor(widgets, "", c[name], "")
        self.assertIn("box-shadow: " + self.tokens["shadow"]["card"], widgets)
        self.assertIn("#define GLASS_SIZE %d" % g["size"], ref)
        self.assertIn("cairo_set_source_rgba(cr, %s, %s, %s, %s)" % tuple(g["base"]), ref)
        self.assertIn("cairo_set_source_rgb(cr, %s, %s, %s)" % tuple(g["fallback"]), ref)
        self.assertIn("%s + (rgb[0] * %s + lum * %s) * %s" % (g["floor"], g["keep"], g["luma"], g["keep"]), ref)
        self.assertIn("st.mean >= %s" % g["light_mean"], ref)
        self.assertIn("(%s - st.lo)" % g["veil_light"], ref)
        self.assertIn("1.0 - %s / fmax" % g["veil_dark"], ref)
        self.assertIn("x + w * %s, y + h" % g["sheen_reach"], ref)

    def test_values_match_themes(self):
        gtk3 = (REPO / "packages/luxos-themes/files/luxos-gtk3.css").read_text()
        light = (REPO / "packages/luxos-themes/files/notify/Light.css").read_text()
        dark = (REPO / "packages/luxos-themes/files/notify/Dark.css").read_text()
        r, c = self.tokens["radius"], self.tokens["colors"]
        self.assertIn(self.rgba(c["accent"]), gtk3)
        self.assertIn(self.rgba(c["selection"]), gtk3)
        self.assertRegex(gtk3, r"menu,\n\.background\.popup > menu \{[^}]*border-radius: %dpx" % r["menu"])
        self.assertRegex(gtk3, r"menu > menuitem \{[^}]*border-radius: %dpx" % r["menu_item"])
        self.assertRegex(gtk3, r"#login_box \{[^}]*border-radius: %dpx" % r["dialog"])
        self.assertIn("box-shadow: " + self.tokens["shadow"]["dialog"], gtk3)
        self.assertIn("box-shadow: " + self.tokens["shadow"]["focus"], gtk3)
        for css, mode in ((light, "light"), (dark, "dark")):
            m = self.tokens[mode]
            self.assertColor(css, "background-color: ", m["notification"], ";")
            self.assertColor(css, "color: ", m["fg"], ";")
            self.assertColor(css, "color: ", m["fg_soft"], ";")
            self.assertIn("border-radius: %dpx;" % r["notification"], css)
            self.assertIn("border-radius: %dpx;" % r["button"], css)
            self.assertIn("color: %s;" % self.rgba(c["close_glyph"]), css)
            self.assertIn("color: %s;" % self.rgba(c["close_glyph_hover"]), css)

    def test_values_match_lock_and_motion(self):
        lock = (REPO / "packages/xfce4-screensaver/luxos-lock-ui.c").read_text()
        cover = (FILES / "src/luxos-session-cover.c").read_text()
        slide = (REPO / "packages/xfwm4/luxos-workspace-slide.patch").read_text()
        m = self.tokens["motion"]
        self.assertIn("ll->target > ll->anim_from ? %d000.0 : %d000.0" % (m["lock_enter"], m["lock_leave"]), lock)
        self.assertIn("/ %d000.0" % m["shake"], lock)
        self.assertIn('conf_str (kf, "font", "%s")' % self.tokens["font"]["family"], lock)
        self.assertIn("return t < 0.5 ? 4 * t * t * t : 1 - pow (-2 * t + 2, 3) / 2;", lock)
        self.assertIn("g_timeout_add (%d, animate" % m["frame"], lock)
        self.assertIn("#define FADE_MS %d" % m["fade"], cover)
        self.assertIn("#define LOGIN_FADE_MS %d" % m["login_fade"], cover)
        self.assertIn("workspace_slide_duration=%d" % m["workspace"], slide)
        x1, y1, x2, y2 = self.tokens["curves"]["ease"]
        self.assertIn("cubic-bezier (%s, y1, %s, %s)" % (x1, x2, int(y2)), slide)
        self.assertIn("y1 = %s" % y1, slide)

    def test_values_match_glass_popups_branch(self):
        popups = git_show("packages/luxos-desktop/files/lsl/luxos_bar_popups.lsl")
        if popups is None:
            self.skipTest("vetev %s neni k dispozici" % GPT_BRANCH)
        r = self.tokens["radius"]
        for mode, block in (("light", "LIGHT = ("), ("dark", "DARK = (")):
            start = popups.index(block)
            text = popups[start:popups.index("\n\n", start)]
            m = self.tokens[mode]
            for name in ("popup", "border", "fg", "dim", "tile", "tile_hover", "bubble", "trough", "fill", "field"):
                key = {"popup": "bg"}.get(name, name)
                self.assertColor(text, "@define-color bp_%s " % key, m[name], ";", (mode, name))
        self.assertIn("border-radius: %dpx; border: 1px solid @bp_border" % r["popup"], popups)
        self.assertIn(".bp-section { background-color: @bp_tile; border-radius: %dpx" % r["tile"], popups)
        self.assertIn("button.bp-row { border-radius: %dpx" % r["row"], popups)


if __name__ == "__main__":
    unittest.main()
