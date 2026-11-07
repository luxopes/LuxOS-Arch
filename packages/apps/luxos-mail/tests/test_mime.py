"""MIME, znakove sady, RFC 2047/2231, HTML -> text a parser odpovedi IMAP (luxos-mail --test-*)."""
import calendar
import email.utils
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mailtest as mt  # noqa: E402

ENV = dict(os.environ, LANG="cs_CZ.UTF-8")


def render(name, lang="cs_CZ.UTF-8"):
    env = dict(os.environ, LANG=lang)
    env.pop("LC_ALL", None)
    r = mt.run_bin(["--test-render", os.path.join(mt.FIXTURES, name)], env=env)
    assert r.returncode == 0, r.stderr.decode()
    return json.loads(r.stdout)


def unix(date):
    return calendar.timegm(email.utils.parsedate_tz(date)[:9]) - email.utils.parsedate_tz(date)[9]


class MimeTest(unittest.TestCase):
    def test_iso88592_quoted_printable(self):
        m = render("cs-iso88592-qp.eml")
        self.assertEqual(m["subject"], "Příliš žluťoučký kůň")
        self.assertEqual(m["from"], [["Jana Dvořáková", "jana@example.cz"]])
        self.assertEqual(m["text"], "Dobrý den,\npříliš žluťoučký kůň úpěl ďábelské ódy.\nS pozdravem\nJana")
        self.assertEqual(m["date"], unix("Tue, 03 Nov 2026 09:15:00 +0100"))
        self.assertEqual(m["message_id"], "<cs1@example.cz>")

    def test_cp1250_8bit_and_split_encoded_words(self):
        m = render("cs-cp1250-8bit.eml")
        # vicebajtove "č" rozdelene mezi dve kodovana slova se slozi pred dekodovanim
        self.assertEqual(m["subject"], "Faktura č. 2026/118 – říjen")
        # neoznacena 8bit hlavicka: sada podle jazyka (cestina -> windows-1250)
        self.assertEqual(m["from"][0][0], "Účtárna s.r.o.")
        self.assertEqual(m["text"], "Částka: 12 500 Kč\nSplatnost: 14 dní")

    def test_german_alternative_prefers_plain(self):
        m = render("de-alternative.eml")
        self.assertEqual(m["subject"], "Grüße aus München")
        self.assertEqual(m["from"], [["Jürgen Müller", "juergen@example.de"]])
        self.assertEqual(m["to"], [["Info", "info@example.test"], ["Novák, Jan", "jan@example.cz"]])
        self.assertEqual(m["cc"], [["", "team@example.de"]])
        # iso-8859-1 oznaceny text s pomlckou z windows-1252 (bezne u Outlooku)
        self.assertEqual(m["text"], "Grüße aus München!\nÜbermorgen um 10 Uhr – passt das?")
        self.assertFalse(m["html"])
        self.assertNotIn("alert", m["text"])

    def test_ukrainian_koi8u_base64(self):
        m = render("uk-koi8u-base64.eml")
        self.assertEqual(m["subject"], "Зустріч у п'ятницю")
        self.assertEqual(m["from"][0][0], "Олена Ковальчук")
        self.assertEqual(m["text"], "Добрий день! Зустріч у п'ятницю о 15:00. Ґанок, їжак, є.")

    def test_mixed_attachments_rfc2231(self):
        m = render("mixed-attachment.eml")
        self.assertEqual(m["text"], "V příloze posílám smlouvu.")
        names = [a["name"] for a in m["attachments"]]
        self.assertEqual(names, ["smlouva č.2026.pdf", "poznámka.txt"])
        self.assertEqual(m["attachments"][0]["type"], "application/pdf")
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "a.pdf")
            r = mt.run_bin(["--test-part", os.path.join(mt.FIXTURES, "mixed-attachment.eml"), m["attachments"][0]["path"], out])
            self.assertEqual(r.returncode, 0)
            with open(out, "rb") as f, open(os.path.join(mt.FIXTURES, "mixed-attachment.pdf"), "rb") as g:
                self.assertEqual(f.read(), g.read())

    def test_html_only_to_text(self):
        m = render("html-only.eml")
        self.assertTrue(m["html"])
        t = m["text"]
        self.assertTrue(t.startswith("Novinky v listopadu\n\nAhoj,\nmáme pro tebe akci <https://example.cz/akce?id=1> – 20 % sleva."), t)
        self.assertIn("• První\n• Druhá & třetí", t)
        self.assertIn("Cena 1 200 Kč", t)
        self.assertIn("[Logo]", t)
        self.assertIn("  zachovat   mezery", t)
        self.assertIn("😀 €", t)
        # styl, titulek, komentar ani sledovaci obrazek se neukazuji
        for bad in ("Novinky\nNovinky", ".x{}", "komentar", "tracker", "pixel"):
            self.assertNotIn(bad, t)

    def test_format_flowed(self):
        m = render("flowed.eml")
        self.assertEqual(m["text"].split("\n")[0], "Tohle je dlouhy odstavec, ktery se zalomil na vice radku.")
        self.assertIn("\n-- \npodpis", m["text"])

    def test_undeclared_charsets(self):
        self.assertEqual(render("no-charset-utf8.eml")["subject"], "Žádná sada")
        self.assertEqual(render("no-charset-cp1250.eml")["text"], "Text: čeština")
        # nemecke prostredi: windows-1252
        self.assertEqual(render("no-charset-cp1250.eml", "de_DE.UTF-8")["text"], "Text: èeština")

    def test_encoded_words(self):
        cases = {
            "=?UTF-8?B?xb5sdcWlb3XEjWvDvQ==?= =?UTF-8?Q?k=C5=AF=C5=88?= test": "žluťoučkýkůň test",
            "=?iso-8859-2?q?=A9koda?=  a  =?windows-1250?Q?=9Akoda?=": "Škoda  a  škoda",
            "=?utf-8?B?0JrQuNGX0LI=?=": "Київ",
            "bez kodovani =? ne": "bez kodovani =? ne",
            "=?unknown-x?Q?abc?=": "abc",
            "=?utf-8*cs?Q?=C4=8Desky?=": "česky",
        }
        for raw, want in cases.items():
            r = mt.run_bin(["--test-words", raw])
            self.assertEqual(json.loads(r.stdout)["text"], want, raw)

    def test_addresses(self):
        r = mt.run_bin(["--test-words", '"Novák, Jan" <jan@x.cz>, b@y.cz (Bob), Skupina: c@z.cz, d@z.cz;, =?utf-8?Q?=C5=BDofie?= <z@x.cz>'])
        self.assertEqual(json.loads(r.stdout)["addresses"], [["Novák, Jan", "jan@x.cz"], ["Bob", "b@y.cz"], ["", "c@z.cz"], ["", "d@z.cz"], ["Žofie", "z@x.cz"]])

    def test_dates(self):
        for d in ("Tue, 5 Nov 2026 14:03:22 +0100 (CET)", "5 Nov 2026 14:03:22 -0730", "Thu, 29 Feb 2024 23:59:59 GMT",
                  "Mon, 1 Jan 2001 00:00:00 +0000"):
            r = mt.run_bin(["--test-date", d])
            self.assertEqual(int(r.stdout), unix(d), d)
        r = mt.run_bin(["--test-date", "05-Nov-2026 14:03:22 +0100"])
        self.assertEqual(int(r.stdout), unix("5 Nov 2026 14:03:22 +0100"))
        self.assertEqual(int(mt.run_bin(["--test-date", "nesmysl"]).stdout), 0)

    def test_charsets(self):
        text = {"windows-1250": "Příliš žluťoučký kůň", "iso-8859-2": "Příliš žluťoučký kůň", "koi8-u": "Ґанок їжак",
                "windows-1251": "Привіт", "iso-8859-15": "Grüße €", "utf-8": "čeština 😀", "gb2312": "中文"}
        with tempfile.TemporaryDirectory() as d:
            for cs, s in text.items():
                path = os.path.join(d, "t")
                codec = {"gb2312": "gb2312"}.get(cs, cs)
                with open(path, "wb") as f:
                    f.write(s.encode(codec))
                r = mt.run_bin(["--test-charset", cs, path])
                self.assertEqual(r.stdout.decode().rstrip("\n"), s, cs)


