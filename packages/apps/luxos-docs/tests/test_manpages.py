#!/usr/bin/env python3
# Testy manualovych stranek z docs/ (man/md2man.py + man/manpages.py).
# 1) jednotkove testy prevodu Markdown -> roff, 2) vygenerovani vsech stranek a jejich
# kontrola: struktura, ASCII, zadny ztraceny text, groff -man -ww bez varovani (je-li groff).
# Spusteni: python3 packages/apps/luxos-docs/tests/test_manpages.py [ADRESAR_DOCS]

import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "man"))
import md2man  # noqa: E402
import manpages  # noqa: E402

DOCS = os.path.normpath(os.environ.get("LUXOS_DOCS_DIR") or os.path.join(HERE, "..", "docs"))
GROFF = shutil.which("groff")

# Makra, ktera smi generator vypsat (vse ostatni na zacatku radku by byla chyba escapovani)
MACROS = {"TH", "SH", "SS", "PP", "TP", "IP", "RS", "RE", "EX", "EE", "br", "sp", "ad", "ds", "nh", "nr", "so", '\\"'}

EXPECTED = {
    "man1/lsl.1", "man1/lslc.1", "man1/luxdrop.1", "man1/luxos-guard.1", "man1/luxos-safe.1",
    "man1/luxos-sandbox.1", "man5/lux.conf.5", "man7/lsl.7", "man7/luxos.7", "man8/luxos-care.8",
    "man8/luxos-update.8",
}


def conv(md, **kw):
    return md2man.convert(md, **kw)


def groff_text(path, width=78):
    """Text stranky z groffu bez formatovani (deleni slov vypina stranka sama: .nr HY 0)."""
    env = dict(os.environ, GROFF_NO_SGR="1", LC_ALL="C.UTF-8")
    r = subprocess.run([GROFF, "-man", "-Tutf8", "-rLL=%dn" % width, "-P-cbou", path],
                       capture_output=True, text=True, env=env, check=True,
                       cwd=os.path.dirname(os.path.dirname(path)))
    return r.stdout


class EscapeTest(unittest.TestCase):
    def test_backslash_hyphen_unicode(self):
        self.assertEqual(md2man.escape("a\\b"), "a\\eb")
        self.assertEqual(md2man.escape("--net"), "\\-\\-net")
        self.assertEqual(md2man.escape("a \u2013 b \u2192 c"), "a \\(en b \\(-> c")
        self.assertEqual(md2man.escape("\u010d"), "\\[u010D]")
        self.assertTrue(md2man.escape("\U0001F600").isascii())
        # v groffu by jinak byly typograficke uvozovky/akcenty a prikaz by nesel zkopirovat
        self.assertEqual(md2man.escape("'`^~"), "\\(aq\\(ga\\(ha\\(ti")

    def test_leading_dot_and_apostrophe(self):
        out = conv(".env is read\n\n'quoted' start")
        self.assertIn("\\&.env is read", out)
        self.assertIn("\\(aqquoted\\(aq start", out)
        code = conv("```\n.hidden\n'x\n```")
        self.assertIn("\\&.hidden", code)
        self.assertIn("\\(aqx", code)

    def test_no_raw_line_starts_with_control_char(self):
        out = conv("text\n`.config` starts here\n\n- `.lux` item\n\n| `.x` | `'y` |\n|---|---|\n| `.a` | b |")
        for line in out.splitlines():
            if line[:1] in (".", "'"):
                self.assertIn(line.split()[0][1:], MACROS, line)


