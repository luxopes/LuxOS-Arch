#!/usr/bin/env python3
"""Sklo shellu pod luxwm na pomalem pocitaci (pripominky 2026-11-21: 3, 5, 9, 11, 12, 17 a Dock nad bilym oknem).

    packages/luxwm/tests/build-host.sh
    scripts/wl-test/run-all packages/luxos-desktop/tests/test_luxos_glass_wl.py
    WLT_RENDER_NODE=/dev/dri/renderD128 ... totez na GPU (gles2)

Pomaly pocitac (QEMU std VGA, pixman) predstira LUXCOMP_BLUR_SLOW_MS=0: kazdy prepocet rozmazani plochy je
"pomaly". Drive pak kompozitor po tretim takovem snimku prepnul vsechny plochy natrvalo na nepruhlednou barvu
(bila lista a Dock po prepnuti rezimu, sedive ztmaveni Launchpadu a Hledani). Ted smi plocha jen docasne
prejit na vyrez rozmazane tapety a sklo zustane sklem.

Tapeta: vlevo cervena, vpravo modra, svisle pruhy 4 px (svetla/tmava). Sklo = pod plochou vlevo cervenejsi nez
vpravo (prosvita tapeta) a bez ostrych pruhu (rozmazani). Nepruhledna barva by byla vlevo i vpravo stejna.
Pismo na skle: odstiny sedi, barevne lemy podpixeloveho vyhlazovani (rgba z gsettings jako v obrazu LuxOS a
fontconfig hostitele s rgba=rgb) jsou chyba. LUXOS_GLASS_SHOTS=adresar ulozi snimky.
"""
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_luxos_material_wl as mat  # noqa: E402
from test_luxos_bar_wl import png_write  # noqa: E402

W, H, BAR = mat.W, mat.H, mat.BAR
GPU = bool(os.environ.get("WLT_RENDER_NODE"))
SLOW = "LUXCOMP_BLUR_SLOW_MS=0"
SHOTS = os.environ.get("LUXOS_GLASS_SHOTS")
WLT_BIN = Path(os.environ.get("WLT_OUT") or mat.REPO / "out/wl-test") / "bin"
RED, BLUE = (225, 70, 40), (40, 90, 225)


