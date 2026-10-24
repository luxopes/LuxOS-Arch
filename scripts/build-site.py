#!/usr/bin/env python3
"""LuxOS - sestaveni webu https://luxos.lux-ai.cz do out/site (nahrava scripts/publish-site.sh).

  scripts/build-site.py

Zdroje: site/ (stranka, styly, skript, obrazky), site/iso.json (posledni ISO - meni se jen
s novym ISO), verze z packages/luxos-branding/files/version, dokumentace z luxos-docs
(packages/apps/luxos-docs/docs, stejna jako offline v LuxOS) a CHANGELOG.md.
Vystup: index.html, release.json (aktualni vydani, nacita ho i stranka), docs/, zmeny/,
download/index.html (presmerovani na /#download - ISO a podpisy zustavaji v /download/).
"""
import html
import json
import os
import re
import shutil
import sys
import time

import markdown

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, "site")
OUT = os.path.join(ROOT, "out", "site")
DOCS = os.path.join(ROOT, "packages", "apps", "luxos-docs", "docs")
FINGERPRINT = "FD18 5DAB 7701 40E8 9C37 275E 7035 CFDF DCA6 C991"
MONTHS = ["ledna", "února", "března", "dubna", "května", "června", "července", "srpna", "září",
          "října", "listopadu", "prosince"]

GALLERY = [
    ("launchpad", "Launchpad – všechny aplikace a dotaz pro LuxAI", True),
    ("control-center", "Ovládací centrum", True),
    ("calendar", "Kalendář z horní lišty", True),
    ("store", "Lux Store – aplikace jedním kliknutím", True),
    ("files-terminal", "Soubory a Terminál", False),
    ("luxai", "LuxAI – asistent, který rozumí vašemu počítači", False),
]


def read_kv(path):
    out = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"')
    return out


def cs_date(iso):
    y, m, d = (int(x) for x in iso.split("-"))
    return f"{d}. {MONTHS[m - 1]} {y}"


def cs_size(n):
    return f"{n / 2 ** 30:.1f}".replace(".", ",") + " GB"


