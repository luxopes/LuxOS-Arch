#!/usr/bin/env python3
"""LuxOS - sestaveni webu https://luxos.lux-ai.cz do out/site (nahrava scripts/publish-site.sh).

  scripts/build-site.py

Dva jazyky: anglictina v korenu (/), cestina pod /cs/. Zdroje: site/ (sablony uvodni stranky
home.en.html a home.cs.html, styly, skript, obrazky), site/iso.json (posledni ISO - meni se jen
s novym ISO), verze z packages/luxos-branding/files/version, dokumentace z luxos-docs
(packages/apps/luxos-docs/docs, stejna jako offline v LuxOS) doplnena strankami z site/content
(LuxAI, Lux Code, hardware, zkratky, FAQ; cs/ = ceske verze), seznam zmen z CHANGELOG.md
(cesky) a jeho anglicky preklad site/content/en/changes/ (soubor na vydani, scripts/changelog_sections.py),
stranka o pouzivani (countme) ze sablon usage.en.html a usage.cs.html (grafy kresli usage.js
z /stats/usage.json, ktery vytvari server), stranky Posty LuxOS, zasad ochrany soukromi a podminek
ze site/pages (mail, privacy, terms), stranky pro konkretni hledani a stranka Stahnout ze site/landing
(pages.json: adresy, titulky, popisy; Windows 10, Linux jako macOS, starsi pocitace, skoly, srovnani).
Vystup: index.html, cs/index.html, release.json (aktualni vydani, nacita ho i stranka), docs/,
cs/docs/, changes/, cs/zmeny/, usage/, cs/pouzivani/, mail/, privacy/, terms/ (+ cs/), download/ a cs/stahnout/
(stranka Stahnout; ISO a podpisy lezi na serveru vedle ni v /download/), compare/ a cs/srovnani/, sitemap.xml,
robots.txt, llms.txt, llms-full.txt, klic IndexNow (<klic>.txt), announcements.json (kanal aplikace Novinky
LuxOS ze site/announcements.json, docs/developers/announcements.md). Titulky nejvyse 60 a rucne psane popisy
nejvyse 155 znaku (jinak sestaveni skonci chybou). Kontrola: scripts/check-site.py.
"""
import datetime
import html
import json
import os
import posixpath
import re
import shutil
import subprocess
import sys
import time

import markdown

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import changelog_sections  # noqa: E402
import site_html  # noqa: E402
import site_seo  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, "site")
CONTENT = os.path.join(SITE, "content")
OUT = os.path.join(ROOT, "out", "site")
DOCS = os.path.join(ROOT, "packages", "apps", "luxos-docs", "docs")
BASE = "https://luxos.lux-ai.cz"
FINGERPRINT = "FD18 5DAB 7701 40E8 9C37 275E 7035 CFDF DCA6 C991"
LANGS = ("en", "cs")
OTHER = {"en": "cs", "cs": "en"}
# nahled odkazu (1200x630 JPEG - WebP nekteri klienti v nahledech neukazi):: obrazek s logem, nazvem a plochou (scripts/site-og/render-og.sh), cestina ma vlastni text
OG_IMAGE = {"en": BASE + "/assets/og-image.jpg", "cs": BASE + "/assets/og-image-cs.jpg"}
OG_ALT = {"en": "LuxOS – fast, lightweight Linux with a macOS-like desktop, free download",
          "cs": "LuxOS – rychlý a lehký Linux s prostředím jako macOS, ke stažení zdarma"}
# stranky pro konkretni hledani (Windows 10, macOS, starsi pocitace, skoly, srovnani, stazeni): site/landing
LANDING = os.path.join(SITE, "landing")
# strukturovana data (schema.org): entity s @id definuje uvodni stranka (@graph), ostatni stranky na ne odkazuji
GITHUB = "https://github.com/luxopes/LuxOS-Arch"
# Komunita LuxOS na Discordu (trvala pozvanka do #welcome-and-rules)
DISCORD = "https://discord.gg/FFpaF7Ayp"
ORG_ID, AUTHOR_ID, SITE_ID, APP_ID = (BASE + "/#org", BASE + "/#author", BASE + "/#website", BASE + "/#luxos")
CONTACT = "info@lux-ai.cz"
AUTHOR = "Antonín Tomeček"
# IndexNow (Bing, Seznam, Yandex): verejny klic, web ho publikuje jako /<klic>.txt; odeslani URL po zverejneni
# dela vlastnik scripts/indexnow-submit.sh
INDEXNOW_KEY_FILE = os.path.join(SITE, "indexnow-key.txt")
# llms.txt (llmstxt.org): prehled pro jazykove modely; llms-full.txt = vybrane anglicke stranky v jednom souboru
LLMS_FULL_DOCS = ("luxos/faq.md", "luxos/compare.md", "luxos/overview.md", "luxos/hardware.md", "luxos/installer.md",
                  "luxos/package-management.md", "luxos/care-updates.md", "luxos/guard.md", "luxos/luxai.md")
# logo LuxOS ze systemu (packages/luxos-branding/files/logo/luxos-logo.svg, tri zahnute cepele); oriznute
# na tvar (viewBox), barvy prechodu z CSS (--logo-1..3: svetly a tmavy vzhled), vlozene primo do stranky
LOGO_PATH = ("M246.27 209.91C188.18 163.23 147.07 104.71 133.55 30.45C116.12 140.58 158.36 161.65 246.27 209.91Z"
             "M8.09 211.18C89.02 173.90 133.08 136.86 126.09 40.64C105.95 110.22 62.88 165.17 8.09 211.18Z"
             "M248.64 226.09C158.26 151.17 105.77 146.57 13.73 222.82C95.86 182.21 167.60 183.49 248.64 226.09Z")
# Stranky Posty LuxOS a pravni stranky (overeni aplikace OAuth u Googlu: domovska stranka aplikace,
# zasady ochrany soukromi a podminky na overene domene). Sablony site/pages/<nazev>.<jazyk>.html,
# datum posledni zmeny zasad a podminek se meni rucne (s obsahem).
LEGAL_UPDATED = "2026-11-19"
PAGES = ("mail", "privacy", "terms")

MONTHS_CS = ["ledna", "února", "března", "dubna", "května", "června", "července", "srpna", "září",
             "října", "listopadu", "prosince"]
MONTHS_EN = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
             "October", "November", "December"]

# Galerie: snimky cele plochy ze scripts/site-screenshots (svetly i tmavy vzhled, prepina se s webem);
# <nazev>-<light|dark>{-small,-960,}.webp = 640, 960 a 1920 px; cestina ma vlastni snimky v shots/cs/
GALLERY = {
    "cs": [
        ("launchpad", "Launchpad – všechny aplikace a dotaz pro LuxAI"),
        ("control-center", "Ovládací centrum"),
        ("files", "Soubory"),
        ("store", "Obchod LuxOS – aplikace jedním kliknutím"),
        ("weather", "Počasí"),
        ("luxai", "LuxAI – asistent, který rozumí vašemu počítači"),
        ("terminal", "Terminál"),
        ("settings", "Nastavení"),
        ("calendar", "Kalendář z horní lišty"),
    ],
    "en": [
        ("launchpad", "Launchpad – all apps and a question box for LuxAI"),
        ("control-center", "Control Center"),
        ("files", "Files"),
        ("store", "LuxOS Store – apps in one click"),
        ("weather", "Weather"),
        ("luxai", "LuxAI – an assistant that understands your computer"),
        ("terminal", "Terminal"),
        ("settings", "Settings"),
        ("calendar", "Calendar from the top bar"),
    ],
}
SHOT_SIZES = (("-small", 640), ("-960", 960), ("", 1920))