class InlineTest(unittest.TestCase):
    def r(self, s, resolve=None):
        return md2man.Renderer(resolve).inline(s)

    def test_code_bold_italic(self):
        self.assertEqual(self.r("run `lux update` now"), "run \\fB\\%lux \\%update\\fR now")
        self.assertEqual(self.r("**bold** and *it*"), "\\fBbold\\fR and \\fIit\\fR")
        self.assertEqual(self.r("**bold `code` more**"), "\\fBbold \\%code more\\fR")
        self.assertEqual(self.r("*it `code`*"), "\\fIit \\f(BI\\%code\\fR")

    def test_code_mid_word_has_no_hyphenation_point(self):
        # \% uprostred slova by byl bod deleni - hned za '(' se nevklada
        self.assertEqual(self.r("(`abc`)"), "(\\fBabc\\fR)")

    def test_stars_and_underscores_kept(self):
        self.assertEqual(self.r("2 * 3 * 4"), "2 * 3 * 4")
        self.assertEqual(self.r("snake_case_name"), "snake_case_name")
        self.assertEqual(self.r("`a*b*c`"), "\\fB\\%a*b*c\\fR")
        self.assertEqual(self.r("a \\* b \\| c"), "a * b | c")

    def test_backslash_in_code(self):
        self.assertEqual(self.r("`C:\\dir`"), "\\fB\\%C:\\edir\\fR")

    def test_links(self):
        self.assertEqual(self.r("[LSL](https://lsl.lux-ai.cz)"), "LSL (https://lsl.lux\\-ai.cz)")
        self.assertEqual(self.r("[https://x.cz](https://x.cz)"), "https://x.cz")
        self.assertEqual(self.r("<https://a.b/c>"), "https://a.b/c")
        man = lambda url: ("man", "luxos-safe", "1")  # noqa: E731
        self.assertEqual(self.r("see [safe.md](safe.md)", man), "see \\fBluxos\\-safe\\fR(1)")
        self.assertEqual(self.r("the [Safe](safe.md#x)", man), "the Safe (\\fBluxos\\-safe\\fR(1))")
        path = lambda url: ("path", "/usr/share/luxos/docs/luxos/x.md")  # noqa: E731
        self.assertEqual(self.r("[x.md](x.md)", path), "\\fB\\%/usr/share/luxos/docs/luxos/x.md\\fR")
        self.assertEqual(self.r("[below](#anchor)", lambda url: None), "below")
        same = lambda url: ("same", "LSL errors")  # noqa: E731
        self.assertEqual(self.r("in [errors.md](errors.md)", same), "in \\(lqLSL errors\\(rq")


class BlockTest(unittest.TestCase):
    def test_headings_and_offset(self):
        out = conv("# Title\n## Section\n### Sub\n#### Deep", heading_offset=0)
        self.assertEqual(out.split("\n")[:8], [".SH", "Title", ".SS", "Section", ".PP", "\\fBSub\\fR",
                                               ".PP", "\\fBDeep\\fR"])
        out = conv("## Section `code`\n### Sub", heading_offset=1)
        self.assertEqual(out.split("\n")[:4], [".SH", "Section code", ".SS", "Sub"])

    def test_paragraph_joined(self):
        self.assertEqual(conv("one\ntwo\n\nthree"), ".PP\none two\n.PP\nthree\n")

    def test_bullets_and_numbers(self):
        out = conv("- a\n- b\n  continued\n\n1. x\n2. y")
        self.assertEqual(out, ".IP \\(bu 2\na\n.IP \\(bu 2\nb continued\n.IP 1. 4\nx\n.IP 2. 4\ny\n")

    def test_lazy_continuation_and_star_bullets(self):
        out = conv("* first\nlazy line\n* second")
        self.assertEqual(out, ".IP \\(bu 2\nfirst lazy line\n.IP \\(bu 2\nsecond\n")

    def test_nested_list_and_code_in_item(self):
        md = "- top\n  - inner\n  - inner2\n- with code\n  ```\n  repo x\n      server y\n  ```\n- last"
        out = conv(md).split("\n")
        self.assertEqual(out[:9], [".IP \\(bu 2", "top", ".RS 2", ".IP \\(bu 2", "inner", ".IP \\(bu 2",
                                   "inner2", ".RE", ".IP \\(bu 2"])
        i = out.index(".EX")
        self.assertEqual(out[i + 1:i + 3], ["repo x", "    server y"])   # odsazeni plotu odebrano
        self.assertIn("last", out)
        self.assertEqual(sum(l.startswith(".RS") for l in out), out.count(".RE"))

    def test_code_block(self):
        out = conv("```bash\nlux -y update   # x\n\n\\path\n```\nafter")
        self.assertEqual(out, ".PP\n.RS 4\n.EX\nlux \\-y update   # x\n\n\\epath\n.EE\n.RE\n.PP\nafter\n")

    def test_heading_inside_code_is_code(self):
        out = conv("```lsl\n# comment\n```")
        self.assertNotIn(".SH", out)
        self.assertIn("# comment", out)

    def test_table_two_columns(self):
        out = conv("| Key | Meaning |\n|---|---|\n| `hold` | keep `a \\| b` |\n| x | |")
        self.assertEqual(out, ".PP\n.TP\n\\fB\\%hold\\fR\nkeep \\fB\\%a \\%| \\%b\\fR\n.TP\nx\n\\&\n")

    def test_table_three_columns_labels(self):
        out = conv("| Key | Value | Meaning |\n|:--|:-:|--:|\n| a | 1 \\| 2 | m |")
        self.assertIn(".TP\na\n\\fIValue:\\fR 1 | 2\n.br\n\\fIMeaning:\\fR m\n", out)

    def test_blockquote_and_rule(self):
        out = conv("> quoted\n\n---\n\ntext")
        self.assertEqual(out, ".RS 4\n.PP\nquoted\n.RE\n.sp\n.PP\ntext\n")


class PagesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="luxos-man-")
        cls.written = manpages.build(DOCS, cls.tmp, date="2026-01-01")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def files(self):
        return sorted(os.path.relpath(p, self.tmp) for p in self.written)

    def read(self, rel):
        with open(os.path.join(self.tmp, rel), encoding="ascii") as f:
            return f.read()

    def test_expected_pages(self):
        self.assertEqual(set(self.files()), EXPECTED)

    def test_no_conflict_with_other_packages(self):
        # lux(1) je rucne psana v balicku lux; zadna jina stranka z repozitare se nesmi prekryvat
        self.assertNotIn("man1/lux.1", self.files())
        pkgs = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
        if not os.path.isdir(os.path.join(pkgs, "lux")):
            self.skipTest("repository packages/ not available")
        ours = {os.path.basename(f) for f in self.files()}
        for root, _dirs, names in os.walk(pkgs):
            if os.path.join("apps", "luxos-docs") in root or "/src/" in root or "/pkg/" in root:
                continue
            if "PKGBUILD" in names:
                with open(os.path.join(root, "PKGBUILD"), encoding="utf-8", errors="replace") as f:
                    text = f.read()
                for name in ours:
                    with self.subTest(pkg=root, page=name):
                        self.assertNotRegex(text, r"share/man/man\d/%s\b" % re.escape(name))

    def test_structure(self):
        for rel in self.files():
            text = self.read(rel)   # encoding ascii: UnicodeDecodeError = chyba
            with self.subTest(page=rel):
                if rel == "man8/luxos-update.8":
                    self.assertEqual(text, ".so man8/luxos-care.8\n")
                    continue
                lines = text.splitlines()
                name, sec = os.path.basename(rel).rsplit(".", 1)
                self.assertTrue(lines[0].startswith('.\\"'))
                self.assertTrue(lines[1].startswith('.TH "%s" "%s" "2026-01-01"' % (md2man.escape(name.upper()), sec)))
                # nadpisy .SH (text na stejnem nebo nasledujicim radku)
                titles = [l[4:] if l != ".SH" else lines[k + 1] for k, l in enumerate(lines)
                          if l == ".SH" or l.startswith(".SH ")]
                expected = ["NAME"] + (["SYNOPSIS"] if sec in ("1", "5", "8") else []) + ["DESCRIPTION"]
                self.assertEqual(titles[:len(expected)], expected)
                self.assertEqual(titles[-1], "SEE ALSO")
                self.assertEqual(len(titles), len(set(titles)), "duplicate sections")
                self.assertRegex(lines[lines.index(".SH NAME") + 1], r"^[\w\\.,\- ]+ \\- \S")
                for line in lines:
                    if line[:1] in (".", "'"):
                        self.assertIn(line[1:].split(" ")[0], MACROS, line)
                    self.assertFalse(line.endswith(" ") and not line.startswith("."), repr(line))
                self.assertEqual(text.count("\n.RS"), text.count("\n.RE"))
                self.assertEqual(text.count("\n.EX"), text.count("\n.EE"))
                # zadne zbytky Markdownu mimo kod
                for line in lines:
                    if "\\fB" not in line and not line.startswith(".") and "](" in line:
                        self.fail("unconverted link: " + line)

    def test_see_also_targets_exist(self):
        known = {os.path.basename(f) for f in self.files()} | {"lux.1", "bwrap.1", "gocryptfs.1"}
        for rel in self.files():
            text = self.read(rel)
            for name, sec in re.findall(r"\\fB([\w.\\-]+)\\fR\((\d)\)", text):
                with self.subTest(page=rel, ref=name):
                    self.assertIn(name.replace("\\-", "-") + "." + sec, known)

    def test_luxos7_points_everywhere(self):
        text = self.read("man7/luxos.7")
        see = text.split(".SH SEE ALSO", 1)[1]
        for rel in EXPECTED - {"man7/luxos.7", "man8/luxos-update.8"}:
            name, sec = os.path.basename(rel).rsplit(".", 1)
            self.assertIn("\\fB%s\\fR(%s)" % (md2man.escape(name), sec), see)
        self.assertIn("/usr/share/luxos/docs", see)

    def test_synopsis_matches_real_usage(self):
        # SYNOPSIS musi odpovidat skutecnemu --help/usage prikazu v repozitari
        pkgs = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
        src = {
            "luxos-sandbox": "luxos-sandbox/files/luxos-sandbox",
            "luxos-guard": "luxos-guard/files/luxos-guard",
            "luxos-safe": "luxos-safe/files/luxos-safe",
            "luxos-care": "luxos-care/files/luxos-care",
        }
        if not os.path.isdir(os.path.join(pkgs, "luxos-care")):
            self.skipTest("repository packages/ not available")
        for page in manpages.PAGES:
            if page["name"] not in src:
                continue
            with open(os.path.join(pkgs, src[page["name"]]), encoding="utf-8") as f:
                code = f.read()
            for line in page["synopsis"]:
                words = re.findall(r"\*\*([^*]+)\*\*", line)
                sub = words[0].split()[1:] if words else []
                for w in sub + [x for x in words[1:] if not x.startswith("luxos")]:
                    for tok in re.findall(r"[a-z][\w-]*|--[\w-]+", w):
                        with self.subTest(page=page["name"], token=tok):
                            self.assertRegex(code, r"[\"'(\s|\[]%s[\"'\s\])|\]]" % re.escape(tok))

    def test_sections_exist_in_docs(self):
        # vyber sekci odkazuje jen na existujici nadpisy (jinak build selze s ValueError)
        for page in manpages.PAGES:
            list(manpages.select_markdown(page, DOCS))

    @unittest.skipUnless(GROFF, "groff not installed")
    def test_groff_no_warnings(self):
        env = dict(os.environ, LC_ALL="C.UTF-8")
        for rel in self.files():
            with self.subTest(page=rel):
                r = subprocess.run([GROFF, "-man", "-Tutf8", "-ww", "-z", rel], cwd=self.tmp,
                                   capture_output=True, text=True, env=env)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(r.stderr.strip(), "", r.stderr)

    @unittest.skipUnless(GROFF, "groff not installed")
    def test_no_text_lost(self):
        """Kazde slovo vybraneho Markdownu (mimo cile odkazu) je ve vykreslene strance."""
        word = re.compile(r"[A-Za-z0-9]{2,}")
        for page in manpages.PAGES:
            rel = "man%d/%s.%d" % (page["section"], page["name"], page["section"])
            with self.subTest(page=rel):
                rendered = groff_text(os.path.join(self.tmp, rel), width=1000)
                have = set(word.findall(rendered))
                md = "\n".join(t for _d, _k, t in manpages.select_markdown(page, DOCS))
                # zahlavi tabulek (radky jsou stitky .TP) a jazyk bloku kodu se nevypisuji
                lines = md.split("\n")
                md = "\n".join(l for k, l in enumerate(lines)
                               if not (k + 1 < len(lines) and md2man.TABLE_SEP_RE.match(lines[k + 1])
                                       and l.lstrip().startswith("|")))
                md = re.sub(r"(?m)^(\s*```)\w+", r"\1", md)
                md = re.sub(r"\]\([^)\s]+\)", "]", md)            # cile odkazu se nahrazuji
                md = re.sub(r"\[[\w./-]+\.md\]", "", md)          # nazev souboru jako popisek
                missing = set(word.findall(md)) - have
                self.assertEqual(missing, set())
                # ASCII ' ` ^ ~ z prikazu nesmi groff nahradit typografickymi znaky
                for ch in "\u2018\u2019\u02c6\u02dc":
                    if ch not in md:
                        self.assertNotIn(ch, rendered)

    @unittest.skipUnless(GROFF, "groff not installed")
    def test_readable_at_80_columns(self):
        for rel in ("man7/luxos.7", "man5/lux.conf.5", "man1/luxos-sandbox.1", "man7/lsl.7"):
            with self.subTest(page=rel):
                text = groff_text(os.path.join(self.tmp, rel), width=78)
                self.assertNotIn("\\f", text)            # zadne nevykreslene escape sekvence
                self.assertNotIn("](", text)              # zadny neprevedeny odkaz
                self.assertRegex(text, r"(?m)^NAME$")
                self.assertNotRegex(text, r"\u2010\n")      # zadne deleni slov na konci radku
                # sirka: ani dlouhe cesty v prozaickem textu nepretecou (bloky kodu se nezalamuji)
                code = set()
                for page in manpages.PAGES:
                    if rel.endswith("/%s.%d" % (page["name"], page["section"])):
                        for _d, _k, md in manpages.select_markdown(page, DOCS):
                            code.update(l.strip() for l in re.findall(r"```\w*\n(.*?)```", md, re.S)
                                        for l in l.split("\n"))
                wide = [l for l in text.splitlines() if len(l) > 80 and l.strip() not in code]
                self.assertEqual(wide, [])

if __name__ == "__main__":
    if len(sys.argv) > 1 and os.path.isdir(sys.argv[1]):
        DOCS = os.path.normpath(sys.argv.pop(1))
    unittest.main(verbosity=1)