def write(rel, text):
    path = os.path.join(OUT, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def page(title, body, description="LuxOS – rychlý a lehký Linux s krásným prostředím.", stamp=""):
    """Podstranka (dokumentace, zmeny) se stejnou hlavickou jako hlavni stranka."""
    e = html.escape
    return f"""<!doctype html>
<html lang="cs">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#080b16">
  <meta name="description" content="{e(description)}">
  <title>{e(title)} – LuxOS</title>
  <link rel="icon" href="/assets/luxos-logo.svg" type="image/svg+xml">
  <link rel="stylesheet" href="/styles.css?v={stamp}">
  <script src="/script.js?v={stamp}" defer></script>
</head>
<body>
  <script>try{{var t=localStorage.getItem("luxos-theme");if(t?t==="light":matchMedia("(prefers-color-scheme: light)").matches)document.body.classList.add("light")}}catch(e){{}}</script>
  <div class="site-bg" aria-hidden="true"><div class="orb orb-one"></div><div class="orb orb-two"></div><div class="blue-horizon"></div></div>
  <header class="site-header shell">
    <a class="brand" href="/" aria-label="LuxOS – domů"><img src="/assets/luxos-logo.svg" alt=""><span>LuxOS</span></a>
    <nav class="desktop-nav" aria-label="Hlavní navigace"><a href="/">Domů</a><a href="/#gallery">Galerie</a><a href="/#download">Stáhnout</a><a href="/docs/"{' class="active"' if title != "Změny" else ''}>Dokumentace</a><a href="/zmeny/"{' class="active"' if title == "Změny" else ''}>Změny</a></nav>
    <button class="theme-toggle" aria-label="Přepnout světlý a tmavý režim" aria-pressed="false"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M4.93 4.93l1.42 1.42m11.3 11.3 1.42 1.42M2 12h2m16 0h2M4.93 19.07l1.42-1.42m11.3-11.3 1.42-1.42"/></svg><span class="toggle-track"><span class="toggle-knob"></span></span></button>
    <button class="mobile-nav-toggle" aria-label="Otevřít nabídku" aria-expanded="false"><span></span><span></span><span></span></button>
  </header>
  <nav class="mobile-nav shell" aria-label="Mobilní navigace"><a href="/">Domů</a><a href="/#gallery">Galerie</a><a href="/#download">Stáhnout</a><a href="/docs/">Dokumentace</a><a href="/zmeny/">Změny</a></nav>
  <main class="shell">
{body}
    <footer><span>© 2026 LuxOS</span><span class="footer-links"><a href="/docs/">Dokumentace</a><a href="/zmeny/">Změny</a><a href="/repo/">Repozitáře</a><a href="https://github.com/luxopes/luxos-kernel">Jádro na GitHubu</a><a href="https://lux-ai.cz">lux-ai.cz</a></span></footer>
  </main>
</body>
</html>
"""


def md_to_html(text, current_dir):
    """Markdown dokumentace -> HTML; odkazy na .md vedou na .html stranky webu."""
    out = markdown.markdown(text, extensions=["tables", "fenced_code", "sane_lists", "toc"],
                            output_format="html")

    def fix(m):
        href = m.group(2)
        if re.match(r"^[a-z]+:", href) or href.startswith("#"):
            return m.group(0)
        path, _sep, frag = href.partition("#")
        if path.endswith(".md"):
            path = path[:-3] + ".html"
        return f'{m.group(1)}{path}{"#" + frag if frag else ""}"'
    return re.sub(r'(<a href=")([^"]+)"', fix, out)


def build_docs(stamp):
    with open(os.path.join(DOCS, "index.json")) as f:
        index = json.load(f)
    nav_parts = []
    for col in index["collections"]:
        nav_parts.append(f"<h3>{html.escape(col['title'])}</h3>")
        for doc in col["files"]:
            nav_parts.append(f'<a href="/docs/{doc["path"][:-3]}.html" data-path="{doc["path"]}">{html.escape(doc["title"])}</a>')
    nav_html = "\n".join(nav_parts)

    def layout(content, current=""):
        nav = nav_html.replace(f'data-path="{current}">', f'data-path="{current}" class="current">') if current else nav_html
        return f'    <div class="doc-layout"><nav class="doc-nav panel" aria-label="Dokumentace">{nav}</nav><article class="doc panel">{content}</article></div>'

    cards = []
    for col in index["collections"]:
        cards.append(f"<h2>{html.escape(col['title'])}</h2><ul class=\"doc-index\">")
        for doc in col["files"]:
            src = os.path.join(DOCS, doc["path"])
            with open(src) as f:
                text = f.read()
            body = md_to_html(text, os.path.dirname(doc["path"]))
            write(f"docs/{doc['path'][:-3]}.html",
                  page(doc["title"], layout(body, doc["path"]), doc.get("summary", ""), stamp))
            cards.append(f'<li><a href="/docs/{doc["path"][:-3]}.html"><strong>{html.escape(doc["title"])}</strong>'
                         f'<span>{html.escape(doc.get("summary", ""))}</span></a></li>')
        cards.append("</ul>")
    intro = ('<h1>Dokumentace</h1><p class="lead">Stejná příručka, jakou má LuxOS offline (balík luxos-docs) '
             'a ze které čerpá i LuxAI. Je v angličtině.</p>')
    write("docs/index.html", page("Dokumentace", layout(intro + "\n".join(cards)), stamp=stamp))
    return sum(len(c["files"]) for c in index["collections"])


def main():
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT)
    stamp = time.strftime("%Y%m%d%H%M")
    ver = read_kv(os.path.join(ROOT, "packages", "luxos-branding", "files", "version"))
    with open(os.path.join(SITE, "iso.json")) as f:
        iso = json.load(f)
    release = {"version": ver["VERSION"], "codename": ver["CODENAME"], "channel": "beta",
               "iso": iso, "repo": "https://luxos.lux-ai.cz/repo/", "fingerprint": FINGERPRINT}
    write("release.json", json.dumps(release, ensure_ascii=False, indent=2) + "\n")

    gallery = []
    for name, caption, has_dark in GALLERY:
        e = html.escape(caption)
        dark = f' data-dark="/assets/shots/{name}-dark-small.webp" data-light="/assets/shots/{name}-light-small.webp"' if has_dark else ""
        full_dark = f' data-full-dark="/assets/shots/{name}-dark.webp"' if has_dark else ""
        gallery.append(f'        <a class="gallery-item" href="/assets/shots/{name}-light.webp"{full_dark} data-caption="{e}">'
                       f'<img src="/assets/shots/{name}-light-small.webp"{dark} width="640" height="360" alt="{e}" loading="lazy">'
                       f'<span>{e}</span></a>')
    values = {
        "VERSION": ver["VERSION"], "CODENAME": ver["CODENAME"], "ISO_VERSION": iso["version"],
        "ISO_FILE": iso["file"], "ISO_SIZE": cs_size(iso["size"]), "ISO_DATE": cs_date(iso["date"]),
        "ISO_SHA256": iso["sha256"], "FINGERPRINT": FINGERPRINT, "STAMP": stamp,
        "UPDATE_HIDDEN": "" if ver["VERSION"] != iso["version"] else " hidden",
        "GALLERY": "\n".join(gallery),
    }
    with open(os.path.join(SITE, "index.html")) as f:
        text = f.read()
    for k, v in values.items():
        text = text.replace("{{" + k + "}}", v)
    left = re.findall(r"\{\{[A-Z_]+\}\}", text)
    if left:
        sys.exit(f"build-site: unfilled placeholders {left}")
    write("index.html", text)
    for name in ("styles.css", "script.js"):
        shutil.copy(os.path.join(SITE, name), os.path.join(OUT, name))
    shutil.copytree(os.path.join(SITE, "assets"), os.path.join(OUT, "assets"))

    n = build_docs(stamp)
    with open(os.path.join(ROOT, "CHANGELOG.md")) as f:
        changes = md_to_html(f.read(), "")
    write("zmeny/index.html", page("Změny", f'    <article class="doc panel">{changes}</article>',
                                   "Seznam změn v jednotlivých verzích LuxOS.", stamp))
    write("download/index.html", '<!doctype html><meta charset="utf-8"><title>Stáhnout LuxOS</title>'
          '<meta http-equiv="refresh" content="0; url=/#download"><link rel="canonical" href="/#download">'
          '<a href="/#download">Stáhnout LuxOS</a>\n')
    print(f"site: LuxOS {ver['VERSION']} (ISO {iso['version']}), {n} documentation pages -> {OUT}")


if __name__ == "__main__":
    main()