# texty rozhrani (hlavicka, paticka, dokumentace)
T = {
    "en": {
        "locale": "en_US", "home": "Home", "features": "Features", "gallery": "Gallery",
        "download": "Download", "docs": "Documentation", "changes": "Changes", "luxai": "LuxAI",
        "faq": "FAQ", "repos": "Repositories", "kernel": "Kernel on GitHub",
        "hero_alt": "LuxOS desktop with the Dock and the top bar", "home_aria": "LuxOS – home", "main_nav": "Main navigation", "mobile_nav": "Mobile navigation",
        "theme": "Switch between light and dark mode", "menu": "Open menu", "skip": "Skip to content",
        "lang_label": "Language", "docs_aria": "Documentation", "docs_h1": "Documentation",
        "docs_lead": ("The LuxOS manual: the same pages LuxOS ships offline (package luxos-docs) and "
                      "that LuxAI reads, with extra guides for LuxAI, Lux Code, hardware, shortcuts and the FAQ. "
                      "The documentation is in English."),
        "crumb_home": "LuxOS", "crumb_docs": "Documentation", "prev": "Previous", "next": "Next",
        "title_suffix": "LuxOS", "docs_suffix": "LuxOS documentation",
        "docs_suffixes": (" – LuxOS documentation", " – LuxOS docs", " | LuxOS"),
        # titulek a popis seznamu zmen: hlavni novinky posledniho vydani (pri novem vydani prepsat)
        "changes_title": "LuxOS {version} – What's new: safer backups, more privacy",
        "changes_desc": ("Changelog of every LuxOS release. {version} “{codename}”: hundreds of fixes from a full audit, "
                         "safer backups, safe install next to Windows and more privacy."),
        "home_title": "LuxOS – free, fast Linux with a macOS-like desktop",
        "home_desc": "LuxOS is a free, lightweight Linux based on Arch with a macOS-like desktop, automatic drivers, undoable updates and the LuxAI assistant. Download the ISO.",
        "site_desc": ("LuxOS is a fast, lightweight Arch Linux based distribution with a macOS-like desktop, "
                      "the lux package manager, automatic drivers and the LuxAI assistant."),
        "landing_title": "LuxOS for you", "more_pages": "More about LuxOS", "compare_more": "More comparisons",
        "cta_title": "Try LuxOS {ISO_VERSION} for free", "cta_text": ("64-bit PC · ISO {ISO_SIZE} · try it from a USB stick "
                     "without installing. Back up your data before installing."),
        "cta_button": "Download LuxOS", "cta_secondary": "Installation guide",
        "sources": "Sources", "checked": "checked",
        "docs_index_title": "LuxOS documentation – LuxOS, LuxAI, Lux Code and LSL",
        "app_disambig": "Desktop Linux distribution based on Arch Linux, developed in the Czech Republic.",
        "docs_index_desc": "LuxOS manual: installation, the lux package manager, LuxAI, Lux Code, drivers, Store, Care, Guard, Safe, Sandbox, LuxDrop and the LSL language.",
        "gallery_label": "Screenshot", "close": "Close", "prev_shot": "Previous", "next_shot": "Next",
        "copy_https": "Copying works only over HTTPS.", "other_name": "Čeština",
        "doc_note_en": "", "footer_docs": "Documentation", "en_only": "EN",
        "en_only_title": "English only", "usage": "Usage",
        "usage_title": "LuxOS usage – weekly active computers and versions",
        "usage_desc": "How many computers run LuxOS each week, how many keep using it and which versions they run. Anonymous weekly counts: what is sent and how to turn it off.",
        "mail": "LuxOS Mail", "privacy": "Privacy", "terms": "Terms",
        "mail_crumb": "LuxOS Mail", "privacy_crumb": "Privacy Policy", "terms_crumb": "Terms of Use",
        "mail_title": "LuxOS Mail – light mail app for Gmail and any IMAP mailbox",
        "mail_desc": "LuxOS Mail is a light desktop mail app for LuxOS: Gmail, Microsoft and any IMAP mailbox, instant notifications, offline reading. Mail stays on your PC.",
        "privacy_title": "Privacy Policy – LuxOS and LuxOS Mail",
        "privacy_desc": ("How LuxOS and LuxOS Mail handle your data: Google user data stays on your computer, anonymous "
                         "countme, LuxAI account, feedback reports and your rights."),
        "terms_title": "Terms of Use – LuxOS and LuxOS Mail",
        "terms_desc": "Terms of use for LuxOS, LuxOS Mail and the other LuxOS apps: free software, no warranty, third-party services.",
    },
    "cs": {
        "locale": "cs_CZ", "home": "Domů", "features": "Funkce", "gallery": "Galerie",
        "download": "Stáhnout", "docs": "Dokumentace", "changes": "Změny", "luxai": "LuxAI",
        "faq": "Časté otázky", "repos": "Repozitáře", "kernel": "Jádro na GitHubu",
        "hero_alt": "Plocha LuxOS s Dockem a horní lištou", "home_aria": "LuxOS – domů", "main_nav": "Hlavní navigace", "mobile_nav": "Mobilní navigace",
        "theme": "Přepnout světlý a tmavý režim", "menu": "Otevřít nabídku", "skip": "Přejít na obsah",
        "lang_label": "Jazyk", "docs_aria": "Dokumentace", "docs_h1": "Dokumentace",
        "docs_lead": ("Příručka LuxOS: stejné stránky, jaké má LuxOS offline (balík luxos-docs) a ze kterých čerpá "
                      "i LuxAI, doplněné o návody k LuxAI, Lux Code, hardwaru, zkratkám a často kladené otázky. "
                      "Většina dokumentace je v angličtině (značka EN); české jsou stránky bez značky."),
        "crumb_home": "LuxOS", "crumb_docs": "Dokumentace", "prev": "Předchozí", "next": "Další",
        "title_suffix": "LuxOS", "docs_suffix": "Dokumentace LuxOS",
        "docs_suffixes": (" – Dokumentace LuxOS", " | LuxOS"),
        "changes_title": "LuxOS {version} – novinky: bezpečnější zálohy a soukromí",
        "changes_desc": ("Seznam změn všech verzí LuxOS. {version} „{codename}“: stovky oprav z úplné kontroly, bezpečnější "
                         "zálohy, bezpečná instalace vedle Windows a víc soukromí."),
        "home_title": "LuxOS – rychlý Linux zdarma s prostředím jako macOS",
        "home_desc": "LuxOS je lehký systém zdarma na Arch Linuxu: prostředí jako macOS, ovladače se najdou samy, aktualizace jdou vrátit, pomůže asistent LuxAI. Stáhněte ISO.",
        "site_desc": ("LuxOS je rychlý a lehký systém na Arch Linuxu s prostředím ve stylu macOS, správcem balíků lux, "
                      "automatickými ovladači a asistentem LuxAI."),
        "landing_title": "LuxOS pro vás", "more_pages": "Další o LuxOS", "compare_more": "Další srovnání",
        "cta_title": "Vyzkoušejte LuxOS {ISO_VERSION} zdarma", "cta_text": ("64bitové PC · ISO {ISO_SIZE} · vyzkoušíte ho z USB "
                     "disku bez instalace. Před instalací si zálohujte data."),
        "cta_button": "Stáhnout LuxOS", "cta_secondary": "Návod k instalaci",
        "sources": "Zdroje", "checked": "ověřeno",
        "docs_index_title": "Dokumentace LuxOS – příručka k LuxOS, LuxAI, Lux Code a LSL",
        "app_disambig": "Desktopová linuxová distribuce založená na Arch Linuxu, vyvíjená v Česku.",
        "docs_index_desc": "Příručka LuxOS: instalace, správce balíků lux, LuxAI, Lux Code, ovladače, Obchod, Care, Guard, Trezor, Sandbox, LuxDrop a jazyk LSL.",
        "gallery_label": "Snímek obrazovky", "close": "Zavřít", "prev_shot": "Předchozí", "next_shot": "Další",
        "copy_https": "Kopírování funguje jen přes HTTPS.", "other_name": "English",
        "doc_note_en": "", "footer_docs": "Dokumentace", "en_only": "EN",
        "en_only_title": "Pouze anglicky", "usage": "Používání LuxOS",
        "usage_title": "Používání LuxOS – aktivní počítače, verze a věrnost",
        "usage_desc": ("Kolik počítačů každý týden používá LuxOS, kolik lidí u něj zůstává a jaké verze mají. "
                       "Anonymní týdenní součty (countme): co se odesílá a jak to vypnout."),
        "mail": "Pošta LuxOS", "privacy": "Soukromí", "terms": "Podmínky",
        "mail_crumb": "Pošta LuxOS", "privacy_crumb": "Zásady ochrany soukromí", "terms_crumb": "Podmínky použití",
        "mail_title": "Pošta LuxOS – lehká poštovní aplikace pro Gmail a IMAP",
        "mail_desc": "Pošta LuxOS je lehká poštovní aplikace pro LuxOS: Gmail, Microsoft i jakákoli schránka IMAP, okamžitá upozornění, čtení offline. Pošta zůstává u vás.",
        "privacy_title": "Zásady ochrany soukromí – LuxOS a Pošta LuxOS",
        "privacy_desc": ("Jak LuxOS a Pošta LuxOS zacházejí s daty: data uživatelů Google zůstávají ve vašem počítači, anonymní "
                         "countme, účet LuxAI, hlášení chyb a vaše práva."),
        "terms_title": "Podmínky použití – LuxOS a Pošta LuxOS",
        "terms_desc": "Podmínky použití LuxOS, Pošty LuxOS a dalších aplikací LuxOS: svobodný software, bez záruky, služby třetích stran.",
    },
}

SITEMAP = []      # (cesta, {jazyk: cesta}) vsech indexovatelnych stranek
SOURCES = {}      # cesta -> zdrojove soubory stranky (lastmod v sitemap.xml podle posledniho commitu)
PAGE_COUNT = {"en": 0, "cs": 0}


# ---- pomocne funkce ----

def read_kv(path):
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"')
    return out


def fmt_date(iso, lang):
    y, m, d = (int(x) for x in iso.split("-"))
    return f"{d}. {MONTHS_CS[m - 1]} {y}" if lang == "cs" else f"{d} {MONTHS_EN[m - 1]} {y}"


def fmt_size(n, lang):
    # desetinne GB jako v instalatoru a ve spravci souboru (2 ** 30 by byly GiB)
    s = f"{n / 1e9:.1f}"
    return (s.replace(".", ",") if lang == "cs" else s) + " GB"


def clip(text, n=site_seo.DESC_MAX):
    """Popis do meta description: nejvyse n znaku, rez na hranici slova."""
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= n:
        return text
    cut = text[:n - 1].rsplit(" ", 1)[0].rstrip(",;:-–")
    return cut + "…"


def logo_svg(uid, cls="logo"):
    """Logo LuxOS jako vlozene SVG (barvy z CSS podle vzhledu); uid = jedinecne id prechodu na strance."""
    return (f'<svg class="{cls}" viewBox="4 26 249 204" aria-hidden="true" focusable="false">'
            f'<defs><linearGradient id="lg-{uid}" gradientUnits="userSpaceOnUse" x1="40" y1="30" x2="225" y2="230">'
            '<stop offset="0" class="ls1"/><stop offset=".5" class="ls2"/><stop offset="1" class="ls3"/>'
            f'</linearGradient></defs><path fill="url(#lg-{uid})" d="{LOGO_PATH}"/></svg>')


def shot_dir(lang):
    """Snimky galerie a notebooku: cestina ze shots/cs/, pokud tam jsou (jinak anglicke)."""
    if lang != "en" and os.path.isdir(os.path.join(SITE, "assets", "shots", lang)):
        return f"/assets/shots/{lang}/"
    return "/assets/shots/"


def shot_srcset(base, name, variant, sizes=SHOT_SIZES):
    return ", ".join(f"{base}{name}-{variant}{suffix}.webp {w}w" for suffix, w in sizes)


def favicon_ico(png_path):
    """/favicon.ico (prohlizece a ctecky se na nej ptaji i bez odkazu): ICO s jednim obrazkem PNG 32x32."""
    import struct
    with open(png_path, "rb") as f:
        png = f.read()
    return struct.pack("<HHH", 0, 1, 1) + struct.pack("<BBBBHHII", 32, 32, 0, 0, 1, 32, len(png), 22) + png


