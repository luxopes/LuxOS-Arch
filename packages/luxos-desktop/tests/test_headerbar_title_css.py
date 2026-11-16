#!/usr/bin/env python3
"""Vlastni CSS aplikaci nesmi prepsat titulek okna (HeaderBar).

    python3 packages/luxos-desktop/tests/test_headerbar_title_css.py

Popisek titulku HeaderBaru GTK 3 ma tridy .title a .subtitle. Aplikace, ktera ve svem CSS (poskytovatel pro
celou obrazovku) nastavi holou tridu .title (napr. velky nadpis stranky 20 px), zvetsi tim i titulek
v horni liste okna - okno pak vypada jinak nez ostatni (Tiskarny a skenery, Zpetna vazba, instalator).
Test projde zdroje vsech baliku: soubor s HeaderBarem nesmi definovat pravidlo zacinajici .title/.subtitle.
"""
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PACKAGES = os.path.normpath(os.path.join(HERE, "..", ".."))
# pravidlo s holou tridou na zacatku selektoru (ne ".tile .title" ani "label.title")
BARE = re.compile(r'(?m)(?:^|["}]|,)\s*\.(title|subtitle)\s*[{,:]')
SKIP_DIRS = {"tests", "docs", "__pycache__", "src"}


def sources():
    for root, dirs, files in os.walk(PACKAGES):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for name in files:
            if name.endswith((".png", ".svg", ".jpg", ".tsv", ".md", ".json", ".gz", ".xml", ".desktop")):
                continue
            path = os.path.join(root, name)
            try:
                with open(path, encoding="utf-8") as f:
                    text = f.read()
            except (UnicodeDecodeError, OSError):
                continue
            yield path, text


class HeaderBarTitle(unittest.TestCase):
    def test_no_bare_title_class_next_to_headerbar(self):
        bad = []
        for path, text in sources():
            if "HeaderBar" not in text and "headerbar" not in text:
                continue
            for m in BARE.finditer(text):
                line = text.count("\n", 0, m.start()) + 1
                bad.append(f"{os.path.relpath(path, PACKAGES)}:{line}: .{m.group(1)}")
        self.assertEqual(bad, [], "bare .title/.subtitle CSS would restyle the window title")

    def test_pattern(self):
        self.assertTrue(BARE.search('CSS = b"""\n.title { font-size: 20px; }\n"""'))
        self.assertTrue(BARE.search('"  .subtitle, .x { opacity: 0.5; }"'))
        self.assertFalse(BARE.search('.tile .title { font-weight: 600; }'))
        self.assertFalse(BARE.search('.dev-title { font-size: 20px; }'))
        self.assertFalse(BARE.search('label.title { }'))


if __name__ == "__main__":
    unittest.main()
