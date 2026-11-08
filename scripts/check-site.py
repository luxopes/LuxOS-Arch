#!/usr/bin/env python3
"""LuxOS - kontrola vysledku scripts/build-site.py (out/site): vnitrni odkazy a kotvy, unikatni
title a description, canonical, hreflang, jedno h1, alt u obrazku, sitemap.xml a robots.txt,
anglicky seznam zmen proti CHANGELOG.md (vsechna vydani a polozky, scripts/changelog_sections.py)
a prepinac jazyka (pevne poradi EN | CS, zvyrazneni aktualniho jazyka), strukturovana data JSON-LD,
llms.txt a llms-full.txt a klic IndexNow. Nic nestahuje (zadne pozadavky na server), jen cte soubory.

  scripts/check-site.py [adresar]      vychozi out/site; navratovy kod 1 pri chybe
"""
import json
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
        # strukturovana data: text kazdeho <script type="application/ld+json">
        self.ld, self._in_ld = [], False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "script" and (a.get("type") or "").lower() == "application/ld+json":
            self._in_ld = True
            self.ld.append("")
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
        if tag == "script":
            self._in_ld = False
        if tag == "title":
            self._in_title = False
        elif tag == "article":
            self._article = False
        elif self._article and tag in ("ul", "ol"):
            self._lists -= 1
        elif tag == "span" and self._in_switch:
            self._in_switch -= 1

    def handle_data(self, data):
        if self._in_ld:
            self.ld[-1] += data
        if self._in_title:
            self.title += data


def ld_nodes(value):
    """Vsechny objekty (dict) ve strukturovanych datech, rekurzivne."""
    if isinstance(value, dict):
        yield value
        for v in value.values():
            yield from ld_nodes(v)
    elif isinstance(value, list):
        for v in value:
            yield from ld_nodes(v)


def ld_types(node):
    t = node.get("@type")
    return set(t) if isinstance(t, list) else ({t} if t else set())


def check_jsonld(pages, url_of, exists, out):
    """JSON-LD: platny JSON, @context schema.org, typy s povinnymi poli, odkazy @id na entity definovane na webu,
    URL v url/item existuji, uvodni stranky maji Organization + WebSite + SoftwareApplication s aktualni verzi."""
    errors, defined, refs = [], set(), []
    try:
        with open(os.path.join(out, "release.json"), encoding="utf-8") as f:
            iso_version = json.load(f)["iso"]["version"]
    except (OSError, ValueError, KeyError):
        iso_version = None
        errors.append("release.json missing or invalid (needed to check softwareVersion)")

    def local(u):
        return u.startswith(BASE) and not urlparse(u).path.startswith(SERVER_ONLY)

    for path, p in sorted(pages.items()):
        url = url_of(path)
        if p.refresh is not None:
            continue
        indexable = "noindex" not in p.robots
        if indexable and not p.ld:
            errors.append(f"{url}: no JSON-LD structured data")
        types_on_page = set()
        for raw in p.ld:
            try:
                data = json.loads(raw)
            except ValueError as ex:
                errors.append(f"{url}: invalid JSON-LD ({ex})")
                continue
            blocks = data if isinstance(data, list) else [data]
            for b in blocks:
                if not isinstance(b, dict) or b.get("@context") not in ("https://schema.org", "https://schema.org/"):
                    errors.append(f"{url}: JSON-LD block without @context https://schema.org")
                    continue
                if "@type" not in b and "@graph" not in b:
                    errors.append(f"{url}: JSON-LD block without @type or @graph")
            for node in ld_nodes(data):
                keys = set(node) - {"@context"}
                if keys == {"@id"}:
                    refs.append((url, node["@id"]))
                    continue
                types = ld_types(node)
                types_on_page |= types
                if "@id" in node and types:
                    defined.add(node["@id"])
                for k in ("url", "item"):
                    v = node.get(k)
                    if isinstance(v, str) and local(v) and not exists(urlparse(v).path or "/"):
                        errors.append(f"{url}: JSON-LD {k} {v} does not exist")
                if "SoftwareApplication" in types:
                    for k in ("name", "applicationCategory", "operatingSystem", "offers"):
                        if not node.get(k):
                            errors.append(f"{url}: SoftwareApplication without {k}")
                    if "price" not in (node.get("offers") or {}):
                        errors.append(f"{url}: SoftwareApplication offers without price")
                if "FAQPage" in types:
                    qs = node.get("mainEntity") or []
                    if not qs:
                        errors.append(f"{url}: FAQPage without questions")
                    for q in qs:
                        ans = (q.get("acceptedAnswer") or {}).get("text", "")
                        if "Question" not in ld_types(q) or not q.get("name") or not ans.strip():
                            errors.append(f"{url}: FAQPage question without name or answer: {q.get('name')!r}")
                if "BreadcrumbList" in types:
                    items = node.get("itemListElement") or []
                    if [i.get("position") for i in items] != list(range(1, len(items) + 1)) or not items:
                        errors.append(f"{url}: BreadcrumbList positions are not 1..n")
                    if items and items[-1].get("item") != BASE + url:
                        errors.append(f"{url}: last breadcrumb item is {items[-1].get('item')}, expected {BASE + url}")
                if "TechArticle" in types:
                    if not node.get("headline"):
                        errors.append(f"{url}: TechArticle without headline")
                    if node.get("url") != BASE + url:
                        errors.append(f"{url}: TechArticle url {node.get('url')} is not the page URL")
        if url in ("/", "/cs/"):
            for need in ("Organization", "WebSite", "SoftwareApplication", "Person"):
                if need not in types_on_page:
                    errors.append(f"{url}: JSON-LD missing {need}")
            apps = [n for raw in p.ld for n in ld_nodes(json.loads(raw)) if "SoftwareApplication" in ld_types(n)]
            for a in apps:
                if iso_version and a.get("softwareVersion") != iso_version:
                    errors.append(f"{url}: SoftwareApplication softwareVersion {a.get('softwareVersion')}, ISO is {iso_version}")
                for s in a.get("screenshot") or []:
                    if not exists(urlparse(s).path):
                        errors.append(f"{url}: JSON-LD screenshot {s} does not exist")
    for url, ref in refs:
        if ref not in defined:
            errors.append(f"{url}: JSON-LD reference {ref} is not defined on any page")
    return errors


