#!/usr/bin/env python3
"""LuxOS - sestaveni webu https://luxos.lux-ai.cz do out/site (nahrava scripts/publish-site.sh).

  scripts/build-site.py

Dva jazyky: anglictina v korenu (/), cestina pod /cs/. Zdroje: site/ (sablony uvodni stranky
home.en.html a home.cs.html, styly, skript, obrazky), site/iso.json (posledni ISO - meni se jen
s novym ISO), verze z packages/luxos-branding/files/version, dokumentace z luxos-docs
(packages/apps/luxos-docs/docs, stejna jako offline v LuxOS) doplnena strankami z site/content
(LuxAI, Lux Code, hardware, zkratky, FAQ; cs/ = ceske verze), seznam zmen z CHANGELOG.md
(cesky) a site/content/en/changes.md (anglicky).
Vystup: index.html, cs/index.html, release.json (aktualni vydani, nacita ho i stranka), docs/,
cs/docs/, changes/, cs/zmeny/, sitemap.xml, robots.txt, download/index.html (presmerovani
na /#download - ISO a podpisy zustavaji v /download/). Kontrola odkazu: scripts/check-site.py.
"""
import datetime
import html
import json
import os
import posixpath
import re
import shutil
import sys
import time

import markdown

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, "site")
CONTENT = os.path.join(SITE, "content")
OUT = os.path.join(ROOT, "out", "site")
DOCS = os.path.join(ROOT, "packages", "apps", "luxos-docs", "docs")
BASE = "https://luxos.lux-ai.cz"
FINGERPRINT = "FD18 5DAB 7701 40E8 9C37 275E 7035 CFDF DCA6 C991"
LANGS = ("en", "cs")
OTHER = {"en": "cs", "cs": "en"}
OG_IMAGE = BASE + "/assets/shots/desktop-dark.webp"

MONTHS_CS = ["ledna", "února", "března", "dubna", "května", "června", "července", "srpna", "září",
             "října", "listopadu", "prosince"]
MONTHS_EN = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
             "October", "November", "December"]

GALLERY = {
    "cs": [
        ("launchpad", "Launchpad – všechny aplikace a dotaz pro LuxAI", True),
        ("control-center", "Ovládací centrum", True),
        ("calendar", "Kalendář z horní lišty", True),
        ("store", "Lux Store – aplikace jedním kliknutím", True),
        ("files-terminal", "Soubory a Terminál", False),
        ("luxai", "LuxAI – asistent, který rozumí vašemu počítači", False),
    ],
    "en": [
        ("launchpad", "Launchpad – all apps and a question box for LuxAI", True),
        ("control-center", "Control Center", True),
        ("calendar", "Calendar from the top bar", True),
        ("store", "Lux Store – apps in one click", True),
        ("files-terminal", "Files and Terminal", False),
        ("luxai", "LuxAI – an assistant that understands your computer", False),
    ],
}

