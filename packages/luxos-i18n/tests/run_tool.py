#!/usr/bin/env python3
"""Spusteni nastroje LuxOS v Pythonu ze zdroju (testy): run_tool.py SOUBOR [ARGUMENTY...]

Nastroje si pridavaji /usr/lib/luxos/python (a /usr/lib/luxdrop) na zacatek sys.path; tady se
misto nich pouziji adresare ze zdrojoveho stromu, aby test videl prave upravene moduly
(luxos_i18n, luxos_care ...), ne nainstalovane.
"""
import glob
import os
import runpy
import sys

sys.dont_write_bytecode = True          # zadne __pycache__ ve zdrojich (PKGBUILD instaluje cele adresare)
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
PK = os.path.join(ROOT, "packages")
SRC = [os.path.join(PK, "luxos-i18n", "files")]
SRC += sorted(d for d in glob.glob(os.path.join(PK, "*", "files", "python")) if os.path.isdir(d))
SRC += sorted(d for d in glob.glob(os.path.join(PK, "*", "files")) if os.path.isdir(d))
SRC += [os.path.join(PK, p) for p in ("lux", "lux-engine", "luxos-drivers")]
MAP = {"/usr/lib/luxos/python": SRC, "/usr/lib/luxdrop": [os.path.join(PK, "luxdrop", "files", "lib")],
       "/usr/lib/lux": [os.path.join(PK, "lux"), os.path.join(PK, "lux-engine")]}


class SrcPath(list):
    def insert(self, i, p):
        for d in reversed(MAP.get(str(p).rstrip("/"), [p])):
            super().insert(i, d)

    def append(self, p):
        for d in MAP.get(str(p).rstrip("/"), [p]):
            super().append(d)


sys.path = SrcPath(SRC + sys.path)
if os.environ.get("LUXOS_I18N_MISS"):
    # LUXOS_I18N_MISS=SOUBOR: zapsat texty bez prekladu (hledani chybejicich radku v <jazyk>.tsv)
    import luxos_i18n

    def _logged(text, _orig=luxos_i18n._):
        if text not in luxos_i18n._TR:
            with open(os.environ["LUXOS_I18N_MISS"], "a", encoding="utf-8") as f:
                f.write(text.replace("\n", "\\n") + "\n")
        return _orig(text)
    luxos_i18n._ = _logged
os.environ.setdefault("LUXDROP_LIB", MAP["/usr/lib/luxdrop"][0])
tool = sys.argv[1]
sys.argv = sys.argv[1:]
runpy.run_path(tool, run_name="__main__")