class ImapParserTest(unittest.TestCase):
    def setUp(self):
        r = mt.run_bin(["--test-imap", os.path.join(mt.FIXTURES, "imap-responses.txt")])
        self.assertEqual(r.returncode, 0, r.stderr.decode())
        self.items = json.loads(r.stdout)

    def test_list_mutf7_and_literal(self):
        self.assertEqual(self.items[0]["mailbox"], "Odeslané pošta")
        self.assertEqual(self.items[1]["mailbox"], "Archiv.")

    def test_fetch_envelope_literal_groups(self):
        f = self.items[2]["fetch"]
        self.assertEqual(f["UID"], 34)
        self.assertEqual(f["FLAGS"], ["\\Seen", "$Forwarded"])
        self.assertEqual(f["RFC822.SIZE"], 2048)
        e = f["envelope"]
        self.assertEqual(e["subject"], "Příloha {x}")
        self.assertEqual(e["from"], [["Jan Novák", "jan@example.cz"]])
        # skupina (NIL NIL "team" NIL) ... (NIL NIL NIL NIL) se preskoci
        self.assertEqual(e["to"], [["Info", "info@lux-ai.cz"], ["", "a@b.cz"]])
        self.assertEqual(e["message_id"], "<a@b>")
        self.assertEqual(f["BODY[1]"], "Ahoj (svete)")

    def test_bodystructure(self):
        f = self.items[2]["fetch"]
        bs = f["bodystructure"]
        self.assertEqual(bs["type"], "multipart/mixed")
        self.assertEqual([p["section"] for p in bs["parts"]], ["1", "2", "3"])
        self.assertEqual(bs["parts"][1]["type"], "multipart/related")
        self.assertEqual([p["section"] for p in bs["parts"][1]["parts"]], ["2.1", "2.2"])
        self.assertEqual(bs["parts"][2]["filename"], "faktura č.pdf")
        self.assertEqual(f["preview_part"], "1")
        self.assertTrue(f["attachments"])
        single = self.items[3]["fetch"]
        self.assertEqual(single["bodystructure"]["type"], "text/plain")
        self.assertEqual(single["bodystructure"]["params"]["charset"], "iso-8859-2")
        self.assertEqual(single["bodystructure"]["section"], "1")
        self.assertFalse(single["attachments"])

    def test_status_lines(self):
        self.assertEqual(self.items[4]["line"], "VANISHED (EARLIER) 1:3,7")
        self.assertEqual(self.items[5]["tag"], "L5")
        self.assertEqual(len(self.items), 6)


if __name__ == "__main__":
    unittest.main()
