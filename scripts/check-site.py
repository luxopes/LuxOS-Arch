#!/usr/bin/env python3
"""LuxOS - kontrola vysledku scripts/build-site.py (out/site): vnitrni odkazy a kotvy, unikatni
title a description, canonical, hreflang, jedno h1, alt u obrazku, sitemap.xml a robots.txt,
anglicky seznam zmen proti CHANGELOG.md (vsechna vydani a polozky, scripts/changelog_sections.py)
a prepinac jazyka (pevne poradi EN | CS, zvyrazneni aktualniho jazyka). Nic nestahuje (zadne pozadavky na server), jen cte soubory.

  scripts/check-site.py [adresar]      vychozi out/site; navratovy kod 1 pri chybe
"""
import os
import re
import sys
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from urllib.parse import unquote, urldefrag, urljoin, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import changelog_sections  # noqa: E402
import site_html  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = "https://luxos.lux-ai.cz"
# cesty, ktere existuji jen na serveru (ISO, podpisy, repozitare), v out/site nejsou
SERVER_ONLY = ("/repo/", "/download/", "/stats/")
# stranka Pouzivani LuxOS (countme) a dokument, na ktery odkazuje (z luxos-docs docs/luxos/countme.md)
USAGE_PAGES = ("/usage/", "/cs/pouzivani/")
COUNTME_DOC = "/docs/luxos/countme.html"
# veta, kterou Google vyzaduje v zasadach ochrany soukromi aplikace s omezenymi rozsahy (Gmail)
LIMITED_USE = ("LuxOS Mail's use and transfer to any other app of information received from Google APIs will adhere to "
               "the Google API Services User Data Policy, including the Limited Use requirements.")
# nazvy jazyku v prepinaci (title odkazu na druhy jazyk)
LANG_NAMES = {"en": "English", "cs": "Čeština"}


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids, self.links, self.errors = set(), [], []
        self.title, self.desc, self.canon, self.lang, self.h1 = None, None, None, None, 0
        self.hreflang, self.refresh, self.robots = [], None, ""
        self._in_title = False
        # seznam zmen: nadpisy h2 a polozky li (jen primo v clanku) v <article class="doc ...">
        self.article_h2, self.article_li, self._article, self._lists = 0, 0, False, 0
        # prepinac jazyka: [(lang, aria-current)] a zda ma vrstvu zvyrazneni
        self.switch, self.switch_pill, self.switch_active, self._in_switch = [], False, None, 0
        self.switch_titles = {}

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids.add(a["id"])
        cls = (a.get("class") or "").split()
        if not site_html.known(tag):
            self.errors.append(f"unknown element <{tag}> (unescaped <...> placeholder in markdown?)")
        if tag == "article" and "doc" in cls:
            self._article = True
        elif self._article and tag in ("ul", "ol"):
            self._lists += 1
        elif self._article and tag == "h2":
            self.article_h2 += 1
        elif self._article and tag == "li" and self._lists == 1:
            self.article_li += 1
        if tag == "span" and "lang-switch" in cls and not self.switch:
            self._in_switch, self.switch_active = 1, a.get("data-active")
        elif self._in_switch and tag == "a":
            self.switch.append((a.get("lang"), "aria-current" in a))
            self.switch_titles[a.get("lang")] = a.get("title")
        elif self._in_switch and tag == "span":
            self._in_switch += 1
            self.switch_pill = self.switch_pill or "lang-pill" in cls
        if tag == "html":
            self.lang = a.get("lang")
        elif tag == "title":
            self._in_title = True
            self.title = ""
        elif tag == "h1":
            self.h1 += 1
        elif tag == "meta":
            n = (a.get("name") or "").lower()
            if n == "description":
                self.desc = a.get("content", "")
            elif n == "robots":
                self.robots = a.get("content", "")
            elif (a.get("http-equiv") or "").lower() == "refresh":
                self.refresh = a.get("content", "")
        elif tag == "link":
            rel = a.get("rel", "")
            if rel == "canonical":
                self.canon = a.get("href")
            elif rel == "alternate" and a.get("hreflang"):
                self.hreflang.append((a["hreflang"], a.get("href")))
            elif a.get("href"):
                self.links.append(a["href"])
        elif tag == "a" and a.get("href"):
            self.links.append(a["href"])
        elif tag in ("script", "img", "source") and a.get("src"):
            self.links.append(a["src"])
        # obrazky pro druhy vzhled a velikosti (srcset, data-light/-dark, data-full-dark): soubor musi existovat,
        # jinak by se snimek po prepnuti vzhledu nebo na jinem displeji nenacetl
        if tag in ("img", "source"):
            for k in ("srcset", "data-light-srcset", "data-dark-srcset"):
                for part in (a.get(k) or "").split(","):
                    if part.strip():
                        self.links.append(part.split()[0])
            for k in ("data-light", "data-dark"):
                if a.get(k):
                    self.links.append(a[k])
        if tag == "a" and a.get("data-full-dark"):
            self.links.append(a["data-full-dark"])
        if tag == "img" and "alt" not in a:
            self.errors.append(f"img without alt: {a.get('src')}")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag == "article":
            self._article = False
        elif self._article and tag in ("ul", "ol"):
            self._lists -= 1
        elif tag == "span" and self._in_switch:
            self._in_switch -= 1

    def handle_data(self, data):
        if self._in_title:
            self.title += data