def write(rel, text):
    path = os.path.join(OUT, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def home_url(lang):
    return "/" if lang == "en" else "/cs/"


def docs_index_url(lang):
    return "/docs/" if lang == "en" else "/cs/docs/"


def changes_url(lang):
    return "/changes/" if lang == "en" else "/cs/zmeny/"


def soon_url(lang):
    """Co je zatim jen v testovacim kanalu staging (sekce „Připravuje se“ z CHANGELOG.md)."""
    return "/changes/coming-soon/" if lang == "en" else "/cs/zmeny/pripravuje-se/"


def usage_url(lang):
    return "/usage/" if lang == "en" else "/cs/pouzivani/"


def page_url(lang, name):
    """Stranky site/pages: /mail/, /privacy/, /terms/ (cs: /cs/mail/ ...)."""
    return ("/" if lang == "en" else "/cs/") + name + "/"


def doc_url(lang, path):
    """path = 'luxos/luxai.md' -> /docs/luxos/luxai.html (cs: /cs/docs/...)."""
    return ("/docs/" if lang == "en" else "/cs/docs/") + path[:-3] + ".html"


def abs_url(path):
    return BASE + path


def e(s):
    return html.escape(s, quote=True)


# ---- dokumenty ----

def load_docs():
    """Seznam dokumentu: index.json z luxos-docs + stranky navic z site/content/docs.json."""
    with open(os.path.join(DOCS, "index.json"), encoding="utf-8") as f:
        index = json.load(f)
    with open(os.path.join(CONTENT, "docs.json"), encoding="utf-8") as f:
        docs_json = json.load(f)
    extras = docs_json["files"]
    # ceske nazvy a popisy stranek z luxos-docs, ktere maji ceskou verzi (site/content/cs/<cesta>)
    cs_meta = docs_json.get("cs", {})
    # vlastni titulky stranek do vysledku hledani ({cesta: {jazyk: titulek}}, nejvyse 60 znaku)
    seo = docs_json.get("seo_title", {})
    cols = []
    for col in index["collections"]:
        files = []
        for d in col["files"]:
            cs = cs_meta.get(d["path"], {})
            files.append({"path": d["path"], "title": {"en": d["title"], "cs": cs.get("title", d["title"])},
                          "summary": {"en": d.get("summary", ""), "cs": cs.get("summary", d.get("summary", ""))},
                          "src": {"en": os.path.join(DOCS, d["path"])}, "seo_title": seo.get(d["path"], {}),
                          # popisy psane pro web (docs.json) musi mit do 155 znaku, popisy z luxos-docs se zkrati
                          "own_summary": {"cs"} if "summary" in cs else set()})
        cols.append({"id": col["id"], "title": col["title"], "files": files})
    for x in extras:
        col = next(c for c in cols if c["id"] == x["path"].split("/")[0])
        item = {"path": x["path"], "title": x["title"], "summary": x["summary"], "src": {},
                "seo_title": seo.get(x["path"], {}), "own_summary": set(LANGS)}
        for lang in LANGS:
            p = os.path.join(CONTENT, lang, x["path"])
            if os.path.isfile(p):
                item["src"][lang] = p
        pos = next(i for i, d in enumerate(col["files"]) if d["path"] == x["after"]) + 1
        col["files"].insert(pos, item)
    # ceske verze ostatnich stranek, pokud existuji (site/content/cs/<soubor>.md pod stejnou cestou)
    for col in cols:
        for d in col["files"]:
            p = os.path.join(CONTENT, "cs", d["path"])
            if "cs" not in d["src"] and os.path.isfile(p):
                d["src"]["cs"] = p
    return cols


def gh_slug(value, sep):
    """Kotvy nadpisu jako na GitHubu (odkazy v dokumentaci je tak pocitaji: 'rang / range' -> rang--range)."""
    return re.sub(r"[^\w\s-]", "", value.lower()).strip().replace(" ", sep)


def make_md_to_html(known):
    """Markdown -> HTML; odkazy na dokumenty (.md i .html) vedou na stranky webu v jazyce stranky,
    kdyz ceska verze neexistuje, na anglickou."""
    def conv(text, cur_path, lang):
        out = markdown.markdown(text, extensions=["tables", "fenced_code", "sane_lists", "toc"],
                                extension_configs={"toc": {"slugify": gh_slug}}, output_format="html")
        out = site_html.escape_unknown_tags(out)  # zastupny text <jméno> mimo kod jinak zmizi

        def fix(m):
            href = m.group(2)
            if re.match(r"^[a-z]+:", href) or href.startswith(("#", "/")):
                return m.group(0)
            path, _sep, frag = href.partition("#")
            if path.endswith((".md", ".html")) and cur_path:
                target = posixpath.normpath(posixpath.join(posixpath.dirname(cur_path), path[:path.rindex(".")] + ".md"))
                if target in known:
                    use = lang if lang in known[target]["src"] else "en"
                    path = doc_url(use, target)
                    return f'{m.group(1)}{path}{"#" + frag if frag else ""}"'
            if path.endswith(".md"):
                path = path[:-3] + ".html"
            return f'{m.group(1)}{path}{"#" + frag if frag else ""}"'
        return re.sub(r'(<a href=")([^"]+)"', fix, out)
    return conv


# ---- spolecny layout ----

def hreflang_links(alt):
    out = []
    for lang in LANGS:
        if lang in alt:
            out.append(f'  <link rel="alternate" hreflang="{lang}" href="{abs_url(alt[lang])}">')
    default = alt.get("en") or next(iter(alt.values()))
    out.append(f'  <link rel="alternate" hreflang="x-default" href="{abs_url(default)}">')
    return "\n".join(out)


def org_ref():
    """Vydavatel na podstrankach: odkaz na Organization z @graph uvodni stranky (s nazvem pro ctecky bez grafu)."""
    return {"@type": "Organization", "@id": ORG_ID, "name": "LuxOS", "url": BASE + "/"}


def git_date(files, fallback):
    """Datum posledniho commitu, ktery menil nektery ze souboru (YYYY-MM-DD); necommitovane zmeny = fallback."""
    files = [f for f in files if f and os.path.exists(f)]
    if not files:
        return fallback
    try:
        dirty = subprocess.run(["git", "-C", ROOT, "status", "--porcelain", "--", *files],
                               capture_output=True, text=True, encoding="utf-8", check=True).stdout.strip()
        if dirty:
            return fallback
        out = subprocess.run(["git", "-C", ROOT, "log", "-1", "--format=%cs", "--", *files],
                             capture_output=True, text=True, encoding="utf-8", check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return fallback
    return out or fallback


def jsonld(*items):
    return "\n".join('  <script type="application/ld+json">' + json.dumps(i, ensure_ascii=False, separators=(",", ":"))
                     .replace("</", "<\\/") + "</script>" for i in items)


def shell(lang, path, title, desc, body, alt, active="", stamp="", og_type="website", ld=(), home=False, desc_exact=True,
          switch_to=None, noindex=False, sitemap=True, dialog=False, scripts=(), src=()):
    """Cela stranka: hlavicka se SEO znackami, navigace s prepinacem jazyka, obsah, paticka."""
    t = T[lang]
    other = OTHER[lang]
    full_title = title
    # rucne psane titulky a popisy se nezkracuji: delsi nez ukaze Google = chyba sestaveni (opravit text)
    if len(title) > site_seo.TITLE_MAX:
        sys.exit(f"build-site: {path}: title longer than {site_seo.TITLE_MAX} characters: {title}")
    if desc_exact and len(re.sub(r"\s+", " ", desc).strip()) > site_seo.DESC_MAX:
        sys.exit(f"build-site: {path}: description longer than {site_seo.DESC_MAX} characters: {desc}")
    canon = abs_url(path)
    hu = home_url(lang)

    def nav_href(anchor):
        return anchor if home else hu + anchor

    items = [("home", t["home"], "#top" if home else hu),
             ("features", t["features"], nav_href("#features")),
             ("gallery", t["gallery"], nav_href("#gallery")),
             ("download", t["download"], landing_url(lang, "download")),
             ("luxai", t["luxai"], doc_url(lang if lang in DOCS_BY_PATH["luxos/luxai.md"]["src"] else "en", "luxos/luxai.md")),
             ("docs", t["docs"], docs_index_url(lang)),
             ("changes", t["changes"], changes_url(lang)),
             ("discord", "Discord", DISCORD)]
    def is_active(k):
        return k == active or (home and k == "home" and not active)
    desk = "".join('<a%s href="%s">%s</a>' % (' class="active"' if is_active(k) else "", h, e(label))
                   for k, label, h in items)
    mobile = "".join(f'<a href="{h}">{e(label)}</a>' for _k, label, h in items)

    sw_target = switch_to or (alt.get(other) if alt.get(other) else home_url(other))
    cur_lang_tag = lang.upper()
    other_tag = other.upper()
    # pevne poradi EN | CS (aktivni zvyrazneni pak muze plynule prejet na druhy jazyk, script.js)
    sw_links = {lang: f'<a href="{path}" lang="{lang}" hreflang="{lang}" aria-current="true">{cur_lang_tag}</a>',
                other: f'<a href="{sw_target}" lang="{other}" hreflang="{other}" title="{e(t["other_name"])}" rel="alternate">{other_tag}</a>'}
    switch = (f'<span class="lang-switch" role="group" aria-label="{e(t["lang_label"])}" data-active="{LANGS.index(lang)}">'
              + "".join(sw_links[l] for l in LANGS) + '<span class="lang-pill" aria-hidden="true"></span></span>')

    robots = '  <meta name="robots" content="noindex, follow">\n' if noindex else '  <meta name="robots" content="index, follow, max-image-preview:large">\n'
    og_alt = "".join(f'  <meta property="og:locale:alternate" content="{T[l]["locale"]}">\n' for l in LANGS if l != lang and l in alt)
    foot_links = (f'<a href="{docs_index_url(lang)}">{e(t["footer_docs"])}</a>'
                  f'<a href="{doc_url(lang if lang in DOCS_BY_PATH["luxos/luxai.md"]["src"] else "en", "luxos/luxai.md")}">LuxAI</a>'
                  f'<a href="{doc_url(lang if lang in DOCS_BY_PATH["luxos/faq.md"]["src"] else "en", "luxos/faq.md")}">{e(t["faq"])}</a>'
                  f'<a href="{changes_url(lang)}">{e(t["changes"])}</a><a href="{usage_url(lang)}">{e(t["usage"])}</a>'
                  f'<a href="{DISCORD}" rel="noopener">Discord</a>'
                  f'<a href="/repo/">{e(t["repos"])}</a>'
                  f'<a href="{page_url(lang, "mail")}">{e(t["mail"])}</a>'
                  f'<a href="{page_url(lang, "privacy")}">{e(t["privacy"])}</a>'
                  f'<a href="{page_url(lang, "terms")}">{e(t["terms"])}</a>'
                  f'<a href="https://github.com/luxopes/luxos-kernel">{e(t["kernel"])}</a>'
                  f'<a href="https://lux-ai.cz">lux-ai.cz</a>')
    dlg = ""
    if dialog:
        dlg = (f'  <dialog class="lightbox" aria-label="{e(t["gallery_label"])}">\n'
               f'    <button class="lightbox-close" aria-label="{e(t["close"])}">✕</button>\n'
               f'    <button class="lightbox-prev" aria-label="{e(t["prev_shot"])}">‹</button>\n'
               '    <figure><img alt=""><figcaption></figcaption></figure>\n'
               f'    <button class="lightbox-next" aria-label="{e(t["next_shot"])}">›</button>\n'
               '  </dialog>\n')
    extra_js = "".join(f'  <script src="/{s}?v={stamp}" defer></script>\n' for s in scripts)
    if home:
        body = '    <span id="top"></span>\n' + body
    # kazdy obrazek s rozmery (bez poskakovani pri nacitani) a mimo prvni obrazovku az pri posunu
    body = site_seo.add_img_dims(body, SITE)
    if sitemap and not noindex:
        SITEMAP.append((path, alt))
        SOURCES[path] = tuple(src)
    PAGE_COUNT[lang] += 1
    return f"""<!doctype html>
<html lang="{lang}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#080b16">
  <title>{e(full_title)}</title>
  <meta name="description" content="{e(clip(desc))}">
{robots}  <link rel="canonical" href="{canon}">
{hreflang_links(alt)}
  <link rel="icon" href="/assets/favicon.svg" type="image/svg+xml">
  <link rel="icon" href="/assets/favicon-32.png" sizes="32x32" type="image/png">
  <link rel="apple-touch-icon" href="/assets/apple-touch-icon.png">
  <meta property="og:site_name" content="LuxOS">
  <meta property="og:type" content="{og_type}">
  <meta property="og:title" content="{e(full_title)}">
  <meta property="og:description" content="{e(clip(desc))}">
  <meta property="og:url" content="{canon}">
  <meta property="og:locale" content="{t['locale']}">
{og_alt}  <meta property="og:image" content="{OG_IMAGE[lang]}">
  <meta property="og:image:width" content="1200">
  <meta property="og:image:height" content="630">
  <meta property="og:image:type" content="image/jpeg">
  <meta property="og:image:alt" content="{e(OG_ALT[lang])}">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{e(full_title)}">
  <meta name="twitter:description" content="{e(clip(desc))}">
  <meta name="twitter:image" content="{OG_IMAGE[lang]}">
  <meta name="twitter:image:alt" content="{e(OG_ALT[lang])}">
{jsonld(*ld) if ld else ""}
  <link rel="stylesheet" href="/styles.css?v={stamp}">
  <script src="/script.js?v={stamp}" defer></script>
{extra_js}</head>
<body>
  <script>try{{var t=localStorage.getItem("luxos-theme");if(t?t==="light":matchMedia("(prefers-color-scheme: light)").matches)document.body.classList.add("light")}}catch(e){{}}</script>
  <a class="skip-link" href="#content">{e(t["skip"])}</a>
  <div class="site-bg" aria-hidden="true"><div class="orb orb-one"></div><div class="orb orb-two"></div><div class="blue-horizon"></div></div>
  <header class="site-header shell">
    <a class="brand" href="{hu}" aria-label="{e(t["home_aria"])}">{logo_svg("brand")}<span>LuxOS</span></a>
    <nav class="desktop-nav" aria-label="{e(t["main_nav"])}">{desk}</nav>
    {switch}
    <button class="theme-toggle" aria-label="{e(t["theme"])}" aria-pressed="false"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M4.93 4.93l1.42 1.42m11.3 11.3 1.42 1.42M2 12h2m16 0h2M4.93 19.07l1.42-1.42m11.3-11.3 1.42-1.42"/></svg><span class="toggle-track"><span class="toggle-knob"></span></span></button>
    <button class="mobile-nav-toggle" aria-label="{e(t["menu"])}" aria-expanded="false"><span></span><span></span><span></span></button>
  </header>
  <nav class="mobile-nav shell" aria-label="{e(t["mobile_nav"])}">{mobile}</nav>
  <main id="content" class="shell">
{body}
    <footer><span class="footer-brand">{logo_svg("footer", "logo footer-logo")}© 2026 LuxOS</span><span class="footer-links">{foot_links}</span></footer>
  </main>
{dlg}</body>
</html>
"""


DOCS_BY_PATH = {}


def build_docs(cols, stamp, md_to_html):
    flat = [d for c in cols for d in c["files"]]
    for d in flat:
        DOCS_BY_PATH[d["path"]] = d
    return flat


def render_docs(cols, flat, stamp, md_to_html):
    count = {"en": 0, "cs": 0}
    for lang in LANGS:
        t = T[lang]

        def nav_html(current=""):
            parts = []
            for col in cols:
                parts.append(f"<h3>{e(col['title'])}</h3>")
                for d in col["files"]:
                    has = lang in d["src"]
                    url = doc_url(lang if has else "en", d["path"])
                    cls = ' class="current" aria-current="page"' if d["path"] == current else ""
                    badge = f' <span class="badge-en" title="{e(t["en_only_title"])}">{t["en_only"]}</span>' if (lang == "cs" and not has) else ""
                    parts.append(f'<a href="{url}"{cls}>{e(d["title"][lang if has else "en"])}{badge}</a>')
            return "\n".join(parts)

        def layout(content, current=""):
            return (f'    <div class="doc-layout"><nav class="doc-nav panel" aria-label="{e(t["docs_aria"])}">{nav_html(current)}</nav>'
                    f'<article class="doc panel">{content}</article></div>')

        def crumbs(*trail):
            ol = "".join(f'<li><a href="{h}">{e(n)}</a></li>' if h else f'<li aria-current="page">{e(n)}</li>' for n, h in trail)
            return f'<nav class="breadcrumbs" aria-label="Breadcrumb"><ol>{ol}</ol></nav>'

        def breadcrumb_ld(*trail):
            return {"@context": "https://schema.org", "@type": "BreadcrumbList",
                    "itemListElement": [{"@type": "ListItem", "position": i + 1, "name": n,
                                         "item": abs_url(h)} for i, (n, h) in enumerate(trail)]}

        for i, d in enumerate(flat):
            if lang not in d["src"]:
                continue
            with open(d["src"][lang], encoding="utf-8") as f:
                text = f.read()
            body = md_to_html(text, d["path"], lang)
            title = d["title"][lang]
            desc = d["summary"][lang]
            path = doc_url(lang, d["path"])
            alt = {l: doc_url(l, d["path"]) for l in LANGS if l in d["src"]}
            trail = [(t["crumb_home"], home_url(lang)), (t["crumb_docs"], docs_index_url(lang)), (title, path)]
            pager = []
            if i > 0:
                p = flat[i - 1]
                pl = lang if lang in p["src"] else "en"
                pager.append(f'<a rel="prev" href="{doc_url(pl, p["path"])}">‹ {e(t["prev"])}: {e(p["title"][pl])}</a>')
            if i < len(flat) - 1:
                n = flat[i + 1]
                nl = lang if lang in n["src"] else "en"
                pager.append(f'<a rel="next" href="{doc_url(nl, n["path"])}">{e(t["next"])}: {e(n["title"][nl])} ›</a>')
            content = crumbs(*[(n, h if k < 2 else None) for k, (n, h) in enumerate(trail)]) + body + \
                f'<nav class="doc-pager" aria-label="Pager">{"".join(pager)}</nav>'
            article = {"@context": "https://schema.org", "@type": "TechArticle", "headline": title,
                       "description": clip(desc), "inLanguage": lang, "url": abs_url(path),
                       "isPartOf": {"@type": "WebSite", "name": "LuxOS", "url": BASE + "/"},
                       "about": {"@id": APP_ID}, "publisher": org_ref()}
            ld = [breadcrumb_ld(*trail), article]
            if d["path"] == "luxos/faq.md":
                ld.append(faq_ld(text))
            # titulek do 60 znaku: vlastni seo_title (docs.json) nebo nazev s co nejdelsi priponou
            page_title = d.get("seo_title", {}).get(lang) or site_seo.fit_title(title, t["docs_suffixes"])
            write(path.lstrip("/"), shell(lang, path, page_title, desc,
                                          layout(content, d["path"]), alt, "docs", stamp, "article", ld,
                                          desc_exact=lang in d.get("own_summary", ()), src=[d["src"][lang]],
                                          switch_to=None if OTHER[lang] in alt else docs_index_url(OTHER[lang])))
            count[lang] += 1
        # rozcestnik dokumentace
        cards = []
        for col in cols:
            cards.append(f'<h2>{e(col["title"])}</h2><ul class="doc-index">')
            for d in col["files"]:
                has = lang in d["src"]
                ul = lang if has else "en"
                badge = f' <span class="badge-en" title="{e(t["en_only_title"])}">{t["en_only"]}</span>' if (lang == "cs" and not has) else ""
                cards.append(f'<li><a href="{doc_url(ul, d["path"])}"><strong>{e(d["title"][ul])}{badge}</strong>'
                             f'<span>{e(clip(d["summary"][ul], 200))}</span></a></li>')
            cards.append("</ul>")
        intro = f'<h1>{e(t["docs_h1"])}</h1><p class="lead">{e(t["docs_lead"])}</p>'
        ipath = docs_index_url(lang)
        trail = [(t["crumb_home"], home_url(lang)), (t["crumb_docs"], ipath)]
        crumb_html = crumbs((trail[0][0], trail[0][1]), (trail[1][0], None))
        ialt = {l: docs_index_url(l) for l in LANGS}
        coll = {"@context": "https://schema.org", "@type": "CollectionPage", "name": t["docs_h1"] + " – LuxOS",
                "url": abs_url(ipath), "inLanguage": lang, "description": t["docs_index_desc"]}
        write(ipath.lstrip("/") + "index.html",
              shell(lang, ipath, t["docs_index_title"],
                    t["docs_index_desc"], layout(crumb_html + intro + "\n".join(cards)), ialt, "docs", stamp,
                    "website", [breadcrumb_ld(*trail), coll],
                    src=[os.path.join(DOCS, "index.json"), os.path.join(CONTENT, "docs.json")]))
        count[lang] += 1
    return count


def faq_ld(text):
    """FAQPage z Markdownu: kazdy '## otazka' + text pod nim je odpoved."""
    qa = []
    for block in re.split(r"^## ", text, flags=re.M)[1:]:
        q, _, a = block.partition("\n")
        a = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", a)
        a = re.sub(r"[`*]", "", a)
        a = re.sub(r"\s+", " ", a).strip()
        qa.append({"@type": "Question", "name": q.strip(),
                   "acceptedAnswer": {"@type": "Answer", "text": a}})
    return {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": qa}


# ---- stranky pro konkretni hledani (site/landing) ----

with open(os.path.join(LANDING, "pages.json"), encoding="utf-8") as _f:
    LANDING_META = json.load(_f)


def landing_url(lang, key):
    """Adresa stranky ze site/landing/pages.json ('compare' = rozcestnik srovnani)."""
    if key == "compare":
        return LANDING_META["compare_hub"][lang]["path"]
    return LANDING_META["pages"][key][lang]["path"]


def landing_alt(key):
    return {l: landing_url(l, key) for l in LANGS}


def iso_fill(text, iso, lang):
    """{ISO_VERSION} a {ISO_SIZE} v titulcich, popisech a textech vyzvy (pages.json, T)."""
    return text.replace("{ISO_VERSION}", iso["version"]).replace("{ISO_SIZE}", fmt_size(iso["size"], lang))


def breadcrumbs_html(trail):
    ol = "".join(f'<li><a href="{h}">{e(n)}</a></li>' if k < len(trail) - 1 else f'<li aria-current="page">{e(n)}</li>'
                 for k, (n, h) in enumerate(trail))
    return f'<nav class="breadcrumbs" aria-label="Breadcrumb"><ol>{ol}</ol></nav>'


def breadcrumb_ld_list(trail):
    return {"@context": "https://schema.org", "@type": "BreadcrumbList",
            "itemListElement": [{"@type": "ListItem", "position": i + 1, "name": n, "item": abs_url(h)}
                                for i, (n, h) in enumerate(trail)]}


def shot_figure(lang, name, alt, caption="", eager=False):
    """Snimek plochy (svetly/tmavy podle webu jako v galerii): 960 px, na hustych displejich 1920 px."""
    sd = shot_dir(lang)
    if not os.path.isfile(os.path.join(SITE, sd.lstrip("/"), f"{name}-light-960.webp")):
        sd = "/assets/shots/"
    sizes = SHOT_SIZES[1:]
    load = 'fetchpriority="high"' if eager else 'loading="lazy"'
    cap = f"<figcaption>{e(caption)}</figcaption>" if caption else ""
    return (f'<figure class="app-shot landing-shot"><img src="{sd}{name}-light-960.webp" '
            f'srcset="{shot_srcset(sd, name, "light", sizes)}" sizes="(max-width: 980px) calc(100vw - 64px), 860px" '
            f'data-light="{sd}{name}-light-960.webp" data-dark="{sd}{name}-dark-960.webp" '
            f'data-light-srcset="{shot_srcset(sd, name, "light", sizes)}" '
            f'data-dark-srcset="{shot_srcset(sd, name, "dark", sizes)}" '
            f'width="1920" height="1080" alt="{e(alt)}" {load} decoding="async">{cap}</figure>')


def cta_html(lang, iso):
    """Vyzva ke stazeni na konci stranek pro konkretni hledani (odkaz na stranku Stahnout, ne primo na ISO)."""
    t = T[lang]
    inst = doc_url(lang if lang in DOCS_BY_PATH["luxos/installer.md"]["src"] else "en", "luxos/installer.md")
    return (f'<aside class="landing-cta" aria-label="{e(t["cta_button"])}">{logo_svg("cta", "logo cta-logo")}'
            f'<div class="cta-copy"><h2>{e(iso_fill(t["cta_title"], iso, lang))}</h2>'
            f'<p>{e(iso_fill(t["cta_text"], iso, lang))}</p></div>'
            f'<div class="cta-actions"><a class="button button-primary" href="{landing_url(lang, "download")}">'
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">'
            f'<path d="M12 3v12m-5-5 5 5 5-5M4 17v4h16v-4"/></svg>{e(t["cta_button"])}</a>'
            f'<a class="button button-outline" href="{inst}">{e(t["cta_secondary"])}</a></div></aside>')


def landing_cards(lang, keys):
    items = []
    for k in keys:
        m = LANDING_META["pages"][k][lang]
        items.append(f'<li><a href="{m["path"]}"><strong>{e(m["crumb"])}</strong><span>{e(m["card"])}</span></a></li>')
    return '<ul class="doc-index landing-cards">' + "".join(items) + "</ul>"


def app_ld(lang, iso, ver, url, description):
    """LuxOS jako SoftwareApplication (applicationCategory OperatingSystem; schema.org typ pro OS nema).
    Stejne @id na uvodni strance i na strance Stahnout. RAM 4 GB = instalace overena v 4GB VM (1.0.2)."""
    sd = shot_dir(lang)
    return {"@type": "SoftwareApplication", "@id": APP_ID, "name": "LuxOS",
            "alternateName": ["LuxOS Linux", f"LuxOS {ver['VERSION']} {ver['CODENAME']}"],
            "disambiguatingDescription": T[lang]["app_disambig"],
            "applicationCategory": "OperatingSystem", "operatingSystem": "Linux",
            "processorRequirements": "x86-64", "memoryRequirements": "4 GB", "storageRequirements": "20 GB",
            "softwareVersion": iso["version"], "description": description, "url": abs_url(url),
            "downloadUrl": f"{BASE}/download/{iso['file']}", "fileSize": fmt_size(iso["size"], "en"),
            "datePublished": iso["date"], "inLanguage": lang, "image": OG_IMAGE[lang],
            "screenshot": [f"{BASE}{sd}{name}-light.webp" for name, _c in GALLERY[lang]],
            "releaseNotes": abs_url(changes_url(lang)),
            "softwareHelp": {"@type": "CreativeWork", "url": abs_url(docs_index_url(lang))},
            "license": "https://spdx.org/licenses/GPL-3.0-or-later.html", "isAccessibleForFree": True,
            "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD",
                       "url": abs_url(landing_url(lang, "download"))},
            "author": {"@id": AUTHOR_ID}, "publisher": {"@id": ORG_ID}, "sameAs": [GITHUB, DISCORD]}


def faq_page_ld(pairs):
    return {"@context": "https://schema.org", "@type": "FAQPage",
            "mainEntity": [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}}
                           for q, a in pairs]}


