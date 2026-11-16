#!/usr/bin/env python3
"""LuxOS - preklady Name/GenericName/Comment v souborech .desktop z tabulek luxos-i18n (pri sestaveni).

    desktop-i18n.py ADRESAR_TSV SOUBOR.desktop...           doplni chybejici Name[xx]= atd. (na miste)
    desktop-i18n.py --check ADRESAR_TSV SOUBOR.desktop...   jen vypise texty bez prekladu (kod 1)

Launchpad, Hledani a nabidka aplikaci ctou nazvy z .desktop - kdyz mel soubor jen Name[cs], ostatnich
10 jazyku videlo anglictinu. Rucne napsane preklady v souboru maji prednost (neprepisuji se); prelozi
se jen sekce [Desktop Entry] (akce [Desktop Action ...] taky, maji vlastni Name).
"""
import os
import sys

KEYS = ("Name", "GenericName", "Comment")


def load(tsv_dir):
    tabs = {}
    for fn in sorted(os.listdir(tsv_dir)):
        if not fn.endswith(".tsv"):
            continue
        d = {}
        with open(os.path.join(tsv_dir, fn), encoding="utf-8") as f:
            for line in f:
                if line.startswith("#") or "\t" not in line:
                    continue
                k, v = line.rstrip("\n").split("\t", 1)
                if v:
                    d[k] = v
        tabs[fn[:-4]] = d
    return tabs


def translate(text, tabs, check=None):
    lines = text.splitlines()
    out, i = [], 0
    while i < len(lines):
        # jedna sekce: [..] az po dalsi [..]
        j = i + 1
        while j < len(lines) and not lines[j].startswith("["):
            j += 1
        sec = lines[i:j]
        have = {ln.split("=", 1)[0] for ln in sec if "=" in ln}
        new = []
        for ln in sec:
            new.append(ln)
            key, _, val = ln.partition("=")
            if key not in KEYS or not val:
                continue
            for lang in sorted(tabs):
                if f"{key}[{lang}]" in have:
                    continue
                tr = tabs[lang].get(val)
                if tr:
                    new.append(f"{key}[{lang}]={tr}")
                elif check is not None:
                    check.add((lang, val))
        out.extend(new)
        i = j
    return "\n".join(out) + "\n"


def main(argv):
    check = argv and argv[0] == "--check"
    if check:
        argv = argv[1:]
    if len(argv) < 2:
        sys.exit(__doc__)
    tabs = load(argv[0])
    missing = set()
    for path in argv[1:]:
        with open(path, encoding="utf-8") as f:
            text = f.read()
        res = translate(text, tabs, missing if check else None)
        if not check and res != text:
            with open(path, "w", encoding="utf-8") as f:
                f.write(res)
    if check and missing:
        for lang, val in sorted(missing):
            print(f"{lang}\t{val}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
