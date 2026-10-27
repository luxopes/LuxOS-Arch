#!/usr/bin/env python3
"""LuxOS - razeni Launchpadu (luxos-launchpad) a lokalni pocitani spusteni aplikaci.

Launchpad je rofi (drun v combi). Rofi radi dlazdice podle sve historie (soubor rofi3.druncache
v adresari -cache-dir: radky "<pocet> <desktop-id>", v poradi souboru) a zbytek abecedne. Pro
kazdy zpusob razeni proto pripravime vlastni "historii" s pozadovanym poradim:

  alpha     Abecedne        - jen zarazka (vse abecedne podle rofi)
  recent    Naposledy pouzite - podle casu posledniho spusteni
  most      Nejpouzivanejsi - podle poctu spusteni (shoda: novejsi drive)
  category  Podle kategorie - Internet, Kancelar, Grafika, ... a v kategorii abecedne

Zarazka "0 luxos-launchpad-sentinel" drzi nejmensi hodnotu 0, takze rofi pri ulozeni nic
neposune; spustena aplikace ma po zavreni rofi o 1 vic (nebo je v souboru nove) - tak se pozna,
co uzivatel spustil, a zapise se do ~/.local/share/luxos/launchpad-usage.json (jen id aplikaci,
pocty a casy, nikam se neposila).

  luxos_launchpad.py order MODE OUT        pripravit historii pro rofi
  luxos_launchpad.py record BEFORE AFTER   zapsat spusteni a obnovit pripravene poradi
"""
import json
import locale
import os
import sys
import tempfile
import time

MODES = ("alpha", "recent", "most", "category")
DEFAULT_MODE = "most"
SENTINEL = "luxos-launchpad-sentinel"
# hlavni kategorie freedesktop v poradi Launchpadu (ostatni na konci)
CATEGORY_ORDER = ("Network", "Office", "Graphics", "AudioVideo", "Development", "Education",
                  "Game", "Science", "Utility", "Settings", "System")


def data_dir():
    return os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "luxos")


def cache_dir():
    return os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "luxos")


def usage_path():
    return os.path.join(data_dir(), "launchpad-usage.json")


def order_path(mode):
    return os.path.join(cache_dir(), "launchpad-order-" + mode)


def write_atomic(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def read_history(path):
    """rofi historie -> {desktop-id: pocet} (poradi souboru zachovano)."""
    out = {}
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                num, _, name = line.rstrip("\n").partition(" ")
                if name:
                    try:
                        out[name] = int(num)
                    except ValueError:
                        pass
    except OSError:
        pass
    return out


def load_usage():
    try:
        with open(usage_path(), encoding="utf-8") as f:
            data = json.load(f)
        apps = data.get("apps") if isinstance(data, dict) else None
        if isinstance(apps, dict):
            return {k: {"count": int(v.get("count", 0)), "last": int(v.get("last", 0))}
                    for k, v in apps.items() if isinstance(k, str) and isinstance(v, dict)}
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    # prvni spusteni: prevzit pocty z puvodni historie rofi (Launchpad dosud radil podle ni)
    old = read_history(os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"),
                                    "rofi3.druncache"))
    return {k: {"count": max(int(v), 1), "last": 0} for k, v in old.items() if k != SENTINEL}


def save_usage(apps):
    write_atomic(usage_path(), json.dumps({"version": 1, "apps": apps}, indent=1, sort_keys=True) + "\n")


def _lang_keys():
    lang = os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES") or os.environ.get("LANG") or ""
    lang = lang.split(".")[0].split("@")[0]
    keys = []
    if lang:
        keys.append("Name[%s]" % lang)
        if "_" in lang:
            keys.append("Name[%s]" % lang.split("_")[0])
    keys.append("Name")
    return keys


def desktop_apps():
    """{desktop-id: (hlavni kategorie, jmeno)} jako drun: uzivatelske prvni, pak systemove."""
    dirs = [os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "applications")]
    for d in (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":"):
        if d:
            dirs.append(os.path.join(d, "applications"))
    keys = _lang_keys()
    apps = {}
    for root in dirs:
        for base, _subdirs, files in os.walk(root, followlinks=True):
            for fn in files:
                if not fn.endswith(".desktop"):
                    continue
                path = os.path.join(base, fn)
                did = os.path.relpath(path, root).replace("/", "-")
                if did in apps:
                    continue
                fields = {}
                try:
                    with open(path, encoding="utf-8", errors="replace") as f:
                        group = None
                        for line in f:
                            line = line.strip()
                            if line.startswith("["):
                                group = line
                                continue
                            if group == "[Desktop Entry]" and "=" in line:
                                k, v = line.split("=", 1)
                                fields.setdefault(k.strip(), v.strip())
                except OSError:
                    continue
                cats = [c for c in fields.get("Categories", "").split(";") if c]
                main = next((c for c in CATEGORY_ORDER if c in cats), "")
                name = next((fields[k] for k in keys if fields.get(k)), did)
                apps[did] = (main, name)
    return apps


def order_ids(mode, usage):
    """desktop-id v poradi pro dany zpusob razeni (nepouzite aplikace doplni rofi abecedne)."""
    if mode == "recent":
        used = [k for k, v in usage.items() if v["last"] > 0]
        return sorted(used, key=lambda k: (-usage[k]["last"], k))
    if mode == "most":
        used = [k for k, v in usage.items() if v["count"] > 0]
        return sorted(used, key=lambda k: (-usage[k]["count"], -usage[k]["last"], k))
    if mode == "category":
        try:
            locale.setlocale(locale.LC_COLLATE, "")
        except locale.Error:
            pass
        rank = {c: i for i, c in enumerate(CATEGORY_ORDER)}
        apps = desktop_apps()
        return sorted(apps, key=lambda k: (rank.get(apps[k][0], len(rank)),
                                           locale.strxfrm(apps[k][1].casefold()), k))
    return []


def history_text(ids):
    n = len(ids)
    lines = ["%d %s" % (n - i, did) for i, did in enumerate(ids)]
    lines.append("0 " + SENTINEL)
    return "\n".join(lines) + "\n"


def write_order(mode, out, usage=None):
    if mode not in MODES:
        mode = DEFAULT_MODE
    if usage is None:
        usage = load_usage()
    write_atomic(out, history_text(order_ids(mode, usage)))


def launched(before, after):
    """desktop-id spustene aplikace (pocet o 1 vyssi nebo nova polozka), jinak None."""
    for k, v in after.items():
        if k != SENTINEL and v > before.get(k, 0):
            return k
    return None


def record(before_path, after_path, now=None):
    app = launched(read_history(before_path), read_history(after_path))
    if app is None:
        return None
    usage = load_usage()
    entry = usage.setdefault(app, {"count": 0, "last": 0})
    entry["count"] += 1
    entry["last"] = int(now if now is not None else time.time())
    save_usage(usage)
    # pripravene poradi pro dalsi otevreni (Launchpad pak jen kopiruje soubor)
    for mode in ("recent", "most"):
        write_order(mode, order_path(mode), usage)
    return app


def main(argv):
    if len(argv) == 4 and argv[1] == "order":
        write_order(argv[2], argv[3])
        return 0
    if len(argv) == 4 and argv[1] == "record":
        record(argv[2], argv[3])
        return 0
    sys.stderr.write("usage: luxos_launchpad.py order MODE OUT | record BEFORE AFTER  (used by luxos-launchpad)\n")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
