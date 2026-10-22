#!/usr/bin/env python3
"""LuxOS - slouceni novych prekladu do packages/luxos-i18n/files/<jazyk>.tsv.

  scripts/merge-i18n.py SOUBOR.tsv [...]

Vstup: prvni radek = kody jazyku ("en<TAB>cs<TAB>de..."), dalsi radky = anglicky text a preklady.
Pridaji se jen texty, ktere v danem jazyce jeste nejsou; %s a %d musi v prekladu zustat.
"""
import os
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
I18N = os.path.join(ROOT, "packages", "luxos-i18n", "files")


def main(paths):
    add = {}
    for path in paths:
        with open(path, encoding="utf-8") as f:
            rows = [line.rstrip("\n").split("\t") for line in f if line.strip()]
        head = rows[0]
        for r in rows[1:]:
            if r[0].startswith("#"):
                continue
            if len(r) != len(head):
                sys.exit(f"{path}: wrong number of columns: {r[0]}")
            for code, text in zip(head[1:], r[1:]):
                if text.count("%s") != r[0].count("%s") or text.count("%d") != r[0].count("%d"):
                    sys.exit(f"{path}: {code}: placeholders differ: {r[0]}")
                add.setdefault(code, {}).setdefault(r[0], text)
    for code, items in sorted(add.items()):
        tsv = os.path.join(I18N, code + ".tsv")
        with open(tsv, encoding="utf-8") as f:
            have = {line.split("\t", 1)[0] for line in f if "\t" in line}
        new = [(k, v) for k, v in items.items() if k not in have]
        with open(tsv, "a", encoding="utf-8") as out:
            for k, v in new:
                out.write(f"{k}\t{v}\n")
        print(code, len(new))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1:])
