#!/usr/bin/env python3
# Kontrola offline dokumentace LuxOS a LSL (balicek luxos-docs).
# Overuje kontrakt pro ctenare (LuxAI, Lux Code): index.json odpovida souborum,
# kazdy soubor ma nadpis, rozumnou velikost a funkcni vnitrni odkazy.
# Spusteni: python3 packages/apps/luxos-docs/tests/test_docs.py [ADRESAR_DOCS]

import json
import os
import re
import sys
import unittest

DOCS = os.environ.get("LUXOS_DOCS_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs")
DOCS = os.path.normpath(DOCS)
COLLECTIONS = {"luxos": "LuxOS", "lsl": "LSL"}
MIN_SIZE = 1024          # mensi soubor nema smysl samostatne
MAX_SIZE = 20 * 1024     # idealne 2-15 KB, tvrdy limit 20 KB
LINK_RE = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)\)")


def read(rel):
    with open(os.path.join(DOCS, rel), encoding="utf-8") as f:
        return f.read()


def strip_code(text):
    """Radky mimo bloky kodu (```), aby se '#' v ukazkach nepocitaly jako nadpisy."""
    out, fence = [], False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fence = not fence
            continue
        if not fence:
            out.append(line)
    return out


def slug(heading):
    """Kotva nadpisu jako na GitHubu: mala pismena, bez interpunkce, mezery -> '-'."""
    s = heading.strip().lower()
    s = "".join(ch for ch in s if ch.isalnum() or ch in " -_")
    return s.replace(" ", "-")


def anchors(rel):
    seen, result = {}, set()
    for line in strip_code(read(rel)):
        m = re.match(r"^(#{1,6})\s+(.*?)\s*#*\s*$", line)
        if not m:
            continue
        base = slug(m.group(2))
        n = seen.get(base, 0)
        seen[base] = n + 1
        result.add(base if n == 0 else f"{base}-{n}")
    return result


def all_markdown():
    found = set()
    for root, _dirs, files in os.walk(DOCS):
        for name in files:
            if name.endswith(".md"):
                found.add(os.path.relpath(os.path.join(root, name), DOCS).replace(os.sep, "/"))
    return found


class IndexTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(DOCS, "index.json"), encoding="utf-8") as f:
            cls.index = json.load(f)
        cls.entries = [(c["id"], e) for c in cls.index["collections"] for e in c["files"]]

    def test_structure(self):
        self.assertEqual(self.index.get("version"), 1)
        ids = [c.get("id") for c in self.index["collections"]]
        self.assertEqual(ids, list(COLLECTIONS))
        for c in self.index["collections"]:
            self.assertEqual(set(c), {"id", "title", "files"})
            self.assertEqual(c["title"], COLLECTIONS[c["id"]])
            self.assertTrue(c["files"], f"collection {c['id']} is empty")

    def test_entries(self):
        paths = []
        for cid, e in self.entries:
            with self.subTest(path=e.get("path")):
                self.assertEqual(set(e), {"path", "title", "summary", "keywords"})
                self.assertRegex(e["path"], rf"^{cid}/[a-z0-9][a-z0-9-]*\.md$")
                self.assertTrue(e["title"].strip())
                self.assertTrue(e["summary"].strip())
                self.assertNotIn("\n", e["summary"], "summary must be one line")
                self.assertLessEqual(len(e["summary"]), 300)
                self.assertIsInstance(e["keywords"], list)
                self.assertGreaterEqual(len(e["keywords"]), 3)
                for k in e["keywords"]:
                    self.assertIsInstance(k, str)
                    self.assertTrue(k.strip())
                paths.append(e["path"])
        self.assertEqual(len(paths), len(set(paths)), "duplicate paths in index.json")

    def test_index_matches_files(self):
        listed = {e["path"] for _cid, e in self.entries}
        self.assertEqual(listed - all_markdown(), set(), "index.json lists missing files")
        self.assertEqual(all_markdown() - listed, set(), "Markdown files missing from index.json")

    def test_titles_match_headings(self):
        for _cid, e in self.entries:
            with self.subTest(path=e["path"]):
                first = read(e["path"]).splitlines()[0]
                self.assertEqual(first, "# " + e["title"])


class FileTest(unittest.TestCase):
    files = sorted(all_markdown())

    def test_headings(self):
        for rel in self.files:
            with self.subTest(path=rel):
                text = read(rel)
                self.assertTrue(text.startswith("# "), "file must start with a '# ' title")
                lines = strip_code(text)
                h1 = [l for l in lines if re.match(r"^# \S", l)]
                self.assertEqual(len(h1), 1, "exactly one '#' heading")
                self.assertTrue(any(l.startswith("## ") for l in lines), "needs '##' sections")
                self.assertEqual(text.count("```") % 2, 0, "unbalanced code fences")
                self.assertTrue(text.endswith("\n"))

    def test_sizes(self):
        for rel in self.files:
            with self.subTest(path=rel):
                size = os.path.getsize(os.path.join(DOCS, rel))
                self.assertGreaterEqual(size, MIN_SIZE)
                self.assertLessEqual(size, MAX_SIZE)

    def test_internal_links(self):
        for rel in self.files:
            text = "\n".join(strip_code(read(rel)))
            text = re.sub(r"`[^`\n]*`", "", text)   # odkazy uvnitr inline kodu nejsou odkazy
            for target in LINK_RE.findall(text):
                if re.match(r"^[a-z][a-z0-9+.-]*:", target):
                    continue        # http(s), mailto ...
                with self.subTest(path=rel, link=target):
                    path, _, frag = target.partition("#")
                    if path:
                        self.assertFalse(path.startswith("/"), "use relative links")
                        dest = os.path.normpath(os.path.join(os.path.dirname(rel), path)).replace(os.sep, "/")
                        self.assertFalse(dest.startswith(".."), "link leaves the docs tree")
                        self.assertTrue(os.path.isfile(os.path.join(DOCS, dest)), f"broken link to {dest}")
                    else:
                        dest = rel
                    if frag and dest.endswith(".md"):
                        self.assertIn(frag, anchors(dest), f"missing anchor #{frag} in {dest}")

    def test_utf8_and_no_secrets(self):
        secret = re.compile(r"(sk-[A-Za-z0-9]{20,}|BEGIN [A-Z ]*PRIVATE KEY|sessionToken\"\s*:\s*\"[A-Za-z0-9]{16,})")
        for rel in self.files:
            with self.subTest(path=rel):
                text = read(rel)   # UnicodeDecodeError = neplatne UTF-8
                self.assertIsNone(secret.search(text))


if __name__ == "__main__":
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        DOCS = os.path.normpath(sys.argv.pop(1))
        FileTest.files = sorted(all_markdown())
    unittest.main(verbosity=1)
