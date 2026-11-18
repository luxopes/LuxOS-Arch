#!/usr/bin/env python3
"""Skripty webu a prekladu musi cist/zapisovat text jako UTF-8 nezavisle na locale (LC_ALL=C)."""
import ast
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
FILES = ("build-site.py", "check-site.py", "merge-i18n.py", "changelog_sections.py", "site_html.py", "site_seo.py")


def text_calls_without_encoding(path):
    """Volani open()/subprocess s text=True bez encoding= -> [(radek, popis)]."""
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), path)
    bad = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        kw = {k.arg: k.value for k in node.keywords}
        name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
        if name == "open" and isinstance(node.func, ast.Name):
            mode = node.args[1] if len(node.args) > 1 else kw.get("mode")
            if isinstance(mode, ast.Constant) and "b" in str(mode.value):
                continue
            if "encoding" not in kw:
                bad.append((node.lineno, "open() without encoding"))
        elif name in ("read_text", "write_text") and "encoding" not in kw:
            bad.append((node.lineno, name + "() without encoding"))
        elif name in ("run", "check_output", "Popen") and "encoding" not in kw:
            t = kw.get("text") or kw.get("universal_newlines")
            if isinstance(t, ast.Constant) and t.value is True:
                bad.append((node.lineno, name + "(text=True) without encoding"))
    return bad


class EncodingTest(unittest.TestCase):
    def test_site_scripts_use_utf8(self):
        for name in FILES:
            with self.subTest(name=name):
                self.assertEqual(text_calls_without_encoding(os.path.join(SCRIPTS, name)), [])

    def test_detector_finds_missing_encoding(self):
        # Kontrola kontroly: vzorek s chybami musi byt nalezen
        sample = os.path.join(HERE, "..", "..", "out", "test_site_encoding_sample.py")
        os.makedirs(os.path.dirname(sample), exist_ok=True)
        with open(sample, "w", encoding="utf-8") as f:
            f.write('open("a")\nopen("a", "w")\nopen("a", "rb")\nopen("a", encoding="utf-8")\n'
                    'import subprocess\nsubprocess.run(["x"], text=True)\n')
        try:
            self.assertEqual([ln for ln, _ in text_calls_without_encoding(sample)], [1, 2, 6])
        finally:
            os.unlink(sample)


if __name__ == "__main__":
    unittest.main()
