#!/usr/bin/env python3
"""LuxOS - katalog aplikaci LuxOS pro Obchod (sekce Aplikace LuxOS).

Aplikace deklaruji samy baliky LuxOS svymi soubory .desktop v /usr/share/applications:
  - aplikace je kazdy .desktop typu Application v balicku LuxOS (repozitar [luxos-apps] cely,
    z [luxos] jen vlastni baliky lux*); prevzate baliky Archu (vte3, rofi, xfwm4...) ani knihovny
    a dokumentace bez .desktop se nezobrazi
  - skryte (NoDisplay/Hidden), panely Nastaveni (Categories=Settings) a kopie pro Launchpad
    (*-launchpad.desktop) se nezobrazi
  - X-LuxOS-Store=show v .desktop: zobrazit i tak (napr. Ucet LuxAI, Tiskarny a skenery)
  - X-LuxOS-Store=hide: nezobrazit (soucast systemu, napr. Launchpad, Instalace LuxOS)
Nazev a popis jsou z Name/Comment vcetne prekladu Name[cs]...; chybejici preklad doplni Obchod
z luxos-i18n.

Katalog se generuje pri zverejneni repozitare z podepsanych baliku (scripts/publish-repo.sh,
pro ISO scripts/container-build.sh), takze Obchod zna i aplikace nenainstalovanych baliku:
  luxos_app_catalog.py generate KOREN_REPOZITARU  -> KOREN/apps.json a KOREN/app-icons/
Bez katalogu (offline, prvni spusteni) slozi Obchod stejny seznam z nainstalovanych baliku
(build_catalog nad jejich .desktop).
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile

FORMAT = 1
LANGS = ("cs", "sk", "pl", "uk", "hu", "de", "fr", "es", "it", "pt", "nl", "sv")
# Doporucene aplikace: v tomto poradi na zacatku seznamu (a v Objevovat), ostatni podle nazvu
FEATURED = ("luxai", "luxos-terminal", "luxos-text", "luxos-maps", "luxos-weather", "luxos-mail",
            "luxos-calculator", "luxdrop", "luxos-backup", "luxos-safe", "luxos-screenshot", "lsl-ide", "lux-code")
# Hlavni kategorie Obchodu (CATEGORIES v luxos-store); aplikace bez nich patri do System
STORE_CATEGORIES = ("Network", "Office", "Graphics", "AudioVideo", "Audio", "Video", "Development", "Game",
                    "Education", "Science", "Utility", "System")
APPS_DIR = "usr/share/applications/"
REPOS = ("luxos-apps", "luxos")      # poradi: pri stejnem desktop-id vyhrava [luxos-apps]
SYSTEM_PACKAGE = "luxos-desktop"


def is_luxos_package(name, repo):
    """Balik LuxOS s aplikacemi: cely [luxos-apps], z [luxos] jen vlastni baliky (lux*)."""
    if name.endswith("-debug"):
        return False
    return repo == "luxos-apps" or (repo == "luxos" and name.startswith("lux"))


def parse_desktop(text):
    """Klice skupiny [Desktop Entry] (ostatni skupiny, napr. [Desktop Action], se ignoruji)."""
    entry, group = {}, None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            group = line[1:-1]
            continue
        if group == "Desktop Entry" and "=" in line:
            k, v = line.split("=", 1)
            entry.setdefault(k.strip(), v.strip())
    return entry


def _true(value):
    return (value or "").strip().lower() == "true"


def _list(value):
    return [x for x in (value or "").split(";") if x]


def _localized(entry, key):
    out = {}
    for lang in LANGS:
        v = entry.get(f"{key}[{lang}]")
        if v:
            out[lang] = v
    return out


def app_from_desktop(desktop_id, text, pkg):
    """Zaznam katalogu pro .desktop balicku pkg, None = neni aplikace pro Obchod."""
    if desktop_id.endswith("-launchpad"):
        return None             # kopie panelu Nastaveni pro Launchpad (original rozhoduje sam)
    e = parse_desktop(text)
    if e.get("Type", "Application") != "Application" or not e.get("Name") or not e.get("Exec"):
        return None
    store = e.get("X-LuxOS-Store", "").strip().lower()
    if store == "hide":
        return None
    cats = _list(e.get("Categories"))
    if store != "show":
        if _true(e.get("NoDisplay")) or _true(e.get("Hidden")) or "Settings" in cats:
            return None
        only = _list(e.get("OnlyShowIn"))
        if only and not {"XFCE", "LuxOS"} & set(only):
            return None
    if _true(e.get("Hidden")):
        return None             # Hidden=true = smazana polozka, ani se show
    store_cats = [c for c in cats if c in STORE_CATEGORIES] or ["System"]
    app = {"id": desktop_id, "package": pkg, "name": e["Name"], "summary": e.get("Comment", ""),
           "icon": e.get("Icon", ""), "categories": store_cats}
    names, summaries = _localized(e, "Name"), _localized(e, "Comment")
    if names:
        app["names"] = names
    if summaries:
        app["summaries"] = summaries
    if desktop_id in FEATURED:
        app["featured"] = FEATURED.index(desktop_id) + 1
    return app


def sort_key(app, name=None):
    return (app.get("featured") or len(FEATURED) + 1, (name or app["name"]).lower())


def build_catalog(packages):
    """packages: [{"name", "repo", "version", "depends", "desktop": {desktop-id: text}}] -> katalog
    {"format", "apps": [...]}; jen baliky LuxOS, kazde desktop-id jednou. Aplikace balicku luxos-desktop
    a jeho zavislosti jsou soucast systemu ("system": vzdy nainstalovane, Obchod je nenabizi k odebrani)."""
    apps, seen = [], set()
    order = {r: i for i, r in enumerate(REPOS)}
    system = {SYSTEM_PACKAGE}
    for p in packages:
        if p["name"] == SYSTEM_PACKAGE:
            system |= {re.split(r"[<>=]", d, maxsplit=1)[0] for d in p.get("depends", [])}
    for p in sorted(packages, key=lambda p: (order.get(p.get("repo"), 9), p["name"])):
        if not is_luxos_package(p["name"], p.get("repo", "")):
            continue
        for did, text in sorted(p.get("desktop", {}).items()):
            if did in seen:
                continue
            app = app_from_desktop(did, text, p["name"])
            if app:
                seen.add(did)
                if p.get("version"):
                    app["version"] = p["version"]
                if p["name"] in system:
                    app["system"] = True
                apps.append(app)
    apps.sort(key=sort_key)
    return {"format": FORMAT, "apps": apps}


# ---- generovani z repozitare ------------------------------------------------
def read_repo_db(db_path):
    """Aktualni baliky z databaze repozitare (repo-add): [{"name", "version", "filename", "depends"}]."""
    out = []
    with tarfile.open(db_path) as tar:
        for m in tar.getmembers():
            if not m.isfile() or not m.name.endswith("/desc"):
                continue
            fields, key = {}, None
            for line in tar.extractfile(m).read().decode("utf-8", "replace").splitlines():
                if line.startswith("%") and line.endswith("%"):
                    key = line[1:-1]
                    fields.setdefault(key, [])
                elif line and key:
                    fields[key].append(line)
            first = {k: v[0] for k, v in fields.items() if v}
            if first.get("NAME") and first.get("FILENAME"):
                out.append({"name": first["NAME"], "version": first.get("VERSION", ""), "filename": first["FILENAME"],
                            "depends": fields.get("DEPENDS", [])})
    return sorted(out, key=lambda p: p["name"])


def _tar(args, path):
    return subprocess.run(["tar", "--zstd", *args, "-f", path], capture_output=True, check=True).stdout


ICON_RE = re.compile(r"^usr/share/(?:icons/[^/]+/(scalable|\d+x\d+)/apps|pixmaps)/([^/]+)\.(svg|png)$")


def _icon_rank(size, ext):
    """Nejlepsi ikona: SVG, pak nejvetsi PNG (aspon 64 px)."""
    if ext == "svg":
        return 100000
    if size and size != "scalable":
        return int(size.split("x")[0])
    return 1        # pixmaps bez velikosti


def generate(root, repos=REPOS):
    """Katalog z repozitaru v ROOT/<repo>/x86_64 -> ROOT/apps.json a ikony ROOT/app-icons/."""
    packages, icons = [], {}           # icons: nazev -> (rank, cesta baliku, clen archivu, pripona)
    for repo in repos:
        d = os.path.join(root, repo, "x86_64")
        db = os.path.join(d, f"{repo}.db.tar.gz")
        if not os.path.exists(db):
            continue
        for entry in read_repo_db(db):
            name = entry["name"]
            if not is_luxos_package(name, repo):
                continue
            path = os.path.join(d, entry["filename"])
            members = _tar(["-t"], path).decode("utf-8", "replace").splitlines()
            desktop = {}
            for m in members:
                if m.startswith(APPS_DIR) and m.endswith(".desktop") and "/" not in m[len(APPS_DIR):]:
                    desktop[m[len(APPS_DIR):-8]] = _tar(["-xO", m], path).decode("utf-8", "replace")
                mi = ICON_RE.match(m)
                if mi:
                    rank = _icon_rank(mi.group(1), mi.group(3))
                    if rank >= 64 or mi.group(1) is None:
                        if mi.group(2) not in icons or rank > icons[mi.group(2)][0]:
                            icons[mi.group(2)] = (rank, path, m, mi.group(3))
            packages.append({"name": name, "repo": repo, "version": entry["version"], "depends": entry["depends"],
                             "desktop": desktop})
    catalog = build_catalog(packages)
    icon_dir = os.path.join(root, "app-icons")
    shutil.rmtree(icon_dir, ignore_errors=True)      # ikony z drivejsiho behu (odebrane aplikace) pryc
    os.makedirs(icon_dir)
    for app in catalog["apps"]:
        found = icons.get(app.get("icon"))
        if found:
            _rank, path, member, ext = found
            fname = f"{app['icon']}.{ext}"
            with open(os.path.join(icon_dir, fname), "wb") as f:
                f.write(_tar(["-xO", member], path))
            app["icon_file"] = fname
    tmp = os.path.join(root, "apps.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(catalog, f, indent=1, ensure_ascii=False)
    os.replace(tmp, os.path.join(root, "apps.json"))
    return catalog


def load_catalog(text):
    """Katalog z JSON (overeni formatu); neplatny -> None."""
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if not isinstance(data, dict) or data.get("format") != FORMAT or not isinstance(data.get("apps"), list):
        return None
    apps = [a for a in data["apps"] if isinstance(a, dict) and a.get("id") and a.get("package") and a.get("name")]
    return {"format": FORMAT, "apps": apps}


def main(argv):
    if len(argv) == 2 and argv[0] == "generate":
        cat = generate(argv[1])
        print(f"LuxOS app catalog: {len(cat['apps'])} apps -> {os.path.join(argv[1], 'apps.json')}")
        return 0
    print("usage: luxos_app_catalog.py generate REPO_ROOT", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
