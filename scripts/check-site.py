#!/usr/bin/env python3
"""LuxOS - kontrola vysledku scripts/build-site.py (out/site): vnitrni odkazy a kotvy, unikatni
title a description, canonical, hreflang, jedno h1, alt u obrazku, sitemap.xml a robots.txt.
Nic nestahuje (zadne pozadavky na server), jen cte soubory.

  scripts/check-site.py [adresar]      vychozi out/site; navratovy kod 1 pri chybe
"""
import os
import re
import sys
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from urllib.parse import unquote, urldefrag, urljoin, urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = "https://luxos.lux-ai.cz"
# cesty, ktere existuji jen na serveru (ISO, podpisy, repozitare), v out/site nejsou
SERVER_ONLY = ("/repo/", "/download/")


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids, self.links, self.errors = set(), [], []
        self.title, self.desc, self.canon, self.lang, self.h1 = None, None, None, None, 0
        self.hreflang, self.refresh, self.robots = [], None, ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids.add(a["id"])
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
        if tag == "img" and "alt" not in a:
            self.errors.append(f"img without alt: {a.get('src')}")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

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

    print(f"check-site: {len(pages)} html pages, {n_links} links checked, {len(errors)} problems")
    for err in errors[:80]:
        print("  " + err)
    if len(errors) > 80:
        print(f"  ... and {len(errors) - 80} more")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
