#!/usr/bin/env python3
"""Web: vydani pripravene jen ve staging (verze vyssi nez site/stable.json) nejsou mezi vydanymi verzemi,
ale na strance „Připravuje se“ / „Coming soon“. Docasny CHANGELOG.md, preklady a stable.json.

    python3 -m unittest scripts/tests/test_changelog_upcoming.py
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import changelog_sections as cl  # noqa: E402

CS = """# LuxOS – seznam změn

## Připravuje se

### Nové
- Pošta

## 1.0.5 „Sirius“ – 2026-11-20

### Nové
- Dotyk

## 1.0.4 „Sirius“ – 2026-11-20

### Opraveno
- Přihlášení
"""
EN = {"_intro.md": "# Changes\n", "unreleased.md": "## Coming soon\n\n### New\n- Mail\n",
      "1.0.5-2026-11-20.md": "## 1.0.5 \"Sirius\" – 2026-11-20\n\n### New\n- Touch\n",
      "1.0.4-2026-11-20.md": "## 1.0.4 \"Sirius\" – 2026-11-20\n\n### Fixed\n- Sign-in\n"}


class Upcoming(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="changes-")
        self.addCleanup(shutil.rmtree, self.d, True)
        with open(os.path.join(self.d, "CHANGELOG.md"), "w", encoding="utf-8") as f:
            f.write(CS)
        en = os.path.join(self.d, "en")
        os.makedirs(en)
        for name, text in EN.items():
            with open(os.path.join(en, name), "w", encoding="utf-8") as f:
                f.write(text)
        self.old = (cl.CHANGELOG, cl.EN_DIR, cl.STABLE)
        self.addCleanup(self.restore)
        cl.CHANGELOG, cl.EN_DIR = os.path.join(self.d, "CHANGELOG.md"), en
        cl.STABLE = os.path.join(self.d, "stable.json")

    def restore(self):
        cl.CHANGELOG, cl.EN_DIR, cl.STABLE = self.old

    def stable(self, version):
        with open(cl.STABLE, "w") as f:
            f.write('{"version": "%s", "codename": "Sirius"}\n' % version)

    def test_staging_release_on_coming_soon(self):
        self.stable("1.0.4")
        rel, soon = cl.cs_split()
        self.assertNotIn("1.0.5", rel)
        self.assertIn("1.0.4", rel)
        self.assertIn("Pošta", soon)
        self.assertIn("## 1.0.5", soon)
        self.assertNotIn("1.0.5", cl.en_text())
        self.assertIn("Touch", cl.en_unreleased())
        self.assertIn("Mail", cl.en_unreleased())
        self.assertEqual(cl.verify(), [])

    def test_after_stable_release(self):
        self.stable("1.0.5")
        rel, soon = cl.cs_split()
        self.assertIn("## 1.0.5", rel)
        self.assertNotIn("1.0.5", soon)
        self.assertIn("Touch", cl.en_text())
        self.assertNotIn("Touch", cl.en_unreleased())

    def test_without_stable_file_everything_released(self):
        rel, _soon = cl.cs_split()
        self.assertIn("## 1.0.5", rel)


if __name__ == "__main__":
    unittest.main()
