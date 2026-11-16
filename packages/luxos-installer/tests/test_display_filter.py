#!/usr/bin/env python3
"""Okno Podrobnosti instalatoru: bez pacmanu a Archu, surovy zaznam beze zmen.
Spusteni: python3 packages/luxos-installer/tests/test_display_filter.py"""
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
import re
import unittest

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "files", "luxos-install-gui")


def load():
    src = open(SRC, encoding="utf-8").read()
    ns = {"re": re}
    exec(src[src.index("_DISPLAY_SKIP = ("):src.index("def logo_image(size):")], ns)
    return ns["display_line"]


class DisplayFilter(unittest.TestCase):
    def test_lines(self):
        d = load()
        self.assertIsNone(d("gpg: Generating pacman keyring master key..."))
        self.assertIsNone(d("Optional dependencies for xarchiver"))
        self.assertIsNone(d("    python-pipx: for installing Python software not packaged on Arch Linux"))
        self.assertIsNone(d("       xarchiver [pending]"))
        self.assertEqual(d("+ arch-chroot /mnt /root/luxos-setup.sh"), "+ chroot /mnt /root/luxos-setup.sh")
        self.assertEqual(d("warning: pacman cache /var/cache/pacman/pkg"), "warning: lux cache /var/cache/lux/pkg")
        self.assertEqual(d(":: Synchronizing package databases..."), ":: Synchronizing package databases...")
        # nazvy baliku zustavaji
        self.assertEqual(d("installing archlinux-keyring..."), "installing archlinux-keyring...")

    def test_real_log(self):
        log = "/var/log/luxos-install.log"
        if not os.path.exists(log):
            self.skipTest("no install log")
        d = load()
        for line in open(log, encoding="utf-8", errors="replace").read().splitlines():
            out = d(line)
            if out is not None:
                self.assertNotRegex(out, r"(?i)\bpacman\b|\bArch Linux\b|/etc/pacman")


if __name__ == "__main__":
    unittest.main()
