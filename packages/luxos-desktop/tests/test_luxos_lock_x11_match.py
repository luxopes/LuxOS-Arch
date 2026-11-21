#!/usr/bin/env python3
"""Zamek a prihlasovaci obrazovka na Waylandu (files/lsl/luxos_lock_draw.lsl) vypadaji presne jako X11: kazdy stav
se kresli bez kompozitoru (tests/lock/lock-render.lsl) a porovnava se snimkem X11 zamku (xfce4-screensaver-dialog
s luxos-lock-ui.c) a X11 prihlaseni (luxos-greeter --demo) ze stejnych vstupu.

    env -u DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u XAUTHORITY DBUS_SYSTEM_BUS_ADDRESS=unix:path=/nonexistent \\
      systemd-run --user --scope -p TasksMax=300 -p MemoryMax=1G -- timeout 1800 \\
      scripts/wl-test/isolate python3 -m unittest packages/luxos-desktop/tests/test_luxos_lock_x11_match.py -v

Vzory: tests/lock-x11-goldens/<jazyk>-<tema>-<WxH>@<meritko>/<stav>.png v pixelech zarizeni, na umele tapete
(tests/lock/pixdiff.py wallpaper) - nezavisi na balicku tapet. Porizuje je tests/lock/x11_goldens.py (postaveny
xfce4-screensaver z packages/xfce4-screensaver, Xvfb, pevne hodiny a rizeny monotonni cas, napodobeny PAM).
Tolerance: nejvys 0,5 % pixelu, ktere se lisi o vic nez 16 a nejsou jen posunutou hranou vyhlazeni (pixdiff).
LUXOS_LOCK_X11_GOLDENS=adresar: navic cela matice ze snimku na skutecnych tapetach (luxos-light/dark.jpg).
"""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
REPO = PKG.parent.parent
sys.path.insert(0, str(HERE / "lock"))
import pixdiff  # noqa: E402

LSLC = os.environ.get("LUXOS_LSLC") or shutil.which("lslc")
GOLDENS = HERE / "lock-x11-goldens"
OUT = REPO / "out/lock-x11-match-test"
TOLERANCE = 0.005
LOCK = ["idle", "prompt", "typing", "wrong", "caps", "fingerprint", "lockout", "battery", "layout", "power",
        "enter-50", "shake"]
GREETER = ["greeter", "greeter-wrong", "greeter-users"]
FRAME_BUDGET_US = 8000


def configs(root):
    for d in sorted(Path(root).iterdir()):
        if d.is_dir() and "@" in d.name:
            lang, theme, rest = d.name.split("-", 2)
            size, scale = rest.split("@")
            w, h = (int(v) for v in size.split("x"))
            yield d, lang, theme, (w, h), int(scale), sorted(p.stem for p in d.glob("*.png"))


@unittest.skipUnless(LSLC, "chybi lslc")
class LockX11Match(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        shutil.rmtree(OUT, True)
        OUT.mkdir(parents=True)
        cls.render = OUT / "lock-render"
        r = subprocess.run([LSLC, "--target", "linux-x86_64-gnu", "--system-bindings", str(PKG / "files/lsl"),
                            str(HERE / "lock/lock-render.lsl"), str(cls.render)], capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
        cls.walls = {}
        for theme in ("light", "dark"):
            cls.walls[theme] = OUT / f"wall-{theme}.png"
            pixdiff.wallpaper(cls.walls[theme], theme == "dark")

    def render_states(self, out, lang, size, scale, wall, states):
        out.mkdir(parents=True, exist_ok=True)
        env = {"PATH": "/usr/bin:/bin", "HOME": str(OUT), "TZ": "UTC", "LANGUAGE": lang,
               "LANG": "cs_CZ.UTF-8" if lang == "cs" else "en_US.UTF-8",
               "LUXOS_I18N_DIR": str(REPO / "packages/luxos-i18n/files")}
        r = subprocess.run([str(self.render), str(out), str(size[0]), str(size[1]), str(scale), str(wall), *states],
                           capture_output=True, text=True, env=env, timeout=900)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return {w[1]: (float(w[2]), float(w[3])) for w in (line.split() for line in r.stdout.splitlines())
                if w and w[0] == "frame"}

    def match(self, golden_dir, lang, theme, size, scale, states, wall):
        out = OUT / golden_dir.name
        self.render_states(out, lang, size, scale, wall, states)
        bad = []
        worst = 0.0
        for state in states:
            r = pixdiff.compare(golden_dir / f"{state}.png", out / f"{state}.png", diff_path=out / f"{state}-diff.png")
            worst = max(worst, r["ratio"])
            if r["ratio"] > TOLERANCE:
                bad.append(f"{state}: {100 * r['ratio']:.3f} % ({r['beyond']} px, box {r['box']})")
        print(f"\n  {golden_dir.name}: {len(states)} states, worst {100 * worst:.3f} % beyond AA")
        self.assertEqual(bad, [], f"{golden_dir.name} differs from X11 (diff images in {out})")

    def test_goldens(self):
        found = list(configs(GOLDENS))
        self.assertTrue(found, f"no goldens in {GOLDENS}")
        states = set()
        for d, lang, theme, size, scale, names in found:
            with self.subTest(config=d.name):
                self.match(d, lang, theme, size, scale, names, self.walls[theme])
            states.update(names)
        # kazdy stav zamku i prihlaseni ma vzor
        self.assertEqual(sorted(states), sorted(LOCK + GREETER))

    @unittest.skipUnless(os.environ.get("LUXOS_LOCK_X11_GOLDENS"), "LUXOS_LOCK_X11_GOLDENS not set")
    def test_external_matrix(self):
        for d, lang, theme, size, scale, names in configs(os.environ["LUXOS_LOCK_X11_GOLDENS"]):
            with self.subTest(config=d.name):
                self.match(d, lang, theme, size, scale, names, f"/usr/share/backgrounds/luxos/luxos-{theme}.jpg")

    def test_frame_cost_1080p(self):
        """Snimek do bufferu ARGB32 (jako wl_shm, pixman) 1920x1080: prumer do 8 ms."""
        cost = self.render_states(OUT / "perf", "en", (1920, 1080), 1, self.walls["light"],
                                  ["idle", "prompt", "typing", "wrong", "greeter-users"])
        print("\n  1920x1080 frame [avg us / max us]: " + ", ".join(f"{k} {v[0]:.0f}/{v[1]:.0f}" for k, v in cost.items()))
        for state, (avg, _worst) in cost.items():
            self.assertLess(avg, FRAME_BUDGET_US, f"{state}: {avg:.0f} us per frame")


if __name__ == "__main__":
    unittest.main()
