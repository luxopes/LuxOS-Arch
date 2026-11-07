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
z luxos-i18n. Dlouhy popis (odstavce a seznam vlastnosti ve vsech jazycich LuxOS) dodava balik souborem
AppStream /usr/share/metainfo/<desktop-id>.metainfo.xml (<description> s prvky xml:lang); snimky obrazovky
(scripts/store-screenshots -> packages/luxos-store/screens) se zverejni vedle katalogu v app-screens/.

Katalog se generuje pri zverejneni repozitare z podepsanych baliku (scripts/publish-repo.sh,
pro ISO scripts/container-build.sh), takze Obchod zna i aplikace nenainstalovanych baliku:
  luxos_app_catalog.py generate KOREN_REPOZITARU [--screens SLOZKA]
      -> KOREN/apps.json, KOREN/app-icons/ (a KOREN/app-screens/ podle SLOZKA/manifest.json)
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
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

FORMAT = 1
LANGS = ("cs", "sk", "pl", "uk", "hu", "de", "fr", "es", "it", "pt", "nl", "sv")
# Doporucene aplikace: v tomto poradi na zacatku seznamu (a v Objevovat), ostatni podle nazvu
FEATURED = ("luxai", "luxos-terminal", "luxos-text", "luxos-maps", "luxos-weather", "luxos-mail",
            "luxos-calculator", "luxdrop", "luxos-backup", "luxos-safe", "luxos-screenshot", "lsl-ide", "lux-code")
# Hlavni kategorie Obchodu (CATEGORIES v luxos-store); aplikace bez nich patri do System
STORE_CATEGORIES = ("Network", "Office", "Graphics", "AudioVideo", "Audio", "Video", "Development", "Game",
                    "Education", "Science", "Utility", "System")
APPS_DIR = "usr/share/applications/"
METAINFO_DIR = "usr/share/metainfo/"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
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


# ---- dlouhy popis (AppStream metainfo) ----------------------------------------
def _clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def _shape(blocks):
    return [("p",) if "p" in b else ("ul", len(b["ul"])) for b in blocks]


def parse_metainfo(text):
    """Soubor metainfo -> (desktop-id, {"en": bloky, "cs": bloky, ...}); bloky = [{"p": text} | {"ul": [text]}].
    Jazyk se prevezme jen s uplnym prekladem (stejne odstavce a polozky jako anglictina), jinak ma Obchod
    anglicky popis. Neplatny soubor -> (None, {})."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return None, {}
    did = None
    for lc in root.findall("launchable"):
        if lc.get("type") == "desktop-id" and (lc.text or "").strip().endswith(".desktop"):
            did = lc.text.strip()[:-8]
            break
    if not did and (root.findtext("id") or "").strip():
        did = root.findtext("id").strip()
        did = did[:-8] if did.endswith(".desktop") else did
    desc = root.find("description")
    if desc is None:
        return did, {}
    out = {}
    for lang in ("en",) + LANGS:
        want = None if lang == "en" else lang
        blocks = []
        for el in desc:
            if el.tag == "p" and el.get(XML_LANG) == want:
                t = _clean("".join(el.itertext()))
                if t:
                    blocks.append({"p": t})
            elif el.tag in ("ul", "ol"):
                items = [_clean("".join(li.itertext())) for li in el if li.tag == "li" and li.get(XML_LANG) == want]
                items = [i for i in items if i]
                if items:
                    blocks.append({"ul": items})
        if blocks:
            out[lang] = blocks
    if "en" not in out:
        return did, {}
    shape = _shape(out["en"])
    return did, {k: v for k, v in out.items() if k == "en" or _shape(v) == shape}


class _DescParser(HTMLParser):
    """Zjednodusene HTML popisu AppStream (p, ul/ol, li, em, code) -> bloky."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks, self.buf, self.items, self.in_list, self.in_li = [], [], [], False, False

    def flush(self):
        t = _clean("".join(self.buf))
        self.buf = []
        if t:
            self.blocks.append({"p": t})

    def handle_starttag(self, tag, attrs):
        if tag in ("ul", "ol"):
            self.flush()
            self.items, self.in_list = [], True
        elif tag == "li" and self.in_list:
            self.in_li, self.buf = True, []
        elif tag == "p" and not self.in_list:
            self.flush()

    def handle_endtag(self, tag):
        if tag == "li" and self.in_li:
            t = _clean("".join(self.buf))
            self.buf, self.in_li = [], False
            if t:
                self.items.append(t)
        elif tag in ("ul", "ol") and self.in_list:
            if self.items:
                self.blocks.append({"ul": self.items})
            self.items, self.in_list = [], False
        elif tag == "p" and not self.in_list:
            self.flush()

    def handle_data(self, data):
        if not self.in_list or self.in_li:
            self.buf.append(data)


