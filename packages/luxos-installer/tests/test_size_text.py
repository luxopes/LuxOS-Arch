#!/usr/bin/env python3
"""Velikosti v pruvodci instalaci: desetinna carka mimo anglictinu ("Stahuji 203 MB z 1,4 GB · 4,5 MB/s").
Regrese (audit 1.0.2): cesky pruvodce psal "1.4 GB" a "4.5 MB/s".
Spusteni: python3 packages/luxos-installer/tests/test_size_text.py"""
import os
import unittest

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "files", "luxos-install-gui")


def load():
    src = open(SRC, encoding="utf-8").read()
    ns = {"os": os}
    exec(src[src.index("def decimal(text):"):src.index("def ram_bytes():")], ns)
    return ns


class SizeText(unittest.TestCase):
    def setUp(self):
        self.old = os.environ.get("LANG")

    def tearDown(self):
        if self.old is None:
            os.environ.pop("LANG", None)
        else:
            os.environ["LANG"] = self.old

    def test_english_point(self):
        ns = load()
        os.environ["LANG"] = "en_US.UTF-8"
        self.assertEqual(ns["size_text"](1.4e9), "1.4 GB")
        self.assertEqual(ns["size_bin"](1.5 * 1024 ** 3), "1.5 GiB")

    def test_other_languages_comma(self):
        ns = load()
        for lang in ("cs_CZ.UTF-8", "de_DE.UTF-8", "uk_UA.UTF-8", "fr_FR.UTF-8"):
            os.environ["LANG"] = lang
            self.assertEqual(ns["size_text"](1.4e9), "1,4 GB", lang)
            self.assertEqual(ns["size_text"](4.5e6), "4,5 MB", lang)
            self.assertEqual(ns["size_bin"](1.5 * 1024 ** 3), "1,5 GiB", lang)

    def test_whole_numbers_unchanged(self):
        ns = load()
        os.environ["LANG"] = "cs_CZ.UTF-8"
        self.assertEqual(ns["size_text"](43e9), "43 GB")
        self.assertEqual(ns["size_text"](512), "512 B")


if __name__ == "__main__":
    unittest.main()
