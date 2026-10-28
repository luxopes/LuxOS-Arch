"""Testy vzoru lux search (^text, text$, ^text$, *, ?, % = *) v repozitarich, nainstalovanych balicich,
aplikacich LuxOS, na Flathubu a v AUR (zastupne RPC, bez site).

    python3 -m unittest discover -s packages/lux/tests -v
"""
import os
import shutil
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.dont_write_bytecode = True
import lux_community as lc  # noqa: E402
import test_lux_alpm as ta  # noqa: E402
import test_lux_cli  # noqa: E402

NAMES = ["vim", "gvim", "vim-airline", "neovim", "python-pyqt5", "python-qtpy", "qt6-base", "libfoo-git",
         "lib32-foo-git", "libfoo", "Vimb"]


def names(term):
    rx = lc.search_pattern(term)
    return [n for n in NAMES if rx.search(n)]


class Patterns(unittest.TestCase):
    def test_plain_word_is_no_pattern(self):
        for t in ("vim", "video", "c++", "python-qt"):
            self.assertFalse(lc.is_pattern(t), t)
            self.assertIsNone(lc.search_pattern(t))
        for t in ("^vim", "vim$", "*qt*", "vi?", "%qt%", "lib*-git"):
            self.assertTrue(lc.is_pattern(t), t)

    def test_starts_with(self):
        self.assertEqual(names("^vim"), ["vim", "vim-airline", "Vimb"])

    def test_ends_with(self):
        self.assertEqual(names("vim$"), ["vim", "gvim", "neovim"])

    def test_exact(self):
        self.assertEqual(names("^vim$"), ["vim"])
        self.assertEqual(names("^VIM$"), ["vim"])                     # bez ohledu na velikost pismen

    def test_contains(self):
        self.assertEqual(names("*qt*"), ["python-pyqt5", "python-qtpy", "qt6-base"])

    def test_glob_whole_name(self):
        self.assertEqual(names("lib*-git"), ["libfoo-git", "lib32-foo-git"])
        self.assertEqual(names("vi?"), ["vim"])
        self.assertEqual(names("?vim"), ["gvim"])

    def test_percent_alias(self):
        self.assertEqual(names("%qt%"), names("*qt*"))
        self.assertEqual(names("lib%-git"), names("lib*-git"))

    def test_combination(self):
        self.assertEqual(names("^python-*qt*"), ["python-pyqt5", "python-qtpy"])
        self.assertEqual(names("^lib*git$"), ["libfoo-git", "lib32-foo-git"])

    def test_regex_chars_are_literal(self):
        rx = lc.search_pattern("^libc++")
        self.assertTrue(rx.search("libc++abi"))
        self.assertFalse(rx.search("libcabi"))
        self.assertFalse(lc.search_pattern("^a.c$").search("abc"))

    def test_literal(self):
        self.assertEqual(lc.pattern_literal("^python-*qt*"), "python-")
        self.assertEqual(lc.pattern_literal("%qt%"), "qt")
        self.assertEqual(lc.search_literal(["video", "*qt*", "^lib"]), "lib")
        self.assertEqual(lc.search_literal(["video"]), "")

    def test_match_plain_and_pattern(self):
        self.assertTrue(lc.search_match(["^vim", "editor"], "vim", "Vi Improved, a text editor"))
        self.assertFalse(lc.search_match(["^vim", "player"], "vim", "Vi Improved, a text editor"))
        # vzor jen v nazvu, ne v popisu
        self.assertFalse(lc.search_match(["*editor*"], "vim", "a text editor"))
        self.assertTrue(lc.search_match(["editor"], "vim", "a text editor"))

    def test_search_filter_lines(self):
        lines = ["vim\t9.1-1\tVi Improved\n", "neovim\t0.10-1\tVim-fork\n", "htop\t3.3-1\tviewer\n"]
        self.assertEqual(list(lc.search_filter(["^vim"], lines)), ["vim\t9.1-1\tVi Improved"])
        self.assertEqual(len(list(lc.search_filter(["vim"], lines))), 2)       # obycejne slovo i v popisu
        apps = ["org.vim.Vim\tVim\tEditor\n", "io.neovim.nvim\tNeovim\tEditor\n"]
        self.assertEqual([x.split("\t")[0] for x in lc.search_filter(["^vim$"], apps, app_id=True)],
                         ["org.vim.Vim"])

    def test_cli_search_filter(self):
        r = subprocess.run([sys.executable, os.path.join(HERE, "..", "lux_community.py"), "search-filter", "--",
                            "%-git"], input="libfoo-git\t1\tx\nlibfoo\t1\ty\n", capture_output=True, text=True)
        self.assertEqual(r.stdout, "libfoo-git\t1\tx\n")