def description_blocks(markup):
    """Popis AppStream (component.get_description(): <p>, <ul><li>...) -> bloky jako v katalogu."""
    p = _DescParser()
    p.feed(markup or "")
    p.close()
    p.flush()
    return p.blocks


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
    """packages: [{"name", "repo", "version", "depends", "desktop": {desktop-id: text},
    "metainfo": {soubor: text}}] -> katalog
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
        descriptions = {}
        for _f, text in sorted(p.get("metainfo", {}).items()):
            mdid, desc = parse_metainfo(text)
            if mdid and desc:
                descriptions[mdid] = desc
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
                if did in descriptions:
                    app["description"] = descriptions[did]
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


def add_screens(catalog, root, screens):
    """Snimky aplikaci ze slozky screens (manifest.json ze scripts/store-screenshots) -> ROOT/app-screens/<id>/
    a odkazy v katalogu (cesta vuci apps.json, rozmery, tmava varianta). Bez slozky zadne snimky."""
    out_dir = os.path.join(root, "app-screens")
    shutil.rmtree(out_dir, ignore_errors=True)
    if not screens:
        return
    try:
        with open(os.path.join(screens, "manifest.json"), encoding="utf-8") as f:
            manifest = json.load(f)
    except (OSError, ValueError):
        return
    if not isinstance(manifest, dict):
        return
    for app in catalog["apps"]:
        refs = []
        for e in manifest.get(app["id"]) or []:
            try:
                files = [os.path.basename(e["file"])]
                ref = {"url": f"app-screens/{app['id']}/{files[0]}", "width": int(e["width"]),
                       "height": int(e["height"])}
            except (KeyError, TypeError, ValueError):
                continue
            if e.get("dark"):
                files.append(os.path.basename(e["dark"]))
                ref["dark"] = f"app-screens/{app['id']}/{files[1]}"
            if not all(os.path.isfile(os.path.join(screens, app["id"], f)) for f in files):
                continue
            os.makedirs(os.path.join(out_dir, app["id"]), exist_ok=True)
            for f in files:
                shutil.copyfile(os.path.join(screens, app["id"], f), os.path.join(out_dir, app["id"], f))
            refs.append(ref)
        if refs:
            app["screenshots"] = refs


def generate(root, repos=REPOS, screens=None):
    """Katalog z repozitaru v ROOT/<repo>/x86_64 -> ROOT/apps.json, ikony ROOT/app-icons/ a snimky
    ROOT/app-screens/ (ze slozky screens)."""
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
            desktop, metainfo = {}, {}
            for m in members:
                if m.startswith(APPS_DIR) and m.endswith(".desktop") and "/" not in m[len(APPS_DIR):]:
                    desktop[m[len(APPS_DIR):-8]] = _tar(["-xO", m], path).decode("utf-8", "replace")
                if m.startswith(METAINFO_DIR) and m.endswith(".metainfo.xml") and "/" not in m[len(METAINFO_DIR):]:
                    metainfo[m[len(METAINFO_DIR):]] = _tar(["-xO", m], path).decode("utf-8", "replace")
                mi = ICON_RE.match(m)
                if mi:
                    rank = _icon_rank(mi.group(1), mi.group(3))
                    if rank >= 64 or mi.group(1) is None:
                        if mi.group(2) not in icons or rank > icons[mi.group(2)][0]:
                            icons[mi.group(2)] = (rank, path, m, mi.group(3))
            packages.append({"name": name, "repo": repo, "version": entry["version"], "depends": entry["depends"],
                             "desktop": desktop, "metainfo": metainfo})
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
    add_screens(catalog, root, screens)
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
    screens = None
    if len(argv) == 4 and argv[2] == "--screens":
        screens, argv = argv[3], argv[:2]
    if len(argv) == 2 and argv[0] == "generate":
        cat = generate(argv[1], screens=screens)
        described = sum(1 for a in cat["apps"] if a.get("description"))
        shots = sum(len(a.get("screenshots", [])) for a in cat["apps"])
        print(f"LuxOS app catalog: {len(cat['apps'])} apps ({described} with descriptions, {shots} screenshots)"
              f" -> {os.path.join(argv[1], 'apps.json')}")
        return 0
    print("usage: luxos_app_catalog.py generate REPO_ROOT [--screens DIR]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
