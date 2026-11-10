"""Zobrazeni zpravy (luxos-mail --test-view): bezpecny dokument HTML pro WebKit. Zakerne HTML bez skriptu, obsluh
udalosti, formularu, iframe a nebezpecnych odkazu; vzdalene obrazky a sledovaci pixely blokovane (a CSP v dokumentu);
prosty text s odkazy, citacemi jako bloky, podpisem a tabulkou z ASCII; vlozene obrazky cid: jako data:; tmavy vzhled.
"""
import html.parser
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mailtest as mt  # noqa: E402

VIEW = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures-view")
FORBIDDEN_TAGS = {"script", "iframe", "frame", "frameset", "object", "embed", "applet", "form", "input", "button", "textarea",
                  "select", "svg", "math", "link", "base", "audio", "video", "canvas", "template", "noscript"}


class Dom(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags = []
        self.links = []
        self.images = []
        self.depth = 0
        self.max_quote = 0
        self.text = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self.tags.append((tag, a))
        if tag == "a" and "href" in a:
            self.links.append(a["href"])
        if tag == "img":
            self.images.append(a.get("src", ""))
        if tag == "blockquote":
            self.depth += 1
            self.max_quote = max(self.max_quote, self.depth)

    def handle_endtag(self, tag):
        if tag == "blockquote":
            self.depth -= 1

    def handle_data(self, data):
        self.text.append(data)


def view(name, *flags):
    r = mt.run_bin(["--test-view", os.path.join(VIEW, name + ".eml")] + list(flags))
    if r.returncode != 0:
        raise AssertionError(r.stderr.decode())
    d = json.loads(r.stdout)
    dom = Dom()
    dom.feed(d["html"])
    d["dom"] = dom
    return d


class ViewTest(unittest.TestCase):
    def assert_safe(self, d):
        h = d["html"]
        # CSP: nic ze site (jen data:), zadne formulare
        self.assertIn("default-src 'none'", h)
        self.assertIn("form-action 'none'", h)
        metas = [a for t, a in d["dom"].tags if t == "meta"]
        self.assertEqual(len([m for m in metas if m.get("http-equiv", "").lower() == "refresh"]), 0)
        for tag, attrs in d["dom"].tags:
            self.assertNotIn(tag, FORBIDDEN_TAGS, tag)
            for k, v in attrs.items():
                self.assertFalse(k.startswith("on"), (tag, k))
                if k in ("href", "src", "background"):
                    low = (v or "").strip().lower()
                    self.assertTrue(low.startswith(("http://", "https://", "mailto:", "tel:", "#", "data:image/")), (tag, k, v))
                    self.assertFalse(low.startswith("data:image/svg"))
                if k == "style":
                    self.assertNotIn("expression(", v.lower())
                    self.assertNotIn("javascript:", v.lower())

    def test_malicious_html_is_sanitized(self):
        d = view("malicious")
        self.assert_safe(d)
        self.assertEqual(d["dom"].links, ["https://legit.example.org/ok", "https://legit.example.org/"])
        self.assertEqual(d["dom"].images, [])
        self.assertEqual(d["tracking"], 1)
        text = "".join(d["dom"].text)
        self.assertIn("Konec ZAKERNE_KONEC", text)
        self.assertIn("Gratulujeme", text)
        self.assertNotIn("alert(1", text.replace("alert(14)", ""))
        self.assertNotIn("document.cookie", d["html"])

    def test_remote_images_blocked_until_allowed(self):
        d = view("newsletter")
        self.assert_safe(d)
        self.assertEqual(d["remote"], 3)
        self.assertFalse(any(s.startswith("http") for s in d["dom"].images))
        self.assertNotIn("127.0.0.1:9", d["html"])
        # alt text misto obrazku, vlastni styly zpravy zustaly (bez @import a vzdaleneho pozadi)
        self.assertIn("Tip 1: klávesové zkratky", "".join(d["dom"].text))
        self.assertIn(".card {", d["html"])
        self.assertNotIn("@import", d["html"])
        a = view("newsletter", "--remote")
        self.assertEqual(a["remote"], 0)
        self.assertIn("img-src data: https: http:", a["html"])
        self.assertEqual(len([s for s in a["dom"].images if s.startswith("http://127.0.0.1:9/tip")]), 2)
        self.assertIn("url(\"http://127.0.0.1:9/hero.jpg\")", a["html"])
        # @import a <link rel=stylesheet> ani s povolenim
        self.assertNotIn("import.css", a["html"])
        self.assertNotIn("style.css", a["html"])

    def test_tracking_pixel_never_loaded(self):
        d = view("security-alert", "--remote")
        self.assertEqual(d["tracking"], 1)
        self.assertFalse(any("open-pixel" in s for s in d["dom"].images))
        self.assertTrue(any(s.endswith("/logo.png") for s in d["dom"].images))
        self.assertIn("https://myaccount.example.com/notifications?x=1&y=2", d["dom"].links)
        # HTML zprava s vlastnimi barvami: bily papir i v tmavem vzhledu
        dark = view("security-alert", "--dark")
        self.assertTrue(dark["paper"])
        self.assertIn("background:#ffffff", dark["html"])

    def test_plain_text_links_quotes_signature_table(self):
        d = view("links-plain")
        self.assert_safe(d)
        self.assertEqual(d["dom"].links, [
            "https://example.cz/dokumenty/zprava.pdf", "https://www.example.cz", "mailto:podpora@example.cz",
            "mailto:info@example.cz?subject=Dotaz",
            "https://example.cz/velmi/dlouha/cesta/ktera/se/musi/zalomit/aby/se/vesla/do/okna?parametr=hodnota&dalsi=123#kotva",
            "https://example.cz/a_(b)", "https://example.cz/konec"])
        pre = [a for t, a in d["dom"].tags if t == "pre"]
        self.assertEqual(len(pre), 1)
        self.assertIn("| leden  | 12 000  | 8 000 |", d["html"])
        t = view("reply-thread")
        self.assertEqual(t["dom"].max_quote, 3)
        self.assertNotIn("&gt; Petře", t["html"])
        self.assertIn('<div class="sig">', t["html"])
        self.assertIn("https://www.example.org", t["dom"].links)
        dark = view("reply-thread", "--dark")
        self.assertIn("background:#232325", dark["html"])
        self.assertFalse(dark["paper"])

    def test_inline_image_and_image_attachment_preview(self):
        d = view("inline-image")
        self.assert_safe(d)
        self.assertEqual(d["inline"], ["foto1@example"])
        self.assertEqual(len(d["dom"].images), 2)
        self.assertTrue(all(s.startswith("data:image/png;base64,") for s in d["dom"].images))

    def test_existing_fixtures_render(self):
        for name in sorted(os.listdir(mt.FIXTURES)):
            if name.endswith(".eml"):
                r = mt.run_bin(["--test-view", os.path.join(mt.FIXTURES, name)])
                self.assertEqual(r.returncode, 0, name)
                d = json.loads(r.stdout)
                dom = Dom()
                dom.feed(d["html"])
                d["dom"] = dom
                self.assert_safe(d)


if __name__ == "__main__":
    unittest.main()
