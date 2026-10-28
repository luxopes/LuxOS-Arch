#!/usr/bin/env python3
"""Kontrola a mereni databaze geocoderu: typicke dotazy pri psani (predpony nazvu), p50/p95, velikost.

    python3 scripts/geocoder/bench.py geocoder.sqlite [--mmap-mb 0] [--runs 1]

Konci chybou, kdyz kontrolni dotazy nenajdou ocekavane misto (napr. "praha" -> Praha).
"""
import argparse
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "server", "geocoder"))
import luxos_geocoder as G  # noqa: E402

CENTERS = {"praha": (50.08, 14.42), "brno": (49.19, 16.61), "ostrava": (49.83, 18.28),
           "bratislava": (48.15, 17.11), "kosice": (48.72, 21.26), "plzen": (49.74, 13.38)}
# co lide pisou do naseptavace: obce, ulice, adresy, zastavky, mista; kazde ve 3-4 delkach predpony
# (poradi zamichane podle delky, aby prvnich --count dotazu pokrylo vsechny texty)
TEXTS = [
    ("praha", "praha"), ("brno", "brno"), ("bratislava", "bratislava"), ("kosice", "košice"),
    ("praha", "náměstí míru"), ("praha", "václavské náměstí"), ("praha", "vodičkova 30"),
    ("praha", "karlovo náměstí"), ("praha", "anděl"), ("praha", "hlavní nádraží"), ("praha", "letiště"),
    ("praha", "národní muzeum"), ("praha", "pražský hrad"), ("praha", "vinohradská 12"),
    ("praha", "budějovická"), ("praha", "palmovka"), ("praha", "lidl"), ("praha", "kavárna"),
    ("brno", "masarykova"), ("brno", "hlavní nádraží"), ("brno", "česká"), ("brno", "kounicova 10"),
    ("brno", "špilberk"), ("ostrava", "stodolní"), ("ostrava", "nádraží svinov"), ("ostrava", "nová karolina"),
    ("bratislava", "obchodná"), ("bratislava", "hlavná stanica"), ("bratislava", "eurovea"),
    ("bratislava", "hodžovo námestie"), ("kosice", "hlavná 1"), ("kosice", "aupark"),
    ("plzen", "náměstí republiky"), ("plzen", "americká"), ("plzen", "pivovar"),
    ("praha", "olomouc"), ("brno", "znojmo"), ("praha", "český krumlov"), ("bratislava", "žilina"),
    ("kosice", "poprad"), ("praha", "karlštejn"), ("praha", "sněžka"), ("praha", "nam miru"),
    ("brno", "namesti svobody"), ("praha", "na příkopě 22"), ("praha", "štefánikova"),
    ("praha", "u kalicha"), ("ostrava", "dolní vítkovice"), ("plzen", "škoda"), ("brno", "mendlovo"),
]
CHECKS = [("praha", None, "Praha"), ("brno", None, "Brno"), ("bratislava", None, "Bratislava"),
          ("namesti miru", CENTERS["praha"], "Náměstí Míru"), ("kosice", None, "Košice")]


def queries():
    out = []
    for n in (3, 4, 6, 9, None):
        for city, text in TEXTS:
            if n is None or n < len(text):
                out.append((text[:n] if n else text, CENTERS[city]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("db")
    ap.add_argument("--mmap-mb", type=int, default=0)
    ap.add_argument("--runs", type=int, default=1, help="repeat (warm cache)")
    ap.add_argument("--count", type=int, default=200, help="queries per run")
    a = ap.parse_args()
    s = G.Searcher(a.db, a.mmap_mb)
    bad = 0
    for q, c, want in CHECKS:
        res = s.search(G.Query(q, *(c or (None, None))))
        got = res[0]["properties"].get("name") if res else None
        print(f"check {q!r}: {got!r}" + ("" if got == want else f"  EXPECTED {want!r}"))
        bad += got != want
    qs = queries()[:a.count]
    times = []
    for _ in range(a.runs):
        for q, c in qs:
            t0 = time.perf_counter()
            s.search(G.Query(q, c[0], c[1], limit=7, lang="cs"))
            times.append((time.perf_counter() - t0) * 1000)
    times.sort()
    p = lambda f: times[min(len(times) - 1, int(f * len(times)))]  # noqa: E731
    print(f"{len(times)} queries: p50 {p(0.5):.1f} ms, p95 {p(0.95):.1f} ms, max {times[-1]:.1f} ms, "
          f"mean {statistics.mean(times):.1f} ms")
    print(f"database: {os.path.getsize(a.db) / 1e6:.0f} MB, {s.meta.get('features')} features, data {s.meta.get('data')}")
    try:
        with open("/proc/self/status") as f:
            print(" ".join(l.split()[0] + l.split()[1] + "kB" for l in f if l.startswith(("VmRSS", "VmHWM"))))
    except OSError:
        pass
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
