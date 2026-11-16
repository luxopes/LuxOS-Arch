#!/usr/bin/env python3
"""Kazde "gum confirm" v LuxOS Care (Obnova LuxOS) ma prelozena tlacitka (regrese audit 1.0.2: gum bez
--affirmative/--negative ukazal anglicke "Yes"/"No" i v cestine).
    python3 packages/luxos-care/tests/test_gum_i18n.py"""
import glob
import os
import unittest

FILES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "files")


class GumI18n(unittest.TestCase):
    def test_confirm_buttons_translated(self):
        bad = []
        for path in glob.glob(os.path.join(FILES, "**", "*"), recursive=True):
            if not os.path.isfile(path):
                continue
            try:
                lines = open(path, encoding="utf-8").read().splitlines()
            except (UnicodeDecodeError, OSError):
                continue
            for n, line in enumerate(lines, 1):
                if "gum confirm" in line and not line.lstrip().startswith("#"):
                    if "--affirmative" not in line or "--negative" not in line:
                        bad.append(f"{os.path.relpath(path, FILES)}:{n}")
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
