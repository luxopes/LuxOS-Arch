#!/usr/bin/env python3
"""Uplnost prekladu: kazdy text z cs.tsv je ve vsech 12 jazycich, se stejnymi %s/%d/{nazev}.

    python3 packages/luxos-i18n/tests/test_tsv_complete.py

Regrese (audit 1.0.2): 131 textu (Obnova LuxOS, Vratit nastaveni aplikace, widgety, budiky)
chybelo v 9 jazycich - napr. spanelsky system ukazoval tyto obrazovky anglicky.
"""
import os
import re
import subprocess
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
I18N = os.path.join(HERE, "..", "files")
LANGS = ["cs", "de", "es", "fr", "hu", "it", "nl", "pl", "pt", "sk", "sv", "uk"]
FEW = {"cs", "sk", "pl", "uk"}          # jazyky s tvarem "|few" (2-4)
PH = re.compile(r"%(?:\([a-z_]+\))?[-0-9.]*[sdfi]|\{[a-zA-Z_0-9]*\}")


def load(lang):
    out = {}
    with open(os.path.join(I18N, lang + ".tsv"), encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.rstrip("\n")
            if not line or line.startswith("#"):
                continue
            assert "\t" in line, f"{lang}.tsv:{n}: no tab: {line[:60]}"
            k, v = line.split("\t", 1)
            out[k] = (v, n)
    return out


class TsvComplete(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tab = {lang: load(lang) for lang in LANGS}

    def test_all_languages_have_every_text(self):
        keys = set(self.tab["cs"])
        for lang in LANGS[1:]:
            miss = sorted(k for k in keys - set(self.tab[lang])
                          if not (k.endswith("|few") and lang not in FEW))
            self.assertEqual(miss, [], f"{lang}.tsv is missing {len(miss)} texts")

    def test_no_text_only_outside_czech(self):
        for lang in LANGS[1:]:
            extra = sorted(k for k in self.tab[lang] if k not in self.tab["cs"])
            self.assertEqual(extra, [], f"{lang}.tsv has texts unknown to cs.tsv")

    def test_placeholders_and_values(self):
        for lang in LANGS:
            for k, (v, n) in self.tab[lang].items():
                with self.subTest(lang=lang, line=n):
                    self.assertTrue(v.strip(), f"{lang}.tsv:{n}: empty translation of {k!r}")
                    self.assertNotIn("\t", v, f"{lang}.tsv:{n}: tab inside the translation")
                    self.assertEqual(sorted(PH.findall(k)), sorted(PH.findall(v)),
                                     f"{lang}.tsv:{n}: placeholders differ: {k!r} -> {v!r}")

    def test_reinstall_word_can_be_typed(self):
        # luxos-recovery porovnava napsane slovo bez diakritiky (iconv ASCII//TRANSLIT, jen a-z):
        # slovo bez latinskych pismen (azbuka) by se porovnalo jako "" - Enter by potvrdil preinstalaci
        for lang in LANGS:
            word = self.tab[lang]["REINSTALL"][0]
            plain = subprocess.run(["iconv", "-f", "UTF-8", "-t", "ASCII//TRANSLIT"], input=word.encode(),
                                   capture_output=True, env={"LC_ALL": "C.UTF-8"}).stdout.decode()
            self.assertGreaterEqual(len(re.sub("[^a-z]", "", plain.lower())), 6, f"{lang}: {word!r}")


if __name__ == "__main__":
    unittest.main()
