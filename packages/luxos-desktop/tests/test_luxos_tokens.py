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
            r = subprocess.run([LSLC, "--target", "linux-x86_64-gnu", "--system-bindings", str(cls.tmp), str(cls.tmp / src), str(out)],
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
            out["gtk3-%s-blur.css" % mode] = self.run_gen("css", mode, "blur")
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
        for argv in ([], ["css"], ["css", "blue"], ["css", "light", "x"], ["labwc", "x"], ["nic"]):
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

    def test_material_contrast(self):
        """Text na kazdem materialu aspon 4,5:1 nad cimkoli, co muze byt pod nim: bile okno, cerny terminal, sede a pestre
        pozadi. S rozmazanim (kompozitor) je pod tonovanim rozmazane pozadi se saturaci 1,6, bez nej (labwc) kryje material
        BLUR fallback_opacity. Lista nese jen hlavni pismo (fg), ostatni plochy i vedlejsi (fg_secondary)."""
        def over(top, a, bottom):
            return [top[i] * a + bottom[i] * (1 - a) for i in range(3)]

        def lum(c):
            return 0.2126 * srgb_linear(c[0]) + 0.7152 * srgb_linear(c[1]) + 0.0722 * srgb_linear(c[2])

        def saturate(c, k):
            l = 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
            return [min(255.0, max(0.0, l + (x - l) * k)) for x in c]

        backgrounds = {"white window": [255, 255, 255], "black terminal": [0, 0, 0], "grey": [128, 128, 128],
                       "wallpaper red": [196, 30, 20], "wallpaper yellow": [250, 220, 60], "wallpaper blue": [20, 40, 120],
                       "green": [40, 160, 60], "magenta": [200, 40, 200]}
        t = self.tokens
        worst = {}
        for surface, texts in (("bar", ("fg",)), ("popup", ("fg", "fg_secondary")), ("menu", ("fg", "fg_secondary")),
                               ("toast", ("fg", "fg_secondary")), ("sheet", ("fg", "fg_secondary"))):
            for mode in ("light", "dark"):
                m = t["material"][t["surface"][surface][0]][mode]
                for blur in (True, False):
                    a = m["opacity"] if blur else max(m["opacity"], t["blur"]["fallback_opacity"])
                    for name, under in backgrounds.items():
                        bg = over(m["tint"], a, saturate(under, t["blur"]["saturation"]) if blur else under)
                        for text in texts:
                            c = t[mode][text]
                            ink = over(c, c[3], bg)
                            l1, l2 = sorted((lum(ink), lum(bg)), reverse=True)
                            ratio = (l1 + 0.05) / (l2 + 0.05)
                            key = (surface, mode, text, "blur" if blur else "solid")
                            worst[key] = min(worst.get(key, 99), ratio)
                            self.assertGreaterEqual(ratio, 4.5, (key, name, round(ratio, 2)))
        print("\n  nejhorsi kontrast: " + ", ".join(f"{' '.join(k)} {v:.2f}" for k, v in sorted(worst.items())))
        css = self.run_gen("css", "light")
        self.assertIn(".lx-notification { background-color: @lx_mat_toast;", css)
        self.assertRegex(css, r"menu, \.menu \{ background-color: @lx_mat_menu;")
        self.assertIn("@define-color lx_mat_popup rgba(246, 247, 252, 0.96);", css)
        self.assertIn("@define-color lx_mat_popup rgba(246, 247, 252, 0.72);", self.run_gen("css", "light", "blur"))

    def test_scales(self):
        """Navrh 1.1.0: sest polomeru, typograficka stupnice se 7 rolemi, mrizka 4/8 bez 6, ovladace 28 px, jeden akcent."""
        t = self.tokens
        self.assertEqual(sorted(t["radius"].values()), [6, 8, 12, 16, 24, 999])
        self.assertEqual(list(t["type"]), ["caption", "footnote", "body", "body_strong", "title", "headline", "large"])
        self.assertTrue(all(v[0] >= 11 for v in t["type"].values()))
        self.assertEqual(sorted(t["space"].values()), [2, 4, 8, 12, 16, 24, 32])
        self.assertEqual(t["control"]["height"], 28)
        blues = [n for n, c in t["colors"].items() if c[2] > 180 and c[0] < 120]
        self.assertEqual(sorted(blues), ["accent", "accent_hover", "accent_pressed"])
        for level in ("1", "2", "3", "4"):
            self.assertIn(level, t["elevation"])
        self.assertGreater(t["window_shadow"]["active_alpha"], t["window_shadow"]["inactive_alpha"])
        for surface, (material, level, radius) in t["surface"].items():
            self.assertIn(material, t["material"], surface)
            self.assertTrue(level == 0 or str(level) in t["elevation"], surface)
            # karta skla vyskakovacich oken 18 px jako verze 1.1.1 (owner feedback 2026-11-21, bod 8)
            self.assertIn(radius, list(t["radius"].values()) + [0, 18], surface)

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

    def test_values_match_glass_and_widgets(self):
        glass = (FILES / "lsl/luxos_glass.lsl").read_text()
        widgets = (FILES / "lsl/luxos-widgets.lsl").read_text()
        ref = (HERE / "glass-ref/luxos-glass-material.c").read_text()
        # sklo oken a karty widgetu maji vlastni hodnoty (WINDOW_GLASS z tokenu nahradil MATERIAL); tady jen semafor a hrany
        g, c = self.tokens["glass"], self.tokens["colors"]
        for name, cls in (("light_close", "lg-close"), ("light_min", "lg-min"), ("light_max", "lg-max")):
            self.assertIn("button.%s { background-color: %s; }" % (cls, self.rgba(c[name])), glass)
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
        """Relace X11 ma vlastni CSS (luxos-themes); material Waylandu ji nemeni. Spolecny zustava akcent, stiny a krizek."""
        gtk3 = (REPO / "packages/luxos-themes/files/luxos-gtk3.css").read_text()
        light = (REPO / "packages/luxos-themes/files/notify/Light.css").read_text()
        c = self.tokens["colors"]
        self.assertIn(self.rgba(c["accent"]), gtk3)
        self.assertIn("box-shadow: " + self.tokens["shadow"]["dialog"], gtk3)
        self.assertIn("box-shadow: " + self.tokens["shadow"]["focus"], gtk3)
        self.assertIn("color: %s;" % self.rgba(c["close_glyph"]), light)
        self.assertIn("color: %s;" % self.rgba(c["close_glyph_hover"]), light)

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
        for mode, block in (("light", "LIGHT = ("), ("dark", "DARK = (")):
            start = popups.index(block)
            text = popups[start:popups.index("\n\n", start)]
            m = self.tokens[mode]
            # podklad a polomery nahradil material a stupnice polomeru, barvy obsahu zustaly
            for name in ("border", "fg", "dim", "tile", "tile_hover", "bubble", "trough", "fill", "field"):
                self.assertColor(text, "@define-color bp_%s " % name, m[name], ";", (mode, name))


if __name__ == "__main__":
    unittest.main()
