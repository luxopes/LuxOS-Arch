#!/usr/bin/env python3
"""Napoveda a chyby pouziti nastroju LuxOS v jazyce systemu (regrese: "luxos-care -h" na anglickem
systemu vypsal cesky docstring bez diakritiky).

    python3 packages/luxos-i18n/tests/test_cli_i18n.py          en, cs, de
    LUXOS_CLI_I18N_ALL=1 python3 ...                            vsech 12 jazyku

1. Kazdy nastroj z TOOLS se spusti jen s --help (nebo jinym volanim, ktere nic nemeni) bez DISPLAY,
   s docasnym HOME a XDG adresari a preklady ze zdrojoveho stromu (LUXOS_I18N_DIR):
   - LANG=en_US.UTF-8: zadna cestina (diakritika ani typicka ceska slova bez diakritiky),
   - LANG=cs_CZ.UTF-8 (a dalsi jazyky): vystup je prelozeny - zadny anglicky radek s vetou
     z anglickeho vystupu nezustal beze zmeny, v cestine je diakritika,
   - nemecky vystup neobsahuje cestinu.
2. Staticky: zadny dodavany program nevypisuje __doc__ ani vlastni komentare (sed -n ... "$0").
"""
import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
PK = os.path.join(ROOT, "packages")
I18N = os.path.join(PK, "luxos-i18n", "files")
RUN = os.path.join(HERE, "run_tool.py")
HAVE_SH_I18N = os.path.exists("/usr/lib/luxos/i18n.sh")   # skripty v bashi ho nacitaji z pevne cesty

# (nastroj relativne k packages, argumenty, vnitrni = napoveda jen anglicky)
TOOLS = (
    ("lux/lux", ["--help"], False),
    ("lux/lux", ["system", "help"], False),
    ("lux/lux", ["domain", "help"], False),
    ("lux/pacman-hint", ["-Syu"], False),
    ("luxos-care/files/luxos-care", ["-h"], False),
    ("luxos-care/files/luxos-care", ["no-such-command"], False),
    ("luxos-guard/files/luxos-guard", ["--help"], False),
    ("luxos-sandbox/files/luxos-sandbox", ["--help"], False),
    ("luxos-safe/files/luxos-safe", ["--help"], False),
    ("luxos-backup/files/luxos-backup", ["--help"], False),
    ("luxdrop/files/luxdrop", ["--help"], False),
    ("luxos-domain/files/lux-domain", ["--help"], False),
    ("luxos-printing/files/luxos-scan", ["--help"], False),
    ("luxos-desktop/files/bin/luxos-app-reset", ["--help"], False),
    ("luxos-companion/files/luxos-companion", ["--help"], False),
    ("luxos-desktop/files/bin/luxos-unfreeze", ["--help"], False),
    ("luxos-desktop/files/bin/luxos-appearance", ["--help"], False),
    ("luxos-desktop/files/bin/luxos-brightness", ["--help"], False),
    ("luxos-desktop/files/bin/luxos-datasaver", ["--help"], False),
    ("luxos-desktop/files/bin/luxos-displays", ["--help"], False),
    ("luxos-desktop/files/bin/luxos-powersaver", ["--help"], False),
    ("luxos-desktop/files/bin/luxos-network-login", ["--help"], False),
    ("luxos-desktop/files/bin/luxos-portal-check", ["--help"], False),
    ("luxos-branding/files/plymouth/luxos-splash", ["--help"], False),
    ("luxos-drivers/luxos-hwdetect", ["--help"], False),
    ("luxos-drivers/luxos-hwdetect", ["--no-such-option"], False),
    ("luxos-installer/files/luxos-oem", ["--help"], False),
    ("luxos-installer/files/luxos-install", ["--help"], False),
    ("luxos-shell/files/bin/adduser", ["--help"], False),
    ("luxos-shell/files/bin/service", ["--help"], False),
    ("luxos-shell/files/bin/update-grub", ["--help"], False),
    ("luxos-desktop/files/fingerprint/luxos-fingerprint-pam", ["--help"], True),
    ("lux-engine/lux_config.py", ["--help"], True),
)
LANGS = ("cs", "sk", "pl", "uk", "hu", "de", "fr", "es", "it", "pt", "nl", "sv")
LOCALES = {"cs": "cs_CZ", "sk": "sk_SK", "pl": "pl_PL", "uk": "uk_UA", "hu": "hu_HU", "de": "de_DE",
           "fr": "fr_FR", "es": "es_ES", "it": "it_IT", "pt": "pt_BR", "nl": "nl_NL", "sv": "sv_SE"}