def render_landing(stamp, iso, ver):
    """Stranky ze site/landing: drobecky, vyzva ke stazeni, souvisejici stranky, JSON-LD (WebPage,
    BreadcrumbList, FAQPage jen z viditelnych otazek, na strance Stahnout i SoftwareApplication)
    a rozcestnik srovnani."""
    pages = LANDING_META["pages"]
    compare_keys = [k for k, v in pages.items() if v.get("group") == "compare"]
    guide_keys = [k for k in pages if k not in compare_keys and k != "download"]
    for key, meta in pages.items():
        alt = landing_alt(key)
        for lang in LANGS:
            t = T[lang]
            m = meta[lang]
            path = m["path"]
            trail = [(t["crumb_home"], home_url(lang))]
            if meta.get("group") == "compare":
                trail.append((LANDING_META["compare_hub"][lang]["crumb"], landing_url(lang, "compare")))
            trail.append((m["crumb"], path))
            src = os.path.join(LANDING, f"{key}.{lang}.html")
            with open(src, encoding="utf-8") as f:
                text = f.read()
            values = {"CRUMBS": breadcrumbs_html(trail), "CTA": cta_html(lang, iso),
                      "ISO_VERSION": iso["version"], "ISO_FILE": iso["file"], "ISO_SIZE": fmt_size(iso["size"], lang),
                      "ISO_DATE": fmt_date(iso["date"], lang), "ISO_SHA256": iso["sha256"], "FINGERPRINT": FINGERPRINT,
                      "CODENAME": ver["CODENAME"], "VERSION": ver["VERSION"], "HOME": home_url(lang),
                      "DOCS": docs_index_url(lang), "CHANGES": changes_url(lang)}
            for k, v in values.items():
                text = text.replace("{{" + k + "}}", v)
            text = re.sub(r"\{\{DOC:([^}#]+)(#[^}]*)?\}\}",
                          lambda mm: doc_url(lang if lang in DOCS_BY_PATH[mm.group(1)]["src"] else "en", mm.group(1))
                          + (mm.group(2) or ""), text)
            text = re.sub(r"\{\{URL:([a-z0-9-]+)\}\}", lambda mm: landing_url(lang, mm.group(1)), text)
            # {{SHOT:nazev|alt|popisek}} nebo {{SHOT:nazev|alt|popisek|eager}} (prvni obrazovka)
            text = re.sub(r"\{\{SHOT:([a-z-]+)\|([^|}]+)\|([^|}]*)(\|eager)?\}\}",
                          lambda mm: shot_figure(lang, mm.group(1), mm.group(2), mm.group(3), bool(mm.group(4))), text)
            left = re.findall(r"\{\{[^}]*\}\}", text)
            if left:
                sys.exit(f"build-site: unfilled placeholders in landing/{key}.{lang}.html {left}")
            # souvisejici stranky: u srovnani ostatni srovnani, jinak ostatni pruvodci
            if meta.get("group") == "compare":
                rel, rel_title = [k for k in compare_keys if k != key], t["compare_more"]
            else:
                rel = [k for k in guide_keys if k != key] + (compare_keys if key == "download" else [])
                rel_title = t["more_pages"]
            related = (f'<section class="landing-related" aria-labelledby="related-title"><h2 id="related-title">'
                       f'{e(rel_title)}</h2>{landing_cards(lang, rel)}</section>')
            body = f'    <article class="doc panel landing">{text.rstrip()}\n{related}</article>'
            title, desc = iso_fill(m["title"], iso, lang), iso_fill(m["desc"], iso, lang)
            crumb_ld = breadcrumb_ld_list(trail)
            crumb_ld["@id"] = abs_url(path) + "#breadcrumb"
            page = {"@context": "https://schema.org", "@type": "WebPage", "@id": abs_url(path) + "#page",
                    "name": title, "description": desc, "url": abs_url(path), "inLanguage": lang,
                    "isPartOf": {"@id": SITE_ID}, "about": {"@id": APP_ID}, "publisher": org_ref(),
                    "breadcrumb": {"@id": abs_url(path) + "#breadcrumb"}}
            ld = [crumb_ld, page]
            if key == "download":
                app = {"@context": "https://schema.org"}
                app.update(app_ld(lang, iso, ver, path, desc))
                ld.append(app)
            pairs = site_seo.faq_pairs(text)
            if pairs:
                ld.append(faq_page_ld(pairs))
            write(path.lstrip("/") + "index.html",
                  shell(lang, path, title, desc, body, alt, "download" if key == "download" else "", stamp,
                        "website", ld, src=[src, os.path.join(LANDING, "pages.json")]
                        + ([os.path.join(SITE, "iso.json")] if key == "download" else [])))
    # rozcestnik srovnani: karty srovnani a odkaz na srovnani s dalsimi distribucemi v dokumentaci
    for lang in LANGS:
        t = T[lang]
        m = LANDING_META["compare_hub"][lang]
        path = m["path"]
        trail = [(t["crumb_home"], home_url(lang)), (m["crumb"], path)]
        cmp_doc = DOCS_BY_PATH["luxos/compare.md"]
        cl = lang if lang in cmp_doc["src"] else "en"
        more = f'<p class="more-link"><a href="{doc_url(cl, "luxos/compare.md")}">{e(cmp_doc["title"][cl])} ›</a></p>'
        body = (f'    <article class="doc panel landing">{breadcrumbs_html(trail)}<h1>{e(m["h1"])}</h1>'
                f'<p class="lead">{e(m["lead"])}</p>{landing_cards(lang, compare_keys)}{more}{cta_html(lang, iso)}</article>')
        coll = {"@context": "https://schema.org", "@type": "CollectionPage", "name": m["title"], "url": abs_url(path),
                "inLanguage": lang, "description": m["desc"], "isPartOf": {"@id": SITE_ID}}
        write(path.lstrip("/") + "index.html",
              shell(lang, path, m["title"], m["desc"], body, landing_alt("compare"), "", stamp, "website",
                    [breadcrumb_ld_list(trail), coll], src=[os.path.join(LANDING, "pages.json")]))