def main():
    out = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "out", "site"))
    pages = {}
    for dp, _dn, files in os.walk(out):
        for fn in files:
            if fn.endswith(".html"):
                path = os.path.join(dp, fn)
                p = Page()
                with open(path, encoding="utf-8") as f:
                    p.feed(f.read())
                pages[path] = p
    errors = []

    def url_of(path):
        rel = "/" + os.path.relpath(path, out).replace(os.sep, "/")
        return rel[:-len("index.html")] if rel.endswith("/index.html") else rel

    def resolve(href, base_url):
        """vraci (soubor nebo None, fragment) pro vnitrni odkaz; None pro vnejsi."""
        if re.match(r"^(mailto|tel|javascript|data):", href):
            return None, None
        full = urljoin(BASE + base_url, href)
        u = urlparse(full)
        if u.netloc and u.netloc != "luxos.lux-ai.cz":
            return None, None
        path = unquote(u.path)
        return path, u.fragment

    def exists(path):
        f = os.path.join(out, path.lstrip("/"))
        if path.endswith("/"):
            f = os.path.join(f, "index.html")
        return f if os.path.isfile(f) else None

    seen_title, seen_desc = {}, {}
    n_links = 0
    for path, p in sorted(pages.items()):
        url = url_of(path)
        indexable = "noindex" not in p.robots and p.refresh is None
        for err in p.errors:
            errors.append(f"{url}: {err}")
        if p.refresh is not None:
            continue
        if not p.lang:
            errors.append(f"{url}: missing <html lang>")
        if not p.title or not p.title.strip():
            errors.append(f"{url}: missing <title>")
        elif indexable:
            if p.title in seen_title:
                errors.append(f"{url}: duplicate title with {seen_title[p.title]}")
            seen_title[p.title] = url
            if len(p.title) > 90:
                errors.append(f"{url}: title too long ({len(p.title)})")
        if not p.desc:
            errors.append(f"{url}: missing meta description")
        elif indexable:
            if p.desc in seen_desc:
                errors.append(f"{url}: duplicate description with {seen_desc[p.desc]}")
            seen_desc[p.desc] = url
            if len(p.desc) > 165:
                errors.append(f"{url}: description too long ({len(p.desc)})")
        if indexable and p.canon != BASE + url:
            errors.append(f"{url}: canonical is {p.canon}, expected {BASE + url}")
        if indexable and p.h1 != 1:
            errors.append(f"{url}: {p.h1} <h1> elements (expected 1)")
        for lang, href in p.hreflang:
            hp, _ = resolve(href, url)
            if hp is None or not exists(hp):
                errors.append(f"{url}: hreflang {lang} -> {href} does not exist")
        for href in p.links:
            n_links += 1
            fp, frag = resolve(href, url)
            if fp is None:
                continue
            f = exists(fp)
            if f is None:
                if fp.startswith(SERVER_ONLY) and not fp.rstrip("/").endswith("download"):
                    continue
                errors.append(f"{url}: broken link {href}")
                continue
            if frag and f.endswith(".html") and f in pages and frag not in pages[f].ids:
                errors.append(f"{url}: missing anchor {href}")

    # prepinac jazyka: vsude stejne poradi EN | CS (zvyrazneni prejizdi), aktualni jazyk = jazyk stranky
    for path, p in sorted(pages.items()):
        if p.refresh is not None or not p.switch:
            continue
        url = url_of(path)
        langs = [l for l, _cur in p.switch]
        current = [l for l, cur in p.switch if cur]
        if langs != ["en", "cs"]:
            errors.append(f"{url}: language switch order {langs}, expected ['en', 'cs']")
        if current != [p.lang]:
            errors.append(f"{url}: language switch marks {current} as current, page is {p.lang}")
        elif p.switch_active != str(langs.index(p.lang)):
            errors.append(f"{url}: language switch data-active={p.switch_active}, expected {langs.index(p.lang)}")
        if not p.switch_pill:
            errors.append(f"{url}: language switch without .lang-pill")
        for l, name in LANG_NAMES.items():
            if l != p.lang and p.switch_titles.get(l) not in (None, name):
                errors.append(f"{url}: language switch link {l} has title {p.switch_titles[l]!r}, expected {name!r}")

    # seznam zmen: anglicky preklad ma vsechna vydani a polozky z CHANGELOG.md
    errors.extend(changelog_sections.verify())
    en_ch, cs_ch = exists("/changes/"), exists("/cs/zmeny/")
    if en_ch and cs_ch:
        en_p, cs_p = pages[en_ch], pages[cs_ch]
        if (en_p.article_h2, en_p.article_li) != (cs_p.article_h2, cs_p.article_li):
            errors.append(f"/changes/: {en_p.article_h2} releases and {en_p.article_li} items, "
                          f"/cs/zmeny/ has {cs_p.article_h2} and {cs_p.article_li}")
    else:
        errors.append("changes pages /changes/ or /cs/zmeny/ missing")

    # sitemap a robots
    sm = os.path.join(out, "sitemap.xml")
    if not os.path.isfile(sm):
        errors.append("missing sitemap.xml")
    else:
        ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        locs = [x.text for x in ET.parse(sm).getroot().findall("s:url/s:loc", ns)]
        for loc in locs:
            path = loc[len(BASE):] if loc.startswith(BASE) else None
            if path is None or not exists(path):
                errors.append(f"sitemap: {loc} does not exist")
        listed = {l[len(BASE):] for l in locs}
        for path, p in pages.items():
            if "noindex" not in p.robots and p.refresh is None and url_of(path) not in listed:
                errors.append(f"{url_of(path)}: not in sitemap.xml")
    rb = os.path.join(out, "robots.txt")
    if not os.path.isfile(rb) or "Sitemap: " + BASE + "/sitemap.xml" not in open(rb).read():
        errors.append("robots.txt missing or without Sitemap line")

    # countme: stranky o pouzivani a jejich skript; dokument countme muze chybet, dokud neni v luxos-docs
    warnings = []
    for up in USAGE_PAGES:
        f = exists(up)
        if f is None:
            errors.append(f"{up}: usage page missing")
            continue
        p = pages[f]
        if not any(l.startswith("/usage.js") for l in p.links):
            errors.append(f"{up}: usage.js not loaded")
        if not any(l.startswith(("/docs/luxos/countme.html", "/cs/docs/luxos/countme.html")) for l in p.links):
            warnings.append(f"{up}: no link to {COUNTME_DOC} (luxos/countme.md not in luxos-docs yet?)")
    if exists(COUNTME_DOC) is None:
        warnings.append(f"{COUNTME_DOC} does not exist yet (packages/apps/luxos-docs/docs/luxos/countme.md + index.json)")

    # overeni aplikace OAuth u Googlu: domovska stranka Posty a zasady ochrany soukromi na stejne domene,
    # oddil o datech Google s presnou vetou Limited Use, odkazy na zasady z domovske stranky a z paticky
    for up in ("/mail/", "/cs/mail/", "/privacy/", "/cs/privacy/", "/terms/", "/cs/terms/"):
        f = exists(up)
        if f is None:
            errors.append(f"{up}: page missing (Google OAuth verification)")
            continue
        text = re.sub(r"<[^>]+>", "", open(f, encoding="utf-8").read())
        text = re.sub(r"\s+", " ", text)
        if up.endswith("/privacy/"):
            if "google-user-data" not in pages[f].ids:
                errors.append(f"{up}: missing #google-user-data section")
            if LIMITED_USE not in text:
                errors.append(f"{up}: missing the Limited Use disclosure sentence")
        if up.endswith("/mail/"):
            if not any(l.startswith(("/privacy/", "/cs/privacy/")) for l in pages[f].links):
                errors.append(f"{up}: no link to the privacy policy")
            if "LuxOS Mail" not in text:
                errors.append(f"{up}: app name LuxOS Mail missing")
    for path, p in pages.items():
        if p.refresh is None and not any(l in ("/privacy/", "/cs/privacy/") for l in p.links):
            errors.append(f"{url_of(path)}: no footer link to the privacy policy")

    print(f"check-site: {len(pages)} html pages, {n_links} links checked, {len(errors)} problems")
    for err in errors[:80]:
        print("  " + err)
    if len(errors) > 80:
        print(f"  ... and {len(errors) - 80} more")
    for w in warnings:
        print("  warning: " + w)
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
