"""Testy samoslucovani novych verzi konfigurace (lux_configmerge.py, *.luxnew).

    python3 -m unittest discover -s packages/lux/tests -v

1. Slouceni textu: lux.conf (channel = "staging" zustane - se znamym i neznamym zakladem), hodnoty
   uzivatele vs. zmenene vychozi hodnoty, odebrane klice, konflikty, ostatni textove soubory, chybejici
   zaklad.
2. Soubory: zaloha .lux-old, prava, *.luxnew pryc; konflikt nic nezmeni; kopie verze z baliku
   (/var/lib/lux/pristine) z disku i ze stare verze balicku v cache, neoverena kopie se nepouzije.
3. lux config-diff (--merge/--keep/--new i otazka).
4. Integrace se skutecnym libalpm (pyalpm) v docasnem koreni pod out/ - lux_alpm.py install starsi
   a novejsi verze testovaciho balicku se souborem backup=, bez rootu, bez skutecneho /etc a databaze.
"""
import contextlib
import hashlib
import importlib.util
import io
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
SRC = os.path.join(HERE, "..", "lux_configmerge.py")
spec = importlib.util.spec_from_file_location("lux_configmerge", SRC)
cm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cm)

# velke docasne soubory pod out/ repozitare (ne /tmp)
OUT = os.path.join(REPO, "out", "tests")

# lux.conf z LuxOS 1.0.0 (pred countme) a soucasna z balicku lux-engine
LUX_CONF_OLD = """# LuxOS Package Manager
# Configuration: /etc/lux/lux.conf

[general]
architecture = "auto"
color = true
candy = true
verbose = true
# updates: "stable" (releases) | "staging" (test builds before a release - for testers)
channel = "stable"

[downloads]
parallel = 10
check_space = true
user = "alpm"

[security]
signatures = "required"
local_signatures = "optional"
protect = ["lux-engine", "glibc"]

[packages]
aur = true
review_pkgbuild = true
flatpak = true
cache_keep = 2

# ── LuxOS repositories ────────────────────────

[repo.luxos]
server = "https://luxos.lux-ai.cz/repo/$repo/$arch"

[include]
files = ["/etc/lux/conf.d/*.conf"]
"""
COUNTME = ("# countme: weekly anonymous count of active LuxOS installs (version, channel, install age; no ID)\n"
           "countme = true\n")
LUX_CONF_NEW = LUX_CONF_OLD.replace('channel = "stable"\n', 'channel = "stable"\n' + COUNTME)
STAGING = LUX_CONF_OLD.replace('channel = "stable"', 'channel = "staging"')


def tmpdir(test):
    os.makedirs(OUT, exist_ok=True)
    d = tempfile.mkdtemp(prefix="configmerge-", dir=OUT)
    test.addCleanup(shutil.rmtree, d, True)
    return d


