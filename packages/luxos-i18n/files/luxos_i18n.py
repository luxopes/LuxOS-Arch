"""LuxOS - preklady pro aplikace v Pythonu: _("English") -> text v jazyce uzivatele.

Preklady jsou v /usr/share/luxos/i18n/<jazyk>.tsv (radek "anglicky<TAB>preklad"),
stejne soubory pouzivaji i skripty v bashi (/usr/lib/luxos/i18n.sh).
LUXOS_I18N_DIR prepise adresar s preklady (testy bez instalace balicku).
"""
import os

LANG = (os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES") or os.environ.get("LANG") or "en")
LANG = LANG.split("_")[0].split(".")[0].split("@")[0] or "en"
DIR = os.environ.get("LUXOS_I18N_DIR") or "/usr/share/luxos/i18n"
_TR = {}
try:
    with open(os.path.join(DIR, f"{LANG}.tsv"), encoding="utf-8") as f:
        for line in f:
            if line.startswith("#") or "\t" not in line:
                continue
            k, v = line.rstrip("\n").split("\t", 1)
            if v:
                _TR[k] = v
except OSError:
    pass


def _(text):
    return _TR.get(text, text)


def _keep_space(text):
    """Preklad textu s mezerami/novym radkem na krajich (argparse: "usage: ", "...%(message)s\\n")."""
    core = text.strip()
    if not core:
        return text
    i = text.index(core)
    return text[:i] + _(core) + text[i + len(core):]


def argparse_i18n():
    """Texty argparse (usage:, options, chyby) v jazyce uzivatele - volat pred vytvorenim parseru."""
    import argparse
    argparse._ = _keep_space
    argparse.ngettext = lambda one, many, n: _keep_space(one if n == 1 else many)


def print_usage(head, rows, file=None, width=0):
    """Napoveda prikazu: hlavicka + radky (syntaxe, anglicky popis). Popisy se prekladaji,
    syntaxe zustava. Radek bez popisu ("", nadpis) = nadpis sekce (prelozi se)."""
    import sys
    out = file or sys.stdout
    width = width or min(34, max(len(c) for c, d in rows if d) + 2)
    print(head, file=out)
    for cmd, desc in rows:
        if not desc:
            print("\n" + _(cmd) if cmd else "", file=out)
        elif len(cmd) + 2 > width:
            print(f"  {cmd}\n  {'':{width}}{_(desc)}", file=out)
        else:
            print(f"  {cmd:{width}}{_(desc)}", file=out)
