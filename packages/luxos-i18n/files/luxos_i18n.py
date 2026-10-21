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