def split_wall():
    """Vlevo cervena, vpravo modra; svisle pruhy 4 px plne a polovicni barvy."""
    rows = []
    for y in range(H):
        row = bytearray()
        for x in range(W):
            c = RED if x < W // 2 else BLUE
            if (x // 4) % 2:
                c = tuple(v // 2 for v in c)
            row += bytes(c)
        rows.append(bytes(row))
    return b"".join(rows)


def grey_wall(level):
    return bytes([level]) * (W * H * 3)


def mean(image, x, y, w, h):
    width, _, px = image
    s = [0, 0, 0]
    for r in range(y, y + h):
        for c in range(x, x + w):
            i = (r * width + c) * 3
            for k in range(3):
                s[k] += px[i + k]
    return [v / (w * h) for v in s]


def warmth(c):
    return c[0] - c[2]


def chroma(image, x, y, w, h):
    """Nejvetsi a 99,9. percentil barevnosti (max - min kanalu) v obdelniku."""
    width, _, px = image
    vals = []
    for r in range(y, y + h):
        for c in range(x, x + w):
            i = (r * width + c) * 3
            p = px[i:i + 3]
            vals.append(max(p) - min(p))
    vals.sort()
    return vals[-1], vals[int(len(vals) * 0.999)]


@unittest.skipUnless(mat.LSLC and mat.TOOLS and mat.WLT.exists() and (mat.LUXWM_BUILD / "luxwm").exists()
                     and (mat.SYSROOT / "usr/lib").exists(), "chybi lslc, luxwm (build-host.sh), sysroot nebo dbus/notify-send")
class Glass(mat.MaterialShell):
    test_light = test_dark = None   # material bez nouze testuje test_luxos_material_wl

    @classmethod
    def setUpClass(cls):
        cls.rgba = False
        super().setUpClass()
        cls.split = cls.tmp / "split.png"
        png_write(cls.split, W, H, split_wall())
        cls.grey = cls.tmp / "grey.png"
        png_write(cls.grey, W, H, grey_wall(70))

    def launch(self, dark, wall, slow=True, rgba=False):
        self.wall = wall
        # GTK na Waylandu bere vyhlazovani z gsettings: obraz LuxOS tam ma 'rgba' (luxos-wayland-settings z xsettings
        # Xft/RGBA=rgb)
        self.rgba = rgba
        self.start(dark, SLOW if slow else "")

    def spawn(self, *cmd, out=False):
        if Path(cmd[0]).name == "luxos-dock":
            # Dock neuhyba zamerenemu oknu (vychozi HIDE=dodge by ho nad oknem schoval)
            (self.session / "config/luxos/dock.conf").write_text("HIDE=none\n")
        if self.rgba and getattr(self, "env", None) is not None and "GSETTINGS_BACKEND" not in self.env:
            keyfile = self.session / "config/glib-2.0/settings/keyfile"
            keyfile.parent.mkdir(parents=True, exist_ok=True)
            keyfile.write_text("[org/gnome/desktop/interface]\nfont-antialiasing='rgba'\nfont-rgba-order='rgb'\n")
            self.env["GSETTINGS_BACKEND"] = "keyfile"
        return super().spawn(*cmd, out=out)

    def snap(self, name):
        image = self.shot(name)
        if SHOTS:
            Path(SHOTS).mkdir(parents=True, exist_ok=True)
            png_write(Path(SHOTS) / f"{self._testMethodName}-{name}.png", *image)
        return image

    def set_theme(self, dark):
        mode = "dark" if dark else "light"
        (self.session / "config/luxos/appearance").write_text(mode + "\n")
        r = subprocess.run([str(mat.LUXWM_BUILD / "luxwm-msg"), "set-theme", mode], env=self.env, capture_output=True,
                           text=True, timeout=20)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def log(self):
        path = self.session / "compositor.log"
        return path.read_text(errors="replace") if path.exists() else ""

    # ---- kontroly ----

    def assert_glass(self, image, name, y, h=4, x0=None, x1=None):
        """Pod plochou v radku y prosvita tapeta: vlevo teplejsi nez vpravo, pruhy rozmazane."""
        x0 = W // 2 - 260 if x0 is None else x0
        x1 = W // 2 + 240 if x1 is None else x1
        left, right = mean(image, x0, y, 20, h), mean(image, x1, y, 20, h)
        diff = warmth(left) - warmth(right)
        energy = mat.stripe_energy(image, y, x0, x0 + 64)
        print(f"\n  {name}: vlevo {[round(v) for v in left]} vpravo {[round(v) for v in right]}, rozdil {diff:.0f}, "
              f"pruhy {energy:.1f}", end="")
        self.assertGreater(diff, 40, f"{name}: plocha neprosvita (nepruhledna barva?) {left} / {right}")
        self.assertLess(energy, 8.0, f"{name}: pod plochou jsou ostre pruhy tapety ({energy:.1f})")

    def no_solid(self):
        self.assertNotIn("solid material", self.log())

    # ---- testy ----

    def test_theme_switch_keeps_glass(self):
        """3: svetly <-> tmavy 10x, lista i Dock porad pruhledne; 12: totez po Launchpadu a Hledani."""
        self.launch(False, self.split)
        image = self.snap("light-0")
        self.assert_glass(image, "lista", 12)
        self.assert_glass(image, "Dock", H - 12, x0=W // 2 - 150, x1=W // 2 + 130)
        dark = False
        for i in range(10):
            dark = not dark
            self.set_theme(dark)
            time.sleep(1.2)
            image = self.snap(f"{i + 1}-{'dark' if dark else 'light'}")
            self.assert_glass(image, f"lista po prepnuti {i + 1}", 12)
            self.assert_glass(image, f"Dock po prepnuti {i + 1}", H - 12, x0=W // 2 - 150, x1=W // 2 + 130)
        for mode in ("launchpad", "search"):
            self.spawn(str(self.bin / "luxos-launchpad"), "--show", mode)
            time.sleep(2.5)
            self.close()
            time.sleep(0.6)
            image = self.snap(f"after-{mode}")
            self.assert_glass(image, f"lista po {mode}", 12)
            self.assert_glass(image, f"Dock po {mode}", H - 12, x0=W // 2 - 150, x1=W // 2 + 130)
        self.no_solid()

    def dim_shows_wallpaper(self, dark):
        """5, 9: ztmaveni Launchpadu a Hledani = rozmazana tapeta, ne seda plocha."""
        self.launch(dark, self.split)
        for mode in ("launchpad", "search"):
            self.spawn(str(self.bin / "luxos-launchpad"), "--show", mode)
            time.sleep(2.5)
            image = self.snap(mode)
            # nad panelem Launchpadu / pod polem Hledani: jen ztmaveni
            self.assert_glass(image, f"{mode} ztmaveni nahore", 40, x0=40, x1=W - 80)
            self.assert_glass(image, f"{mode} ztmaveni dole", H - 40, x0=40, x1=W - 80)
            self.close()
            time.sleep(0.6)
        self.no_solid()

    def test_dim_light(self):
        self.dim_shows_wallpaper(False)

    def test_dim_dark(self):
        self.dim_shows_wallpaper(True)

    def fringes(self, dark):
        """11: pismo na skle vyhlazene v odstinech sedi (lista, Launchpad, oznameni)."""
        self.launch(dark, self.grey, slow=False, rgba=True)
        subprocess.run(["notify-send", "-a", "Pošta", "-t", "0", "Nová zpráva", "Krátký text oznámení na skle"],
                       env=self.env, timeout=10)
        time.sleep(1.2)
        image = self.snap("desktop")
        # sede tapete a tonovani (mirne do modra) staci barevnost do ~12; lemy podpixeloveho pisma maji 60+
        areas = {"lista vlevo": (0, 0, 420, BAR), "lista vpravo": (W - 260, 0, 260, BAR),
                 "oznameni text": (W - 300, BAR + 24, 260, 40)}
        self.spawn(str(self.bin / "luxos-launchpad"), "--show", "launchpad")
        time.sleep(2.5)
        launchpad = self.snap("launchpad")
        bad = []
        for name, box in areas.items():
            top, p999 = chroma(image, *box)
            print(f"\n  {name}: barevnost max {top}, 99,9 % {p999}", end="")
            if top > 30:
                bad.append(name)
        # pole hledani a karty razeni (jen text)
        for name, box in {"Launchpad pole": (W // 2 - 300, 100, 600, 60),
                          "Launchpad karty": (W // 2 - 300, H - 170, 600, 60)}.items():
            top, p999 = chroma(launchpad, *box)
            print(f"\n  {name}: barevnost max {top}, 99,9 % {p999}", end="")
            if top > 30:
                bad.append(name)
        self.assertEqual(bad, [], "barevne lemy pisma na skle")

    def test_fringes_light(self):
        self.fringes(False)

    def test_fringes_dark(self):
        self.fringes(True)

    def window(self, color, size, bottom):
        """Okno s jednou barvou; presune ho za zahlavi tak, aby jeho spodni okraj byl na y = bottom."""
        self.spawn(str(WLT_BIN / "wlt-client"), "--solid", "--color", color, "--size", size, "--title", "okno")
        time.sleep(1.5)
        image = self.shot("window")
        width, _, px = image
        x = W // 2
        # sloupec uprostred je na tapete cely modry (pruhy jsou svisle): prvni radek daleko od modre = zahlavi
        top = None
        for y in range(BAR + 2, H - 100):
            p = px[(y * width + x) * 3:(y * width + x) * 3 + 3]
            if sum(abs(p[k] - BLUE[k]) for k in range(3)) > 150:
                top = y
                break
        self.assertIsNotNone(top, "okno neni videt")
        height = int(size.split("x")[1])
        grab = top + 12
        to = grab + bottom - (top + height + 30)
        self.input(f"move {x} {grab}", f"drag {x} {grab} {x} {to} 600")
        time.sleep(0.8)
        return to

    def dock_edge(self, image):
        """Kontrast obrysu Docku proti oknu pod nim: nejvetsi rozdil jasu v sloupci nad stredem Docku."""
        def lum(p):
            return 0.2126 * p[0] + 0.7152 * p[1] + 0.0722 * p[2]
        width, _, px = image
        x = W // 2 - 120
        # horni okraj panelu (~65 px nad spodkem obrazovky), nad ikonami
        col = [lum(px[(y * width + x) * 3:(y * width + x) * 3 + 3]) for y in range(H - 85, H - 56)]
        return max(abs(col[i + 1] - col[i]) for i in range(len(col) - 1))

    def dock_over(self, dark, color):
        self.launch(dark, self.split, slow=False)
        self.window(color, "1000x500", H - 4)
        image = self.snap(f"dock-over-{color}")
        edge = self.dock_edge(image)
        print(f"\n  Dock nad oknem {color}: nejvetsi skok jasu na obrysu {edge:.0f}", end="")
        self.assertGreater(edge, 18, f"Dock nad oknem #{color} splyva s oknem")

    def test_dock_over_white_light(self):
        self.dock_over(False, "ffffff")

    def test_dock_over_black_dark(self):
        self.dock_over(True, "000000")

    @unittest.skipIf(GPU, "nahradni vyrez tapety je jen pod pixman")
    def test_fallback_recovers(self):
        """17: pohyb okna pod Dockem na pomalem pocitaci = docasne sklo z tapety, po zastaveni zase rozmazane okno."""
        self.launch(False, self.split)
        # bile okno pod Dock a sem tam, at se Dock prepocitava kazdy snimek
        y = self.window("ffffff", "700x420", H - 4)
        for _ in range(3):
            self.input(f"drag {W // 2} {y} {W // 2 + 60} {y} 300", f"drag {W // 2 + 60} {y} {W // 2} {y} 300")
        moving = self.snap("moving")
        self.assertIn("wallpaper glass", self.log(), "pohyb pod Dockem na pomalem pocitaci nespustil nahradni sklo")
        # v nahradnim rezimu prosvita tapeta (vlevo cervena, vpravo modra), okno pod Dockem ne
        self.assert_glass(moving, "Dock v nahradnim rezimu", H - 12, x0=W // 2 - 150, x1=W // 2 + 130)
        time.sleep(3.0)
        image = self.snap("recovered")
        # zase rozmazane: bile okno pod Dockem ho zesvetli (obe strany skoro stejne svetle)
        left = mean(image, W // 2 - 150, H - 12, 20, 4)
        right = mean(image, W // 2 + 130, H - 12, 20, 4)
        print(f"\n  Dock po zastaveni: vlevo {[round(v) for v in left]} vpravo {[round(v) for v in right]}", end="")
        before = mean(moving, W // 2 - 150, H - 12, 20, 4)
        self.assertGreater(sum(left) - sum(before), 60, "Dock se po zastaveni nevratil k rozmazani okna pod nim")
        self.no_solid()


if __name__ == "__main__":
    unittest.main()