class FakeRPC:
    """AUR RPC v5: by=name = podretezec nazvu, by=name-desc = nazev nebo popis."""
    PKGS = [{"Name": "vim-git", "Version": "9.1-1", "Description": "Vi Improved (git)", "Popularity": 1.5},
            {"Name": "vim-plug", "Version": "0.14-1", "Description": "plugin manager", "Popularity": 3.0},
            {"Name": "gvim-gtk2", "Version": "9.1-1", "Description": "Vi with GTK2", "Popularity": 0.2},
            {"Name": "neovim-git", "Version": "0.11-1", "Description": "Fork of vim", "Popularity": 2.0},
            {"Name": "editor-x", "Version": "1-1", "Description": "like vim", "Popularity": 9.0}]

    def __init__(self):
        self.calls = []

    def __call__(self, path, params=None):
        self.calls.append((path, params))
        q = path.rsplit("/", 1)[-1].lower()
        by = (params or {}).get("by")
        return {"results": [p for p in self.PKGS if q in p["Name"].lower()
                            or (by == "name-desc" and q in p["Description"].lower())]}


class AUR(unittest.TestCase):
    def test_plain_unchanged(self):
        rpc = FakeRPC()
        rows = lc.aur_search(["vim"], fetch=rpc)
        self.assertEqual(rpc.calls, [("/search/vim", {"by": "name-desc"})])
        self.assertEqual([r[0] for r in rows], ["editor-x", "vim-plug", "neovim-git", "vim-git", "gvim-gtk2"])

    def test_starts_with_filters_locally(self):
        rpc = FakeRPC()
        rows = lc.aur_search(["^vim"], fetch=rpc)
        self.assertEqual(rpc.calls, [("/search/vim", {"by": "name"})])
        self.assertEqual([r[0] for r in rows], ["vim-plug", "vim-git"])

    def test_ends_with_and_glob(self):
        self.assertEqual([r[0] for r in lc.aur_search(["*vim*git$"], fetch=FakeRPC())], ["neovim-git", "vim-git"])
        self.assertEqual([r[0] for r in lc.aur_search(["%-git"], fetch=FakeRPC())], ["neovim-git", "vim-git"])
        rpc = FakeRPC()
        lc.aur_search(["^vim*-git"], fetch=rpc)
        self.assertEqual(rpc.calls[0][0], "/search/-git")              # nejdelsi text vzoru

    def test_pattern_and_word(self):
        self.assertEqual([r[0] for r in lc.aur_search(["*vim*", "fork"], fetch=FakeRPC())], ["neovim-git"])

    def test_short_pattern_skipped(self):
        rpc = FakeRPC()
        self.assertEqual(lc.aur_search(["^v*"], fetch=rpc), lc.AUR_SHORT)
        self.assertEqual(lc.aur_search(["*"], fetch=rpc), lc.AUR_SHORT)
        self.assertEqual(rpc.calls, [])

    def test_unavailable(self):
        self.assertIsNone(lc.aur_search(["^vim"], fetch=lambda p, q=None: None))