def check_llms_indexnow(out, exists):
    """llms.txt (llmstxt.org: # nazev, > shrnuti, odkazy existuji, aktualni verze), llms-full.txt, klic IndexNow."""
    errors = []
    f = os.path.join(out, "llms.txt")
    if not os.path.isfile(f):
        errors.append("missing llms.txt")
    else:
        text = open(f, encoding="utf-8").read()
        lines = text.splitlines()
        if not lines or lines[0] != "# LuxOS":
            errors.append("llms.txt: first line must be '# LuxOS'")
        if not any(l.startswith("> ") for l in lines[:4]):
            errors.append("llms.txt: missing '> summary' line after the title")
        try:
            with open(os.path.join(out, "release.json"), encoding="utf-8") as rf:
                version = json.load(rf)["version"]
            if f"Current version: {version} " not in text:
                errors.append(f"llms.txt: does not state the current version {version}")
        except (OSError, ValueError, KeyError):
            pass
        for href in re.findall(r"\]\((https?://[^)\s]+)\)", text):
            u = urlparse(href)
            if u.netloc == "luxos.lux-ai.cz" and not exists(u.path or "/"):
                errors.append(f"llms.txt: broken link {href}")
    full = os.path.join(out, "llms-full.txt")
    if not os.path.isfile(full) or os.path.getsize(full) < 10000:
        errors.append("llms-full.txt missing or too short")
    elif "# LuxOS FAQ" not in open(full, encoding="utf-8").read():
        errors.append("llms-full.txt: FAQ section missing")
    key_src = os.path.join(ROOT, "site", "indexnow-key.txt")
    key = open(key_src).read().strip() if os.path.isfile(key_src) else ""
    if not re.fullmatch(r"[A-Za-z0-9-]{8,128}", key):
        errors.append("site/indexnow-key.txt missing or invalid")
    else:
        kf = os.path.join(out, key + ".txt")
        if not os.path.isfile(kf) or open(kf).read().strip() != key:
            errors.append(f"IndexNow key file /{key}.txt missing or wrong content")
    return errors


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

    errors.extend(check_jsonld(pages, url_of, exists, out))
    errors.extend(check_llms_indexnow(out, exists))

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
