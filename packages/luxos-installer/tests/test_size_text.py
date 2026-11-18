#!/usr/bin/env python3
"""Velikosti v pruvodci instalaci: desetinna carka mimo anglictinu ("Stahuji 203 MB z 1,4 GB · 4,5 MB/s").
Regrese (audit 1.0.2): cesky pruvodce psal "1.4 GB" a "4.5 MB/s".
Spusteni: python3 packages/luxos-installer/tests/test_size_text.py"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "files", "luxos-install-gui")
sys.path.insert(0, os.path.join(HERE, "..", "..", "luxos-i18n", "files"))
import luxos_i18n  # noqa: E402


def load(with_i18n=True):
    src = open(SRC, encoding="utf-8").read()
    ns = {"os": os}
    if with_i18n:
        ns["luxos_i18n"] = luxos_i18n
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
        # jedna soustava jednotek: rucni rozdeleni ukazuje stejne GB jako prehled disku (zadne GiB)
        self.assertNotIn("size_bin", ns)
        self.assertEqual(ns["size_text"](512e9), "512 GB")

    def test_other_languages_comma(self):
        ns = load()
        for lang in ("cs_CZ.UTF-8", "de_DE.UTF-8", "uk_UA.UTF-8", "fr_FR.UTF-8"):
            os.environ["LANG"] = lang
            self.assertEqual(ns["size_text"](1.4e9), "1,4 GB", lang)
            self.assertEqual(ns["size_text"](4.5e6), "4,5 MB", lang)

    def test_old_luxos_i18n_fallback(self):
        ns = load(with_i18n=False)   # instalovany luxos_i18n bez decimal_separator/format_time
        os.environ["LANG"] = "cs_CZ.UTF-8"
        self.assertEqual(ns["size_text"](1.4e9), "1,4 GB")
        self.assertEqual(ns["ui_time"](9, 5), "9:05")

    def test_rounding_to_next_unit(self):
        ns = load()
        os.environ["LANG"] = "cs_CZ.UTF-8"
        self.assertEqual(ns["size_text"](1000e9 - 2 * 1024 ** 2), "1,0 TB")   # ne "1000 GB"
        self.assertEqual(ns["size_text"](999.4e9), "999 GB")

    def test_time_by_ui_language(self):
        ns = load()
        os.environ["LANG"] = "cs_CZ.UTF-8"
        self.assertEqual(ns["ui_time"](14, 5), "14:05")
        os.environ["LANG"] = "en_US.UTF-8"
        self.assertEqual(ns["ui_time"](14, 5), "2:05 PM")

    def test_whole_numbers_unchanged(self):
        ns = load()
        os.environ["LANG"] = "cs_CZ.UTF-8"
        self.assertEqual(ns["size_text"](43e9), "43 GB")
        self.assertEqual(ns["size_text"](512), "512 B")


if __name__ == "__main__":
    unittest.main()