def write(path, text, mode=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w" if isinstance(text, str) else "wb") as f:
        f.write(text)
    if mode is not None:
        os.chmod(path, mode)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def md5(text):
    return hashlib.md5(text.encode()).hexdigest()


def values(text):
    """{(sekce, klic): hodnota} pres parser modulu (kontrola vysledku nezavisle na poradi radku)."""
    d = cm.parse_keys(text)
    return {k: it.value() for k, it in d.keys.items()}


# ---- 1. slouceni textu ----------------------------------------------------------------------------
class LuxConfCase(unittest.TestCase):
    """Pripad uzivatele: Aktualizace softwaru nastavila channel = "staging", nova lux.conf pridala
    komentar a countme = true -> libalpm nechal lux.conf.luxnew."""

    def check(self, merged):
        self.assertIsNotNone(merged)
        v = values(merged)
        self.assertEqual(v[("general", "channel")], '"staging"')
        self.assertEqual(v[("general", "countme")], "true")
        self.assertIn("# countme: weekly anonymous count", merged)
        self.assertEqual(merged, LUX_CONF_NEW.replace('channel = "stable"', 'channel = "staging"'))

    def test_line_merge_alone_conflicts(self):
        # proto slouceni po klicich: zmena a vlozeni na sousednich radcich
        self.assertIsNone(cm.diff3(LUX_CONF_OLD, STAGING, LUX_CONF_NEW))

    def test_known_base(self):
        merged, how = cm.merge(LUX_CONF_OLD, STAGING, LUX_CONF_NEW, "etc/lux/lux.conf")
        self.assertEqual(how, "keys")
        self.check(merged)

    def test_unknown_base(self):
        merged, how = cm.merge(None, STAGING, LUX_CONF_NEW, "etc/lux/lux.conf")
        self.check(merged)

    def test_staging_stays_even_if_new_file_says_stable(self):
        """Hodnota uzivatele zustane vzdy - i kdyz nova verze vychozi hodnotu zmenila."""
        theirs = LUX_CONF_NEW.replace('channel = "stable"', 'channel = "stable"  # default')
        for base in (LUX_CONF_OLD, None):
            merged, _how = cm.merge(base, STAGING, theirs, "etc/lux/lux.conf")
            self.assertEqual(values(merged)[("general", "channel")], '"staging"', base)

    def test_pinned_channel_kept_even_when_equal_to_old_default(self):
        """channel/countme zapisuje lux-config: patri uzivateli, i kdyz se rovna stare vychozi."""
        ours = LUX_CONF_OLD.replace("cache_keep = 2", "cache_keep = 5")     # jina zmena uzivatele
        theirs = LUX_CONF_OLD.replace('channel = "stable"', 'channel = "staging"').replace(
            "parallel = 10", "parallel = 5")
        merged, _how = cm.merge(LUX_CONF_OLD, ours, theirs, "etc/lux/lux.conf")
        v = values(merged)
        self.assertEqual(v[("general", "channel")], '"stable"')        # pinned: zustava
        self.assertEqual(v[("downloads", "parallel")], "5")            # nepinned + stara vychozi -> nova
        self.assertEqual(v[("packages", "cache_keep")], "5")           # uzivatel
        # stejny soubor mimo lux.conf: channel neni pinned -> nova vychozi
        merged, _how = cm.merge(LUX_CONF_OLD, ours, theirs, "etc/other.conf")
        self.assertEqual(values(merged)[("general", "channel")], '"staging"')

    def test_countme_off_kept(self):
        ours = LUX_CONF_NEW.replace("countme = true", "countme = false").replace(
            'channel = "stable"', 'channel = "staging"')
        theirs = LUX_CONF_NEW.replace("parallel = 10", "parallel = 8")
        merged, _how = cm.merge(LUX_CONF_NEW, ours, theirs, "etc/lux/lux.conf")
        v = values(merged)
        self.assertEqual(v[("general", "countme")], "false")
        self.assertEqual(v[("general", "channel")], '"staging"')
        self.assertEqual(v[("downloads", "parallel")], "8")

    def test_real_lux_engine_conf(self):
        """Soucasna lux.conf z repozitare jako nova verze."""
        theirs = read(os.path.join(REPO, "packages", "lux-engine", "lux.conf"))
        ours = theirs.replace("countme = true", "countme = false").replace('channel = "stable"',
                                                                         'channel = "staging"')
        old = theirs.replace(COUNTME, "")
        ours_old = old.replace('channel = "stable"', 'channel = "staging"')
        for base in (old, None):
            merged, _how = cm.merge(base, ours_old, theirs, "etc/lux/lux.conf")
            self.assertEqual(merged, theirs.replace('channel = "stable"', 'channel = "staging"'))
        merged, _how = cm.merge(theirs, ours, theirs.replace("cache_keep = 2", "cache_keep = 3"),
                                "etc/lux/lux.conf")
        self.assertEqual(values(merged)[("general", "countme")], "false")
        self.assertEqual(values(merged)[("packages", "cache_keep")], "3")


class KeyMerge(unittest.TestCase):
    BASE = "[a]\nx = 1\ny = 2\nz = 3\n"

    def test_user_changed_vs_default_changed(self):
        ours = "[a]\nx = 10\ny = 2\nz = 3\n"          # uzivatel zmenil x
        theirs = "[a]\nx = 1\ny = 20\nz = 30\n"       # balik zmenil y a z
        merged, _how = cm.merge(self.BASE, ours, theirs)
        self.assertEqual(merged, "[a]\nx = 10\ny = 20\nz = 30\n")

    def test_both_changed_same_key_user_wins(self):
        merged, _how = cm.merge(self.BASE, "[a]\nx = 10\ny = 2\nz = 3\n", "[a]\nx = 11\ny = 2\nz = 3\n")
        self.assertEqual(values(merged)[("a", "x")], "10")

    def test_unknown_base_never_changes_user_values(self):
        ours = "[a]\nx = 1\ny = 2\n"
        theirs = "[a]\nx = 5\ny = 2\nnew = 7\n"
        merged, _how = cm.merge(None, ours, theirs)
        self.assertEqual(merged, "[a]\nx = 1\ny = 2\nnew = 7\n")

    def test_removed_key_unchanged_dropped(self):
        merged, _how = cm.merge(self.BASE, "[a]\nx = 10\ny = 2\nz = 3\n", "[a]\nx = 1\ny = 2\n")
        self.assertEqual(merged, "[a]\nx = 10\ny = 2\n")

    def test_removed_key_user_changed_is_conflict(self):
        merged, why = cm.merge(self.BASE, "[a]\nx = 1\ny = 2\nz = 33\n", "[a]\nx = 1\ny = 2\nw = 1\n")
        self.assertIsNone(merged)
        self.assertIn("z", why)

    def test_user_deleted_key_stays_deleted(self):
        merged, _how = cm.merge(self.BASE, "[a]\nx = 1\nz = 3\n", "[a]\nx = 1\ny = 2\nz = 3\nn = 4\n")
        self.assertEqual(merged, "[a]\nx = 1\nz = 3\nn = 4\n")

    def test_user_deleted_key_that_new_version_changed_is_conflict(self):
        merged, _why = cm.merge(self.BASE, "[a]\nx = 1\nz = 3\n", "[a]\nx = 1\ny = 9\nz = 3\n")
        self.assertIsNone(merged)

    def test_user_added_keys_sections_and_comments_kept(self):
        ours = "top = 1\n[a]\nx = 1\ny = 2\n# muj klic\nmine = 5\nz = 3\n\n[own]\nk = 1\n"
        theirs = "[a]\nx = 1\ny = 2\nz = 3\nnew = 4\n\n# dalsi\n[b]\nq = 1\n"
        merged, _how = cm.merge(self.BASE, ours, theirs)
        v = values(merged)
        self.assertEqual(v[("", "top")], "1")
        self.assertEqual(v[("a", "mine")], "5")
        self.assertEqual(v[("a", "new")], "4")
        self.assertEqual(v[("own", "k")], "1")
        self.assertEqual(v[("b", "q")], "1")
        self.assertIn("# muj klic\nmine = 5\n", merged)
        self.assertTrue(merged.startswith("top = 1\n"))
        # vlastni klic v sekci [a] je pred komentarem dalsi sekce, ne az za ni
        self.assertLess(merged.index("mine = 5"), merged.index("# dalsi"))

    def test_user_comment_above_existing_key_kept(self):
        ours = "[a]\nx = 1\n# zmeneno kvuli tiskarne\ny = 20\nz = 3\n"
        theirs = "[a]\nx = 1\ny = 2\nz = 3\nn = 1\n"
        merged, _how = cm.merge(self.BASE, ours, theirs)
        self.assertEqual(merged, "[a]\nx = 1\n# zmeneno kvuli tiskarne\ny = 20\nz = 3\nn = 1\n")

    def test_multiline_toml_array(self):
        base = 'a = 1\nlist = [\n  "x",\n  "y",\n]\nb = 2\n'
        ours = 'a = 1\nlist = [\n  "x",\n  "mine",\n]\nb = 2\n'
        theirs = 'a = 1\nlist = [\n  "x",\n  "y",\n]\nb = 3\nc = """\nmulti\n"""\n'
        merged, _how = cm.merge(base, ours, theirs)
        self.assertEqual(merged, 'a = 1\nlist = [\n  "x",\n  "mine",\n]\nb = 3\nc = """\nmulti\n"""\n')

    def test_ini_with_semicolon_comments(self):
        base = "; vychozi\n[Main]\nTheme=light\nSize = 10\n"
        ours = "; vychozi\n[Main]\nTheme=dark\nSize = 10\n"
        theirs = "; vychozi\n[Main]\nTheme=light\nSize = 12\nNew = yes\n"
        merged, _how = cm.merge(base, ours, theirs)
        self.assertEqual(merged, "; vychozi\n[Main]\nTheme=dark\nSize = 12\nNew = yes\n")

    def test_respects_user_rejects_changed_value(self):
        self.assertFalse(cm.respects_user(self.BASE, "[a]\nx = 10\n", "[a]\nx = 1\n", "[a]\nx = 1\n"))
        self.assertTrue(cm.respects_user(self.BASE, "[a]\nx = 1\n", "[a]\nx = 5\n", "[a]\nx = 5\n"))
        self.assertFalse(cm.respects_user(self.BASE, "[a]\nx = 1\n", "[a]\nx = 5\n", "[a]\nx = 5\n",
                                          pinned={("a", "x")}))

    def test_duplicate_keys_fall_back_to_lines(self):
        base = "[r]\nServer = a\nServer = b\n"
        ours = "[r]\nServer = mine\nServer = b\n"
        theirs = "[r]\nServer = a\nServer = b\nServer = c\n"
        self.assertIsNone(cm.parse_keys(ours))
        merged, how = cm.merge(base, ours, theirs)
        self.assertEqual((merged, how), ("[r]\nServer = mine\nServer = b\nServer = c\n", "lines"))

    def test_invalid_toml_result_rejected(self):
        # obe verze platne TOML, vysledek ne (opakovana tabulka) -> konflikt, nic se nezapise
        self.assertFalse(cm._toml_ok("a = 1\n", "a = 2\n", "a = 1\na = 2\n"))
        self.assertTrue(cm._toml_ok("a = 1\n", "a = 2\n", "a = 3\n"))


class TextMerge(unittest.TestCase):
    def test_diff3_clean(self):
        base = "one\ntwo\nthree\nfour\nfive\n"
        ours = "ONE\ntwo\nthree\nfour\nfive\n"
        theirs = "one\ntwo\nthree\nfour\nFIVE\nsix\n"
        merged, how = cm.merge(base, ours, theirs, "etc/fstab-like")
        self.assertEqual((merged, how), ("ONE\ntwo\nthree\nfour\nFIVE\nsix\n", "lines"))

    def test_diff3_conflict(self):
        merged, why = cm.merge("a b\nc d\n", "a x\nc d\n", "a y\nc d\n")
        self.assertIsNone(merged)
        self.assertEqual(why, "conflict")

    def test_same_change_both_sides(self):
        self.assertEqual(cm.diff3("a\nb\n", "a\nc\n", "a\nc\n"), "a\nc\n")

    def test_missing_trailing_newline(self):
        self.assertEqual(cm.diff3("a\nb", "A\nb", "a\nb\nc"), "A\nb\nc")

    def test_no_base_only_additions(self):
        merged, _how = cm.merge(None, "alias ll ls -l\nmine on\n", "# novy komentar\nalias ll ls -l\nmine on\nx y\n")
        self.assertEqual(merged, "# novy komentar\nalias ll ls -l\nmine on\nx y\n")

    def test_no_base_changed_line_is_conflict(self):
        merged, why = cm.merge(None, "opt yes\n", "opt no\n")
        self.assertIsNone(merged)
        self.assertEqual(why, "nobase")

    def test_identical(self):
        self.assertEqual(cm.merge(None, "x\n", "x\n"), ("x\n", "same"))

    def test_base_equal_to_new_is_ignored(self):
        """Kopie = nova verze (nespolehlivy zaklad): bez ni, aby se nove radky neztratily."""
        merged, _how = cm.merge("[a]\nx = 1\nn = 2\n", "[a]\nx = 5\n", "[a]\nx = 1\nn = 2\n")
        self.assertEqual(values(merged), {("a", "x"): "5", ("a", "n"): "2"})


# ---- 2. soubory, kopie verze z baliku ---------------------------------------------------------------
def make_db_entry(root, name, version, backups, files=None):
    """Zaznam mistni databaze libalpm (desc + files s %BACKUP%)."""
    d = os.path.join(root, "var/lib/lux/local", f"{name}-{version}")
    os.makedirs(d, exist_ok=True)
    write(os.path.join(d, "desc"), f"%NAME%\n{name}\n\n%VERSION%\n{version}\n\n")
    flist = "\n".join(files or [p for p in backups])
    write(os.path.join(d, "files"), "%FILES%\n" + flist + "\n\n%BACKUP%\n"
          + "".join(f"{p}\t{h}\n" for p, h in backups.items()) + "\n")


def make_pkg(path, name, version, files, backup=()):
    """Balicek .pkg.tar (bez komprese) s .PKGINFO - staci libalpm i bsdtar."""
    info = (f"pkgname = {name}\npkgbase = {name}\npkgver = {version}\npkgdesc = test\n"
            f"builddate = {int(time.time())}\npackager = test\nsize = 10\narch = any\n"
            + "".join(f"backup = {b}\n" for b in backup))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with tarfile.open(path, "w") as t:
        for n, data in [(".PKGINFO", info)] + list(files.items()):
            b = data.encode()
            ti = tarfile.TarInfo(n)
            ti.size, ti.mode, ti.mtime = len(b), 0o644, int(time.time())
            t.addfile(ti, io.BytesIO(b))
    return path


class Files(unittest.TestCase):
    def setUp(self):
        self.root = tmpdir(self)
        self.db = os.path.join(self.root, "var/lib/lux")
        self.cache = os.path.join(self.root, "var/cache/lux/pkg")
        self.conf = os.path.join(self.root, "etc/lux/lux.conf")

    def test_read_backups(self):
        make_db_entry(self.root, "lux-engine", "1:7.1-3", {"etc/lux/lux.conf": md5("x"), "etc/x": "(null)"})
        make_db_entry(self.root, "other", "1-1", {"etc/o": md5("o")})
        b = cm.read_backups(self.db)
        self.assertEqual(b["etc/lux/lux.conf"], ("lux-engine", "1:7.1-3", md5("x")))
        self.assertEqual(b["etc/x"][2], None)
        self.assertEqual(set(cm.read_backups(self.db, names={"other"})), {"etc/o"})

    def test_merged_file_backup_mode_and_pristine(self):
        write(self.conf, STAGING, 0o640)
        write(self.conf + ".luxnew", LUX_CONF_NEW)
        make_db_entry(self.root, "lux-engine", "2-1", {"etc/lux/lux.conf": md5(LUX_CONF_NEW)})
        res = cm.merge_pending(self.root, self.db)
        self.assertEqual([(r["status"], r["path"]) for r in res], [("merged", "/etc/lux/lux.conf")])
        self.assertFalse(os.path.exists(self.conf + ".luxnew"))
        self.assertEqual(read(self.conf + ".lux-old"), STAGING)
        self.assertEqual(values(read(self.conf))[("general", "channel")], '"staging"')
        self.assertIn("countme = true", read(self.conf))
        self.assertEqual(os.stat(self.conf).st_mode & 0o777, 0o640)
        # nova verze z baliku je zakladem pro priste
        self.assertEqual(read(cm.pristine_path(self.root, "etc/lux/lux.conf")), LUX_CONF_NEW)
        self.assertEqual(os.stat(os.path.join(self.root, cm.PRISTINE_DIR)).st_mode & 0o777, 0o700)
        kinds = [k for k, _t in cm.messages(res)]
        self.assertEqual(kinds, ["ok"])
        self.assertIn("your settings were kept", cm.messages(res)[0][1])

    def test_conflict_changes_nothing_and_says_what_to_do(self):
        p = os.path.join(self.root, "etc/x.conf")
        write(p, "opt yes\n")
        write(p + ".luxnew", "opt no\n")
        res = cm.merge_pending(self.root, self.db)
        self.assertEqual(res[0]["status"], "conflict")
        self.assertEqual(read(p), "opt yes\n")
        self.assertTrue(os.path.exists(p + ".luxnew"))
        self.assertFalse(os.path.exists(p + ".lux-old"))
        text = " ".join(t for _k, t in cm.messages(res))
        self.assertIn("/etc/x.conf", text)
        self.assertIn("stays in use", text)
        self.assertIn("sudo lux config-diff /etc/x.conf", text)

    def test_old_pacnew_name_and_unchanged_result(self):
        p = os.path.join(self.root, "etc/y.conf")
        write(p, "[a]\nx = 5\n")
        write(p + ".pacnew", "[a]\nx = 1\n")
        res = cm.merge_pending(self.root, self.db)
        self.assertEqual(res[0]["status"], "merged")
        self.assertFalse(res[0]["changed"])
        self.assertFalse(os.path.exists(p + ".pacnew"))
        self.assertFalse(os.path.exists(p + ".lux-old"))       # nic se nezmenilo, neni co zalohovat
        self.assertEqual(read(p), "[a]\nx = 5\n")

    def test_binary_and_symlink_untouched(self):
        p = os.path.join(self.root, "etc/bin.dat")
        write(p, b"\xff\xfe\x00")
        write(p + ".luxnew", b"\xff\x00")
        q = os.path.join(self.root, "etc/link.conf")
        write(q + ".target", "a = 1\n")
        os.symlink(q + ".target", q)
        write(q + ".luxnew", "a = 1\nb = 2\n")
        res = {r["path"]: r for r in cm.merge_pending(self.root, self.db)}
        self.assertEqual(res["/etc/bin.dat"]["status"], "conflict")
        self.assertEqual(res["/etc/link.conf"]["status"], "conflict")
        self.assertEqual(read(q + ".target"), "a = 1\n")

    def test_pristine_base_used(self):
        """Se zakladem: nova vychozi hodnota tam, kde uzivatel ma presne starou."""
        p = os.path.join(self.root, "etc/z.conf")
        write(cm.pristine_path(self.root, "etc/z.conf"), "[a]\nx = 1\ny = 2\n")
        write(p, "[a]\nx = 1\ny = 22\n")
        write(p + ".luxnew", "[a]\nx = 3\ny = 2\n")
        cm.merge_pending(self.root, self.db)
        self.assertEqual(read(p), "[a]\nx = 3\ny = 22\n")

    def test_ensure_pristine_from_disk_cache_and_stale(self):
        rel = "etc/z.conf"
        v1 = "[a]\nx = 1\n"
        write(os.path.join(self.root, rel), v1)
        entry = ("z", "1-1", md5(v1))
        self.assertTrue(cm.ensure_pristine(self.root, rel, entry, [self.cache]))
        self.assertEqual(read(cm.pristine_path(self.root, rel)), v1)
        # uzivatel soubor zmenil a kopie chybi: ze stare verze balicku v cache (overene md5)
        os.unlink(cm.pristine_path(self.root, rel))
        write(os.path.join(self.root, rel), "[a]\nx = 9\n")
        make_pkg(os.path.join(self.cache, "z-1-1-any.pkg.tar"), "z", "1-1", {rel: v1}, [rel])
        if shutil.which("bsdtar"):
            self.assertTrue(cm.ensure_pristine(self.root, rel, entry, [self.cache]))
            self.assertEqual(read(cm.pristine_path(self.root, rel)), v1)
        # kopie, ktera nesedi s databazi (a neda se overit), se smaze - zadny chybny zaklad
        write(cm.pristine_path(self.root, rel), "[a]\nx = 7\n")
        self.assertFalse(cm.ensure_pristine(self.root, rel, ("z", "2-1", md5("[a]\nx = 2\n")), [self.cache]))
        self.assertFalse(os.path.exists(cm.pristine_path(self.root, rel)))

    def test_cached_package_name_exact(self):
        for f in ("z-1-1-any.pkg.tar.zst", "z-1-1-any.pkg.tar.zst.sig", "zz-1-1-any.pkg.tar.zst",
                  "z-extra-1-1-any.pkg.tar.zst"):
            write(os.path.join(self.cache, f), "")
        self.assertEqual(os.path.basename(cm.cached_package([self.cache], "z", "1-1")), "z-1-1-any.pkg.tar.zst")
        self.assertIsNone(cm.cached_package([self.cache], "z", "2-1"))

    def test_refresh_keeps_base_of_waiting_file(self):
        """Nesloucitelny soubor: kopie stare verze zustane (zaklad pro pozdejsi slouceni)."""
        rel = "etc/w.conf"
        write(cm.pristine_path(self.root, rel), "old\n")
        write(os.path.join(self.root, rel), "mine\n")
        write(os.path.join(self.root, rel + ".luxnew"), "new\n")
        make_db_entry(self.root, "w", "2-1", {rel: md5("new\n")})
        cm.refresh(self.root, self.db, [self.cache])
        self.assertEqual(read(cm.pristine_path(self.root, rel)), "old\n")

    def test_cli_merge_and_results_file(self):
        write(self.conf, STAGING)
        write(self.conf + ".luxnew", LUX_CONF_NEW)
        env = dict(os.environ, LUX_CONFIG_MERGE_RESULT="/var/lib/lux/pristine/.r.json", LANG="C")
        r = subprocess.run([sys.executable, SRC, "merge", "--root", self.root], capture_output=True, text=True,
                           env=env, stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Updated /etc/lux/lux.conf; your settings were kept", r.stdout)
        data = cm.read_results(self.root, "/var/lib/lux/pristine/.r.json")
        self.assertEqual(data[0]["status"], "merged")
        r = subprocess.run([sys.executable, SRC, "pending", "--root", self.root], capture_output=True, text=True)
        self.assertEqual(r.stdout, "")


# ---- 3. lux config-diff ---------------------------------------------------------------------------
class ConfigDiff(unittest.TestCase):
    def setUp(self):
        self.root = tmpdir(self)
        self.p = os.path.join(self.root, "etc/lux/lux.conf")
        write(self.p, STAGING)
        write(self.p + ".luxnew", LUX_CONF_NEW)

    def run_diff(self, choice=None, answers="", path="/etc/lux/lux.conf", yes=False):
        out = io.StringIO()
        rc = cm.config_diff(self.root, path, choice, yes=yes, out=out, inp=io.StringIO(answers))
        return rc, out.getvalue()

    def test_nothing_waiting(self):
        os.unlink(self.p + ".luxnew")
        rc, out = self.run_diff()
        self.assertEqual(rc, 0)
        self.assertIn("No new version", out)

    def test_interactive_merge(self):
        rc, out = self.run_diff(answers="d\nm\n")
        self.assertEqual(rc, 0)
        self.assertIn("+countme = true", out)                  # rozdil
        self.assertIn("LuxOS can combine both", out)
        self.assertIn("your settings were kept", out)
        self.assertEqual(values(read(self.p))[("general", "channel")], '"staging"')
        self.assertFalse(os.path.exists(self.p + ".luxnew"))

    def test_keep(self):
        rc, _out = self.run_diff("keep")
        self.assertEqual(read(self.p), STAGING)
        self.assertFalse(os.path.exists(self.p + ".luxnew"))

    def test_new_by_luxnew_path(self):
        rc, out = self.run_diff("new", path="/etc/lux/lux.conf.luxnew")
        self.assertEqual(read(self.p), LUX_CONF_NEW)
        self.assertEqual(read(self.p + ".lux-old"), STAGING)
        self.assertIn(".lux-old", out)

    def test_yes_skips_unmergeable(self):
        write(self.p, "not toml at all {\n")
        rc, _out = self.run_diff(yes=True)
        self.assertTrue(os.path.exists(self.p + ".luxnew"))
        rc, out = self.run_diff("merge")
        self.assertEqual(rc, 1)
        self.assertIn("cannot be combined", out)


# ---- 4. integrace se skutecnym libalpm ---------------------------------------------------------------
try:
    import pyalpm
except ImportError:
    pyalpm = None


@unittest.skipUnless(pyalpm is not None, "pyalpm neni k dispozici")
class AlpmIntegration(unittest.TestCase):
    """lux_alpm.py install (skutecne libalpm) v docasnem koreni: stara verze, uzivatel zmeni soubor,
    nova verze -> slouceni bez *.luxnew; konflikt -> srozumitelne hlaseni, soubor beze zmeny."""

    def setUp(self):
        sys.path.insert(0, os.path.join(REPO, "packages", "lux-engine"))
        s = importlib.util.spec_from_file_location("lux_alpm_int", os.path.join(HERE, "..", "lux_alpm.py"))
        self.la = importlib.util.module_from_spec(s)
        s.loader.exec_module(self.la)
        self.root = tmpdir(self)
        r = self.root
        for d in ("var/lib/lux/local", "var/cache/lux/pkg", "etc/lux/hooks", "usr/share/libalpm/hooks",
                  "var/log"):
            os.makedirs(os.path.join(r, d), exist_ok=True)
        write(os.path.join(r, "var/lib/lux/local/ALPM_DB_VERSION"), "9\n")
        self.conf_text = (f"[options]\nRootDir = {r}/\nDBPath = {r}/var/lib/lux/\nCacheDir = {r}/var/cache/lux/pkg/\n"
                          f"HookDir = {r}/etc/lux/hooks/\nGPGDir = {r}/etc/lux/keyring/\nLogFile = {r}/var/log/lux.log\n"
                          "Architecture = x86_64\nSigLevel = Never\nLocalFileSigLevel = Never\n")
        self.pkgs = os.path.join(r, "pkgs")
        os.environ["LUX_ALLOW_NONROOT"] = "1"
        for k in (cm.QUIET_ENV, cm.RESULT_ENV):
            os.environ.pop(k, None)

    def lux(self, *args):
        out = io.StringIO()
        conf = self.la.EngineConf(self.conf_text)
        err = io.StringIO()
        with mock.patch.object(self.la, "system_writable", lambda flags=None: contextlib.nullcontext()), \
                contextlib.redirect_stderr(err):
            rc = self.la.main(["-y", "--color=never", "--lang", "C"] + list(args), api=pyalpm, conf=conf,
                              out=out, inp=io.StringIO())
        return rc, out.getvalue() + err.getvalue()

    def pkg(self, ver, text, rel="etc/lux/lux.conf"):
        return make_pkg(os.path.join(self.pkgs, f"luxtest-{ver}-any.pkg.tar"), "luxtest", ver, {rel: text}, [rel])

    def test_upgrade_merges_lux_conf(self):
        rc, out = self.lux("install", self.pkg("1-1", LUX_CONF_OLD))
        self.assertEqual(rc, 0, out)
        conf = os.path.join(self.root, "etc/lux/lux.conf")
        self.assertEqual(read(conf), LUX_CONF_OLD)
        # Aktualizace softwaru: kanal staging (lux-config set-channel)
        write(conf, STAGING)
        rc, out = self.lux("install", self.pkg("2-1", LUX_CONF_NEW))
        self.assertEqual(rc, 0, out)
        self.assertFalse(os.path.exists(conf + ".luxnew"), out)
        merged = read(conf)
        self.assertEqual(values(merged)[("general", "channel")], '"staging"')
        self.assertIn("countme = true", merged)
        self.assertIn(COUNTME.splitlines()[0], merged)
        self.assertEqual(read(conf + ".lux-old"), STAGING)
        self.assertIn("Updated /etc/lux/lux.conf; your settings were kept", out)
        self.assertNotIn("review", out.lower())
        # zakladem pro priste je nova verze z baliku
        self.assertEqual(read(cm.pristine_path(self.root, "etc/lux/lux.conf")), LUX_CONF_NEW)
        # dalsi verze meni vychozi hodnotu klice, ktery uzivatel nemenil -> nova; staging zustava
        v3 = LUX_CONF_NEW.replace("parallel = 10", "parallel = 6").replace('channel = "stable"',
                                                                           'channel = "stable" ')
        rc, out = self.lux("install", self.pkg("3-1", v3))
        self.assertEqual(rc, 0, out)
        v = values(read(conf))
        self.assertEqual(v[("downloads", "parallel")], "6")
        self.assertEqual(v[("general", "channel")], '"staging"')

    def test_upgrade_conflict_keeps_file_and_explains(self):
        rel = "etc/luxtest/plain.txt"
        self.assertEqual(self.lux("install", self.pkg("1-1", "mode a\nend\n", rel))[0], 0)
        p = os.path.join(self.root, rel)
        write(p, "mode mine\nend\n")
        rc, out = self.lux("install", self.pkg("2-1", "mode b\nend\n", rel))
        self.assertEqual(rc, 0, out)
        self.assertEqual(read(p), "mode mine\nend\n")
        self.assertTrue(os.path.exists(p + ".luxnew"))
        self.assertIn("could not be combined", out)
        self.assertIn("sudo lux config-diff /" + rel, out)
        # kopie stare verze (zaklad) zustala pro pozdejsi slouceni
        self.assertEqual(read(cm.pristine_path(self.root, rel)), "mode a\nend\n")

    def test_plain_text_diff3_through_upgrade(self):
        rel = "etc/luxtest/list.txt"
        v1 = "alpha\nbeta\ngamma\ndelta\n"
        self.assertEqual(self.lux("install", self.pkg("1-1", v1, rel))[0], 0)
        p = os.path.join(self.root, rel)
        write(p, "ALPHA\nbeta\ngamma\ndelta\n")
        rc, out = self.lux("install", self.pkg("2-1", "alpha\nbeta\ngamma\nDELTA\nepsilon\n", rel))
        self.assertEqual(rc, 0, out)
        self.assertEqual(read(p), "ALPHA\nbeta\ngamma\nDELTA\nepsilon\n")
        self.assertFalse(os.path.exists(p + ".luxnew"))

    def test_leftover_luxnew_on_update(self):
        """*.luxnew z doby pred samoslucovanim (bez kopie zakladu): lux update ji slouci."""
        conf = os.path.join(self.root, "etc/lux/lux.conf")
        self.assertEqual(self.lux("install", self.pkg("1-1", LUX_CONF_NEW))[0], 0)
        os.unlink(cm.pristine_path(self.root, "etc/lux/lux.conf"))
        write(conf, STAGING)                                   # stara lux.conf uzivatele
        write(conf + ".luxnew", LUX_CONF_NEW)
        rc, out = self.lux("upgrade")
        self.assertEqual(rc, 0, out)
        self.assertIn("System packages are up to date", out)
        self.assertIn("Updated /etc/lux/lux.conf; your settings were kept", out)
        self.assertFalse(os.path.exists(conf + ".luxnew"))
        self.assertEqual(read(conf), LUX_CONF_NEW.replace('channel = "stable"', 'channel = "staging"'))

    def test_machine_mode_line(self):
        self.assertEqual(self.lux("install", self.pkg("1-1", LUX_CONF_OLD))[0], 0)
        write(os.path.join(self.root, "etc/lux/lux.conf"), STAGING)
        out = io.StringIO()
        conf = self.la.EngineConf(self.conf_text)
        with mock.patch.object(self.la, "system_writable", lambda flags=None: contextlib.nullcontext()):
            self.la.main(["-y", "--machine", "install", self.pkg("2-1", LUX_CONF_NEW)], api=pyalpm, conf=conf,
                         out=out, inp=io.StringIO())
        self.assertIn("@@CONFIG merged /etc/lux/lux.conf", out.getvalue())

    def test_hook_commands_around_engine_transaction(self):
        """Cesta hooku (LuxOS Care, lux-engine): pre/post s cestami na stdin kolem transakce libalpm."""
        rel = "etc/lux/lux.conf"
        self.assertEqual(self.lux("install", self.pkg("1-1", LUX_CONF_OLD))[0], 0)
        os.unlink(cm.pristine_path(self.root, rel))            # kopie vznikne v hooku pred transakci
        write(os.path.join(self.root, rel), STAGING)
        # uzivatel soubor zmenil -> kopie jen ze stare verze balicku v cache
        shutil.copy(os.path.join(self.pkgs, "luxtest-1-1-any.pkg.tar"),
                    os.path.join(self.root, "var/cache/lux/pkg"))
        env = dict(os.environ, LANG="C")
        r = subprocess.run([sys.executable, SRC, "pre", "--root", self.root], input=rel + "\n", text=True,
                           capture_output=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        if shutil.which("bsdtar"):
            self.assertEqual(read(cm.pristine_path(self.root, rel)), LUX_CONF_OLD)
        # transakce primo pres libalpm (jako lux-engine -U), bez slouceni v lux_alpm.py
        h = pyalpm.Handle(self.root + "/", self.root + "/var/lib/lux/")
        t = h.init_transaction()
        t.add_pkg(h.load_pkg(self.pkg("2-1", LUX_CONF_NEW.replace("parallel = 10", "parallel = 4"))))
        t.prepare()
        t.commit()
        t.release()
        self.assertTrue(os.path.exists(os.path.join(self.root, rel + ".luxnew")))
        r = subprocess.run([sys.executable, SRC, "post", "--root", self.root], input=rel + "\n", text=True,
                           capture_output=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("your settings were kept", r.stdout)
        v = values(read(os.path.join(self.root, rel)))
        self.assertEqual(v[("general", "channel")], '"staging"')
        self.assertEqual(v[("general", "countme")], "true")
        if shutil.which("bsdtar"):
            self.assertEqual(v[("downloads", "parallel")], "4")    # znamy zaklad: nova vychozi hodnota


if __name__ == "__main__":
    unittest.main()