class Flathub(unittest.TestCase):
    ROWS = [("org.vim.Vim", "GVim", "Vi Improved", ""), ("io.neovim.nvim", "Neovim", "Vim-fork", ""),
            ("org.kde.kate", "Kate", "Editor with vim mode", "")]

    def search(self, term, limit=20):
        self.queries.append(term)
        return [r for r in self.ROWS if term.lower() in " ".join(r).lower()][:limit]

    def setUp(self):
        self.queries = []

    def test_plain_unchanged(self):
        rows = lc.flathub_search_terms(["vim", "editor"], search=self.search)
        self.assertEqual(self.queries, ["vim editor"])
        self.assertEqual(rows, [])

    def test_pattern_by_id_or_name(self):
        ids = [r[0] for r in lc.flathub_search_terms(["^vim$"], search=self.search)]
        self.assertEqual(ids, ["org.vim.Vim"])                         # posledni cast ID
        ids = [r[0] for r in lc.flathub_search_terms(["^neo"], search=self.search)]
        self.assertEqual(ids, ["io.neovim.nvim"])                      # nazev aplikace
        ids = [r[0] for r in lc.flathub_search_terms(["org.*"], search=self.search)]
        self.assertEqual(ids, ["org.vim.Vim", "org.kde.kate"])         # cele ID
        self.assertEqual(self.queries, ["vim", "neo", "org."])

    def test_short_pattern(self):
        self.assertEqual(lc.flathub_search_terms(["^v"], search=self.search), [])
        self.assertEqual(self.queries, [])


class Repo(unittest.TestCase):
    """lux_alpm.py search nad napodobeninou pyalpm."""

    def names(self, *argv):
        rc, out, _h = ta.run(["search"] + list(argv))
        return rc, [ln.split()[0] for ln in out.splitlines() if ln and not ln.startswith(" ")]

    def test_plain_unchanged(self):
        self.assertEqual(self.names("vlc"), (0, ["extra/vlc"]))
        self.assertEqual(self.names("viewer"), (0, ["extra/htop"]))    # i popis

    def test_patterns(self):
        self.assertEqual(self.names("^lib"), (0, ["extra/libvpx"]))
        self.assertEqual(self.names("vpx$")[1], ["extra/libvpx"])
        self.assertEqual(self.names("^HTOP$")[1], ["extra/htop"])
        self.assertEqual(self.names("*i*")[1], ["core/glibc", "core/archlinux-keyring", "extra/firefox",
                                                "extra/libvpx"])
        self.assertEqual(self.names("%f%")[1], ["extra/firefox"])
        self.assertEqual(self.names("?lc")[1], ["extra/vlc"])
        self.assertEqual(self.names("*viewer*"), (1, []))               # vzor jen v nazvu

    def test_pattern_and_word(self):
        self.assertEqual(self.names("^*i*", "codec")[1], ["extra/libvpx"])
        self.assertEqual(self.names("*i*", "nothing-like-this"), (1, []))

    def test_installed(self):
        rc, out, _h = ta.run(["search", "--installed", "*-*"])
        self.assertEqual(rc, 0)
        self.assertIn("core/archlinux-keyring 20260901-1 [installed]", out)
        self.assertIn("local/orphan-lib 1.0-1", out)
        self.assertIn("local/aur-tool 0.1-1", out)
        self.assertNotIn("vlc", out)
        self.assertEqual(self.names("--installed", "vlc"), (1, []))
        self.assertEqual(self.names("--installed", "^htop$")[1], ["extra/htop"])


ENGINE = """#!/bin/bash
printf '%s\\n' "$*" >>"$LOG/lux-engine.log"
case $1 in
  -Sl) printf 'core glibc 2.40-1 [installed]\\nextra libvpx 1.14-1\\nextra vlc 3.0.21-1\\n' ;;
  -Q) printf 'glibc 2.40-1\\naur-tool 0.1-1\\n' ;;
esac
exit 0
"""