# Typicka ceska slova bez diakritiky (docstringy a komentare LuxOS) - v anglickem vystupu nesmi byt
CZECH_WORDS = re.compile(
    r"\b(je|jsou|neni|nelze|zalozni|jadro|jadra|souboru|soubory|nastaveni|spusteni|spousti|aktualizace|"
    r"aktualizaci|pouziti|pouzit|uzivatel|uzivatele|uzivatelu|pocitac|pocitace|slozka|slozky|slozku|zaloha|"
    r"zalohy|heslo|hesla|prikaz|prikazy|volby|neznamy|neznama|zarizeni|ovladace|ovladacu|balik|baliky|baliku|"
    r"snimek|snimky|snimku|obnova|kontrola|stav|okno|pripojeni|prihlaseni|sluzba|sluzby|zadny|zadne|nebo|"
    r"pres|podle|jako|kdyz|ktery|ktera|ktere|jeste|vsechny|hlaseni|zachrana|predinstalace|viz|napr)\b",
    re.I)
CZECH_LETTERS = re.compile(r"[ěščřžůňťďĚŠČŘŽŮŇŤĎ]")
DIACRITICS = re.compile(r"[áéíóúýěščřžůňťďÁÉÍÓÚÝĚŠČŘŽŮŇŤĎ]")