# texty rozhrani (hlavicka, paticka, dokumentace)
T = {
    "en": {
        "locale": "en_US", "home": "Home", "features": "Features", "gallery": "Gallery",
        "download": "Download", "docs": "Documentation", "changes": "Changes", "luxai": "LuxAI",
        "faq": "FAQ", "repos": "Repositories", "kernel": "Kernel on GitHub",
        "home_aria": "LuxOS – home", "main_nav": "Main navigation", "mobile_nav": "Mobile navigation",
        "theme": "Switch between light and dark mode", "menu": "Open menu", "skip": "Skip to content",
        "lang_label": "Language", "docs_aria": "Documentation", "docs_h1": "Documentation",
        "docs_lead": ("The LuxOS manual: the same pages LuxOS ships offline (package luxos-docs) and "
                      "that LuxAI reads, with extra guides for LuxAI, Lux Code, hardware, shortcuts and the FAQ. "
                      "The documentation is in English."),
        "crumb_home": "LuxOS", "crumb_docs": "Documentation", "prev": "Previous", "next": "Next",
        "title_suffix": "LuxOS", "docs_suffix": "LuxOS documentation", "changes_title": "Changelog",
        "changes_desc": "What is new in each LuxOS release: LuxAI, lux, drivers, installer, security and desktop changes.",
        "home_title": "LuxOS – fast, lightweight Linux with a macOS-like desktop | Download ISO",
        "home_desc": ("LuxOS is a fast, lightweight Arch Linux based distribution with a macOS-like desktop, "
                      "the lux package manager, automatic drivers and the LuxAI assistant. Download the ISO."),
        "docs_index_desc": ("LuxOS documentation: installation, the lux package manager, LuxAI, Lux Code, "
                            "drivers, hardware, Store, Care, security (Guard, Safe, Sandbox), LuxDrop and the LSL language."),
        "gallery_label": "Screenshot", "close": "Close", "prev_shot": "Previous", "next_shot": "Next",
        "copy_https": "Copying works only over HTTPS.", "other_name": "Čeština",
        "doc_note_en": "", "footer_docs": "Documentation", "en_only": "EN",
        "en_only_title": "English only",
    },
    "cs": {
        "locale": "cs_CZ", "home": "Domů", "features": "Funkce", "gallery": "Galerie",
        "download": "Stáhnout", "docs": "Dokumentace", "changes": "Změny", "luxai": "LuxAI",
        "faq": "Časté otázky", "repos": "Repozitáře", "kernel": "Jádro na GitHubu",
        "home_aria": "LuxOS – domů", "main_nav": "Hlavní navigace", "mobile_nav": "Mobilní navigace",
        "theme": "Přepnout světlý a tmavý režim", "menu": "Otevřít nabídku", "skip": "Přejít na obsah",
        "lang_label": "Jazyk", "docs_aria": "Dokumentace", "docs_h1": "Dokumentace",
        "docs_lead": ("Příručka LuxOS: stejné stránky, jaké má LuxOS offline (balík luxos-docs) a ze kterých čerpá "
                      "i LuxAI, doplněné o návody k LuxAI, Lux Code, hardwaru, zkratkám a často kladené otázky. "
                      "Většina dokumentace je v angličtině (značka EN); české jsou stránky bez značky."),
        "crumb_home": "LuxOS", "crumb_docs": "Dokumentace", "prev": "Předchozí", "next": "Další",
        "title_suffix": "LuxOS", "docs_suffix": "Dokumentace LuxOS", "changes_title": "Seznam změn",
        "changes_desc": "Co je nového v jednotlivých verzích LuxOS: LuxAI, lux, ovladače, instalátor, bezpečnost a plocha.",
        "home_title": "LuxOS – rychlý a lehký Linux s prostředím ve stylu macOS | Stáhnout ISO",
        "home_desc": ("LuxOS je rychlý a lehký systém na Arch Linuxu s prostředím ve stylu macOS, správcem balíků lux, "
                      "automatickými ovladači a asistentem LuxAI. Stáhněte si instalační ISO."),
        "docs_index_desc": ("Dokumentace LuxOS: instalace, správce balíků lux, LuxAI, Lux Code, ovladače, hardware, "
                            "Obchod, Care, zabezpečení (Guard, Trezor, Sandbox), LuxDrop a jazyk LSL."),
        "gallery_label": "Snímek obrazovky", "close": "Zavřít", "prev_shot": "Předchozí", "next_shot": "Další",
        "copy_https": "Kopírování funguje jen přes HTTPS.", "other_name": "English",
        "doc_note_en": "", "footer_docs": "Dokumentace", "en_only": "EN",
        "en_only_title": "Pouze anglicky",
    },
}

SITEMAP = []      # (cesta, {jazyk: cesta}) vsech indexovatelnych stranek
PAGE_COUNT = {"en": 0, "cs": 0}


# ---- pomocne funkce ----

def read_kv(path):
    out = {}
    with open(path) as f:
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
    s = f"{n / 2 ** 30:.1f}"
    return (s.replace(".", ",") if lang == "cs" else s) + " GB"


def clip(text, n=158):
    """Popis do meta description: nejvyse n znaku, rez na hranici slova."""
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= n:
        return text
    cut = text[:n - 1].rsplit(" ", 1)[0].rstrip(",;:-–")
    return cut + "…"


