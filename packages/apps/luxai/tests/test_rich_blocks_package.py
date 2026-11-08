#!/usr/bin/env python3
"""LuxAI - bohate bloky v odpovedich: vydany zdrojovy archiv obsahuje moduly a specifikaci
a jeho bezpecnostni jadro funguje (vyhodnocovac vzorcu bez spousteni kodu, sanitace SVG).

    python3 -m unittest packages/apps/luxai/tests/test_rich_blocks_package.py -v

Zdroj LuxAI je jen v archivu luxai-<verze>.tar.gz vedle PKGBUILD: test ho rozbali do docasne
slozky, prelozi maly program nad lsl/rich_expr.lsl a lsl/rich_svg.lsl (`lsl compile`, bez displeje
a bez site) a spusti ho. Potrebuje prekladac LSL (balicek lsl); bez nej se preskoci.
Uplne testy (parsery, diagramy, sazba vzorcu, GUI pod Xvfb) jsou v repozitari LuxAI:
tests_lsl/test_rich_blocks.py a tests_lsl/test_rich_gui.py.
"""
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)

PROGRAM = r'''# lsl: internal-abi
load json
load rich_expr
load rich_svg
load rich_blocks
load rich_quiz
load markdown
output = {}
output["inline"] = markdown.inline("\\\\(|\\\\vec{v}| = \\\\sqrt{3^2 + 4^2}\\\\)")
output["fence"] = markdown.parse_blocks("```quiz {\"q\": \"x\", \"options\": [\"a\", \"b\"], \"correct\": 0}\n```")[0]["text"]
output["mortgage"] = rich_expr.compute("amount * (rate/1200) / (1 - (1 + rate/1200)^(-years*12))", {"amount": 3000000, "rate": 4.9, "years": 30})
output["code"] = rich_expr.compute("system(\"id\")", {})
output["attribute"] = rich_expr.compute("a.b", {"a": 1})
output["format"] = rich_expr.format_value(15921.5, "0", "CZK")
svg = rich_svg.sanitize("<svg onload=\"alert(1)\"><script>alert(1)</script><a href=\"javascript:x()\"><rect width=\"5\" height=\"5\" fill=\"url(http://evil/x)\"/></a><foreignObject><iframe/></foreignObject><use href=\"http://evil#a\"/></svg>")
output["svg"] = svg["svg"]
output["removed"] = svg["removed"]
output["chart"] = rich_blocks.parse("chart", "{\"type\": \"bar\", \"series\": [{\"data\": [1, 2]}]}")["ok"]
output["bad"] = rich_blocks.parse("quiz", "{\"questions\": [")["ok"]
output["prompt"] = "chart: " in rich_blocks.RICH_PROMPT and "quiz: " in rich_blocks.RICH_PROMPT and "\"type\":\"function\"" in rich_blocks.RICH_PROMPT
output["plot"] = rich_blocks.parse("chart", "{\"type\": \"function\", \"x\": [-3, 3], \"functions\": [\"2*x\"], \"points\": [[1, 2]]}")["ok"]
quiz = rich_blocks.parse("quiz", "{\"questions\": [{\"q\": \"a\", \"options\": [\"x\", \"y\"], \"correct\": 0}, {\"q\": \"b\", \"options\": [\"x\", \"y\"], \"correct\": 1}]}")["spec"]
state = rich_quiz.normalize(quiz, {"answers": {"0": [0]}, "hints": []})
output["quiz"] = [quiz["mode"], rich_quiz.mode(quiz, state), state["page"], rich_quiz.answer(quiz, state, 1, [0]), rich_quiz.score(quiz, state)["right"]]
print json.encode(output)
'''


def archive():
    with open(os.path.join(PKG, "PKGBUILD"), encoding="utf-8") as f:
        version = re.search(r"^pkgver=(\S+)", f.read(), re.M).group(1)
    return os.path.join(PKG, f"luxai-{version}.tar.gz"), version


class RichBlocksPackage(unittest.TestCase):
    def test_archive_contains_rich_modules_and_spec(self):
        path, version = archive()
        with tarfile.open(path) as tar:
            names = set(tar.getnames())
        for module in ("rich_blocks", "rich_expr", "rich_svg", "rich_draw", "rich_diagram", "rich_math", "rich_ui", "rich_quiz"):
            self.assertIn(f"luxai-{version}/lsl/{module}.lsl", names)
        self.assertIn(f"luxai-{version}/docs/rich-blocks.md", names)
        # testovaci ovladace do archivu nepatri jako program aplikace, ale nevadi (preklada se jen main.lsl)
        self.assertIn(f"luxai-{version}/lsl/main.lsl", names)

    def test_pkgbuild_installs_spec(self):
        with open(os.path.join(PKG, "PKGBUILD"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("docs/rich-blocks.md", text)
        self.assertIn("librsvg", text)

    @unittest.skipUnless(shutil.which("lsl"), "LSL compiler (package lsl) is not installed")
    def test_safe_core(self):
        path, version = archive()
        with tempfile.TemporaryDirectory(prefix="luxai-rich-pkg-") as folder:
            with tarfile.open(path) as tar:
                tar.extractall(folder, filter="data")
            source = os.path.join(folder, f"luxai-{version}", "lsl")
            program = os.path.join(source, "rich_package_check.lsl")
            with open(program, "w", encoding="utf-8") as f:
                f.write(PROGRAM)
            binary = os.path.join(folder, "check")
            subprocess.run(["lsl", "compile", "--unsafe", "--target", "linux-x86_64-gnu", program, binary],
                           cwd=source, check=True, capture_output=True, text=True)
            env = {"PATH": "/usr/bin:/bin", "HOME": folder, "LANG": "C.UTF-8"}
            result = subprocess.run([binary], env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)
            value = json.loads(result.stdout)
        self.assertAlmostEqual(value["mortgage"][0], 15921.7, delta=0.5)
        self.assertEqual(value["code"], [None, "unknown function system"])
        self.assertEqual(value["attribute"], [None, "unexpected character ."])
        self.assertEqual(value["format"], "15 922 CZK")
        svg = value["svg"].replace('xmlns="http://www.w3.org/2000/svg"', "").lower()
        for word in ("script", "onload", "javascript", "http", "foreignobject", "iframe"):
            self.assertNotIn(word, svg)
        self.assertIn("<rect", svg)
        self.assertTrue(value["chart"])
        self.assertFalse(value["bad"])
        self.assertTrue(value["prompt"])
        self.assertTrue(value["plot"])
        # 2.0.2-6: kviz po strankach je vychozi, stary stav pokracuje prvni nezodpovezenou otazkou
        self.assertEqual(value["quiz"], ["pages", "pages", 1, True, 1])
        self.assertIn("v⃗", value["inline"])          # dvojita lomitka od modelu (2.0.2-5)
        self.assertNotIn("vec", value["inline"])
        self.assertTrue(value["fence"].startswith('{"q"'))   # JSON na radku plotu


if __name__ == "__main__":
    unittest.main()