def run(rel, args, lang, tmp):
    path = os.path.join(PK, rel)
    home = tempfile.mkdtemp(dir=tmp)
    os.makedirs(os.path.join(home, "run"), mode=0o700)
    env = {"PATH": "/usr/bin:/bin", "HOME": home, "XDG_RUNTIME_DIR": os.path.join(home, "run"),
           "XDG_CONFIG_HOME": os.path.join(home, ".config"), "XDG_DATA_HOME": os.path.join(home, ".local/share"),
           "XDG_CACHE_HOME": os.path.join(home, ".cache"), "XDG_STATE_HOME": os.path.join(home, ".local/state"),
           "LANG": lang, "LUXOS_I18N_DIR": I18N, "TERM": "dumb", "NO_COLOR": "1", "PYTHONDONTWRITEBYTECODE": "1",
           "LUX_DOMAIN": os.path.join(PK, "luxos-domain", "files", "lux-domain")}
    with open(path, encoding="utf-8") as f:
        first = f.readline()
    cmd = [sys.executable, RUN, path] if "python" in first else ["bash", path]
    r = subprocess.run(cmd + args, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
    return r.returncode, r.stdout + r.stderr


def prose(line):
    """Radek s anglickou vetou (aspon 3 slova z pismen za sebou) - musi se prelozit; syntaxe prikazu
    ("sudo luxos-oem seal [--yes]", "exclude [list | add PATH]") vetou neni."""
    words = 0
    for tok in line.split(" "):
        tok = tok.strip(",.;:()")
        words = words + 1 if re.fullmatch(r"[A-Za-z][a-z]+", tok) else 0
        if words >= 3:
            return True
    return False


class CliHelpI18n(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="luxos-cli-i18n-")
        cls.en = {}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def english(self, rel, args):
        key = (rel, tuple(args))
        if key not in self.en:
            self.en[key] = run(rel, args, "en_US.UTF-8", self.tmp)
        return self.en[key]

    def test_english_has_no_czech(self):
        for rel, args, _internal in TOOLS:
            with self.subTest(tool=rel, args=args):
                rc, out = self.english(rel, args)
                self.assertIn(rc, (0, 1, 2), out)
                self.assertTrue(out.strip(), "empty help")
                self.assertNotIn("Traceback", out)
                self.assertIsNone(DIACRITICS.search(out), out)
                bad = CZECH_WORDS.findall(out)
                self.assertFalse(bad, "Czech words %s in:\n%s" % (bad, out))

    def check_translated(self, code):
        locale = LOCALES[code] + ".UTF-8"
        for rel, args, internal in TOOLS:
            if internal:
                continue
            if not HAVE_SH_I18N and "python" not in open(os.path.join(PK, rel), encoding="utf-8").readline():
                continue
            with self.subTest(lang=code, tool=rel, args=args):
                rc_en, en = self.english(rel, args)
                rc, out = run(rel, args, locale, self.tmp)
                self.assertEqual(rc, rc_en, out)
                self.assertNotIn("Traceback", out)
                self.assertNotEqual(out, en, "not translated")
                lines = set(out.splitlines())
                left = [ln for ln in en.splitlines() if prose(ln) and ln in lines]
                self.assertFalse(left, "untranslated (%s):\n%s" % (code, "\n".join(left)))
                if code == "cs":
                    self.assertIsNotNone(DIACRITICS.search(out), out)
                elif code not in ("sk",):
                    self.assertIsNone(CZECH_LETTERS.search(out), "Czech in %s:\n%s" % (code, out))

    def test_czech(self):
        self.check_translated("cs")

    def test_german(self):
        self.check_translated("de")

    @unittest.skipUnless(os.environ.get("LUXOS_CLI_I18N_ALL"), "LUXOS_CLI_I18N_ALL=1 for all languages")
    def test_all_languages(self):
        for code in LANGS:
            if code not in ("cs", "de"):
                self.check_translated(code)


# Zdroje, ktere se nedodavaji uzivatelum (sestaveni balicku, vyvojove nastroje)
NOT_SHIPPED = re.compile(r"/(tests|tools|lsl-ide|src|pkg)/|/(make-[\w-]+\.py|merge-xfconf\.py|gen-[\w-]+\.py)$")
PRINT_DOC = re.compile(r"(print|write|exit)\s*\(\s*__doc__|__doc__\s*\.\s*(strip|split)")
SHELL_SELF = re.compile(r"\b(sed|head|tail|grep|awk|cat)\b[^|\n]*\"?\$(0|\{0\}|\{BASH_SOURCE)")


class NoDeveloperDocs(unittest.TestCase):
    def files(self):
        for p in glob.glob(os.path.join(PK, "**", "*"), recursive=True):
            if os.path.isfile(p) and not NOT_SHIPPED.search(p.replace(os.sep, "/")) and \
                    not p.endswith((".tsv", ".md", ".png", ".svg", ".json", ".1")):
                try:
                    with open(p, encoding="utf-8") as f:
                        yield p, f.read()
                except (UnicodeDecodeError, OSError):
                    continue

    def test_no_docstring_or_comment_help(self):
        bad = []
        for p, text in self.files():
            for i, line in enumerate(text.splitlines(), 1):
                code = line.split("#", 1)[0] if not line.lstrip().startswith(("#!", "\"", "'")) else line
                if line.lstrip().startswith("#"):
                    continue
                if PRINT_DOC.search(code) or ("help" in code and SHELL_SELF.search(code)):
                    bad.append(f"{os.path.relpath(p, ROOT)}:{i}: {line.strip()}")
        self.assertFalse(bad, "developer docs printed to users (use translated help):\n" + "\n".join(bad))


if __name__ == "__main__":
    unittest.main()