def llms_txt(ver, iso, cols):
    """/llms.txt podle llmstxt.org: nazev, shrnuti, overitelna fakta a odkazy na stranky s jednovetym popisem."""
    lines = [
        "# LuxOS",
        "",
        "> LuxOS is a fast, lightweight desktop Linux distribution based on Arch Linux with a macOS-like desktop "
        "(Xfce underneath), its own package manager `lux`, its own kernel build `linux-luxos`, automatic drivers, "
        "updates with Btrfs snapshots and rollback, and the optional LuxAI assistant. It is free (GPL-3.0-or-later).",
        "",
        "Key facts:",
        "",
        f"- Current version: {ver['VERSION']} \"{ver['CODENAME']}\" (stable), ISO {iso['version']} released {iso['date']}",
        "- Base: Arch Linux; rolling release (`lux update`); x86_64 PCs with UEFI or BIOS, at least 20 GB disk",
        "- Desktop: Xfce components (xfwm4, panel) arranged like macOS: top bar, Plank Dock, Launchpad, Search, Control Center",
        "- Package manager: `lux` (libalpm); Arch and signed LuxOS repositories, Flathub, AUR (checked, built in a sandbox), "
        "own `.lux` apps; there is no `pacman` command",
        "- Kernel: `linux-luxos`, vanilla stable kernel.org Linux with Arch's configuration, built by GitHub Actions",
        "- Maintenance: LuxOS Care (background updates, snapshot before every update, `lux rollback`, read-only /usr)",
        "- Security: firewall on by default, Lux Guard (checks downloaded programs, sandbox), Safe (encrypted folder)",
        "- LuxAI: optional AI assistant; needs a LuxAI account with 20 000 credits per month shared by all models; answers come from third-party model providers",
        f"- Developer: {AUTHOR}, Czech Republic; contact {CONTACT}; source {GITHUB}; community {DISCORD}",
        "- Not to be confused with LuxOS, the unrelated Bitcoin miner firmware by Luxor.",
        "",
        "## Why people choose LuxOS",
        "",
        "- Free, with no paid edition: The ISO is a free download. Most of LuxOS is open source (GPL-3.0-or-later); LuxAI, Lux Code and LSL IDE are free to use on LuxOS.",
        "- Fast on older computers: A light Xfce desktop with zram swap, earlyoom and its own `linux-luxos` kernel. A 64-bit PC and a 20 GB disk are enough; tested in virtual machines with 3 GB of RAM.",
        "- A familiar macOS-style desktop: Top bar, Dock, Launchpad, Search and Control Center – easy to learn whether you come from Windows or a Mac.",
        "- Drivers without searching: Graphics (NVIDIA including older cards), Wi-Fi, cameras and sound are detected and installed automatically; printers and scanners work without drivers.",
        "- Updates you can undo: LuxOS Care installs updates in the background, takes a Btrfs snapshot before every update (`lux rollback`) and keeps the previous kernel in the boot menu.",
        "- Secure by default: Signed LuxOS repositories, the firewall on, Secure Boot support, Lux Guard checks programs from the internet and runs risky ones only in the Sandbox, and Safe encrypts a folder.",
        "- Privacy: The system needs no account. Firefox comes without telemetry and needless connections to Mozilla. The only statistic is an anonymous weekly count (version and channel, no ID) that you can turn off.",
        "- Plenty of software: One package manager, `lux`, for the Arch Linux repositories, Flathub and checked AUR packages built in a sandbox, plus the LuxOS Store.",
        "- An AI assistant that knows your computer: LuxAI explains errors, changes settings and searches the web for you. It is optional; the free LuxAI account includes 20 000 credits a month.",
        "- Safe next to Windows: The installer can put LuxOS into free space next to Windows and checks first that Windows can be shrunk safely (Fast Startup and hibernation off).",
        "- Backups and undelete: Backups saves your home folder every hour to a USB or network disk, and Lux Guard keeps hourly snapshots of your files, so deleted files come back.",
        "- In your language: English and 12 more languages, including Czech, Slovak, Polish, German, Ukrainian and Hungarian; a new install gets Firefox and Thunderbird in the system language too.",
        "",
        "## Start here",
        "",
        f"- [Home and download]({BASE}/): what LuxOS is, screenshots, ISO download and verification",
        f"- [FAQ]({abs_url(doc_url('en', 'luxos/faq.md'))}): common questions (price, stability, Windows apps, Steam, hardware)",
        f"- [LuxOS compared]({abs_url(doc_url('en', 'luxos/compare.md'))}): differences from Ubuntu, Mint, Zorin, elementary OS and Arch",
        f"- [Download]({abs_url(landing_url('en', 'download'))}): free ISO, SHA-256 and GPG verification, "
        "system requirements, writing a USB stick, Secure Boot",
        f"- [Changelog]({abs_url(changes_url('en'))}): what changed in each release",
        f"- [Full text for LLMs]({BASE}/llms-full.txt): FAQ, comparison and the main manual pages in one Markdown file",
        "",
        "## Guides and comparisons",
        "",
    ]
    for key, meta in LANDING_META["pages"].items():
        if key != "download":
            m = meta["en"]
            lines.append(f"- [{m['crumb']}]({abs_url(m['path'])}): {m['card']}")
    lines.append("")
    for col in cols:
        lines += [f"## {col['title']}", ""]
        for d in col["files"]:
            if "en" not in d["src"]:
                continue
            lines.append(f"- [{d['title']['en']}]({abs_url(doc_url('en', d['path']))}): {d['summary']['en']}")
        lines.append("")
    lines += ["## Optional", "",
              f"- [Czech home page]({abs_url(home_url('cs'))}): the site in Czech",
              f"- [Usage statistics]({abs_url(usage_url('en'))}): anonymous weekly counts of active installations",
              f"- [Privacy policy]({abs_url(page_url('en', 'privacy'))}): data handling of LuxOS, LuxAI and LuxOS Mail",
              f"- [Source code]({GITHUB}): GitHub repository (issues for bug reports)",
              f"- [Discord]({DISCORD}): LuxOS community server (#support with a documentation bot and the team)",
              "- [LSL language](https://lsl.lux-ai.cz): website of Lux Simple Lang", ""]
    return "\n".join(lines)