class CLI(unittest.TestCase):
    """Prikaz lux (bash): napoveda, zalozni cesta pres lux-engine, preskoceni AUR."""
    tearDown = test_lux_cli.CLI.tearDown
    lux = test_lux_cli.CLI.lux
    calls = test_lux_cli.CLI.calls

    def setUp(self):
        test_lux_cli.CLI.setUp(self)
        self.env["LUX_COMMUNITY"] = os.path.join(HERE, "..", "lux_community.py")
        # luxpkg.sh z repozitare s vlastni databazi aplikaci LuxOS
        self.luxdb = os.path.join(self.tmp, "luxdb")
        with open(os.path.join(HERE, "..", "luxpkg.sh")) as f:
            src = f.read().replace("LUX_DB=/var/lib/lux/installed", "LUX_DB=" + self.luxdb)
        self.env["LUXPKG"] = os.path.join(self.tmp, "luxpkg.sh")
        with open(self.env["LUXPKG"], "w") as f:
            f.write(src)

    def engine(self):
        p = os.path.join(self.tmp, "alpm", "lux-engine")
        os.makedirs(os.path.dirname(p))
        with open(p, "w") as f:
            f.write(ENGINE)
        os.chmod(p, 0o755)
        return {"LUX_BACKEND": "engine", "LUX_ENGINE": p}

    def test_help(self):
        for args in (("search", "--help"), ("s", "-h"), ("--help", "search")):
            rc, out = self.lux(*args)
            self.assertEqual(rc, 0)
            self.assertIn("^text$", out)
            self.assertIn("%qt%", out)
            self.assertIn("--installed", out)
        rc, out = self.lux("--help")
        self.assertNotIn("^text$", out)

    def test_backend_args(self):
        self.lux("search", "^vim")
        self.assertTrue(any("search -- ^vim" in x for x in self.calls("lux_alpm.py")))
        self.lux("search", "--installed", "%qt%")
        self.assertTrue(any("search --installed -- %qt%" in x for x in self.calls("lux_alpm.py")))

    def test_engine_fallback_pattern(self):
        env = self.engine()
        rc, out = self.lux("search", "^lib", env=env)
        self.assertEqual(rc, 0, out)
        self.assertIn("extra/libvpx 1.14-1", out)
        self.assertNotIn("glibc", out)
        self.assertIn("-Sl", self.calls("lux-engine"))
        self.assertFalse(any(x.startswith("-Ss") for x in self.calls("lux-engine")))
        rc, out = self.lux("search", "--installed", "*-tool", env=env)
        self.assertIn("local/aur-tool 0.1-1", out)
        self.assertNotIn("glibc", out)
        rc, out = self.lux("search", "%zzz%", env=env)
        self.assertIn("(nothing)", out)

    def test_engine_fallback_plain(self):
        env = self.engine()
        self.lux("search", "vim", env=env)
        self.assertIn("-Ss --color never -- vim", self.calls("lux-engine"))
        self.lux("search", "--installed", "vim", env=env)
        self.assertIn("-Qs --color never -- vim", self.calls("lux-engine"))

    @unittest.skipUnless(shutil.which("jq"), "jq neni k dispozici")
    def test_lux_apps_installed(self):
        os.unlink(os.path.join(self.bin, "jq"))                       # skutecne jq
        os.makedirs(self.luxdb)
        for n, s in (("luxos-notes", "Notes"), ("luxos-maps", "Maps")):
            with open(os.path.join(self.luxdb, n + ".json"), "w") as f:
                f.write('{"name": "%s", "version": "1.0", "summary": "%s"}' % (n, s))
        rc, out = self.lux("search", "--installed", "*notes", env=self.engine())
        self.assertIn("lux/luxos-notes", out)
        self.assertNotIn("luxos-maps", out)

    def test_aur_short_pattern_skipped(self):
        with open(os.path.join(self.bin, "lux-config"), "w") as f:
            f.write("#!/bin/bash\n[[ $1 == env ]] && printf 'AUR=1\\nFLATPAK=0\\n'\nexit 0\n")
        rc, out = self.lux("search", "--aur", "^v*")
        self.assertIn("skipped", out)


if __name__ == "__main__":
    unittest.main()