def write(rel, text):
    path = os.path.join(OUT, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def home_url(lang):
    return "/" if lang == "en" else "/cs/"


def docs_index_url(lang):
    return "/docs/" if lang == "en" else "/cs/docs/"


def changes_url(lang):
    return "/changes/" if lang == "en" else "/cs/zmeny/"


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
    with open(os.path.join(DOCS, "index.json")) as f:
        index = json.load(f)
    with open(os.path.join(CONTENT, "docs.json")) as f:
        extras = json.load(f)["files"]
    cols = []
    for col in index["collections"]:
        files = []
        for d in col["files"]:
            files.append({"path": d["path"], "title": {"en": d["title"], "cs": d["title"]},
                          "summary": {"en": d.get("summary", ""), "cs": d.get("summary", "")},
                          "src": {"en": os.path.join(DOCS, d["path"])}})
        cols.append({"id": col["id"], "title": col["title"], "files": files})
    for x in extras:
        col = next(c for c in cols if c["id"] == x["path"].split("/")[0])
        item = {"path": x["path"], "title": x["title"], "summary": x["summary"], "src": {}}
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


def jsonld(*items):
    return "\n".join('  <script type="application/ld+json">' + json.dumps(i, ensure_ascii=False, separators=(",", ":"))
                     .replace("</", "<\\/") + "</script>" for i in items)


def shell(lang, path, title, desc, body, alt, active="", stamp="", og_type="website", ld=(), home=False,
          switch_to=None, noindex=False, sitemap=True, dialog=False):
    """Cela stranka: hlavicka se SEO znackami, navigace s prepinacem jazyka, obsah, paticka."""
    t = T[lang]
    other = OTHER[lang]
    full_title = title
    canon = abs_url(path)
    hu = home_url(lang)

    def nav_href(anchor):
        return anchor if home else hu + anchor

    items = [("home", t["home"], "#top" if home else hu),
             ("features", t["features"], nav_href("#features")),
             ("gallery", t["gallery"], nav_href("#gallery")),
             ("download", t["download"], nav_href("#download")),
             ("luxai", t["luxai"], doc_url(lang if lang in DOCS_BY_PATH["luxos/luxai.md"]["src"] else "en", "luxos/luxai.md")),
             ("docs", t["docs"], docs_index_url(lang)),
             ("changes", t["changes"], changes_url(lang))]
    def is_active(k):
        return k == active or (home and k == "home" and not active)
    desk = "".join('<a%s href="%s">%s</a>' % (' class="active"' if is_active(k) else "", h, e(label))
                   for k, label, h in items)
    mobile = "".join(f'<a href="{h}">{e(label)}</a>' for _k, label, h in items)

    sw_target = switch_to or (alt.get(other) if alt.get(other) else home_url(other))
    cur_lang_tag = lang.upper()
    other_tag = other.upper()
    switch = (f'<span class="lang-switch" role="group" aria-label="{e(t["lang_label"])}">'
              f'<a href="{path}" lang="{lang}" hreflang="{lang}" aria-current="true">{cur_lang_tag}</a>'
              f'<a href="{sw_target}" lang="{other}" hreflang="{other}" title="{e(T[other]["other_name"])}" rel="alternate">{other_tag}</a></span>')

    robots = '  <meta name="robots" content="noindex, follow">\n' if noindex else '  <meta name="robots" content="index, follow, max-image-preview:large">\n'
    og_alt = "".join(f'  <meta property="og:locale:alternate" content="{T[l]["locale"]}">\n' for l in LANGS if l != lang and l in alt)
    foot_links = (f'<a href="{docs_index_url(lang)}">{e(t["footer_docs"])}</a>'
                  f'<a href="{doc_url(lang if lang in DOCS_BY_PATH["luxos/luxai.md"]["src"] else "en", "luxos/luxai.md")}">LuxAI</a>'
                  f'<a href="{doc_url(lang if lang in DOCS_BY_PATH["luxos/faq.md"]["src"] else "en", "luxos/faq.md")}">{e(t["faq"])}</a>'
                  f'<a href="{changes_url(lang)}">{e(t["changes"])}</a><a href="/repo/">{e(t["repos"])}</a>'
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
    if home:
        body = '    <span id="top"></span>\n' + body
    if sitemap and not noindex:
        SITEMAP.append((path, alt))
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
  <link rel="icon" href="/assets/luxos-logo.svg" type="image/svg+xml">
  <meta property="og:site_name" content="LuxOS">
  <meta property="og:type" content="{og_type}">
  <meta property="og:title" content="{e(full_title)}">
  <meta property="og:description" content="{e(clip(desc))}">
  <meta property="og:url" content="{canon}">
  <meta property="og:locale" content="{t['locale']}">
{og_alt}  <meta property="og:image" content="{OG_IMAGE}">
  <meta property="og:image:alt" content="{e('LuxOS desktop' if lang == 'en' else 'Plocha LuxOS')}">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{e(full_title)}">
  <meta name="twitter:description" content="{e(clip(desc))}">
  <meta name="twitter:image" content="{OG_IMAGE}">
{jsonld(*ld) if ld else ""}
  <link rel="stylesheet" href="/styles.css?v={stamp}">
  <script src="/script.js?v={stamp}" defer></script>
</head>
<body>
  <script>try{{var t=localStorage.getItem("luxos-theme");if(t?t==="light":matchMedia("(prefers-color-scheme: light)").matches)document.body.classList.add("light")}}catch(e){{}}</script>
  <a class="skip-link" href="#content">{e(t["skip"])}</a>
  <div class="site-bg" aria-hidden="true"><div class="orb orb-one"></div><div class="orb orb-two"></div><div class="blue-horizon"></div></div>
  <header class="site-header shell">
    <a class="brand" href="{hu}" aria-label="{e(t["home_aria"])}"><img src="/assets/luxos-logo.svg" alt="" width="32" height="32"><span>LuxOS</span></a>
    <nav class="desktop-nav" aria-label="{e(t["main_nav"])}">{desk}</nav>
    {switch}
    <button class="theme-toggle" aria-label="{e(t["theme"])}" aria-pressed="false"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M4.93 4.93l1.42 1.42m11.3 11.3 1.42 1.42M2 12h2m16 0h2M4.93 19.07l1.42-1.42m11.3-11.3 1.42-1.42"/></svg><span class="toggle-track"><span class="toggle-knob"></span></span></button>
    <button class="mobile-nav-toggle" aria-label="{e(t["menu"])}" aria-expanded="false"><span></span><span></span><span></span></button>
  </header>
  <nav class="mobile-nav shell" aria-label="{e(t["mobile_nav"])}">{mobile}</nav>
  <main id="content" class="shell">
{body}
    <footer><span>© 2026 LuxOS</span><span class="footer-links">{foot_links}</span></footer>
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
            with open(d["src"][lang]) as f:
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
                       "publisher": {"@type": "Organization", "name": "LuxOS", "url": BASE + "/"}}
            ld = [breadcrumb_ld(*trail), article]
            if d["path"] == "luxos/faq.md":
                ld.append(faq_ld(text))
            write(path.lstrip("/"), shell(lang, path, f"{title} – {t['docs_suffix']}", desc,
                                          layout(content, d["path"]), alt, "docs", stamp, "article", ld,
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
              shell(lang, ipath, f"{t['docs_h1']} – LuxOS" if lang == "cs" else "LuxOS documentation – manual for LuxOS, LuxAI, Lux Code and LSL",
                    t["docs_index_desc"], layout(crumb_html + intro + "\n".join(cards)), ialt, "docs", stamp,
                    "website", [breadcrumb_ld(*trail), coll]))
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


def sitemap_xml(today):
    rows = ['<?xml version="1.0" encoding="UTF-8"?>',
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">']
    for path, alt in sorted(SITEMAP):
        pri = "1.0" if path in ("/", "/cs/") else ("0.8" if path.count("/") <= 2 else "0.6")
        rows.append("  <url>")
        rows.append(f"    <loc>{abs_url(path)}</loc>")
        rows.append(f"    <lastmod>{today}</lastmod>")
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
    with open(os.path.join(SITE, "iso.json")) as f:
        iso = json.load(f)
    release = {"version": ver["VERSION"], "codename": ver["CODENAME"], "channel": "beta",
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
        for name, caption, has_dark in GALLERY[lang]:
            c = e(caption)
            dark = f' data-dark="/assets/shots/{name}-dark-small.webp" data-light="/assets/shots/{name}-light-small.webp"' if has_dark else ""
            full_dark = f' data-full-dark="/assets/shots/{name}-dark.webp"' if has_dark else ""
            gallery.append(f'        <a class="gallery-item" href="/assets/shots/{name}-light.webp"{full_dark} data-caption="{c}">'
                           f'<img src="/assets/shots/{name}-light-small.webp"{dark} width="640" height="360" alt="{c}" loading="lazy">'
                           f'<span>{c}</span></a>')
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
            "DOCS": docs_index_url(lang), "CHANGES": changes_url(lang),
        }
        with open(os.path.join(SITE, f"home.{lang}.html")) as f:
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
        site_ld = {"@context": "https://schema.org", "@type": "WebSite", "name": "LuxOS", "url": BASE + "/",
                   "inLanguage": list(LANGS), "description": T["en"]["home_desc"]}
        app_ld = {"@context": "https://schema.org", "@type": "SoftwareApplication", "name": "LuxOS",
                  "alternateName": f"LuxOS {ver['VERSION']} {ver['CODENAME']}",
                  "applicationCategory": "OperatingSystem", "operatingSystem": "Linux (x86_64)",
                  "softwareVersion": iso["version"], "description": t["home_desc"], "url": abs_url(path),
                  "downloadUrl": f"{BASE}/download/{iso['file']}", "fileSize": fmt_size(iso["size"], "en"),
                  "datePublished": iso["date"], "inLanguage": lang, "image": OG_IMAGE,
                  "license": "https://www.gnu.org/licenses/gpl-3.0.html",
                  "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"},
                  "publisher": {"@type": "Organization", "name": "LuxOS", "url": BASE + "/",
                                "logo": BASE + "/assets/luxos-logo.svg"}}
        write(path.lstrip("/") + "index.html",
              shell(lang, path, t["home_title"], t["home_desc"], text.rstrip("\n"), alt, "", stamp, "website",
                    [site_ld, app_ld], home=True, dialog=True))

    # ---- dokumentace ----
    render_docs(cols, flat, stamp, md_to_html)

    # ---- zmeny ----
    with open(os.path.join(ROOT, "CHANGELOG.md")) as f:
        cs_changes = md_to_html(f.read(), "", "cs")
    with open(os.path.join(CONTENT, "en", "changes.md")) as f:
        en_changes = md_to_html(f.read(), "", "en")
    calt = {l: changes_url(l) for l in LANGS}
    for lang, body in (("en", en_changes), ("cs", cs_changes)):
        t = T[lang]
        trail = [(t["crumb_home"], home_url(lang)), (t["changes"], changes_url(lang))]
        ld = [{"@context": "https://schema.org", "@type": "BreadcrumbList",
               "itemListElement": [{"@type": "ListItem", "position": i + 1, "name": n, "item": abs_url(h)}
                                   for i, (n, h) in enumerate(trail)]}]
        write(changes_url(lang).lstrip("/") + "index.html",
              shell(lang, changes_url(lang), f"{t['changes_title']} – LuxOS", t["changes_desc"],
                    f'    <article class="doc panel">{body}</article>', calt, "changes", stamp, "article", ld))
    # stary odkaz /zmeny/ (puvodne cesky) presmeruje na /cs/zmeny/
    write("zmeny/index.html", '<!doctype html><html lang="cs"><meta charset="utf-8"><title>Seznam změn – LuxOS</title>'
          '<meta http-equiv="refresh" content="0; url=/cs/zmeny/"><link rel="canonical" href="https://luxos.lux-ai.cz/cs/zmeny/">'
          '<meta name="robots" content="noindex"><a href="/cs/zmeny/">Seznam změn</a>\n')
    write("download/index.html", '<!doctype html><html lang="en"><meta charset="utf-8"><title>Download LuxOS</title>'
          '<meta http-equiv="refresh" content="0; url=/#download"><link rel="canonical" href="https://luxos.lux-ai.cz/#download">'
          '<meta name="robots" content="noindex"><a href="/#download">Download LuxOS</a>\n')

    for name in ("styles.css", "script.js"):
        shutil.copy(os.path.join(SITE, name), os.path.join(OUT, name))
    shutil.copytree(os.path.join(SITE, "assets"), os.path.join(OUT, "assets"))
    write("sitemap.xml", sitemap_xml(today))
    write("robots.txt", f"User-agent: *\nAllow: /\nDisallow: /download/\n\nSitemap: {BASE}/sitemap.xml\n")
    print(f"site: LuxOS {ver['VERSION']} (ISO {iso['version']}), pages en {PAGE_COUNT['en']}, cs {PAGE_COUNT['cs']}, "
          f"{len(flat)} documents ({sum(1 for d in flat if 'cs' in d['src'])} also in Czech), "
          f"{len(SITEMAP)} urls in sitemap -> {OUT}")


if __name__ == "__main__":
    main()