def llms_full_txt(ver, iso):
    """/llms-full.txt: vybrane anglicke stranky (Markdown) v jednom souboru, kazda s adresou zdroje."""
    parts = [f"# LuxOS – full reference for language models\n\nLuxOS {ver['VERSION']} \"{ver['CODENAME']}\" (stable), "
             f"ISO {iso['version']} from {iso['date']}. Website {BASE}/ · source {GITHUB} · contact {CONTACT}.\n"
             "Each section below is one page of the LuxOS documentation; relative links point to other pages of "
             f"{BASE}/docs/.\n"]
    for p in LLMS_FULL_DOCS:
        d = DOCS_BY_PATH.get(p)
        if not d or "en" not in d["src"]:
            continue
        with open(d["src"]["en"], encoding="utf-8") as f:
            text = f.read().strip()
        parts.append(f"\n---\n\nSource: {abs_url(doc_url('en', p))}\n\n{text}\n")
    return "".join(parts)


def sitemap_xml(today):
    rows = ['<?xml version="1.0" encoding="UTF-8"?>',
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">']
    for path, alt in sorted(SITEMAP):
        pri = "1.0" if path in ("/", "/cs/") else ("0.8" if path.count("/") <= 2 else "0.6")
        rows.append("  <url>")
        rows.append(f"    <loc>{abs_url(path)}</loc>")
        rows.append(f"    <lastmod>{git_date(SOURCES.get(path, ()), today)}</lastmod>")
        rows.append(f"    <priority>{pri}</priority>")
        if len(alt) > 1:
            for lang in LANGS:
                if lang in alt:
                    rows.append(f'    <xhtml:link rel="alternate" hreflang="{lang}" href="{abs_url(alt[lang])}"/>')
            rows.append(f'    <xhtml:link rel="alternate" hreflang="x-default" href="{abs_url(alt["en"])}"/>')
        rows.append("  </url>")
    rows.append("</urlset>")
    return "\n".join(rows) + "\n"


def main():
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT)
    stamp = time.strftime("%Y%m%d%H%M")
    today = datetime.date.today().isoformat()
    ver = read_kv(os.path.join(ROOT, "packages", "luxos-branding", "files", "version"))
    with open(os.path.join(SITE, "iso.json"), encoding="utf-8") as f:
        iso = json.load(f)
    release = {"version": ver["VERSION"], "codename": ver["CODENAME"], "channel": "stable",
               "iso": iso, "repo": "https://luxos.lux-ai.cz/repo/", "fingerprint": FINGERPRINT}
    write("release.json", json.dumps(release, ensure_ascii=False, indent=2) + "\n")

    cols = load_docs()
    flat = build_docs(cols, stamp, None)
    md_to_html = make_md_to_html(DOCS_BY_PATH)

    featured = ["luxos/luxai.md", "luxos/lux-code.md", "luxos/package-management.md", "luxos/store.md",
                "luxos/care-updates.md", "luxos/drivers.md", "luxos/installer.md", "luxos/hardware.md",
                "luxos/guard.md", "luxos/safe.md", "luxos/sandbox.md", "luxos/luxdrop.md",
                "lsl/overview.md", "luxos/faq.md"]

    # ---- uvodni stranky ----
    for lang in LANGS:
        t = T[lang]
        gallery = []
        sd = shot_dir(lang)
        small = SHOT_SIZES[:2]
        for name, caption in GALLERY[lang]:
            c = e(caption)
            # svetly vzhled je vychozi v HTML; script.js prepne src/srcset podle vzhledu webu
            gallery.append(f'        <a class="gallery-item" href="{sd}{name}-light.webp" data-full-dark="{sd}{name}-dark.webp" '
                           f'data-caption="{c}"><img src="{sd}{name}-light-small.webp" '
                           f'srcset="{shot_srcset(sd, name, "light", small)}" '
                           f'sizes="(max-width: 560px) calc(100vw - 32px), (max-width: 1100px) 46vw, 420px" '
                           f'data-light="{sd}{name}-light-small.webp" data-dark="{sd}{name}-dark-small.webp" '
                           f'data-light-srcset="{shot_srcset(sd, name, "light", small)}" '
                           f'data-dark-srcset="{shot_srcset(sd, name, "dark", small)}" '
                           f'width="640" height="360" alt="{c}" loading="lazy" decoding="async"><span>{c}</span></a>')
        hero_sizes = SHOT_SIZES[1:]
        # <picture>: bez JS (a pred nactenim script.js) vybere prohlizec vzhled podle systemu; rucni volbu
        # na webu prepne script.js (srcset zdroje i obrazku)
        hero = (f'<picture><source media="(prefers-color-scheme: light)" srcset="{shot_srcset(sd, "desktop", "light", hero_sizes)}" '
                f'sizes="(max-width: 760px) calc(100vw - 32px), 46vw">'
                f'<img class="hero-shot" src="{sd}desktop-dark-960.webp" srcset="{shot_srcset(sd, "desktop", "dark", hero_sizes)}" '
                f'sizes="(max-width: 760px) calc(100vw - 32px), 46vw" '
                f'data-dark="{sd}desktop-dark-960.webp" data-light="{sd}desktop-light-960.webp" '
                f'data-dark-srcset="{shot_srcset(sd, "desktop", "dark", hero_sizes)}" '
                f'data-light-srcset="{shot_srcset(sd, "desktop", "light", hero_sizes)}" '
                f'width="1920" height="1080" alt="{e(t["hero_alt"])}" fetchpriority="high"></picture>')
        cards = []
        for p in featured:
            d = DOCS_BY_PATH[p]
            ul = lang if lang in d["src"] else "en"
            cards.append(f'        <li><a href="{doc_url(ul, p)}"><strong>{e(d["title"][ul])}</strong>'
                         f'<span>{e(clip(d["summary"][ul], 150))}</span></a></li>')
        values = {
            "VERSION": ver["VERSION"], "CODENAME": ver["CODENAME"], "ISO_VERSION": iso["version"],
            "ISO_FILE": iso["file"], "ISO_SIZE": fmt_size(iso["size"], lang), "ISO_DATE": fmt_date(iso["date"], lang),
            "ISO_SHA256": iso["sha256"], "FINGERPRINT": FINGERPRINT, "STAMP": stamp,
            "UPDATE_HIDDEN": "" if ver["VERSION"] != iso["version"] else " hidden",
            "GALLERY": "\n".join(gallery), "DOC_CARDS": "\n".join(cards),
            "HERO_SHOT": hero, "LOGO_HERO": logo_svg("hero", "logo hero-mark"),
            "DOCS": docs_index_url(lang), "CHANGES": changes_url(lang),
            "DOWNLOAD": landing_url(lang, "download"),
            "LANDING_CARDS": landing_cards(lang, [k for k in LANDING_META["pages"] if k != "download"]),
            "COMPARE": landing_url(lang, "compare"),
        }
        with open(os.path.join(SITE, f"home.{lang}.html"), encoding="utf-8") as f:
            text = f.read()
        for k, v in values.items():
            text = text.replace("{{" + k + "}}", v)
        text = re.sub(r"\{\{DOC:([^}]+)\}\}",
                      lambda m: doc_url(lang if lang in DOCS_BY_PATH[m.group(1)]["src"] else "en", m.group(1)), text)
        left = re.findall(r"\{\{[A-Za-z_:/.-]+\}\}", text)
        if left:
            sys.exit(f"build-site: unfilled placeholders {left}")
        path = home_url(lang)
        alt = {l: home_url(l) for l in LANGS}
        # jeden @graph: projekt (Organization), autor, web a samotny system; LuxOS je operacni system, schema.org
        # na to nema typ, proto SoftwareApplication s applicationCategory OperatingSystem
        org_ld = {"@type": "Organization", "@id": ORG_ID, "name": "LuxOS", "url": BASE + "/",
                  "logo": {"@type": "ImageObject", "url": BASE + "/assets/icon-192.png", "width": 192, "height": 192},
                  "email": CONTACT, "founder": {"@id": AUTHOR_ID}, "sameAs": [GITHUB, DISCORD]}
        author_ld = {"@type": "Person", "@id": AUTHOR_ID, "name": AUTHOR,
                     "address": {"@type": "PostalAddress", "addressCountry": "CZ"}}
        site_ld = {"@type": "WebSite", "@id": SITE_ID, "name": "LuxOS", "url": BASE + "/",
                   "inLanguage": list(LANGS), "description": T["en"]["site_desc"], "publisher": {"@id": ORG_ID}}
        app = app_ld(lang, iso, ver, path, t["home_desc"])
        graph = {"@context": "https://schema.org", "@graph": [org_ld, author_ld, site_ld, app]}
        write(path.lstrip("/") + "index.html",
              shell(lang, path, t["home_title"], t["home_desc"], text.rstrip("\n"), alt, "", stamp, "website",
                    [graph], home=True, dialog=True,
                    src=[os.path.join(SITE, f"home.{lang}.html"), os.path.join(SITE, "iso.json")]))

    # ---- dokumentace ----
    render_docs(cols, flat, stamp, md_to_html)

    # ---- zmeny ----
    # vydane verze; „Připravuje se“ (jen ve staging) ma vlastni stranku soon_url
    cs_rel, cs_soon = changelog_sections.cs_split()
    cs_changes = md_to_html(cs_rel, "", "cs")
    # anglicky preklad musi mit vsechna vydani, sekce a polozky z CHANGELOG.md (jinak by stranka tise chudla)
    bad = changelog_sections.verify()
    if bad:
        sys.exit("build-site: the English changelog does not match CHANGELOG.md:\n  " + "\n  ".join(bad))
    en_changes = md_to_html(changelog_sections.en_text(), "", "en")
    soon_md = {"cs": cs_soon, "en": changelog_sections.en_unreleased()}
    # na vlastni strance: "## Připravuje se" -> nadpis stranky (h1), "### Nové" -> h2
    for k, v in soon_md.items():
        if v:
            v = re.sub(r"(?m)^### ", "## ", re.sub(r"\A## ", "# ", v.lstrip()))
            soon_md[k] = v
    if all(soon_md.values()):
        soon_link = {"en": f'<p class="more-link"><a href="{soon_url("en")}">Coming soon: what is being tested in the staging channel ›</a></p>',
                     "cs": f'<p class="more-link"><a href="{soon_url("cs")}">Připravuje se: co se zkouší v testovacím kanálu staging ›</a></p>'}
        # pod uvod, pred prvni vydani
        en_changes, cs_changes = (body.replace("<h2", soon_link[l] + "<h2", 1) for l, body in (("en", en_changes), ("cs", cs_changes)))
        salt = {l: soon_url(l) for l in LANGS}
        soon_meta = {"en": ("Coming soon – LuxOS staging channel",
                            "Changes being tested in the LuxOS staging channel that are not in a stable release yet."),
                     "cs": ("Připravuje se – testovací kanál LuxOS",
                            "Změny, které se zkoušejí v testovacím kanálu LuxOS staging a zatím nejsou ve vydané verzi.")}
        for lang in LANGS:
            t = T[lang]
            trail = [(t["crumb_home"], home_url(lang)), (t["changes"], changes_url(lang)), (soon_meta[lang][0].split(" – ")[0], soon_url(lang))]
            ld = [{"@context": "https://schema.org", "@type": "BreadcrumbList",
                   "itemListElement": [{"@type": "ListItem", "position": i + 1, "name": n, "item": abs_url(h)}
                                       for i, (n, h) in enumerate(trail)]}]
            back = {"en": f'<p class="more-link"><a href="{changes_url("en")}">‹ All released versions</a></p>',
                    "cs": f'<p class="more-link"><a href="{changes_url("cs")}">‹ Všechny vydané verze</a></p>'}[lang]
            write(soon_url(lang).lstrip("/") + "index.html",
                  shell(lang, soon_url(lang), soon_meta[lang][0], soon_meta[lang][1],
                        f'    <article class="doc panel">{md_to_html(soon_md[lang], "", lang)}{back}</article>', salt, "changes",
                        stamp, "article", ld,
                        src=[os.path.join(ROOT, "CHANGELOG.md") if lang == "cs" else os.path.join(CONTENT, "en", "changes", "unreleased.md")]))
    calt = {l: changes_url(l) for l in LANGS}
    for lang, body in (("en", en_changes), ("cs", cs_changes)):
        t = T[lang]
        trail = [(t["crumb_home"], home_url(lang)), (t["changes"], changes_url(lang))]
        ld = [{"@context": "https://schema.org", "@type": "BreadcrumbList",
               "itemListElement": [{"@type": "ListItem", "position": i + 1, "name": n, "item": abs_url(h)}
                                   for i, (n, h) in enumerate(trail)]}]
        write(changes_url(lang).lstrip("/") + "index.html",
              shell(lang, changes_url(lang), t["changes_title"].format(version=ver["VERSION"]),
                    t["changes_desc"].format(version=ver["VERSION"], codename=ver["CODENAME"]),
                    f'    <article class="doc panel">{body}</article>', calt, "changes", stamp, "article", ld,
                    src=[os.path.join(ROOT, "CHANGELOG.md") if lang == "cs" else os.path.join(CONTENT, "en", "changes")]))
    # stary odkaz /zmeny/ (puvodne cesky) presmeruje na /cs/zmeny/
    write("zmeny/index.html", '<!doctype html><html lang="cs"><meta charset="utf-8"><title>Seznam změn – LuxOS</title>'
          '<meta http-equiv="refresh" content="0; url=/cs/zmeny/"><link rel="canonical" href="https://luxos.lux-ai.cz/cs/zmeny/">'
          '<meta name="robots" content="noindex"><a href="/cs/zmeny/">Seznam změn</a>\n')

    # ---- stranky pro konkretni hledani, stranka Stahnout (/download/, ISO a podpisy lezi vedle ni) ----
    render_landing(stamp, iso, ver)

    # ---- pouzivani (countme): data nacita usage.js z /stats/usage.json na serveru ----
    countme = DOCS_BY_PATH.get("luxos/countme.md")
    if not countme:
        print("build-site: warning: luxos/countme.md is not in the luxos-docs index.json, "
              "the usage page links to the documentation index instead", file=sys.stderr)
    ualt = {l: usage_url(l) for l in LANGS}
    for lang in LANGS:
        t = T[lang]
        path = usage_url(lang)
        trail = [(t["crumb_home"], home_url(lang)), (t["usage"], path)]
        crumbs = ('<nav class="breadcrumbs" aria-label="Breadcrumb"><ol>'
                  f'<li><a href="{trail[0][1]}">{e(trail[0][0])}</a></li>'
                  f'<li aria-current="page">{e(trail[1][0])}</li></ol></nav>')
        if countme:
            cl = lang if lang in countme["src"] else "en"
            doc_href, doc_title = doc_url(cl, "luxos/countme.md"), countme["title"][cl]
        else:
            doc_href, doc_title = docs_index_url(lang), t["docs"]
        with open(os.path.join(SITE, f"usage.{lang}.html"), encoding="utf-8") as f:
            text = f.read()
        for k, v in {"CRUMBS": crumbs, "COUNTME_DOC": doc_href, "COUNTME_DOC_TITLE": e(doc_title)}.items():
            text = text.replace("{{" + k + "}}", v)
        left = re.findall(r"\{\{[A-Za-z_:/.-]+\}\}", text)
        if left:
            sys.exit(f"build-site: unfilled placeholders in usage.{lang}.html {left}")
        ld = [{"@context": "https://schema.org", "@type": "BreadcrumbList",
               "itemListElement": [{"@type": "ListItem", "position": i + 1, "name": n, "item": abs_url(h)}
                                   for i, (n, h) in enumerate(trail)]}]
        write(path.lstrip("/") + "index.html",
              shell(lang, path, t["usage_title"], t["usage_desc"], text.rstrip("\n"), ualt, "", stamp, "website",
                    ld, scripts=("usage.js",), src=[os.path.join(SITE, f"usage.{lang}.html")]))

    # ---- Posta LuxOS, zasady ochrany soukromi, podminky ----
    for name in PAGES:
        palt = {l: page_url(l, name) for l in LANGS}
        for lang in LANGS:
            t = T[lang]
            path = page_url(lang, name)
            trail = [(t["crumb_home"], home_url(lang)), (t[name + "_crumb"], path)]
            crumbs = ('<nav class="breadcrumbs" aria-label="Breadcrumb"><ol>'
                      f'<li><a href="{trail[0][1]}">{e(trail[0][0])}</a></li>'
                      f'<li aria-current="page">{e(trail[1][0])}</li></ol></nav>')
            with open(os.path.join(SITE, "pages", f"{name}.{lang}.html"), encoding="utf-8") as f:
                text = f.read()
            for k, v in {"CRUMBS": crumbs, "UPDATED": fmt_date(LEGAL_UPDATED, lang)}.items():
                text = text.replace("{{" + k + "}}", v)
            left = re.findall(r"\{\{[A-Za-z_:/.-]+\}\}", text)
            if left:
                sys.exit(f"build-site: unfilled placeholders in pages/{name}.{lang}.html {left}")
            ld = [{"@context": "https://schema.org", "@type": "BreadcrumbList",
                   "itemListElement": [{"@type": "ListItem", "position": i + 1, "name": n, "item": abs_url(h)}
                                       for i, (n, h) in enumerate(trail)]}]
            if name == "mail":
                ld.append({"@context": "https://schema.org", "@type": "SoftwareApplication", "name": "LuxOS Mail",
                           "applicationCategory": "CommunicationApplication", "operatingSystem": "LuxOS (Linux)",
                           "description": t["mail_desc"], "url": abs_url(path), "inLanguage": lang,
                           "image": BASE + "/assets/luxos-mail.svg",
                           "license": "https://www.gnu.org/licenses/gpl-3.0.html",
                           "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"},
                           "publisher": org_ref()})
            write(path.lstrip("/") + "index.html",
                  shell(lang, path, t[name + "_title"], t[name + "_desc"], text.rstrip("\n"), palt, "", stamp,
                        "website", ld, src=[os.path.join(SITE, "pages", f"{name}.{lang}.html")]))

    for name in ("styles.css", "script.js", "usage.js"):
        shutil.copy(os.path.join(SITE, name), os.path.join(OUT, name))
    copy_announcements()
    shutil.copytree(os.path.join(SITE, "assets"), os.path.join(OUT, "assets"))
    with open(os.path.join(OUT, "favicon.ico"), "wb") as f:
        f.write(favicon_ico(os.path.join(SITE, "assets", "favicon-32.png")))
    write("sitemap.xml", sitemap_xml(today))
    # stranka Stahnout (/download/) se indexuje, ISO a podpisy vedle ni ne (nejdelsi pravidlo vyhrava)
    write("robots.txt", f"User-agent: *\nAllow: /\nAllow: /download/$\nDisallow: /download/\n\nSitemap: {BASE}/sitemap.xml\n")
    write("llms.txt", llms_txt(ver, iso, cols))
    write("llms-full.txt", llms_full_txt(ver, iso))
    with open(INDEXNOW_KEY_FILE, encoding="utf-8") as f:
        key = f.read().strip()
    if not re.fullmatch(r"[A-Za-z0-9-]{8,128}", key):
        sys.exit(f"build-site: invalid IndexNow key in {INDEXNOW_KEY_FILE}")
    write(f"{key}.txt", key + "\n")
    print(f"site: LuxOS {ver['VERSION']} (ISO {iso['version']}), pages en {PAGE_COUNT['en']}, cs {PAGE_COUNT['cs']}, "
          f"{len(flat)} documents ({sum(1 for d in flat if 'cs' in d['src'])} also in Czech), "
          f"{len(SITEMAP)} urls in sitemap -> {OUT}")


# Kanal Novinek LuxOS (luxos-news --check v kazdem LuxOS): tady jen zakladni tvar a velikost, polozky do
# podrobna kontroluje `luxos-news validate` (stejna pravidla jako aplikace, neplatne polozky preskoci)
ANNOUNCEMENTS_MAX = 262144


def copy_announcements():
    src = os.path.join(SITE, "announcements.json")
    with open(src, "rb") as f:
        raw = f.read()
    if len(raw) > ANNOUNCEMENTS_MAX:
        sys.exit(f"build-site: {src} is larger than {ANNOUNCEMENTS_MAX} bytes (LuxOS would ignore it)")
    try:
        data = json.loads(raw.decode("utf-8"))
    except ValueError as e:
        sys.exit(f"build-site: {src} is not valid JSON: {e}")
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("announcements"), list):
        sys.exit(f'build-site: {src} must be {{"version": 1, "announcements": [...]}}')
    with open(os.path.join(OUT, "announcements.json"), "wb") as f:
        f.write(raw)


if __name__ == "__main__":
    main()
